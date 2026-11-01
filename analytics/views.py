"""
analytics/views.py

Implémente les deux requêtes du scénario "Ahmed / Sarah" (Partie 6,
Étapes 12 et 13) : tableau de bord de classe et analyse détaillée des
erreurs d'un étudiant. Aucune table dédiée : tout est calculé à la volée
(voir Partie 7.3, "Points de vigilance").
"""

from datetime import timedelta

from django.db.models import Avg, Count, Max, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db.models.functions import TruncDate

from assessment.models import ErrorCategory, LogAnswer, StudentProgress
from curriculum.models import Goal, Lesson, Unit
from skills.models import Chunk, Skill
from users.models import User, Wilaya
from .serializers import (
    ClassDashboardRowSerializer,
    StudentErrorAnalysisRowSerializer,
    ReportsOverviewSerializer,
    ReportsUsageSerializer,
    TeacherDashboardOverviewSerializer,
    UnitPerformanceRowSerializer,
)


class IsTeacherOrAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in (User.Role.TEACHER, User.Role.REGIONAL_ADMIN, User.Role.ADMIN)
        )


class IsAdminOrRegionalAdmin(permissions.BasePermission):
    """
    Réservé aux administrateurs système/régionaux - pas aux enseignants.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in (User.Role.REGIONAL_ADMIN, User.Role.ADMIN)
        )


# Seuils du signal "يحتاجون متابعة" (écrans Teacher / T10).
ATTENTION_INACTIVE_DAYS = 5
ATTENTION_CONCEPT_ERRORS = 3
ATTENTION_LOW_MASTERY = 0.5


def _attention_reason(row):
    """
    Raison principale pour laquelle un étudiant a besoin d'un suivi, par
    ordre de priorité ; None si tout va bien.
    """
    if row['concept_errors_14d'] >= ATTENTION_CONCEPT_ERRORS:
        return 'concept_errors'
    if row['blocked_skills'] > 0:
        return 'redirects'
    if row['inactive_days'] is not None and row['inactive_days'] >= ATTENTION_INACTIVE_DAYS:
        return 'inactive'
    if row['skills_started'] and row['average_mastery'] < ATTENTION_LOW_MASTERY:
        return 'low_mastery'
    return None


def _students_progress_rows(level_id=None):
    """
    Ligne par étudiant : nombre de skills commencées/maîtrisées, mastery
    moyen et dernière activité. Partagé par ClassDashboardView et
    TeacherDashboardStudentsProgressView (Étape 12 du scénario).
    Inclut le signal de suivi (needs_attention / attention_reason).
    """
    students = User.objects.filter(role=User.Role.STUDENT).select_related('wilaya')

    if level_id:
        students = students.filter(student_profile__level_id=level_id)

    since_14d = timezone.now() - timedelta(days=14)
    concept_errors = dict(
        LogAnswer.objects.filter(
            student__in=students, is_correct=False,
            error_type=ErrorCategory.CONCEPT, timestamp__gte=since_14d,
        ).values('student').annotate(n=Count('id')).values_list('student', 'n')
    )
    blocked = dict(
        StudentProgress.objects.filter(student__in=students, attempts__gte=3, mastery__lt=0.5)
        .exclude(status=StudentProgress.Status.MASTERED)
        .values('student').annotate(n=Count('id')).values_list('student', 'n')
    )
    today = timezone.now()

    students = students.annotate(
        skills_started=Count('progress__skill', distinct=True),
        skills_mastered=Count(
            'progress__skill',
            filter=Q(progress__status=StudentProgress.Status.MASTERED),
            distinct=True,
        ),
        average_mastery=Avg('progress__mastery'),
        last_active=Max('progress__last_activity'),
    ).order_by('-average_mastery')

    rows = []
    for s in students:
        row = {
            'student_id': s.id,
            'username': s.username,
            'first_name': s.first_name,
            'last_name': s.last_name,
            'skills_started': s.skills_started,
            'skills_mastered': s.skills_mastered,
            'average_mastery': float(s.average_mastery) if s.average_mastery is not None else 0.0,
            'last_active': s.last_active,
            'wilaya_name': s.wilaya.name if s.wilaya else None,
            'inactive_days': (today - s.last_active).days if s.last_active else None,
            'concept_errors_14d': concept_errors.get(s.id, 0),
            'blocked_skills': blocked.get(s.id, 0),
        }
        row['attention_reason'] = _attention_reason(row)
        row['needs_attention'] = row['attention_reason'] is not None
        rows.append(row)
    return rows


def _incomplete_skills():
    """Skills sans le minimum de chunks (1 rule, 1 example, 2 practice)."""
    return Skill.objects.annotate(
        n_rule=Count('chunks', filter=Q(chunks__chunk_type=Chunk.ChunkType.RULE)),
        n_example=Count('chunks', filter=Q(chunks__chunk_type=Chunk.ChunkType.EXAMPLE)),
        n_practice=Count('chunks', filter=Q(chunks__chunk_type=Chunk.ChunkType.PRACTICE)),
    ).filter(Q(n_rule__lt=1) | Q(n_example__lt=1) | Q(n_practice__lt=2))


def _daily_activity(logs, days):
    """Tentatives / réponses correctes par jour sur la fenêtre (graphe "النشاط")."""
    start = timezone.localdate() - timedelta(days=days - 1)
    per_day = {
        row['day']: row
        for row in logs.annotate(day=TruncDate('timestamp')).values('day')
        .annotate(attempts=Count('id'), correct=Count('id', filter=Q(is_correct=True)))
    }
    out = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        row = per_day.get(day, {})
        out.append({'date': day.isoformat(), 'attempts': row.get('attempts', 0), 'correct': row.get('correct', 0)})
    return out


class ClassDashboardView(APIView):
    """
    GET /api/analytics/class-dashboard/?level=<id>

    Équivalent de la requête agrégée de l'Étape 12 : pour chaque
    étudiant, nombre de skills commencées, nombre de skills maîtrisées,
    mastery moyen, dernière activité.
    """
    permission_classes = [IsTeacherOrAdmin]

    def get(self, request):
        rows = _students_progress_rows(level_id=request.query_params.get('level'))
        serializer = ClassDashboardRowSerializer(rows, many=True)
        return Response(serializer.data)


class StudentErrorAnalysisView(APIView):
    """
    GET /api/analytics/students/<student_id>/error-analysis/?days=7

    Équivalent de la requête de l'Étape 13 : erreurs récentes d'un
    étudiant, groupées par skill / catégorie / détail d'erreur.
    """
    permission_classes = [IsTeacherOrAdmin]

    def get(self, request, student_id):
        student = get_object_or_404(User, pk=student_id, role=User.Role.STUDENT)

        days = int(request.query_params.get('days', 7))
        since = timezone.now() - timedelta(days=days)

        qs = (
            LogAnswer.objects
            .filter(student=student, is_correct=False, timestamp__gte=since)
            .values(
                'skill__name',
                'error_type',
                'error_detail__code',
                'error_detail__root_cause',
                'error_detail__severity_level',
            )
            .annotate(occurrences=Count('id'))
            .order_by('-occurrences')
        )

        rows = [
            {
                'skill_name': r['skill__name'],
                'error_category': r['error_type'],
                'error_code': r['error_detail__code'],
                'root_cause': r['error_detail__root_cause'],
                'severity_level': r['error_detail__severity_level'],
                'occurrences': r['occurrences'],
            }
            for r in qs
        ]
        serializer = StudentErrorAnalysisRowSerializer(rows, many=True)
        return Response(serializer.data)


class ReportsOverviewView(APIView):
    """
    GET /api/analytics/reports/

    Rapport global du système, réservé aux administrateurs : effectifs,
    contenu publié et progression moyenne.
    """
    permission_classes = [IsAdminOrRegionalAdmin]

    def get(self, request):
        data = {
            'total_users': User.objects.count(),
            'total_students': User.objects.filter(role=User.Role.STUDENT).count(),
            'total_teachers': User.objects.filter(role=User.Role.TEACHER).count(),
            'total_units': Unit.objects.count(),
            'published_units': Unit.objects.filter(is_published=True).count(),
            'total_skills': Skill.objects.count(),
            'total_attempts': LogAnswer.objects.count(),
            'correct_attempts': LogAnswer.objects.filter(is_correct=True).count(),
            'mastered_skills_count': StudentProgress.objects.filter(
                status=StudentProgress.Status.MASTERED
            ).count(),
            'overall_average_mastery': (
                StudentProgress.objects.aggregate(avg=Avg('mastery'))['avg'] or 0.0
            ),
            'incomplete_skills': _incomplete_skills().count(),
        }
        return Response(ReportsOverviewSerializer(data).data)


class ReportsUsageView(APIView):
    """
    GET /api/analytics/reports/usage/?days=7

    Statistiques d'usage sur une fenêtre glissante, réservé aux
    administrateurs.
    """
    permission_classes = [IsAdminOrRegionalAdmin]

    def get(self, request):
        days = int(request.query_params.get('days', 7))
        since = timezone.now() - timedelta(days=days)

        period_logs = LogAnswer.objects.filter(timestamp__gte=since)
        total_attempts = period_logs.count()
        active_students = period_logs.values('student').distinct().count()

        data = {
            'period_days': days,
            'new_registrations': User.objects.filter(date_joined__gte=since).count(),
            'active_students': active_students,
            'active_users_by_login': User.objects.filter(last_login__gte=since).count(),
            'total_attempts': total_attempts,
            'correct_attempts': period_logs.filter(is_correct=True).count(),
            'average_attempts_per_active_student': (
                round(total_attempts / active_students, 2) if active_students else 0.0
            ),
            'daily': _daily_activity(period_logs, days),
        }
        return Response(ReportsUsageSerializer(data).data)


class TeacherDashboardOverviewView(APIView):
    """
    GET /api/analytics/teacher-dashboard/
    GET /api/analytics/teacher-dashboard/overview/?level=<id>

    Vue d'ensemble pour l'enseignant : effectifs, activité récente et
    progression moyenne, filtrable par niveau.
    """
    permission_classes = [IsTeacherOrAdmin]

    def get(self, request):
        students = User.objects.filter(role=User.Role.STUDENT)
        level_id = request.query_params.get('level')
        if level_id:
            students = students.filter(student_profile__level_id=level_id)

        since = timezone.now() - timedelta(days=7)
        progress_qs = StudentProgress.objects.filter(student__in=students)

        data = {
            'total_students': students.count(),
            'active_students_7d': (
                LogAnswer.objects.filter(student__in=students, timestamp__gte=since)
                .values('student').distinct().count()
            ),
            'average_mastery': progress_qs.aggregate(avg=Avg('mastery'))['avg'] or 0.0,
            'mastered_skills_total': progress_qs.filter(
                status=StudentProgress.Status.MASTERED
            ).count(),
            'attempts_7d': LogAnswer.objects.filter(
                student__in=students, timestamp__gte=since
            ).count(),
        }
        return Response(TeacherDashboardOverviewSerializer(data).data)


class TeacherDashboardStudentsProgressView(APIView):
    """
    GET /api/analytics/teacher-dashboard/students-progress/?level=<id>

    Même contenu que class-dashboard, exposé sous l'espace de noms
    teacher-dashboard pour le frontend enseignant.
    """
    permission_classes = [IsTeacherOrAdmin]

    def get(self, request):
        rows = _students_progress_rows(level_id=request.query_params.get('level'))
        return Response(ClassDashboardRowSerializer(rows, many=True).data)


class TeacherDashboardUnitsPerformanceView(APIView):
    """
    GET /api/analytics/teacher-dashboard/units-performance/?subject=<id>

    Pour chaque unité : nombre de skills, tentatives et mastery moyen des
    étudiants sur les skills qui la composent.
    """
    permission_classes = [IsTeacherOrAdmin]

    def get(self, request):
        units = Unit.objects.select_related('subject').all()
        subject_id = request.query_params.get('subject')
        if subject_id:
            units = units.filter(subject_id=subject_id)

        rows = []
        for unit in units:
            skill_ids = list(
                Skill.objects.filter(goal__lesson__unit=unit).values_list('id', flat=True)
            )
            progress_qs = StudentProgress.objects.filter(skill_id__in=skill_ids)
            rows.append({
                'unit_id': unit.id,
                'unit_code': unit.code,
                'unit_title': unit.title,
                'skills_count': len(skill_ids),
                'average_mastery': progress_qs.aggregate(avg=Avg('mastery'))['avg'] or 0.0,
                'students_mastered': progress_qs.filter(
                    status=StudentProgress.Status.MASTERED
                ).values('student').distinct().count(),
                'attempts_count': LogAnswer.objects.filter(skill_id__in=skill_ids).count(),
            })

        return Response(UnitPerformanceRowSerializer(rows, many=True).data)


class StudentSummaryView(APIView):
    """
    GET /api/analytics/students/<student_id>/summary/

    Écran T11 : indicateurs d'un étudiant (الإتقان · مهارات بدأها ·
    محاولات · نسبة الخطأ الإهمالي) et erreurs par catégorie. Le détail des
    erreurs les plus fréquentes est servi par error-analysis.
    """
    permission_classes = [IsTeacherOrAdmin]

    def get(self, request, student_id):
        student = get_object_or_404(User, pk=student_id, role=User.Role.STUDENT)
        progress_qs = StudentProgress.objects.filter(student=student)
        logs = LogAnswer.objects.filter(student=student)
        wrong = logs.filter(is_correct=False)

        errors = {c.value: 0 for c in ErrorCategory}
        for row in wrong.values('error_type').annotate(n=Count('id')):
            if row['error_type'] in errors:
                errors[row['error_type']] = row['n']
        total_errors = sum(errors.values())

        return Response({
            'student_id': student.id,
            'username': student.username,
            'first_name': student.first_name,
            'last_name': student.last_name,
            'wilaya_name': student.wilaya.name if student.wilaya else None,
            'average_mastery': float(progress_qs.aggregate(avg=Avg('mastery'))['avg'] or 0.0),
            'skills_started': progress_qs.filter(attempts__gt=0).count(),
            'skills_mastered': progress_qs.filter(status=StudentProgress.Status.MASTERED).count(),
            'attempts': logs.count(),
            'correct_attempts': logs.filter(is_correct=True).count(),
            'careless_ratio': round(errors[ErrorCategory.CARELESS] / total_errors, 2) if total_errors else 0.0,
            'errors_by_category': errors,
            'last_active': progress_qs.aggregate(last=Max('last_activity'))['last'],
        })


class ReportsAttentionView(APIView):
    """
    GET /api/analytics/reports/attention/

    Bloc "يحتاج انتباهًا" du tableau de bord admin : contenu qui empêche
    la publication (leçon sans goal, skill sans assez de chunks, unité non
    publiée).
    """
    permission_classes = [IsAdminOrRegionalAdmin]

    def get(self, request):
        items = []

        lessons = Lesson.objects.select_related('unit').annotate(
            n_conceptual=Count('goals', filter=Q(goals__goal_type=Goal.GoalType.CONCEPTUAL)),
            n_operational=Count('goals', filter=Q(goals__goal_type=Goal.GoalType.OPERATIONAL)),
        ).filter(Q(n_conceptual=0) | Q(n_operational=0))
        for lesson in lessons[:10]:
            items.append({
                'kind': 'lesson_missing_goal',
                'code': lesson.code,
                'missing': (
                    Goal.GoalType.OPERATIONAL if lesson.n_conceptual else Goal.GoalType.CONCEPTUAL
                ),
                'unit_id': lesson.unit_id,
                'lesson_id': lesson.id,
            })

        for skill in _incomplete_skills().select_related('goal__lesson')[:10]:
            items.append({
                'kind': 'skill_incomplete_chunks',
                'code': skill.code,
                'practice': skill.n_practice,
                'rule': skill.n_rule,
                'example': skill.n_example,
                'unit_id': skill.goal.lesson.unit_id,
                'lesson_id': skill.goal.lesson_id,
            })

        for unit in Unit.objects.filter(is_published=False)[:10]:
            items.append({'kind': 'unit_unpublished', 'code': unit.code, 'unit_id': unit.id})

        return Response(items)


class ReportsByWilayaView(APIView):
    """
    GET /api/analytics/reports/by-wilaya/

    Écran A7 "متوسط الإتقان حسب الولاية" : mastery moyen et effectif des
    étudiants par wilaya.
    """
    permission_classes = [IsAdminOrRegionalAdmin]

    def get(self, request):
        rows = []
        for wilaya in Wilaya.objects.all():
            students = User.objects.filter(role=User.Role.STUDENT, wilaya=wilaya)
            avg = StudentProgress.objects.filter(student__in=students).aggregate(avg=Avg('mastery'))['avg']
            rows.append({
                'wilaya_id': wilaya.id,
                'wilaya_name': wilaya.name,
                'students': students.count(),
                'average_mastery': float(avg) if avg is not None else None,
            })
        rows.sort(key=lambda r: (r['average_mastery'] is None, -(r['average_mastery'] or 0)))
        return Response(rows)
