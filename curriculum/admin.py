"""
curriculum/admin.py
"""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import Stage, Level, Subject, Unit, Lesson, Goal, AcademicYear


@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    list_display = ('order_index', 'name', 'code')
    ordering = ('order_index',)
    search_fields = ('name', 'code')


@admin.register(Level)
class LevelAdmin(admin.ModelAdmin):
    list_display = ('order_index', 'name', 'code', 'stage')
    list_filter = ('stage',)
    ordering = ('stage__order_index', 'order_index')
    search_fields = ('name', 'code')
    autocomplete_fields = ('stage',)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'level', 'is_active', 'updated_at')
    list_filter = ('level__stage', 'level', 'is_active')
    search_fields = ('name',)
    autocomplete_fields = ('level',)


class UnitInline(admin.TabularInline):
    model = Unit
    extra = 0
    fields = ('code', 'title', 'order_index', 'is_published')
    show_change_link = True


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('code', 'title', 'subject', 'order_index', 'is_published', 'created_by')
    list_filter = ('subject__level__stage', 'subject', 'is_published')
    search_fields = ('code', 'title', 'central_question')
    autocomplete_fields = ('subject', 'created_by')
    readonly_fields = ('created_at',)


class GoalInline(admin.TabularInline):
    model = Goal
    extra = 0
    fields = ('goal_type', 'title', 'order_index')


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('code', 'title', 'unit', 'order_index', 'is_published', 'goals_status')
    list_filter = ('unit__subject', 'is_published')
    search_fields = ('code', 'title')
    autocomplete_fields = ('unit',)
    inlines = [GoalInline]

    @admin.display(description=_('حالة الأهداف'))
    def goals_status(self, obj):
        c = obj.goals.filter(goal_type='conceptual').count()
        o = obj.goals.filter(goal_type='operational').count()
        ok = c == 1 and o == 1
        return f"{'✅' if ok else '⚠️'} C:{c} / O:{o}"


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    list_display = ('title', 'lesson', 'goal_type', 'order_index')
    list_filter = ('goal_type', 'lesson__unit__subject')
    search_fields = ('title', 'lesson__title')
    autocomplete_fields = ('lesson',)


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_date', 'is_current', 'current_week_display')
    list_filter = ('is_current',)

    @admin.display(description=_('الأسبوع الحالي'))
    def current_week_display(self, obj):
        from django.utils import timezone
        return obj.week_of(timezone.localdate())
