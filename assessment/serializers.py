"""
assessment/serializers.py
"""

from rest_framework import serializers

from .models import Error, StudentProgress, LogAnswer


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
            'time_taken', 'timestamp',
        ]
        read_only_fields = ['timestamp']

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