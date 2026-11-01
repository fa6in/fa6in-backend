"""
assessment/views.py
"""

from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets, permissions, mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from curriculum.models import Unit
from curriculum.views import IsTeacherOrAdminOrReadOnly
from skills.models import Skill, Prerequisite, Chunk
from skills.serializers import ChunkSerializer
from users.models import User
from . import engine, path as student_path
from .models import Error, ErrorCategory, StudentProgress, LogAnswer
from .serializers import ErrorSerializer, StudentProgressSerializer, LogAnswerSerializer


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


# Message affiché sur la fiche d'erreur (écran S5) quand le catalogue Error
# n'a pas d'entrée pour la skill / catégorie.
DEFAULT_ERROR_FEEDBACK = {
    ErrorCategory.CONCEPT: "يبدو أن الفكرة الأساسية تحتاج إلى مراجعة. أعد قراءة القاعدة ثم حاول مرة أخرى.",
    ErrorCategory.PROCEDURE: "فهمت الفكرة لكن خطوات الحل غير صحيحة. راجع المثال خطوة بخطوة.",
    ErrorCategory.CARELESS: "أجبت بسرعة كبيرة. خذ وقتك وتحقق من إجابتك قبل الإرسال.",
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
    return {
        'skill': {
            'id': skill.id,
            'code': skill.code,
            'name': skill.name,
            'skill_type': skill.skill_type,
            'mastery_threshold': skill.mastery_threshold,
            'required_consecutive_correct': skill.required_consecutive_correct,
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
        if not progress or progress.attempts < engine.REDIRECT_MIN_ATTEMPTS \
                or float(progress.mastery) >= engine.REDIRECT_MASTERY_CEILING:
            return Response({'blocked': False, 'recommendation': None})

        # Même règle que le Decision Engine (prérequis non maîtrisé le plus faible).
        redirect = engine.find_prerequisite_redirect(student, skill)
        if redirect is None:
            return Response({'blocked': True, 'recommendation': None, 'detail': "Aucun prérequis disponible."})
        return Response({
            'blocked': True,
            'recommendation': {
                'skill_id': redirect['new_skill'].id,
                'skill_code': redirect['new_skill'].code,
                'mastery': redirect['new_mastery'],
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

        was_mastered = progress.status == StudentProgress.Status.MASTERED
        progress.register_attempt(is_correct=is_correct, error_category=error_type)
        mastered_now = not was_mastered and progress.status == StudentProgress.Status.MASTERED

        # Écran S5 (fiche d'erreur) : explication + exemple de la skill.
        feedback = None
        if not is_correct:
            example = skill.chunks.filter(chunk_type=Chunk.ChunkType.EXAMPLE).order_by('order_index').first()
            rule = skill.chunks.filter(chunk_type=Chunk.ChunkType.RULE).order_by('order_index').first()
            feedback = {
                'category': error_type,
                'message': (
                    (error_detail.feedback_message or error_detail.root_cause) if error_detail
                    else DEFAULT_ERROR_FEEDBACK.get(error_type)
                ),
                'example': example.content if example else None,
                'rule': rule.content if rule else None,
            }

        # Écran S6 : bloqué (>= 3 tentatives, mastery < 0.5) -> prérequis à revoir.
        redirect = None
        if not is_correct:
            found = engine.find_prerequisite_redirect(student, skill)
            if found is not None:
                redirect = {
                    'skill': {
                        'id': found['new_skill'].id,
                        'code': found['new_skill'].code,
                        'name': found['new_skill'].name,
                    },
                    'attempts': progress.attempts,
                    'mastery': progress.mastery,
                }

        # Écran S7 : skill maîtrisée -> points gagnés + skill suivante débloquée.
        next_skill = None
        points = None
        if mastered_now:
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

        return Response({
            'is_correct': is_correct,
            'error_type': error_type,
            'error_detail': ErrorSerializer(error_detail).data if error_detail else None,
            'feedback': feedback,
            'progress': {
                'attempts': progress.attempts,
                'correct_count': progress.correct_count,
                'mastery': progress.mastery,
                'consecutive_correct': progress.consecutive_correct,
                'status': progress.status,
            },
            'mastered_now': mastered_now,
            'points': points,
            'next_skill': next_skill,
            'redirect': redirect,
            'session': _session_context(skill, progress),
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
            # Même logique que ci-dessous : on sert la 'rule' du prérequis,
            # donc on marque rule_seen pour SA progression à lui (pas celle
            # de `skill`), afin que le prochain passage sur ce prérequis
            # n'y reste pas non plus bloqué en boucle sur l'onboarding.
            new_skill_progress, _c = StudentProgress.objects.get_or_create(
                student=student, skill=redirect['new_skill'],
            )
            if redirect['chunk'] and redirect['chunk'].chunk_type == Chunk.ChunkType.RULE:
                if not new_skill_progress.rule_seen:
                    new_skill_progress.rule_seen = True
                    new_skill_progress.save(update_fields=['rule_seen'])

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
                'session': _session_context(redirect['new_skill'], new_skill_progress),
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

        # Le fait de SERVIR un chunk 'rule'/'example' constitue, côté
        # Backend, la preuve que l'étudiant y a été exposé (ces types ne
        # passent jamais par /answer/, donc rien d'autre ne peut
        # l'enregistrer). On persiste ça avant de répondre :
        #
        # 1. rule_seen / example_seen -> fait avancer l'onboarding
        #    (rule -> example -> practice) sans AUCUNE logique côté
        #    Frontend, qui reçoit juste "voici le chunk à afficher".
        # 2. last_error_type -> remis à None une fois le rappel montré,
        #    sinon last_error_type=='concept' bloquerait pick_next_chunk
        #    sur RULE indéfiniment (un chunk que /answer/ refuse).
        update_fields = []
        if chunk and chunk.chunk_type == Chunk.ChunkType.RULE and not progress.rule_seen:
            progress.rule_seen = True
            update_fields.append('rule_seen')
        if chunk and chunk.chunk_type == Chunk.ChunkType.EXAMPLE and not progress.example_seen:
            progress.example_seen = True
            update_fields.append('example_seen')
        if progress.last_error_type and chunk and chunk.chunk_type != Chunk.ChunkType.PRACTICE:
            progress.last_error_type = None
            update_fields.append('last_error_type')
        if update_fields:
            progress.save(update_fields=update_fields)

        return Response({
            'action': 'show_chunk',
            'current_skill': {'id': skill.id, 'code': skill.code},
            'chunk': ChunkSerializer(chunk, context={'request': request}).data if chunk else None,
            'context': {
                'reason': reason,
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
            redirect = engine.find_prerequisite_redirect(student, get_object_or_404(Skill, pk=resume['skill']['id']))
            if redirect is not None:
                suggestion = {
                    'skill': {
                        'id': redirect['new_skill'].id,
                        'code': redirect['new_skill'].code,
                        'name': redirect['new_skill'].name,
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
