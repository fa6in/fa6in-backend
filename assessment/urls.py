# assessment/urls.py

from django.urls import path
from .views import ErrorViewSet, StudentProgressViewSet, LogAnswerViewSet, UnitActivitiesView

urlpatterns = [
    # Units - Activities
    path('units/<int:unit_id>/activities/', UnitActivitiesView.as_view(), name='unit-activities'),

    # Attempts (alias en lecture/écriture sur les logs de réponses)
    path('attempts/', LogAnswerViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='attempt-list'),
    path('attempts/<int:pk>/', LogAnswerViewSet.as_view({
        'get': 'retrieve',
    }), name='attempt-detail'),

    # Errors
    path('errors/', ErrorViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='error-list'),
    path('errors/<int:pk>/', ErrorViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='error-detail'),
    
    # Student Progress
    path('progress/', StudentProgressViewSet.as_view({
        'get': 'list'
        # 'post': 'create'
    }), name='student-progress-list'),
    path('progress/next_recommendation/', StudentProgressViewSet.as_view({
        'get': 'next_recommendation'
    }), name='student-progress-next-recommendation'),
    path('progress/<int:pk>/', StudentProgressViewSet.as_view({
        'get': 'retrieve',
        # 'put': 'update',
        # 'patch': 'partial_update',
        # 'delete': 'destroy'
    }), name='student-progress-detail'),
    
    # Log Answers
    path('log-answers/', LogAnswerViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='log-answer-list'),
    path('log-answers/<int:pk>/', LogAnswerViewSet.as_view({
        'get': 'retrieve',
        # append-only (Partie 4.3, Règle 8) : pas de put/patch/delete exposé
    }), name='log-answer-detail'),
]