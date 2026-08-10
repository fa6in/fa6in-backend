# skills/urls.py

from django.urls import path
from .views import SkillViewSet, PrerequisiteViewSet, ChunkViewSet

urlpatterns = [
    # Skills
    path('skills/', SkillViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='skill-list'),
    path('skills/<int:pk>/', SkillViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='skill-detail'),
    path('skills/<int:pk>/prerequisites/', SkillViewSet.as_view({
        'get': 'prerequisites'
    }), name='skill-prerequisites'),
    path('skills/<int:pk>/publication_check/', SkillViewSet.as_view({
        'get': 'publication_check'
    }), name='skill-publication-check'),

    # Prerequisites
    path('prerequisites/', PrerequisiteViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='prerequisite-list'),
    path('prerequisites/<int:pk>/', PrerequisiteViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='prerequisite-detail'),
    
    # Chunks
    path('chunks/', ChunkViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='chunk-list'),
    path('chunks/<int:pk>/', ChunkViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='chunk-detail'),
]