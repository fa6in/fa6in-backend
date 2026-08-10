"""
assessment/views.py
"""

from django.shortcuts import get_object_or_404
from rest_framework import viewsets, permissions, mixins
from rest_framework.decorators import action
from rest_framework.response import Response

from curriculum.views import IsTeacherOrAdminOrReadOnly
from skills.models import Skill, Prerequisite
from users.models import User
from .models import Error, StudentProgress, LogAnswer
from .serializers import ErrorSerializer, StudentProgressSerializer, LogAnswerSerializer


class ErrorViewSet(viewsets.ModelViewSet):
    queryset = Error.objects.select_related('skill').all()
    serializer_class = ErrorSerializer
    permission_classes = [IsTeacherOrAdminOrReadOnly]
    filterset_fields = ['skill', 'category', 'severity_level']
    search_fields = ['code', 'error_type', 'root_cause']


class StudentProgressViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Lecture seule : StudentProgress est mis à jour uniquement via
    LogAnswer (register_attempt), jamais modifié directement.
    """
    queryset = StudentProgress.objects.select_related('student', 'skill').all()
    serializer_class = StudentProgressSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['student', 'skill', 'status']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role in (User.Role.ADMIN, User.Role.REGIONAL_ADMIN, User.Role.TEACHER):
            return qs
        return qs.filter(student=user)

    @action(detail=False, methods=['get'])
    def next_recommendation(self, request):
        """
        Implémente la logique du Decision Engine décrite dans le
        scénario d'Ahmed (Partie 6, Étape 11) :
        si une skill est bloquée (attempts >= 3 et mastery < 0.5),
        on redirige vers le prérequis le moins maîtrisé.
        """
        skill_id = request.query_params.get('skill')
        if not skill_id:
            return Response({'detail': "Le paramètre 'skill' est requis."}, status=400)

        skill = get_object_or_404(Skill, pk=skill_id)
        student = request.user

        progress = StudentProgress.objects.filter(student=student, skill=skill).first()
        if not progress or progress.attempts < 3 or float(progress.mastery) >= 0.5:
            return Response({'blocked': False, 'recommendation': None})

        prereq_ids = Prerequisite.objects.filter(skill=skill).values_list('prerequisite_id', flat=True)
        if not prereq_ids:
            return Response({'blocked': True, 'recommendation': None, 'detail': "Aucun prérequis disponible."})

        candidates = (
            StudentProgress.objects
            .filter(student=student, skill_id__in=prereq_ids)
            .order_by('mastery')
        )
        covered_ids = set(candidates.values_list('skill_id', flat=True))
        remaining_ids = [pid for pid in prereq_ids if pid not in covered_ids]

        if candidates.exists():
            weakest = candidates.first()
            return Response({
                'blocked': True,
                'recommendation': {
                    'skill_id': weakest.skill_id,
                    'skill_code': weakest.skill.code,
                    'mastery': weakest.mastery,
                },
            })

        # Aucune tentative encore sur les prérequis : recommander le premier non-tenté
        if remaining_ids:
            recommended = Skill.objects.get(pk=remaining_ids[0])
            return Response({
                'blocked': True,
                'recommendation': {
                    'skill_id': recommended.id,
                    'skill_code': recommended.code,
                    'mastery': 0.0,
                },
            })

        return Response({'blocked': True, 'recommendation': None})


class LogAnswerViewSet(mixins.CreateModelMixin, mixins.ListModelMixin,
                        mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Création (obligatoire, append-only) et lecture seule.
    Aucune méthode update/destroy n'est exposée (Partie 4.3, Règle 8).
    """
    # AJOUTER CETTE LIGNE POUR LIMITER LES MÉTHODES HTTP
    http_method_names = ['get', 'post', 'head', 'options']
    
    queryset = LogAnswer.objects.select_related('student', 'skill', 'chunk', 'error_detail').all()
    serializer_class = LogAnswerSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['student', 'skill', 'chunk', 'is_correct']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role in (User.Role.ADMIN, User.Role.REGIONAL_ADMIN, User.Role.TEACHER):
            return qs
        return qs.filter(student=user)

    def perform_create(self, serializer):
        log = serializer.save(student=self.request.user)

        progress, _created = StudentProgress.objects.get_or_create(
            student=log.student, skill=log.skill,
        )
        progress.register_attempt(is_correct=log.is_correct, error_category=log.error_type)
