"""
analytics/urls.py
"""

from django.urls import path

from .views import (
    ClassDashboardView,
    StudentErrorAnalysisView,
    ReportsOverviewView,
    ReportsUsageView,
    TeacherDashboardOverviewView,
    TeacherDashboardStudentsProgressView,
    TeacherDashboardUnitsPerformanceView,
)

urlpatterns = [
    path('class-dashboard/', ClassDashboardView.as_view(), name='class-dashboard'),
    path('students/<int:student_id>/error-analysis/', StudentErrorAnalysisView.as_view(), name='student-error-analysis'),

    # Reports (admin)
    path('reports/', ReportsOverviewView.as_view(), name='reports-overview'),
    path('reports/usage/', ReportsUsageView.as_view(), name='reports-usage'),

    # Teacher dashboard
    path('teacher-dashboard/', TeacherDashboardOverviewView.as_view(), name='teacher-dashboard'),
    path('teacher-dashboard/overview/', TeacherDashboardOverviewView.as_view(), name='teacher-dashboard-overview'),
    path('teacher-dashboard/students-progress/', TeacherDashboardStudentsProgressView.as_view(), name='teacher-dashboard-students-progress'),
    path('teacher-dashboard/units-performance/', TeacherDashboardUnitsPerformanceView.as_view(), name='teacher-dashboard-units-performance'),
]
