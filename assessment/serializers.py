"""
assessment/serializers.py
"""

from rest_framework import serializers

from .models import (
    EngineSettings, Error, ExerciseGroup, LearningTrace, LogAnswer, PrerequisiteReturn, StudentProgress,
)


class ErrorSerializer(serializers.ModelSerializer):
    skill_code = serializers.CharField(source='skill.code', read_only=True)

    class Meta:
        model = Error
        fields = [
            'id', 'skill', 'skill_code', 'code', 'category', 'error_type',
            'root_cause', 'severity_level', 'feedback_message', 'created_at',
        ]
        read_only_fields = ['created_at']


class StudentProgressSerializer(serializers.ModelSerializer):
    skill_code = serializers.CharField(source='skill.code', read_only=True)
    skill_name = serializers.CharField(source='skill.name', read_only=True)
    student_username = serializers.CharField(source='student.username', read_only=True)

    class Meta:
        model = StudentProgress
        fields = [
            'id', 'student', 'student_username', 'skill', 'skill_code', 'skill_name',
            'attempts', 'correct_count', 'mastery', 'consecutive_correct',
            'last_error_type', 'status', 'rule_seen', 'example_seen',
            'started_at', 'mastered_at', 'last_activity',
        ]
        read_only_fields = [
            'attempts', 'correct_count', 'mastery', 'consecutive_correct',
            'last_error_type', 'status', 'rule_seen', 'example_seen',
            'started_at', 'mastered_at', 'last_activity',
        ]


class LogAnswerSerializer(serializers.ModelSerializer):
    """
    Serializer d'écriture (create uniquement - log_answers est append-only).
    La création déclenche automatiquement la mise à jour de StudentProgress.
    """
    student_username = serializers.CharField(source='student.username', read_only=True)
    chunk_code = serializers.CharField(source='chunk.code', read_only=True)

    class Meta:
        model = LogAnswer
        fields = [
            'id', 'student', 'student_username', 'skill', 'chunk', 'chunk_code',
            'answer', 'is_correct', 'error_type', 'error_detail',
            'selected_option', 'error_source', 'exercise_group', 'intervention',
            'time_taken', 'timestamp',
        ]
        read_only_fields = [
            'timestamp', 'selected_option', 'error_source', 'exercise_group', 'intervention',
        ]

    def validate(self, attrs):
        is_correct = attrs.get('is_correct')
        error_type = attrs.get('error_type')
        if not is_correct and not error_type:
            raise serializers.ValidationError(
                {'error_type': "error_type est obligatoire lorsque is_correct est False."}
            )
        return attrs

    def update(self, instance, validated_data):
        raise serializers.ValidationError("log_answers est append-only : la modification est interdite.")

class EngineSettingsSerializer(serializers.ModelSerializer):
    """Section 11 du guide MVP : seuils et paramètres du moteur."""

    class Meta:
        model = EngineSettings
        fields = [
            'low_threshold', 'high_threshold', 'required_correct_streak',
            'min_attempts', 'group_size', 'updated_at',
        ]
        read_only_fields = ['updated_at']

    def validate(self, attrs):
        get = lambda key: attrs.get(key, getattr(self.instance, key, None))
        low, high = get('low_threshold'), get('high_threshold')
        if not (0 < low < high <= 1):
            raise serializers.ValidationError("Il faut 0 < low_threshold < high_threshold <= 1.")
        if get('group_size') < get('min_attempts'):
            raise serializers.ValidationError({'group_size': "group_size doit être >= min_attempts."})
        return attrs


class LearningTraceSerializer(serializers.ModelSerializer):
    skill_code = serializers.CharField(source='skill.code', read_only=True)
    skill_name = serializers.CharField(source='skill.name', read_only=True)
    mastery_improvement = serializers.FloatField(read_only=True)
    intervention_type = serializers.CharField(source='intervention.error_type', read_only=True, default=None)

    class Meta:
        model = LearningTrace
        fields = [
            'id', 'student', 'skill', 'skill_code', 'skill_name', 'evaluation_date',
            'exercise_group', 'total_attempts', 'correct_answers', 'mastery_before',
            'mastery_level', 'error_frequency', 'dominant_error_type', 'decision',
            'intervention', 'intervention_type', 'intervention_sequence', 'intervention_status',
            'mastery_after', 'error_type_after', 'evaluation_after_date', 'mastery_improvement',
        ]
        read_only_fields = fields


class PrerequisiteReturnSerializer(serializers.ModelSerializer):
    student_username = serializers.CharField(source='student.username', read_only=True)
    student_name = serializers.SerializerMethodField()
    from_skill_code = serializers.CharField(source='from_skill.code', read_only=True)
    from_skill_name = serializers.CharField(source='from_skill.name', read_only=True)
    to_skill_code = serializers.CharField(source='to_skill.code', read_only=True, default=None)
    to_skill_name = serializers.CharField(source='to_skill.name', read_only=True, default=None)
    reviewed_by_username = serializers.CharField(source='reviewed_by.username', read_only=True, default=None)

    class Meta:
        model = PrerequisiteReturn
        fields = [
            'id', 'student', 'student_username', 'student_name',
            'from_skill', 'from_skill_code', 'from_skill_name',
            'to_skill', 'to_skill_code', 'to_skill_name', 'exercise_group',
            'status', 'reason', 'dominant_error_type',
            'skill_mastery_before', 'prerequisite_mastery_before',
            'prerequisite_mastery_after', 'skill_mastery_after',
            'review_note', 'reviewed_by', 'reviewed_by_username', 'created_at', 'resolved_at',
        ]
        read_only_fields = [f for f in fields if f != 'review_note']

    def get_student_name(self, obj):
        return obj.student.get_full_name() or obj.student.username
