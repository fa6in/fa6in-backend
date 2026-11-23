"""
assessment/engine.py

Moteur de décision côté Backend (Revue de l'API REST - Partie 1).

Regroupe la logique métier qui, avant cette revue, aurait dû être
reconstituée côté Frontend :

- evaluate_answer   : compare la réponse de l'étudiant à correct_answer
                       (avec gestion des équivalences mathématiques simples)
- classify_error     : classifie une erreur en CONCEPT / PROCEDURE / CARELESS
- pick_error_detail  : cherche l'entrée du catalogue Error correspondante
- pick_next_chunk    : Decision Engine "interne à la skill" (Problème 2),
                       organisé en séries d'exercices avec reprise des erreurs
- record_round_answer: met à jour la série après une réponse
- find_prerequisite_redirect : Decision Engine "backtracking pédagogique" (Problème 3)
"""

from fractions import Fraction

from curriculum.models import AcademicYear
from skills.models import Chunk, Prerequisite
from .models import ErrorCategory, Error, StudentProgress
from .path import skill_is_open

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


REVIEW_MAX_RETRIES = 2


def _practice_ids(skill):
    return set(skill.chunks.filter(chunk_type=Chunk.ChunkType.PRACTICE).values_list('id', flat=True))


def _round_exercises(skill, progress: StudentProgress):
    """
    Exercices d'une nouvelle série, choisis selon le niveau de maîtrise :
    faciles (difficulty <= 2) tant que la skill n'est pas maîtrisée,
    avancés (difficulty >= 3) ensuite. Si aucun exercice ne correspond,
    on prend tous les exercices de la skill.
    """
    practice = skill.chunks.filter(chunk_type=Chunk.ChunkType.PRACTICE)
    if progress.attempts < 3:
        reason = "Phase de diagnostic (< 3 tentatives) : série d'exercices faciles"
        qs = practice.filter(difficulty__lte=2)
    elif float(progress.mastery) < float(skill.mastery_threshold):
        reason = "Série de renforcement (mastery intermédiaire)"
        qs = practice.filter(difficulty__lte=2)
    else:
        reason = "Série d'exercices avancés (mastery élevé)"
        qs = practice.filter(difficulty__gte=3)
    if not qs.exists():
        qs = practice
    return list(qs.order_by('order_index', 'id').values_list('id', flat=True)), reason


def _clean_round(skill, progress: StudentProgress):
    """Retire de la série les chunks supprimés / qui ne sont plus des exercices."""
    valid = _practice_ids(skill)
    queue = [cid for cid in (progress.round_queue or []) if cid in valid]
    mistakes = [m for m in (progress.round_mistakes or []) if m.get('chunk_id') in valid]
    if queue != (progress.round_queue or []) or mistakes != (progress.round_mistakes or []):
        progress.round_queue, progress.round_mistakes = queue, mistakes
        progress.save(update_fields=['round_queue', 'round_mistakes'])


def round_state(progress: StudentProgress):
    """
    Résumé de la série en cours, renvoyé au Frontend :
    phase = 'practice' (exercices de la série), 'review' (reprise des
    exercices ratés) ou None (aucune série en cours).
    """
    queue = progress.round_queue or []
    mistakes = progress.round_mistakes or []
    phase = 'practice' if queue else ('review' if mistakes else None)
    return {
        'phase': phase,
        'remaining': len(queue),
        'to_review': len(mistakes),
        'mistakes': [m['chunk_id'] for m in mistakes],
    }


def in_round_practice(progress: StudentProgress) -> bool:
    """Vrai tant que l'étudiant n'a pas fini les exercices de la série."""
    return bool(progress.round_queue)


def pick_next_chunk(skill, progress: StudentProgress, exclude_chunk_id=None):
    """
    Decision Engine - Problème 2 (Section 9.1/9.2 du cahier des charges).

    Retourne un dict {chunk, reason, mode, mistake} :
    - mode 'learn'    : onboarding (règle puis exemple, une seule fois) ;
    - mode 'practice' : exercice suivant de la série. Une erreur ne bloque
                        PAS l'étudiant : il passe à l'exercice suivant ;
    - mode 'review'   : la série est terminée, on revient sur un exercice
                        raté ; `mistake` porte la catégorie d'erreur pour
                        afficher le feedback (règle / exemple) avant de le
                        refaire.
    Une nouvelle série démarre automatiquement quand la précédente (et
    ses reprises) est terminée.
    """
    chunks = skill.chunks.all()

    if not progress.rule_seen:
        chunk = chunks.filter(chunk_type=Chunk.ChunkType.RULE).order_by('order_index').first()
        if chunk:
            return {'chunk': chunk, 'reason': "Première visite : découverte de la règle",
                    'mode': 'learn', 'mistake': None}
    if not progress.example_seen:
        chunk = chunks.filter(chunk_type=Chunk.ChunkType.EXAMPLE).order_by('order_index').first()
        if chunk:
            return {'chunk': chunk, 'reason': "Première visite : découverte de l'exemple",
                    'mode': 'learn', 'mistake': None}

    _clean_round(skill, progress)
    reason = "Suite de la série d'exercices"
    if not progress.round_queue and not progress.round_mistakes:
        queue, reason = _round_exercises(skill, progress)
        # Évite de reproposer immédiatement le dernier exercice répondu.
        if exclude_chunk_id in queue and len(queue) > 1:
            queue.remove(exclude_chunk_id)
            queue.append(exclude_chunk_id)
        progress.round_queue, progress.round_mistakes = queue, []
        progress.save(update_fields=['round_queue', 'round_mistakes'])

    if progress.round_queue:
        chunk = chunks.filter(pk=progress.round_queue[0]).first()
        return {'chunk': chunk, 'reason': reason, 'mode': 'practice', 'mistake': None}

    if progress.round_mistakes:
        mistake = progress.round_mistakes[0]
        chunk = chunks.filter(pk=mistake['chunk_id']).first()
        return {
            'chunk': chunk,
            'reason': "Fin de la série : reprise d'un exercice raté avec son feedback",
            'mode': 'review',
            'mistake': mistake,
        }

    return {'chunk': None, 'reason': "Aucun exercice disponible pour cette skill",
            'mode': 'practice', 'mistake': None}


def record_round_answer(progress: StudentProgress, chunk: Chunk, is_correct: bool, error_type=None):
    """
    Met à jour la série après une réponse.

    - Exercice de la série : il sort de la file ; s'il est faux, il est
      noté dans round_mistakes pour être repris en fin de série.
      L'étudiant passe à l'exercice suivant dans tous les cas.
    - Reprise d'un exercice raté : juste -> retiré des erreurs ; faux ->
      remis en fin de liste (au plus REVIEW_MAX_RETRIES reprises, pour ne
      jamais bloquer l'étudiant sur le même exercice).
    Retourne le mode de la réponse : 'practice', 'review' ou None (hors série).
    """
    queue = list(progress.round_queue or [])
    mistakes = [dict(m) for m in (progress.round_mistakes or [])]
    idx = next((i for i, m in enumerate(mistakes) if m.get('chunk_id') == chunk.id), None)

    mode = None
    if chunk.id in queue:
        mode = 'practice'
        queue.remove(chunk.id)
        if not is_correct:
            if idx is None:
                mistakes.append({'chunk_id': chunk.id, 'error_type': error_type, 'retries': 0})
            else:
                mistakes[idx]['error_type'] = error_type
    elif idx is not None:
        mode = 'review'
        entry = mistakes.pop(idx)
        if not is_correct:
            entry['retries'] = entry.get('retries', 0) + 1
            entry['error_type'] = error_type
            if entry['retries'] < REVIEW_MAX_RETRIES:
                mistakes.append(entry)

    progress.round_queue, progress.round_mistakes = queue, mistakes
    progress.save(update_fields=['round_queue', 'round_mistakes'])
    return mode


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

    week = AcademicYear.current_week()
    prereqs = [
        p for p in Prerequisite.objects.filter(skill=skill)
        .select_related('prerequisite__goal__lesson')
        .order_by('prerequisite__order_index', 'prerequisite_id')
        if skill_is_open(p.prerequisite, week)
    ]
    if not prereqs:
        return None

    # Seuls les prérequis NON maîtrisés sont des cibles de redirection : un
    # prérequis déjà maîtrisé renverrait l'étudiant en boucle vers une skill
    # qu'il sait déjà. Un prérequis jamais tenté compte comme mastery 0.
    progress_by_skill = {
        p.skill_id: p
        for p in StudentProgress.objects.filter(
            student=student, skill_id__in=[p.prerequisite_id for p in prereqs],
        )
    }
    candidates = []
    for p in prereqs:
        pre_progress = progress_by_skill.get(p.prerequisite_id)
        if pre_progress and pre_progress.status == StudentProgress.Status.MASTERED:
            continue
        candidates.append((float(pre_progress.mastery) if pre_progress else 0.0, p.prerequisite))
    if not candidates:
        return None

    weakest_mastery, weakest_skill = min(candidates, key=lambda c: c[0])

    chunk = weakest_skill.chunks.filter(chunk_type=Chunk.ChunkType.RULE).order_by('order_index').first()

    return {
        'previous_skill': skill,
        'previous_progress': progress,
        'new_skill': weakest_skill,
        'new_mastery': weakest_mastery,
        'chunk': chunk,
    }