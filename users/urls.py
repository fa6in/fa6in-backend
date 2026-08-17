# users/urls.py

from django.urls import path
from .views import (
    UserViewSet,
    WilayaViewSet,
    StudentProfileViewSet,
    TeacherProfileViewSet,
    RegisterView,
    LoginView,
    MeView,
    LogoutView,
    ForgotPasswordView,
    ResetPasswordView,
    AdminStudentListView,
    AdminStudentDetailView,
    AdminTeacherListView,
    AdminTeacherDetailView,
)

urlpatterns = [
    # Authentification
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('me/', MeView.as_view(), name='me'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    path('reset-password/', ResetPasswordView.as_view(), name='reset-password'),

    # Users
    path('users/', UserViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='user-list'),
    path('users/<int:pk>/', UserViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='user-detail'),
    path('users/<int:pk>/change_password/', UserViewSet.as_view({
        'post': 'change_password'
    }), name='user-change-password'),

    # Wilayas
    path('wilayas/', WilayaViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='wilaya-list'),
    path('wilayas/<int:pk>/', WilayaViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='wilaya-detail'),
    
    # Student Profiles
    path('student-profiles/', StudentProfileViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='student-profile-list'),
    path('student-profiles/<int:pk>/', StudentProfileViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='student-profile-detail'),
    
    # Admin - Students / Teachers
    path('admin/students/', AdminStudentListView.as_view(), name='admin-student-list'),
    path('admin/students/<int:pk>/', AdminStudentDetailView.as_view(), name='admin-student-detail'),
    path('admin/teachers/', AdminTeacherListView.as_view(), name='admin-teacher-list'),
    path('admin/teachers/<int:pk>/', AdminTeacherDetailView.as_view(), name='admin-teacher-detail'),

    # Teacher Profiles
    path('teacher-profiles/', TeacherProfileViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='teacher-profile-list'),
    path('teacher-profiles/<int:pk>/', TeacherProfileViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='teacher-profile-detail'),
]