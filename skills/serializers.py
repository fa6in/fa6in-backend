"""
skills/serializers.py
"""

from rest_framework import serializers

from .models import Skill, Prerequisite, Chunk


class ChunkSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chunk
        fields = [
            'id', 'skill', 'code', 'chunk_type', 'title', 'content',
            'correct_answer', 'options', 'difficulty', 'order_index',
            'points', 'time_limit', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate(self, attrs):
        chunk_type = attrs.get('chunk_type') or getattr(self.instance, 'chunk_type', None)
        correct_answer = attrs.get('correct_answer', getattr(self.instance, 'correct_answer', None))
        if chunk_type == Chunk.ChunkType.PRACTICE and not correct_answer:
            raise serializers.ValidationError(
                {'correct_answer': "Un chunk de type 'practice' doit avoir une réponse correcte."}
            )
        return attrs

    def to_representation(self, instance):
        """
        Sécurité (Revue API, Problème 1) : un étudiant qui inspecte les
        appels réseau ne doit jamais pouvoir lire correct_answer. Seuls
        les enseignants/admins qui gèrent le contenu y ont accès.
        """
        data = super().to_representation(instance)
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        from users.models import User
        is_staff_role = bool(
            user and user.is_authenticated
            and user.role in (User.Role.TEACHER, User.Role.REGIONAL_ADMIN, User.Role.ADMIN)
        )
        if not is_staff_role:
            data.pop('correct_answer', None)
        return data


class PrerequisiteSerializer(serializers.ModelSerializer):
    skill_code = serializers.CharField(source='skill.code', read_only=True)
    prerequisite_code = serializers.CharField(source='prerequisite.code', read_only=True)

    class Meta:
        model = Prerequisite
        fields = ['id', 'skill', 'skill_code', 'prerequisite', 'prerequisite_code']

    def validate(self, attrs):
        skill = attrs.get('skill') or getattr(self.instance, 'skill', None)
        prerequisite = attrs.get('prerequisite') or getattr(self.instance, 'prerequisite', None)

        if skill == prerequisite:
            raise serializers.ValidationError("Une compétence ne peut pas être son propre prérequis.")

        qs = Prerequisite.objects.filter(skill=prerequisite, prerequisite=skill)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                f"La relation inverse existe déjà ({prerequisite.code} → {skill.code})."
            )

        if self._creates_cycle(skill.id, prerequisite.id, exclude_pk=self.instance.pk if self.instance else None):
            raise serializers.ValidationError(
                "Cette relation créerait un cycle dans le graphe des prérequis."
            )
        return attrs

    @staticmethod
    def _creates_cycle(skill_id, prerequisite_id, exclude_pk=None):
        visited = set()
        stack = [prerequisite_id]
        while stack:
            current = stack.pop()
            if current == skill_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            qs = Prerequisite.objects.filter(skill_id=current)
            if exclude_pk:
                qs = qs.exclude(pk=exclude_pk)
            stack.extend(qs.values_list('prerequisite_id', flat=True))
        return False


class SkillListSerializer(serializers.ModelSerializer):
    goal_type = serializers.CharField(source='goal.goal_type', read_only=True)
    chunks_ready = serializers.SerializerMethodField()

    class Meta:
        model = Skill
        fields = [
            'id', 'code', 'name', 'skill_type', 'goal', 'goal_type',
            'difficulty', 'order_index', 'chunks_ready',
        ]

    def get_chunks_ready(self, obj):
        return obj.chunks_meet_minimum()


class SkillDetailSerializer(serializers.ModelSerializer):
    chunks = ChunkSerializer(many=True, read_only=True)
    prerequisites = serializers.SerializerMethodField()
    chunks_ready = serializers.SerializerMethodField()

    class Meta:
        model = Skill
        fields = [
            'id', 'code', 'name', 'description', 'goal', 'skill_type',
            'difficulty', 'mastery_threshold', 'required_consecutive_correct',
            'order_index', 'created_at', 'updated_at', 'chunks',
            'prerequisites', 'chunks_ready',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_prerequisites(self, obj):
        return PrerequisiteSerializer(obj.prerequisites_required.all(), many=True).data

    def get_chunks_ready(self, obj):
        return obj.chunks_meet_minimum()

    def validate(self, attrs):
        goal = attrs.get('goal') or getattr(self.instance, 'goal', None)
        skill_type = attrs.get('skill_type') or getattr(self.instance, 'skill_type', None)
        if goal and skill_type and skill_type != goal.goal_type:
            raise serializers.ValidationError(
                {'skill_type': (
                    f"Le skill_type ('{skill_type}') doit correspondre au goal_type "
                    f"du Goal parent ('{goal.goal_type}')."
                )}
            )
        return attrs
