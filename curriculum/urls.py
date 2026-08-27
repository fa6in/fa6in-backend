# curriculum/urls.py

from django.urls import path
from .views import (
    StageViewSet,
    LevelViewSet,
    SubjectViewSet,
    UnitViewSet,
    LessonViewSet,
    GoalViewSet,
)

# On utilise as_view() pour chaque action (list, create, retrieve, update, partial_update, destroy)
urlpatterns = [
    # Stages
    path('stages/', StageViewSet.as_view({'get': 'list','post': 'create'}), name='stage-list'),
    path('stages/<int:pk>/', StageViewSet.as_view({'get': 'retrieve','put': 'update','patch': 'partial_update','delete': 'destroy'}), name='stage-detail'),
    
    # Levels
    path('levels/', LevelViewSet.as_view({'get': 'list','post': 'create'}), name='level-list'),
    path('levels/<int:pk>/', LevelViewSet.as_view({'get': 'retrieve','put': 'update','patch': 'partial_update','delete': 'destroy'}), name='level-detail'),
    
    # Subjects
    path('subjects/', SubjectViewSet.as_view({'get': 'list','post': 'create'}), name='subject-list'),
    path('subjects/<int:pk>/', SubjectViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='subject-detail'),
    
    # Units
    path('units/', UnitViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='unit-list'),
    path('units/<int:pk>/', UnitViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='unit-detail'),
    path('units/<int:pk>/sections/', UnitViewSet.as_view({
        'get': 'sections'
    }), name='unit-sections'),
    
    # Lessons
    path('lessons/', LessonViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='lesson-list'),
    path('lessons/<int:pk>/', LessonViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='lesson-detail'),
    path('lessons/<int:pk>/publish/', LessonViewSet.as_view({
        'post': 'publish'
    }), name='lesson-publish'),
    
    # Goals
    path('goals/', GoalViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='goal-list'),
    path('goals/<int:pk>/', GoalViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='goal-detail'),
]