"""
analytics/serializers.py

Serializers "de sortie" uniquement : ils mettent en forme des résultats
de requêtes agrégées, ils ne sont adossés à aucun modèle dédié
(voir analytics/models.py).
"""

from rest_framework import serializers


class ClassDashboardRowSerializer(serializers.Serializer):
    student_id = serializers.IntegerField()
    username = serializers.CharField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    skills_started = serializers.IntegerField()
    skills_mastered = serializers.IntegerField()
    average_mastery = serializers.FloatField()
    last_active = serializers.DateTimeField(allow_null=True)


class StudentErrorAnalysisRowSerializer(serializers.Serializer):
    skill_name = serializers.CharField()
    error_category = serializers.CharField()
    error_code = serializers.CharField(allow_null=True)
    root_cause = serializers.CharField(allow_null=True)
    severity_level = serializers.CharField(allow_null=True)
    occurrences = serializers.IntegerField()


class ReportsOverviewSerializer(serializers.Serializer):
    total_users = serializers.IntegerField()
    total_students = serializers.IntegerField()
    total_teachers = serializers.IntegerField()
    total_units = serializers.IntegerField()
    published_units = serializers.IntegerField()
    total_skills = serializers.IntegerField()
    total_attempts = serializers.IntegerField()
    correct_attempts = serializers.IntegerField()
    mastered_skills_count = serializers.IntegerField()
    overall_average_mastery = serializers.FloatField()


class ReportsUsageSerializer(serializers.Serializer):
    period_days = serializers.IntegerField()
    new_registrations = serializers.IntegerField()
    active_students = serializers.IntegerField()
    active_users_by_login = serializers.IntegerField()
    total_attempts = serializers.IntegerField()
    correct_attempts = serializers.IntegerField()
    average_attempts_per_active_student = serializers.FloatField()


class TeacherDashboardOverviewSerializer(serializers.Serializer):
    total_students = serializers.IntegerField()
    active_students_7d = serializers.IntegerField()
    average_mastery = serializers.FloatField()
    mastered_skills_total = serializers.IntegerField()
    attempts_7d = serializers.IntegerField()


class UnitPerformanceRowSerializer(serializers.Serializer):
    unit_id = serializers.IntegerField()
    unit_code = serializers.CharField()
    unit_title = serializers.CharField()
    skills_count = serializers.IntegerField()
    average_mastery = serializers.FloatField()
    students_mastered = serializers.IntegerField()
    attempts_count = serializers.IntegerField()
