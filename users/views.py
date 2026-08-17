"""
users/views.py
"""

from rest_framework import viewsets, permissions, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from django.contrib.auth import authenticate

import logging

from .models import User, Wilaya, StudentProfile, TeacherProfile, PasswordResetCode
from .serializers import (
    UserSerializer,
    UserRegistrationSerializer,
    WilayaSerializer,
    StudentProfileSerializer,
    TeacherProfileSerializer,
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
)
from utilities.emailjs import send_password_reset_code_email

logger = logging.getLogger(__name__)


class IsOwnerOrAdmin(permissions.BasePermission):
    """
    Un utilisateur ne peut voir/modifier que son propre compte,
    sauf s'il est admin ou regional_admin.
    """

    def has_object_permission(self, request, view, obj):
        if request.user.role in (User.Role.ADMIN, User.Role.REGIONAL_ADMIN):
            return True
        return obj == request.user


class IsAdminOrRegionalAdmin(permissions.BasePermission):
    """
    Réservé aux administrateurs (système ou régionaux).
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in (User.Role.ADMIN, User.Role.REGIONAL_ADMIN)
        )


class WilayaViewSet(viewsets.ModelViewSet):
    queryset = Wilaya.objects.all()
    serializer_class = WilayaSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    search_fields = ['name', 'code']


class UserViewSet(viewsets.ModelViewSet):
    """
    CRUD sur les utilisateurs. La création publique passe par /auth/register/.
    """
    queryset = User.objects.select_related('wilaya').all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]
    filterset_fields = ['role', 'wilaya', 'is_active']
    search_fields = ['username', 'email', 'first_name', 'last_name']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role in (User.Role.ADMIN, User.Role.REGIONAL_ADMIN):
            return qs
        return qs.filter(id=user.id)

    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def me(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def change_password(self, request, pk=None):
        user = self.get_object()
        if user != request.user:
            return Response(
                {'detail': "Vous ne pouvez modifier que votre propre mot de passe."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not user.check_password(serializer.validated_data['old_password']):
            return Response({'old_password': 'Mot de passe incorrect.'}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(serializer.validated_data['new_password'])
        user.save()
        return Response({'detail': 'Mot de passe mis à jour avec succès.'})


class StudentProfileViewSet(viewsets.ModelViewSet):
    queryset = StudentProfile.objects.select_related('user', 'level').all()
    serializer_class = StudentProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['level']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role in (User.Role.ADMIN, User.Role.REGIONAL_ADMIN, User.Role.TEACHER):
            return qs
        return qs.filter(user=user)


class TeacherProfileViewSet(viewsets.ModelViewSet):
    queryset = TeacherProfile.objects.select_related('user').all()
    serializer_class = TeacherProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role in (User.Role.ADMIN, User.Role.REGIONAL_ADMIN):
            return qs
        return qs.filter(user=user)


class AdminStudentListView(generics.ListAPIView):
    """
    GET /api/auth/admin/students/
    Liste de tous les étudiants, réservée aux administrateurs.
    """
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrRegionalAdmin]
    filterset_fields = ['wilaya', 'is_active']
    search_fields = ['username', 'email', 'first_name', 'last_name']
    queryset = User.objects.filter(role=User.Role.STUDENT).select_related(
        'wilaya', 'student_profile', 'student_profile__level'
    )


class AdminTeacherListView(generics.ListAPIView):
    """
    GET /api/auth/admin/teachers/
    Liste de tous les enseignants, réservée aux administrateurs.
    """
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrRegionalAdmin]
    filterset_fields = ['wilaya', 'is_active']
    search_fields = ['username', 'email', 'first_name', 'last_name']
    queryset = User.objects.filter(role=User.Role.TEACHER).select_related(
        'wilaya', 'teacher_profile'
    )


class AdminStudentDetailView(generics.RetrieveAPIView):
    """
    GET /api/auth/admin/students/<id>/
    Détail d'un étudiant, réservé aux administrateurs.
    """
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrRegionalAdmin]
    queryset = User.objects.filter(role=User.Role.STUDENT).select_related(
        'wilaya', 'student_profile', 'student_profile__level'
    )


class AdminTeacherDetailView(generics.RetrieveAPIView):
    """
    GET /api/auth/admin/teachers/<id>/
    Détail d'un enseignant, réservé aux administrateurs.
    """
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrRegionalAdmin]
    queryset = User.objects.filter(role=User.Role.TEACHER).select_related(
        'wilaya', 'teacher_profile'
    )


def _jwt_pair_for(user):
    refresh = RefreshToken.for_user(user)
    return {'access': str(refresh.access_token), 'refresh': str(refresh)}


class RegisterView(generics.CreateAPIView):
    """
    POST /api/auth/register/
    Inscription publique (étudiant ou enseignant) + émission access/refresh JWT.
    """
    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {**_jwt_pair_for(user), 'user': UserSerializer(user).data},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    """
    POST /api/auth/login/  {username, password} -> {access, refresh, user}
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response({'detail': "Identifiants invalides."}, status=status.HTTP_401_UNAUTHORIZED)
        return Response({**_jwt_pair_for(user), 'user': UserSerializer(user).data})


class MeView(generics.RetrieveAPIView):
    """
    GET /api/auth/me/ -> infos de l'utilisateur authentifié.
    """
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class ForgotPasswordView(APIView):
    """
    POST /api/auth/forgot-password/  {email}
    Génère un code à 4 chiffres et l'envoie par email s'il existe un compte
    avec cette adresse. La réponse est volontairement générique pour ne pas
    révéler si l'email est enregistré.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        user = User.objects.filter(email__iexact=email).first()
        if user is not None:
            reset_code = PasswordResetCode.create_for_user(user)
            try:
                send_password_reset_code_email(user, reset_code.code)
            except Exception:
                # L'envoi de l'email ne doit jamais faire échouer la requête ;
                # le code reste valide même si la notification échoue.
                logger.exception("Échec de l'envoi du code de réinitialisation à %s", user.email)

        return Response(
            {'detail': "Si cet email est associé à un compte, un code de vérification a été envoyé."}
        )


class ResetPasswordView(APIView):
    """
    POST /api/auth/reset-password/  {email, code, new_password, new_password_confirm}
    Vérifie le code reçu par email puis réinitialise le mot de passe.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = User.objects.filter(email__iexact=data['email']).first()
        if user is None:
            return Response({'detail': "Code invalide ou expiré."}, status=status.HTTP_400_BAD_REQUEST)

        reset_code = user.password_reset_codes.filter(is_used=False).order_by('-created_at').first()
        if reset_code is None or not reset_code.is_valid():
            return Response({'detail': "Code invalide ou expiré."}, status=status.HTTP_400_BAD_REQUEST)

        if reset_code.code != data['code']:
            reset_code.attempts += 1
            reset_code.save(update_fields=['attempts'])
            return Response({'detail': "Code invalide ou expiré."}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(data['new_password'])
        user.save()

        reset_code.is_used = True
        reset_code.save(update_fields=['is_used'])

        return Response({'detail': "Mot de passe réinitialisé avec succès."})


class LogoutView(APIView):
    """
    POST /api/auth/logout/  {refresh} -> blackliste le refresh token.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response({'refresh': "Ce champ est requis."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            RefreshToken(refresh_token).blacklist()
        except TokenError:
            return Response({'detail': "Token invalide ou déjà expiré."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'detail': "Déconnexion réussie."}, status=status.HTTP_205_RESET_CONTENT)
