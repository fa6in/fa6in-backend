"""
curriculum/views.py
"""

from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

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


class StageViewSet(viewsets.ModelViewSet):
    queryset = Stage.objects.all()
    serializer_class = StageSerializer
    permission_classes = [IsTeacherOrAdminOrReadOnly]
    search_fields = ['name', 'code']


class LevelViewSet(viewsets.ModelViewSet):
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

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """
        Publie la leçon après vérification de la règle métier
        (exactement 1 Goal Conceptual + 1 Goal Operational).
        """
        lesson = self.get_object()
        c = lesson.goals.filter(goal_type=Goal.GoalType.CONCEPTUAL).count()
        o = lesson.goals.filter(goal_type=Goal.GoalType.OPERATIONAL).count()
        if c != 1 or o != 1:
            return Response(
                {
                    'detail': "Publication refusée : la leçon doit avoir exactement "
                              "1 Goal Conceptual et 1 Goal Operational.",
                    'conceptual_count': c,
                    'operational_count': o,
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
