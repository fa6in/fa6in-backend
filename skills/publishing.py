"""
skills/publishing.py

Règles de publication d'une leçon (écran T9 "جاهز للنشر؟" du design et
Partie 4 du cahier des charges) :

1. Exactement un Goal Conceptual et un Goal Operational (Règle 1).
2. Chaque Goal a au moins une Skill, et le type de chaque Skill
   correspond à celui de son Goal (Règle 2).
3. Aucun cycle dans le graphe de prérequis des skills de la leçon (Règle 4).
4. Chaque Skill a assez de chunks : 1 rule, 1 example, 2 practice (Règle 3).
"""

from curriculum.models import Goal
from .models import Chunk, Prerequisite, Skill


def _has_cycle_from(start_ids):
    """
    Détecte un cycle atteignable depuis `start_ids` dans le graphe
    skill -> prerequisite (DFS avec pile de couleurs).
    """
    edges = {}

    def neighbours(node):
        if node not in edges:
            edges[node] = list(
                Prerequisite.objects.filter(skill_id=node).values_list('prerequisite_id', flat=True)
            )
        return edges[node]

    WHITE, GREY, BLACK = 0, 1, 2
    color = {}
    for start in start_ids:
        if color.get(start, WHITE) != WHITE:
            continue
        stack = [(start, iter(neighbours(start)))]
        color[start] = GREY
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                color[node] = BLACK
                stack.pop()
            elif color.get(nxt, WHITE) == GREY:
                return True
            elif color.get(nxt, WHITE) == WHITE:
                color[nxt] = GREY
                stack.append((nxt, iter(neighbours(nxt))))
    return False


def lesson_publication_checks(lesson):
    """
    Retourne {'ready': bool, 'checks': [{'key', 'ok', 'detail'}]}.
    `detail` donne les éléments à corriger (codes) pour l'interface.
    """
    goals = list(lesson.goals.all())
    conceptual = [g for g in goals if g.goal_type == Goal.GoalType.CONCEPTUAL]
    operational = [g for g in goals if g.goal_type == Goal.GoalType.OPERATIONAL]
    skills = list(Skill.objects.filter(goal__lesson=lesson).select_related('goal'))

    goals_ok = len(conceptual) == 1 and len(operational) == 1
    missing_goals = []
    if len(conceptual) != 1:
        missing_goals.append(Goal.GoalType.CONCEPTUAL)
    if len(operational) != 1:
        missing_goals.append(Goal.GoalType.OPERATIONAL)

    goals_without_skill = [g.goal_type for g in goals if not any(s.goal_id == g.id for s in skills)]
    mismatched = [s.code for s in skills if s.skill_type != s.goal.goal_type]
    types_ok = bool(skills) and not goals_without_skill and not mismatched

    cycles_ok = not _has_cycle_from([s.id for s in skills])

    incomplete = []
    for s in skills:
        counts = {t: 0 for t in (Chunk.ChunkType.RULE, Chunk.ChunkType.EXAMPLE, Chunk.ChunkType.PRACTICE)}
        for t in s.chunks.values_list('chunk_type', flat=True):
            if t in counts:
                counts[t] += 1
        if counts[Chunk.ChunkType.RULE] < 1 or counts[Chunk.ChunkType.EXAMPLE] < 1 \
                or counts[Chunk.ChunkType.PRACTICE] < 2:
            incomplete.append({
                'skill': s.code,
                'rule': counts[Chunk.ChunkType.RULE],
                'example': counts[Chunk.ChunkType.EXAMPLE],
                'practice': counts[Chunk.ChunkType.PRACTICE],
            })
    chunks_ok = bool(skills) and not incomplete

    checks = [
        {'key': 'goals', 'ok': goals_ok, 'detail': {'missing': missing_goals}},
        {'key': 'skill_types', 'ok': types_ok, 'detail': {
            'goals_without_skill': goals_without_skill, 'mismatched_skills': mismatched,
        }},
        {'key': 'no_cycles', 'ok': cycles_ok, 'detail': {}},
        {'key': 'chunks', 'ok': chunks_ok, 'detail': {'incomplete_skills': incomplete}},
    ]
    return {'ready': all(c['ok'] for c in checks), 'checks': checks}
