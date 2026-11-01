"""
curriculum/views.py
"""

from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from skills.publishing import lesson_publication_checks
from users.models import User
from .models import Stage, Level, Subject, Unit, Lesson, Goal
from .serializers import (
    StageSerializer,
    LevelSerializer,
    SubjectSerializer,
    UnitListSerializer,
    UnitDetailSerializer,
    LessonListSerializer,
    LessonDetailSerializer,
    GoalSerializer,
)


class IsTeacherOrAdminOrReadOnly(permissions.BasePermission):
    """
    Lecture ouverte à tous les utilisateurs authentifiés.
    Écriture réservée aux enseignants, admins régionaux et admins.
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return request.user and request.user.is_authenticated
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in (User.Role.TEACHER, User.Role.REGIONAL_ADMIN, User.Role.ADMIN)
        )


class PublicReadMixin:
    """
    Lecture publique (formulaire d'inscription : choix de l'année scolaire),
    écriture réservée aux enseignants / admins.
    """

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.AllowAny()]
        return super().get_permissions()


class StageViewSet(PublicReadMixin, viewsets.ModelViewSet):
    queryset = Stage.objects.all()
    serializer_class = StageSerializer
    permission_classes = [IsTeacherOrAdminOrReadOnly]
    search_fields = ['name', 'code']


class LevelViewSet(PublicReadMixin, viewsets.ModelViewSet):
    queryset = Level.objects.select_related('stage').all()
    serializer_class = LevelSerializer
    permission_classes = [IsTeacherOrAdminOrReadOnly]
    filterset_fields = ['stage']
    search_fields = ['name', 'code']


class SubjectViewSet(viewsets.ModelViewSet):
    queryset = Subject.objects.select_related('level').all()
    serializer_class = SubjectSerializer
    permission_classes = [IsTeacherOrAdminOrReadOnly]
    filterset_fields = ['level', 'is_active']
    search_fields = ['name']


class UnitViewSet(viewsets.ModelViewSet):
    queryset = Unit.objects.select_related('subject', 'created_by').all()
    permission_classes = [IsTeacherOrAdminOrReadOnly]
    filterset_fields = ['subject', 'is_published']
    search_fields = ['code', 'title', 'central_question']

    def get_serializer_class(self):
        if self.action == 'list':
            return UnitListSerializer
        return UnitDetailSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """
        POST /api/curriculum/units/<id>/publish/
        Une unité n'est visible par les étudiants qu'une fois publiée, et
        seulement si au moins une de ses leçons l'est.
        """
        unit = self.get_object()
        if not unit.lessons.filter(is_published=True).exists():
            return Response(
                {'detail': "Publication refusée : l'unité doit contenir au moins une leçon publiée."},
                status=400,
            )
        unit.is_published = True
        unit.save(update_fields=['is_published'])
        return Response(UnitDetailSerializer(unit, context={'request': request}).data)

    @action(detail=True, methods=['get'])
    def sections(self, request, pk=None):
        """
        GET /api/curriculum/units/<id>/sections/
        Les "sections" d'une unité correspondent à ses leçons.
        """
        unit = self.get_object()
        lessons = unit.lessons.all()
        return Response(LessonListSerializer(lessons, many=True).data)


class LessonViewSet(viewsets.ModelViewSet):
    queryset = Lesson.objects.select_related('unit').prefetch_related('goals').all()
    permission_classes = [IsTeacherOrAdminOrReadOnly]
    filterset_fields = ['unit', 'is_published']
    search_fields = ['code', 'title']

    def get_serializer_class(self):
        if self.action == 'list':
            return LessonListSerializer
        return LessonDetailSerializer

    @action(detail=True, methods=['get'])
    def publication_check(self, request, pk=None):
        """
        GET /api/curriculum/lessons/<id>/publication_check/
        Liste de contrôle de l'écran T9 (voir skills/publishing.py).
        """
        return Response(lesson_publication_checks(self.get_object()))

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """
        Publie la leçon si toutes les règles de publication sont respectées
        (goals, types des skills, absence de cycle, chunks suffisants).
        """
        lesson = self.get_object()
        result = lesson_publication_checks(lesson)
        if not result['ready']:
            return Response(
                {
                    'detail': "Publication refusée : la leçon ne respecte pas les règles de publication.",
                    'conceptual_count': lesson.goals.filter(goal_type=Goal.GoalType.CONCEPTUAL).count(),
                    'operational_count': lesson.goals.filter(goal_type=Goal.GoalType.OPERATIONAL).count(),
                    **result,
                },
                status=400,
            )
        lesson.is_published = True
        lesson.save()
        return Response(LessonDetailSerializer(lesson).data)


class GoalViewSet(viewsets.ModelViewSet):
    queryset = Goal.objects.select_related('lesson').all()
    serializer_class = GoalSerializer
    permission_classes = [IsTeacherOrAdminOrReadOnly]
    filterset_fields = ['lesson', 'goal_type']
