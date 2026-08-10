"""
assessment/engine.py

Moteur de décision côté Backend (Revue de l'API REST - Partie 1).

Regroupe la logique métier qui, avant cette revue, aurait dû être
reconstituée côté Frontend :

- evaluate_answer   : compare la réponse de l'étudiant à correct_answer
                       (avec gestion des équivalences mathématiques simples)
- classify_error     : classifie une erreur en CONCEPT / PROCEDURE / CARELESS
- pick_error_detail  : cherche l'entrée du catalogue Error correspondante
- pick_next_chunk    : Decision Engine "interne à la skill" (Problème 2)
- find_prerequisite_redirect : Decision Engine "backtracking pédagogique" (Problème 3)
"""

from fractions import Fraction

from skills.models import Chunk, Prerequisite
from .models import ErrorCategory, Error, StudentProgress

REDIRECT_MIN_ATTEMPTS = 3
REDIRECT_MASTERY_CEILING = 0.5
CARELESS_TIME_RATIO = 0.2


def _normalize(text):
    return (text or '').strip().lower()


def evaluate_answer(chunk: Chunk, answer: str) -> bool:
    """
    Compare la réponse fournie à chunk.correct_answer.
    Gère l'égalité textuelle stricte ainsi que l'équivalence de fractions
    (ex: '5/6' et '10/12' sont considérées correctes).
    """
    correct = _normalize(chunk.correct_answer)
    given = _normalize(answer)

    if not correct:
        return False
    if given == correct:
        return True

    try:
        return Fraction(given) == Fraction(correct)
    except (ValueError, ZeroDivisionError):
        return False


def classify_error(progress: StudentProgress, time_taken, chunk: Chunk) -> str:
    """
    Classification automatique de l'erreur (Problème 1, étape 9).

    Règles appliquées :
    - CARELESS  : réponse donnée très rapidement par rapport à la limite
                  de temps du chunk (précipitation, pas d'incompréhension).
    - CONCEPT   : première tentative de l'étudiant sur cette skill
                  (il n'a jamais réussi ni échoué avant) -> lacune de fond.
    - PROCEDURE : l'étudiant a déjà réussi au moins une fois sur cette
                  skill -> il comprend le concept mais exécute mal.
    - CONCEPT   : cas par défaut (échecs répétés sans réussite).
    """
    if time_taken is not None and chunk.time_limit:
        if time_taken < chunk.time_limit * CARELESS_TIME_RATIO:
            return ErrorCategory.CARELESS

    if progress.attempts == 0:
        return ErrorCategory.CONCEPT

    if progress.correct_count > 0:
        return ErrorCategory.PROCEDURE

    return ErrorCategory.CONCEPT


def pick_error_detail(skill_id, category: str):
    return Error.objects.filter(skill_id=skill_id, category=category).order_by('id').first()


def pick_next_chunk(skill, progress: StudentProgress, exclude_chunk_id=None):
    """
    Decision Engine - Problème 2 (Section 9.1/9.2 du cahier des charges).

    Retourne (chunk, reason) ou (None, reason) si aucun chunk ne correspond.
    """
    chunks = skill.chunks.all()
    mastery = float(progress.mastery)

    if progress.last_error_type == ErrorCategory.CONCEPT:
        candidate_type, reason = Chunk.ChunkType.RULE, "Retour à la règle car dernière erreur = concept"
        qs = chunks.filter(chunk_type=candidate_type)
    elif progress.last_error_type == ErrorCategory.PROCEDURE:
        candidate_type, reason = Chunk.ChunkType.EXAMPLE, "Retour à un exemple car dernière erreur = procedure"
        qs = chunks.filter(chunk_type=candidate_type)
    elif mastery < 0.5:
        reason = "Rappel de la règle (mastery < 0.5)"
        qs = chunks.filter(chunk_type=Chunk.ChunkType.RULE)
    elif mastery < float(skill.mastery_threshold):
        reason = "Exercice de renforcement (mastery intermédiaire)"
        qs = chunks.filter(chunk_type=Chunk.ChunkType.PRACTICE, difficulty__lte=2)
    else:
        reason = "Exercice avancé (mastery élevé)"
        qs = chunks.filter(chunk_type=Chunk.ChunkType.PRACTICE, difficulty__gte=3)

    qs = qs.order_by('order_index')

    if exclude_chunk_id is not None:
        not_recent = qs.exclude(pk=exclude_chunk_id)
        if not_recent.exists():
            return not_recent.first(), reason

    chunk = qs.first()
    return chunk, reason


def find_prerequisite_redirect(student, skill):
    """
    Decision Engine - Problème 3 (Section 9.3 du cahier des charges).

    Si l'étudiant est bloqué (attempts >= 3 et mastery < 0.5) sur `skill`,
    identifie le prérequis le plus faible et son premier chunk de type
    'rule'. Retourne None si aucune redirection n'est nécessaire ou possible.
    """
    progress = StudentProgress.objects.filter(student=student, skill=skill).first()
    if not progress or progress.attempts < REDIRECT_MIN_ATTEMPTS or float(progress.mastery) >= REDIRECT_MASTERY_CEILING:
        return None

    prereq_ids = list(Prerequisite.objects.filter(skill=skill).values_list('prerequisite_id', flat=True))
    if not prereq_ids:
        return None

    candidates = (
        StudentProgress.objects
        .filter(student=student, skill_id__in=prereq_ids)
        .select_related('skill')
        .order_by('mastery')
    )

    if candidates.exists():
        weakest_progress = candidates.first()
        weakest_skill = weakest_progress.skill
        weakest_mastery = float(weakest_progress.mastery)
    else:
        from skills.models import Skill
        weakest_skill = Skill.objects.get(pk=prereq_ids[0])
        weakest_mastery = 0.0

    chunk = weakest_skill.chunks.filter(chunk_type=Chunk.ChunkType.RULE).order_by('order_index').first()

    return {
        'previous_skill': skill,
        'previous_progress': progress,
        'new_skill': weakest_skill,
        'new_mastery': weakest_mastery,
        'chunk': chunk,
    }
