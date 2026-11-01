"""
skills/views.py
"""

from django.db.models import Count, Q
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from curriculum.views import IsTeacherOrAdminOrReadOnly
from .models import Skill, Prerequisite, Chunk
from .serializers import (
    SkillListSerializer,
    SkillDetailSerializer,
    PrerequisiteSerializer,
    ChunkSerializer,
)


class SkillViewSet(viewsets.ModelViewSet):
    queryset = Skill.objects.select_related('goal').prefetch_related('chunks', 'prerequisites_required').all()
    permission_classes = [IsTeacherOrAdminOrReadOnly]
    filterset_fields = ['goal', 'goal__lesson', 'goal__lesson__unit', 'skill_type', 'difficulty']
    search_fields = ['code', 'name']

    def get_serializer_class(self):
        if self.action == 'list':
            return SkillListSerializer
        return SkillDetailSerializer

    @action(detail=True, methods=['get'])
    def prerequisites(self, request, pk=None):
        skill = self.get_object()
        data = PrerequisiteSerializer(skill.prerequisites_required.all(), many=True).data
        return Response(data)

    @action(detail=True, methods=['get'])
    def publication_check(self, request, pk=None):
        """
        Vérifie la règle CMS (min. 1 rule, 1 example, 2 practice)
        avant de permettre la publication du contenu de la skill.
        """
        skill = self.get_object()
        ready = skill.chunks_meet_minimum()
        counts = {
            c['chunk_type']: c['n']
            for c in skill.chunks.values('chunk_type').annotate(n=Count('id'))
        }
        return Response({'ready': ready, 'chunk_counts': counts})


    @action(detail=True, methods=['get'])
    def prerequisite_candidates(self, request, pk=None):
        """
        GET /api/skills/skills/<id>/prerequisite_candidates/?search=
        Écran T7 : skills proposables comme prérequis, avec leur état :
        - 'available' : peut être ajoutée ;
        - 'linked'    : déjà prérequis de cette skill ;
        - 'cycle'     : l'ajouter créerait un cycle -> interdit.
        """
        skill = self.get_object()

        # Skills qui dépendent (transitivement) de `skill` : en faire un
        # prérequis de `skill` fermerait la boucle.
        dependents, frontier = set(), [skill.id]
        while frontier:
            current = frontier.pop()
            for dep_id in Prerequisite.objects.filter(prerequisite_id=current).values_list('skill_id', flat=True):
                if dep_id not in dependents:
                    dependents.add(dep_id)
                    frontier.append(dep_id)
        linked = set(skill.prerequisites_required.values_list('prerequisite_id', flat=True))

        qs = Skill.objects.exclude(pk=skill.pk).select_related('goal__lesson__unit')
        search = request.query_params.get('search')
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(code__icontains=search))
        qs = qs.order_by('goal__lesson__unit__order_index', 'goal__lesson__order_index', 'order_index')[:50]

        def state(candidate_id):
            if candidate_id in linked:
                return 'linked'
            if candidate_id in dependents:
                return 'cycle'
            return 'available'

        return Response([
            {
                'id': c.id,
                'code': c.code,
                'name': c.name,
                'skill_type': c.skill_type,
                'lesson_code': c.goal.lesson.code,
                'state': state(c.id),
            }
            for c in qs
        ])


class PrerequisiteViewSet(viewsets.ModelViewSet):
    queryset = Prerequisite.objects.select_related('skill', 'prerequisite').all()
    serializer_class = PrerequisiteSerializer
    permission_classes = [IsTeacherOrAdminOrReadOnly]
    filterset_fields = ['skill', 'prerequisite', 'skill__goal__lesson']


class ChunkViewSet(viewsets.ModelViewSet):
    queryset = Chunk.objects.select_related('skill').all()
    serializer_class = ChunkSerializer
    permission_classes = [IsTeacherOrAdminOrReadOnly]
    filterset_fields = ['skill', 'skill__goal__lesson', 'chunk_type', 'difficulty']
    search_fields = ['code', 'title', 'content']
