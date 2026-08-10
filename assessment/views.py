"""
assessment/views.py
"""

from django.shortcuts import get_object_or_404
from rest_framework import viewsets, permissions, mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from curriculum.views import IsTeacherOrAdminOrReadOnly
from skills.models import Skill, Prerequisite, Chunk
from skills.serializers import ChunkSerializer
from users.models import User
from . import engine
from .models import Error, StudentProgress, LogAnswer
from .serializers import ErrorSerializer, StudentProgressSerializer, LogAnswerSerializer


def _ensure_can_act_for_student(request, student):
    """
    Un étudiant ne peut agir que sur son propre compte ; enseignants/admins
    peuvent consulter/agir pour n'importe quel étudiant (supervision).
    """
    staff_roles = (User.Role.ADMIN, User.Role.REGIONAL_ADMIN, User.Role.TEACHER)
    if request.user != student and request.user.role not in staff_roles:
        raise PermissionDenied("Vous ne pouvez agir que pour votre propre compte.")


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


class SubmitAnswerView(APIView):
    """
    POST /api/students/{id}/answer/

    Endpoint intelligent (Revue de l'API, Problème 1) : le Frontend
    n'envoie que chunk_id/answer/time_taken. Toute la logique - vérité
    de la réponse, classification de l'erreur, mise à jour de la
    progression - est calculée côté serveur. correct_answer n'est
    jamais transmis au client.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, student_id):
        student = get_object_or_404(User, pk=student_id)
        _ensure_can_act_for_student(request, student)

        chunk_id = request.data.get('chunk_id')
        answer = request.data.get('answer', '')
        time_taken = request.data.get('time_taken')

        if not chunk_id:
            return Response({'chunk_id': "Ce champ est requis."}, status=status.HTTP_400_BAD_REQUEST)

        chunk = get_object_or_404(Chunk, pk=chunk_id)
        if chunk.chunk_type != Chunk.ChunkType.PRACTICE:
            return Response(
                {'detail': "Seuls les chunks de type 'practice' peuvent être soumis à évaluation."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        skill = chunk.skill
        progress, _created = StudentProgress.objects.get_or_create(student=student, skill=skill)

        is_correct = engine.evaluate_answer(chunk, answer)
        error_type = None
        error_detail = None
        if not is_correct:
            error_type = engine.classify_error(progress, time_taken, chunk)
            error_detail = engine.pick_error_detail(skill.id, error_type)

        log = LogAnswer(
            student=student, skill=skill, chunk=chunk, answer=answer,
            is_correct=is_correct, error_type=error_type, error_detail=error_detail,
            time_taken=time_taken,
        )
        log.save()

        progress.register_attempt(is_correct=is_correct, error_category=error_type)

        return Response({
            'is_correct': is_correct,
            'error_type': error_type,
            'error_detail': ErrorSerializer(error_detail).data if error_detail else None,
            'progress': {
                'attempts': progress.attempts,
                'correct_count': progress.correct_count,
                'mastery': progress.mastery,
                'consecutive_correct': progress.consecutive_correct,
                'status': progress.status,
            },
        })


class NextActionView(APIView):
    """
    GET /api/students/{id}/next-action/?skill=<skill_id>

    Endpoint unifié (Revue de l'API, Problèmes 2 et 3) : décide, côté
    serveur, si l'étudiant doit continuer sur la skill actuelle (avec le
    chunk approprié) ou être redirigé vers un prérequis plus faible.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, student_id):
        student = get_object_or_404(User, pk=student_id)
        _ensure_can_act_for_student(request, student)

        skill_id = request.query_params.get('skill')
        if not skill_id:
            return Response({'detail': "Le paramètre 'skill' est requis."}, status=status.HTTP_400_BAD_REQUEST)
        skill = get_object_or_404(Skill, pk=skill_id)

        redirect = engine.find_prerequisite_redirect(student, skill)
        if redirect is not None:
            return Response({
                'action': 'redirect_to_prerequisite',
                'previous_skill': {
                    'id': redirect['previous_skill'].id,
                    'code': redirect['previous_skill'].code,
                    'mastery': redirect['previous_progress'].mastery,
                    'attempts': redirect['previous_progress'].attempts,
                },
                'new_skill': {
                    'id': redirect['new_skill'].id,
                    'code': redirect['new_skill'].code,
                    'name': redirect['new_skill'].name,
                    'current_mastery': redirect['new_mastery'],
                    'reason': "Prerequisite le plus faible",
                },
                'chunk': ChunkSerializer(redirect['chunk'], context={'request': request}).data
                if redirect['chunk'] else None,
                'message': "Renforçons cette compétence avant de continuer",
            })

        progress, _created = StudentProgress.objects.get_or_create(student=student, skill=skill)
        last_chunk_id = (
            LogAnswer.objects
            .filter(student=student, skill=skill)
            .order_by('-timestamp')
            .values_list('chunk_id', flat=True)
            .first()
        )
        chunk, reason = engine.pick_next_chunk(skill, progress, exclude_chunk_id=last_chunk_id)

        return Response({
            'action': 'show_chunk',
            'current_skill': {'id': skill.id, 'code': skill.code},
            'chunk': ChunkSerializer(chunk, context={'request': request}).data if chunk else None,
            'context': {
                'reason': reason,
                'current_mastery': progress.mastery,
                'attempts': progress.attempts,
            },
        })
