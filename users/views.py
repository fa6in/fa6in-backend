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

from .models import User, Wilaya, StudentProfile, TeacherProfile
from .serializers import (
    UserSerializer,
    UserRegistrationSerializer,
    WilayaSerializer,
    StudentProfileSerializer,
    TeacherProfileSerializer,
    ChangePasswordSerializer,
)


class IsOwnerOrAdmin(permissions.BasePermission):
    """
    Un utilisateur ne peut voir/modifier que son propre compte,
    sauf s'il est admin ou regional_admin.
    """

    def has_object_permission(self, request, view, obj):
        if request.user.role in (User.Role.ADMIN, User.Role.REGIONAL_ADMIN):
            return True
        return obj == request.user


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
