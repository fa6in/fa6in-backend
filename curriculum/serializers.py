"""
curriculum/serializers.py
"""

from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Stage, Level, Subject, Unit, Lesson, Goal

User = get_user_model()


class UserMiniSerializer(serializers.ModelSerializer):
    """Version allégée du user, pour les FK created_by, etc."""
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name']


class StageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Stage
        fields = ['id', 'name', 'code', 'order_index', 'description']


class LevelSerializer(serializers.ModelSerializer):
    stage_name = serializers.CharField(source='stage.name', read_only=True)

    class Meta:
        model = Level
        fields = ['id', 'stage', 'stage_name', 'name', 'code', 'order_index', 'description']

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['stage'] = StageSerializer(instance.stage).data
        return rep


class SubjectSerializer(serializers.ModelSerializer):
    level_name = serializers.CharField(source='level.name', read_only=True)

    class Meta:
        model = Subject
        fields = [
            'id', 'level', 'level_name', 'name', 'description',
            'color', 'icon', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['level'] = LevelSerializer(instance.level).data
        return rep


class UnitListSerializer(serializers.ModelSerializer):
    """Version allégée pour les listes."""
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    lessons_count = serializers.IntegerField(source='lessons.count', read_only=True)

    class Meta:
        model = Unit
        fields = [
            'id', 'code', 'title', 'subject', 'subject_name',
            'order_index', 'is_published', 'thumbnail', 'lessons_count',
        ]

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['subject'] = SubjectSerializer(instance.subject).data
        return rep


class UnitDetailSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Unit
        fields = [
            'id', 'code', 'title', 'description', 'subject', 'subject_name',
            'main_goal_description', 'central_question', 'main_skill_domain',
            'order_index', 'is_published', 'thumbnail', 'created_by',
            'created_by_username', 'created_at',
        ]
        read_only_fields = ['created_at', 'created_by']

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['subject'] = SubjectSerializer(instance.subject).data
        rep['created_by'] = (
            UserMiniSerializer(instance.created_by).data if instance.created_by else None
        )
        return rep


class GoalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Goal
        fields = ['id', 'lesson', 'goal_type', 'title', 'description', 'order_index', 'created_at']
        read_only_fields = ['created_at']

    def validate(self, attrs):
        """
        Empêche la création de deux Goals du même type pour la même Lesson
        (Partie 4, Règle 1 : exactement 1 Conceptual + 1 Operational par Lesson).
        """
        lesson = attrs.get('lesson') or getattr(self.instance, 'lesson', None)
        goal_type = attrs.get('goal_type') or getattr(self.instance, 'goal_type', None)
        qs = Goal.objects.filter(lesson=lesson, goal_type=goal_type)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                f"Cette leçon a déjà un Goal de type '{goal_type}'."
            )
        return attrs

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['lesson'] = LessonListSerializer(instance.lesson).data
        return rep


class LessonListSerializer(serializers.ModelSerializer):
    goals_complete = serializers.SerializerMethodField()

    class Meta:
        model = Lesson
        fields = [
            'id', 'code', 'title', 'unit', 'order_index',
            'is_published', 'goals_complete',
        ]

    def get_goals_complete(self, obj):
        c = obj.goals.filter(goal_type=Goal.GoalType.CONCEPTUAL).count()
        o = obj.goals.filter(goal_type=Goal.GoalType.OPERATIONAL).count()
        return c == 1 and o == 1

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['unit'] = UnitListSerializer(instance.unit).data
        return rep


class LessonDetailSerializer(serializers.ModelSerializer):
    goals = GoalSerializer(many=True, read_only=True)
    unit_title = serializers.CharField(source='unit.title', read_only=True)

    class Meta:
        model = Lesson
        fields = [
            'id', 'code', 'title', 'description', 'unit', 'unit_title',
            'order_index', 'is_published', 'created_at', 'goals',
        ]
        read_only_fields = ['created_at']

    def validate(self, attrs):
        is_published = attrs.get('is_published', getattr(self.instance, 'is_published', False))
        if is_published and self.instance:
            c = self.instance.goals.filter(goal_type=Goal.GoalType.CONCEPTUAL).count()
            o = self.instance.goals.filter(goal_type=Goal.GoalType.OPERATIONAL).count()
            if c != 1 or o != 1:
                raise serializers.ValidationError(
                    "Impossible de publier : la leçon doit avoir exactement "
                    "1 Goal Conceptual et 1 Goal Operational."
                )
        return attrs

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['unit'] = UnitListSerializer(instance.unit).data
        return rep
