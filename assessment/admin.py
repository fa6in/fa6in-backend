"""
assessment/admin.py
"""

from django.contrib import admin

from .models import Error, StudentProgress, LogAnswer


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
