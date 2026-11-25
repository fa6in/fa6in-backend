"""
assessment/admin.py
"""

from django.contrib import admin

from .models import (
    EngineSettings, Error, ExerciseGroup, Intervention, LearningTrace, LogAnswer,
    PrerequisiteReturn, StudentProgress,
)


@admin.register(Error)
class ErrorAdmin(admin.ModelAdmin):
    list_display = ('code', 'error_type', 'category', 'severity_level', 'skill')
    list_filter = ('category', 'severity_level', 'skill__goal__lesson__unit__subject')
    search_fields = ('code', 'error_type', 'root_cause')
    autocomplete_fields = ('skill',)


@admin.register(StudentProgress)
class StudentProgressAdmin(admin.ModelAdmin):
    list_display = (
        'student', 'skill', 'status', 'mastery', 'attempts',
        'correct_count', 'consecutive_correct', 'last_activity',
    )
    list_filter = ('status', 'skill__goal__lesson__unit__subject')
    search_fields = ('student__username', 'skill__code')
    autocomplete_fields = ('student', 'skill')
    readonly_fields = ('last_activity',)


@admin.register(LogAnswer)
class LogAnswerAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'student', 'chunk', 'is_correct', 'error_type', 'time_taken')
    list_filter = ('is_correct', 'error_type')
    search_fields = ('student__username', 'chunk__code')
    autocomplete_fields = ('student', 'skill', 'chunk', 'error_detail')
    readonly_fields = [f.name for f in LogAnswer._meta.fields]

    # ✅ Suppression autorisée
    def has_delete_permission(self, request, obj=None):
        return True

    # ⚠️ À garder False si vous voulez rester append-only en modification
    def has_change_permission(self, request, obj=None):
        return False

    # ⚠️ Si has_change_permission est False, Django n'affiche PAS le bouton "Supprimer"
    #    sur la page de détail. Pour pouvoir supprimer, il faut aussi autoriser le changement
    #    OU passer par l'action "delete_selected" depuis la liste.



@admin.register(EngineSettings)
class EngineSettingsAdmin(admin.ModelAdmin):
    list_display = ('low_threshold', 'high_threshold', 'required_correct_streak', 'min_attempts', 'group_size', 'updated_at')

    def has_add_permission(self, request):
        return not EngineSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ExerciseGroup)
class ExerciseGroupAdmin(admin.ModelAdmin):
    list_display = ('id', 'student', 'skill', 'status', 'mastery', 'mastery_level', 'dominant_error_type', 'decision', 'created_at')
    list_filter = ('status', 'mastery_level', 'dominant_error_type', 'decision')
    search_fields = ('student__username', 'skill__code')
    raw_id_fields = ('student', 'skill')


@admin.register(Intervention)
class InterventionAdmin(admin.ModelAdmin):
    list_display = ('id', 'student', 'skill', 'error_type', 'mastery_level', 'status', 'current_step', 'created_at')
    list_filter = ('error_type', 'status')
    search_fields = ('student__username', 'skill__code')
    raw_id_fields = ('student', 'skill', 'group')


@admin.register(LearningTrace)
class LearningTraceAdmin(admin.ModelAdmin):
    list_display = (
        'evaluation_date', 'student', 'skill', 'mastery_before', 'dominant_error_type',
        'decision', 'intervention_status', 'mastery_after', 'error_type_after',
    )
    list_filter = ('decision', 'dominant_error_type', 'mastery_level')
    search_fields = ('student__username', 'skill__code')
    readonly_fields = [f.name for f in LearningTrace._meta.fields]

    def has_delete_permission(self, request, obj=None):
        return False  # historique (section 9) : jamais supprimé


@admin.register(PrerequisiteReturn)
class PrerequisiteReturnAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'student', 'from_skill', 'to_skill', 'status', 'dominant_error_type')
    list_filter = ('status', 'dominant_error_type')
    search_fields = ('student__username', 'from_skill__code', 'to_skill__code')
    raw_id_fields = ('student', 'from_skill', 'to_skill', 'exercise_group', 'reviewed_by')
