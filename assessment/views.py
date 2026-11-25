"""
assessment/views.py
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets, permissions, mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from curriculum.models import AcademicYear, Unit
from curriculum.views import IsTeacherOrAdminOrReadOnly
from skills.models import Skill, Prerequisite, Chunk
from skills.serializers import ChunkSerializer
from users.models import User
from . import decision, engine, path as student_path
from .models import (
    Decision, EngineSettings, Error, ErrorCategory, ExerciseGroup, Intervention, LearningTrace,
    LogAnswer, PrerequisiteReturn, StudentProgress,
)
from .serializers import (
    EngineSettingsSerializer, ErrorSerializer, LearningTraceSerializer, LogAnswerSerializer,
    PrerequisiteReturnSerializer, StudentProgressSerializer,
)


class IsTeacherOrAdmin(permissions.BasePermission):
    """
    Réservé aux enseignants et administrateurs (pas de lecture publique).
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in (User.Role.TEACHER, User.Role.REGIONAL_ADMIN, User.Role.ADMIN)
        )


def _ensure_can_act_for_student(request, student):
    """
    Un étudiant ne peut agir que sur son propre compte ; enseignants/admins
    peuvent consulter/agir pour n'importe quel étudiant (supervision).
    """
    staff_roles = (User.Role.ADMIN, User.Role.REGIONAL_ADMIN, User.Role.TEACHER)
    if request.user != student and request.user.role not in staff_roles:
        raise PermissionDenied("Vous ne pouvez agir que pour votre propre compte.")


def _locked_skill_response(request, skill):
    """
    403 si la leçon de la skill n'est pas encore ouverte (semaine du
    programme pas encore atteinte). Les enseignants/admins ne sont pas
    concernés (prévisualisation du contenu).
    """
    staff_roles = (User.Role.ADMIN, User.Role.REGIONAL_ADMIN, User.Role.TEACHER)
    if request.user.role in staff_roles:
        return None
    week = AcademicYear.current_week()
    if student_path.skill_is_open(skill, week):
        return None
    return Response(
        {
            'detail': "Cette leçon n'est pas encore ouverte.",
            'code': 'lesson_locked',
            'opens_week': student_path.lesson_week(skill.goal.lesson),
            'current_week': week,
        },
        status=status.HTTP_403_FORBIDDEN,
    )


def _engine_state(progress):
    """Groupe et intervention en cours (pour le Frontend)."""
    group = progress.active_group
    intervention = progress.active_intervention
    return {
        'group': (
            {
                'id': group.id,
                'status': group.status,
                'answered': len(decision.group_answered_ids(group)),
                'total': len(group.exercise_ids),
            }
            if group is not None and group.status != ExerciseGroup.Status.COMPLETED else None
        ),
        'intervention': (
            {
                'id': intervention.id,
                'error_type': intervention.error_type,
                'step_index': min(intervention.current_step + 1, len(intervention.sequence)),
                'steps_total': len(intervention.sequence),
            }
            if intervention is not None and intervention.status == Intervention.Status.IN_PROGRESS else None
        ),
    }


def _evaluation_payload(group, result, outcome):
    """
    Résultat de fin de groupe : indicateurs, décision et retour sur les
    exercices ratés avec leur feedback (l'étudiant n'a pas été bloqué
    pendant le groupe ; on revient maintenant sur ses erreurs).
    """
    mistakes = []
    for log in (
        LogAnswer.objects.filter(exercise_group=group, is_correct=False)
        .select_related('chunk', 'error_detail').order_by('timestamp', 'id')
    ):
        option = engine.selected_option(log.chunk, log.answer)
        mistakes.append({
            'chunk_id': log.chunk_id,
            'content': log.chunk.content,
            'answer': log.answer,
            'error_type': log.error_type,
            'feedback': engine.answer_feedback(log.skill, log.error_type, option, log.error_detail)['message'],
        })
    intervention = outcome.get('new_intervention')
    ret = outcome.get('prerequisite_return')
    return {
        'group_id': group.id,
        'total_attempts': result.total_attempts,
        'correct_answers': result.correct_answers,
        'mastery': float(result.mastery),
        'mastery_level': result.mastery_level,
        'judged': result.judged,
        'error_frequency': result.error_frequency,
        'dominant_error_type': result.dominant_error_type or None,
        'correct_streak': result.correct_streak,
        'decision': outcome.get('decision'),
        'mistakes': mistakes,
        'intervention': (
            {
                'id': intervention.id,
                'error_type': intervention.error_type,
                'reason': decision.INTERVENTION_REASON.get(intervention.error_type),
                'steps': [decision.STEP_LABELS.get(s['step']) for s in intervention.sequence],
            }
            if intervention is not None else None
        ),
        'teacher_review': bool(ret and ret.status == PrerequisiteReturn.Status.TEACHER_REVIEW),
    }


def _session_context(skill, progress):
    """
    Contexte d'une séance d'apprentissage (écran S4) : fil d'Ariane,
    objectif de maîtrise, série en cours et étapes déjà vues
    (قاعدة ✓ · مثال ✓ · تمرين · تمرين · تطبيق).
    """
    lesson = skill.goal.lesson
    unit = lesson.unit
    counts = {
        c['chunk_type']: c['n']
        for c in skill.chunks.values('chunk_type').annotate(n=Count('id'))
    }
    hint = skill.chunks.filter(chunk_type=Chunk.ChunkType.HINT).order_by('order_index').first()
    settings = EngineSettings.load()
    return {
        'skill': {
            'id': skill.id,
            'code': skill.code,
            'name': skill.name,
            'skill_type': skill.skill_type,
            'mastery_threshold': float(settings.high_threshold),
            'required_consecutive_correct': settings.required_correct_streak,
        },
        'breadcrumb': {
            'subject_id': unit.subject_id,
            'subject_name': unit.subject.name,
            'unit_id': unit.id,
            'unit_code': unit.code,
            'lesson_id': lesson.id,
            'lesson_code': lesson.code,
            'lesson_title': lesson.title,
        },
        'progress': {
            'attempts': progress.attempts,
            'correct_count': progress.correct_count,
            'mastery': progress.mastery,
            'consecutive_correct': progress.consecutive_correct,
            'status': progress.status,
            'rule_seen': progress.rule_seen,
            'example_seen': progress.example_seen,
        },
        **_engine_state(progress),
        'chunk_counts': counts,
        'hint': hint.content if hint else None,
    }


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
        Indique si l'étudiant a été renvoyé vers une skill préalable
        pour `skill` (retour actif du Decision Engine).
        """
        skill_id = request.query_params.get('skill')
        if not skill_id:
            return Response({'detail': "Le paramètre 'skill' est requis."}, status=400)

        skill = get_object_or_404(Skill, pk=skill_id)
        student = request.user

        # Retour vers une skill préalable décidé par le Decision Engine
        # (exercices épuisés sans maîtrise, section 8 du guide MVP).
        ret = decision.active_return(student, skill)
        if ret is None:
            return Response({'blocked': False, 'recommendation': None})
        progress = StudentProgress.objects.filter(student=student, skill=ret.to_skill).first()
        return Response({
            'blocked': True,
            'recommendation': {
                'skill_id': ret.to_skill.id,
                'skill_code': ret.to_skill.code,
                'mastery': progress.mastery if progress else 0,
                'reason': ret.reason,
            },
        })


class LogAnswerViewSet(mixins.CreateModelMixin, mixins.ListModelMixin,
                        mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Création (obligatoire, append-only) et lecture seule.
    Aucune méthode update/destroy n'est exposée (Partie 4.3, Règle 8).
    """
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


class UnitActivitiesView(APIView):
    """
    GET /api/assessment/units/<unit_id>/activities/

    Les "activités" d'une unité sont les chunks (rule/example/practice/...)
    des skills rattachées à ses leçons, réservé aux enseignants/admins
    pour la gestion du contenu.
    """
    permission_classes = [IsTeacherOrAdmin]

    def get(self, request, unit_id):
        unit = get_object_or_404(Unit, pk=unit_id)
        chunks = (
            Chunk.objects
            .filter(skill__goal__lesson__unit=unit)
            .select_related('skill')
            .order_by('skill__goal__lesson__order_index', 'skill__order_index', 'order_index')
        )
        chunk_type = request.query_params.get('chunk_type')
        if chunk_type:
            chunks = chunks.filter(chunk_type=chunk_type)
        return Response(ChunkSerializer(chunks, many=True, context={'request': request}).data)


class SubmitAnswerView(APIView):
    """
    POST /api/students/{id}/answer/

    Le Frontend n'envoie que chunk_id/answer/time_taken. Correction, Error
    Mapping, évaluation de fin de groupe et décision sont calculées côté
    serveur ; correct_answer n'est jamais transmis au client.

    Pendant un groupe d'exercices, une réponse fausse reçoit un feedback
    immédiat et l'étudiant continue : aucune décision n'est prise avant la
    fin du groupe (`evaluation` est alors renseigné).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, student_id):
        student = get_object_or_404(User, pk=student_id)
        _ensure_can_act_for_student(request, student)

        chunk_id = request.data.get('chunk_id')
        answer = request.data.get('answer', '')
        try:
            time_taken = int(request.data.get('time_taken'))
        except (TypeError, ValueError):
            time_taken = None

        if not chunk_id:
            return Response({'chunk_id': "Ce champ est requis."}, status=status.HTTP_400_BAD_REQUEST)

        chunk = get_object_or_404(Chunk, pk=chunk_id)
        if chunk.chunk_type != Chunk.ChunkType.PRACTICE:
            return Response(
                {'detail': "Seuls les chunks de type 'practice' peuvent être soumis à évaluation."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        skill = chunk.skill
        locked = _locked_skill_response(request, skill)
        if locked is not None:
            return locked

        with transaction.atomic():
            out = decision.handle_answer(student, chunk, answer, time_taken)
        progress = out['progress']

        evaluation = None
        if out['result'] is not None and out['decision'] != Decision.CONTINUE:
            evaluation = _evaluation_payload(out['group'], out['result'], out)

        # Écran S6 : retour vers une skill préalable.
        redirect = None
        ret = out['prerequisite_return']
        if ret is not None and ret.status == PrerequisiteReturn.Status.ACTIVE:
            redirect = {
                'skill': {'id': ret.to_skill.id, 'code': ret.to_skill.code, 'name': ret.to_skill.name},
                'attempts': progress.attempts,
                'mastery': progress.mastery,
                'reason': ret.reason,
            }

        # Écran S7 : skill maîtrisée -> points gagnés + skill suivante débloquée.
        next_skill = None
        points = None
        if out['mastered_now']:
            points = (
                LogAnswer.objects.filter(student=student, skill=skill, is_correct=True)
                .aggregate(total=Sum('chunk__points'))['total'] or 0
            )
            path = student_path.build_subject_path(student, student_path.subject_of_skill(skill))
            found = student_path.first_open_skill(path, exclude_skill_id=skill.id)
            if found is not None:
                unit_entry, _lesson_entry, skill_entry = found
                next_skill = {
                    'id': skill_entry['skill'].id,
                    'code': skill_entry['skill'].code,
                    'name': skill_entry['skill'].name,
                    'unit_id': unit_entry['unit'].id,
                }

        feedback = out['feedback']
        if feedback is not None and out['group'] is not None and evaluation is None:
            # Erreur au milieu d'un groupe : on continue, retour en fin de groupe.
            feedback['continue'] = True
            feedback['short_message'] = CONTINUE_MESSAGE

        error_detail = out['error_detail']
        return Response({
            'is_correct': out['is_correct'],
            'error_type': out['error_type'],
            'error_source': out['error_source'],
            'error_detail': ErrorSerializer(error_detail).data if error_detail else None,
            'feedback': feedback,
            'progress': {
                'attempts': progress.attempts,
                'correct_count': progress.correct_count,
                'mastery': progress.mastery,
                'consecutive_correct': progress.consecutive_correct,
                'status': progress.status,
            },
            'answer_context': (
                'intervention' if out['intervention'] is not None
                else 'group' if out['group'] is not None else 'free'
            ),
            'evaluation': evaluation,
            'decision': out['decision'],
            'mastered_now': out['mastered_now'],
            'points': points,
            'next_skill': next_skill,
            'redirect': redirect,
            'session': _session_context(skill, progress),
        })


CONTINUE_MESSAGE = "إجابة غير صحيحة. تابع بقية التمارين، وسنعود إلى أخطائك في نهاية المجموعة."


class NextActionView(APIView):
    """
    GET /api/students/{id}/next-action/?skill=<skill_id>

    Le Decision Engine choisit, côté serveur, le prochain contenu :
    - mode 'learn'        : règle puis exemple (première visite) ;
    - mode 'group'        : exercice suivant du groupe en cours ;
    - mode 'intervention' : pas de la séquence d'intervention ;
    - mode 'verify'       : exercice de vérification de la stabilité ;
    ou une redirection vers une skill préalable.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, student_id):
        student = get_object_or_404(User, pk=student_id)
        _ensure_can_act_for_student(request, student)

        skill_id = request.query_params.get('skill')
        if not skill_id:
            return Response({'detail': "Le paramètre 'skill' est requis."}, status=status.HTTP_400_BAD_REQUEST)
        skill = get_object_or_404(Skill, pk=skill_id)
        locked = _locked_skill_response(request, skill)
        if locked is not None:
            return locked

        with transaction.atomic():
            step = decision.next_step(student, skill)
        progress = step['progress']

        if step['action'] == 'redirect':
            ret = step['return']
            new_skill = ret.to_skill
            # On sert directement la règle du prérequis : elle compte comme vue.
            new_progress, _c = StudentProgress.objects.get_or_create(student=student, skill=new_skill)
            rule = new_skill.chunks.filter(chunk_type=Chunk.ChunkType.RULE).order_by('order_index').first()
            if rule is not None and not new_progress.rule_seen:
                new_progress.rule_seen = True
                new_progress.save(update_fields=['rule_seen'])
            return Response({
                'action': 'redirect_to_prerequisite',
                'previous_skill': {
                    'id': skill.id,
                    'code': skill.code,
                    'mastery': progress.mastery,
                    'attempts': progress.attempts,
                },
                'new_skill': {
                    'id': new_skill.id,
                    'code': new_skill.code,
                    'name': new_skill.name,
                    'current_mastery': new_progress.mastery,
                    'reason': ret.reason,
                },
                'chunk': ChunkSerializer(rule, context={'request': request}).data if rule else None,
                'message': "Renforçons cette compétence avant de continuer",
                'session': _session_context(new_skill, new_progress),
            })

        chunk = step['chunk']
        return Response({
            'action': 'show_chunk',
            'mode': step['mode'],
            'current_skill': {'id': skill.id, 'code': skill.code},
            'chunk': ChunkSerializer(chunk, context={'request': request}).data if chunk else None,
            'instruction': step.get('instruction'),
            'intervention': step.get('intervention'),
            'group': step.get('group'),
            'context': {
                'reason': step['reason'],
                'current_mastery': progress.mastery,
                'attempts': progress.attempts,
            },
            'session': _session_context(skill, progress),
        })


def _activity_dates(student):
    return set(
        LogAnswer.objects.filter(student=student)
        .annotate(day=TruncDate('timestamp'))
        .values_list('day', flat=True)
        .distinct()
    )


def _streak_days(student):
    """Nombre de jours consécutifs d'activité, se terminant aujourd'hui (ou hier)."""
    dates = _activity_dates(student)
    day = timezone.localdate()
    if day not in dates:
        day -= timedelta(days=1)
    streak = 0
    while day in dates:
        streak += 1
        day -= timedelta(days=1)
    return streak


def _skill_brief(unit_entry, lesson_entry, skill_entry):
    skill, progress = skill_entry['skill'], skill_entry['progress']
    return {
        'skill': {'id': skill.id, 'code': skill.code, 'name': skill.name},
        'unit': {'id': unit_entry['unit'].id, 'code': unit_entry['unit'].code},
        'lesson': {
            'id': lesson_entry['lesson'].id,
            'code': lesson_entry['lesson'].code,
            'title': lesson_entry['lesson'].title,
        },
        'mastery': float(progress.mastery) if progress else 0.0,
        'mastery_threshold': skill.mastery_threshold,
    }


class StudentHomeView(APIView):
    """
    GET /api/students/{id}/home/

    Écran S1 : "تابع من حيث توقفت", compteurs (مهارة متقنة · أيام متتالية ·
    تمرين اليوم), matières de l'étudiant et suggestion de révision.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, student_id):
        student = get_object_or_404(User, pk=student_id)
        _ensure_can_act_for_student(request, student)

        subjects = list(student_path.student_subjects(student))
        skills_qs = student_path.subjects_with_skills_query(student)
        totals = {
            row['goal__lesson__unit__subject']: row['n']
            for row in skills_qs.values('goal__lesson__unit__subject').annotate(n=Count('id'))
        }
        mastered = {
            row['goal__lesson__unit__subject']: row['n']
            for row in skills_qs.filter(
                student_progress__student=student,
                student_progress__status=StudentProgress.Status.MASTERED,
            ).values('goal__lesson__unit__subject').annotate(n=Count('id'))
        }

        # "Continuer" : la skill ouverte la plus récemment travaillée, sinon
        # la première skill ouverte de la première matière.
        resume = None
        recent = (
            StudentProgress.objects
            .filter(student=student, status=StudentProgress.Status.IN_PROGRESS, skill__in=skills_qs)
            .select_related('skill__goal__lesson__unit__subject')
            .order_by('-last_activity')
            .first()
        )
        candidates_subjects = ([student_path.subject_of_skill(recent.skill)] if recent else []) + subjects
        for subject in candidates_subjects:
            path = student_path.build_subject_path(student, subject)
            found = student_path.find_skill(path, recent.skill_id) if recent else None
            if found is None or found[2]['status'] not in ('available', 'in_progress'):
                found = student_path.first_open_skill(path)
            if found is not None:
                resume = {
                    'subject': {'id': subject.id, 'name': subject.name},
                    **_skill_brief(*found),
                }
                break

        suggestion = None
        if resume:
            ret = decision.active_return(student, get_object_or_404(Skill, pk=resume['skill']['id']))
            if ret is not None:
                suggestion = {
                    'skill': {
                        'id': ret.to_skill.id,
                        'code': ret.to_skill.code,
                        'name': ret.to_skill.name,
                    },
                    'reason': 'prerequisite',
                }

        return Response({
            'resume': resume,
            'suggestion': suggestion,
            'stats': {
                'mastered_skills': StudentProgress.objects.filter(
                    student=student, status=StudentProgress.Status.MASTERED,
                ).count(),
                'streak_days': _streak_days(student),
                'attempts_today': LogAnswer.objects.filter(
                    student=student, timestamp__date=timezone.localdate(),
                ).count(),
            },
            'subjects': [
                {
                    'id': s.id,
                    'name': s.name,
                    'color': s.color,
                    'icon': s.icon,
                    'skills_total': totals.get(s.id, 0),
                    'skills_mastered': mastered.get(s.id, 0),
                }
                for s in subjects
            ],
        })


class StudentPathView(APIView):
    """
    GET /api/students/{id}/path/?subject=<subject_id>

    Écran S2 "مساري" : unités et leçons d'une matière avec leur état
    (مكتملة / قيد التقدم / مقفلة) calculé à partir de la maîtrise.
    Sans `subject`, utilise la première matière de l'étudiant.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, student_id):
        student = get_object_or_404(User, pk=student_id)
        _ensure_can_act_for_student(request, student)

        subjects = list(student_path.student_subjects(student))
        subject_id = request.query_params.get('subject')
        if subject_id:
            subject = get_object_or_404(student_path.Subject, pk=subject_id)
        elif subjects:
            subject = subjects[0]
        else:
            return Response({'subject': None, 'units': [], 'subjects': []})

        data = student_path.serialize_path(student_path.build_subject_path(student, subject))
        data['subjects'] = [{'id': s.id, 'name': s.name, 'color': s.color} for s in subjects]
        return Response(data)


class StudentSkillMapView(APIView):
    """
    GET /api/students/{id}/skill-map/?unit=<unit_id>

    Écran S3 "خريطة المهارات" : skills de l'unité, dans l'ordre du
    parcours, avec statut (متقنة / قيد التقدم / متاحة / مقفلة), mastery et
    prérequis manquants.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, student_id):
        student = get_object_or_404(User, pk=student_id)
        _ensure_can_act_for_student(request, student)

        unit_id = request.query_params.get('unit')
        if not unit_id:
            return Response({'detail': "Le paramètre 'unit' est requis."}, status=status.HTTP_400_BAD_REQUEST)
        unit = get_object_or_404(Unit.objects.select_related('subject'), pk=unit_id)

        path = student_path.build_subject_path(student, unit.subject)
        unit_entry = next((u for u in path['units'] if u['unit'].id == unit.id), None)
        if unit_entry is None:
            return Response({'detail': "Unité non publiée."}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            'subject': {'id': unit.subject.id, 'name': unit.subject.name},
            'unit': {
                'id': unit.id, 'code': unit.code, 'title': unit.title,
                'status': unit_entry['status'],
                'skills_total': unit_entry['skills_total'],
                'skills_mastered': unit_entry['skills_mastered'],
            },
            'lessons': [
                {
                    'id': l['lesson'].id,
                    'code': l['lesson'].code,
                    'title': l['lesson'].title,
                    'status': l['status'],
                    'skills': [student_path.serialize_skill_entry(s) for s in l['skills']],
                }
                for l in unit_entry['lessons']
            ],
        })


class StudentProgressSummaryView(APIView):
    """
    GET /api/students/{id}/progress-summary/

    Écran S8 "تقدمي" : répartition des skills (متقنة / قيد التقدم / لم تبدأ),
    activité des 7 derniers jours et erreurs par catégorie.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, student_id):
        student = get_object_or_404(User, pk=student_id)
        _ensure_can_act_for_student(request, student)

        skills_qs = student_path.subjects_with_skills_query(student)
        total = skills_qs.count()
        progress_qs = StudentProgress.objects.filter(student=student, skill__in=skills_qs)
        mastered = progress_qs.filter(status=StudentProgress.Status.MASTERED).count()
        in_progress = progress_qs.filter(status=StudentProgress.Status.IN_PROGRESS).count()

        today = timezone.localdate()
        start = today - timedelta(days=6)
        per_day = {
            row['day']: row
            for row in LogAnswer.objects.filter(student=student, timestamp__date__gte=start)
            .annotate(day=TruncDate('timestamp'))
            .values('day')
            .annotate(attempts=Count('id'), correct=Count('id', filter=Q(is_correct=True)))
        }
        weekly = []
        for offset in range(7):
            day = start + timedelta(days=offset)
            row = per_day.get(day, {})
            weekly.append({
                'date': day.isoformat(),
                'attempts': row.get('attempts', 0),
                'correct': row.get('correct', 0),
            })

        errors = {c.value: 0 for c in ErrorCategory}
        for row in (
            LogAnswer.objects.filter(student=student, is_correct=False)
            .values('error_type').annotate(n=Count('id'))
        ):
            if row['error_type'] in errors:
                errors[row['error_type']] = row['n']

        return Response({
            'skills_total': total,
            'skills_mastered': mastered,
            'skills_in_progress': in_progress,
            'skills_not_started': max(0, total - mastered - in_progress),
            'completion': round(mastered / total, 2) if total else 0.0,
            'weekly_activity': weekly,
            'errors_by_category': errors,
            'streak_days': _streak_days(student),
        })


class EngineSettingsView(APIView):
    """
    GET/PATCH /api/assessment/engine-settings/

    Section 11 du guide MVP : seuils Low/High, streak requis, minimum de
    tentatives et taille des groupes. Lecture : enseignants/admins ;
    modification : administrateurs.
    """
    permission_classes = [IsTeacherOrAdmin]

    def get(self, request):
        return Response(EngineSettingsSerializer(EngineSettings.load()).data)

    def patch(self, request):
        if request.user.role not in (User.Role.ADMIN, User.Role.REGIONAL_ADMIN):
            raise PermissionDenied("Seuls les administrateurs peuvent modifier les paramètres du moteur.")
        serializer = EngineSettingsSerializer(EngineSettings.load(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    put = patch


class StudentLearningTraceView(APIView):
    """
    GET /api/students/{id}/learning-trace/?skill=<skill_id>

    Student Learning Trace (section 9) : évaluations, décisions,
    interventions (mastery avant / après) et retours aux skills préalables.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, student_id):
        student = get_object_or_404(User, pk=student_id)
        _ensure_can_act_for_student(request, student)

        traces = LearningTrace.objects.filter(student=student).select_related('skill', 'intervention')
        returns = PrerequisiteReturn.objects.filter(student=student).select_related(
            'student', 'from_skill', 'to_skill', 'reviewed_by',
        )
        skill_id = request.query_params.get('skill')
        if skill_id:
            traces = traces.filter(skill_id=skill_id)
            returns = returns.filter(Q(from_skill_id=skill_id) | Q(to_skill_id=skill_id))
        return Response({
            'evaluations': LearningTraceSerializer(traces, many=True).data,
            'prerequisite_returns': PrerequisiteReturnSerializer(returns, many=True).data,
        })


class ReviewCaseViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                        mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """
    /api/assessment/review-cases/

    Section 8.3 : cas où les exercices d'une skill sont épuisés sans
    maîtrise et sans skill préalable adaptée -> revue par l'enseignant.
    Filtre `status` (par défaut : teacher_review). PATCH avec
    {"review_note": "..."} marque le cas comme revu.
    """
    serializer_class = PrerequisiteReturnSerializer
    permission_classes = [IsTeacherOrAdmin]
    filterset_fields = ['student', 'from_skill', 'status']

    def get_queryset(self):
        qs = PrerequisiteReturn.objects.select_related('student', 'from_skill', 'to_skill', 'reviewed_by')
        if self.action == 'list' and 'status' not in self.request.query_params:
            qs = qs.filter(status=PrerequisiteReturn.Status.TEACHER_REVIEW)
        return qs

    def perform_update(self, serializer):
        instance = serializer.instance
        extra = {}
        if instance.status == PrerequisiteReturn.Status.TEACHER_REVIEW:
            extra = {
                'status': PrerequisiteReturn.Status.REVIEWED,
                'resolved_at': timezone.now(),
            }
        serializer.save(reviewed_by=self.request.user, **extra)
