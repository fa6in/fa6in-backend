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

from assessment.models import LogAnswer, StudentProgress
from curriculum.models import Unit
from skills.models import Skill
from users.models import User
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


def _students_progress_rows(level_id=None):
    """
    Ligne par étudiant : nombre de skills commencées/maîtrisées, mastery
    moyen et dernière activité. Partagé par ClassDashboardView et
    TeacherDashboardStudentsProgressView (Étape 12 du scénario).
    """
    students = User.objects.filter(role=User.Role.STUDENT)

    if level_id:
        students = students.filter(student_profile__level_id=level_id)

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

    return [
        {
            'student_id': s.id,
            'username': s.username,
            'first_name': s.first_name,
            'last_name': s.last_name,
            'skills_started': s.skills_started,
            'skills_mastered': s.skills_mastered,
            'average_mastery': float(s.average_mastery) if s.average_mastery is not None else 0.0,
            'last_active': s.last_active,
        }
        for s in students
    ]


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
