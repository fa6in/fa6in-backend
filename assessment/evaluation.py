"""
assessment/evaluation.py

Evaluation Engine (guide MVP, section 12.1) : analyse les réponses d'un
groupe d'exercices et calcule les indicateurs.

- Mastery            : correct / total sur le DERNIER groupe seulement (3)
- Minimum d'attempts : pas de jugement avant settings.min_attempts (3.2)
- Mastery Level      : Low / Medium / High selon les seuils (3.1)
- Error Frequency    : nombre d'occurrences de chaque type d'erreur (4.2)
- Dominant Error     : le plus fréquent, égalité -> Careless > Procedure > Concept (4.3)
- Correct Streak     : réponses correctes consécutives en fin de groupe
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from .models import EngineSettings, ErrorCategory, LogAnswer, MasteryLevel

# Ordre de priorité en cas d'égalité : le DERNIER de cette liste gagne.
TIE_BREAK_ORDER = [ErrorCategory.CONCEPT, ErrorCategory.PROCEDURE, ErrorCategory.CARELESS]


@dataclass
class EvaluationResult:
    total_attempts: int
    correct_answers: int
    mastery: Decimal
    mastery_level: str
    error_frequency: dict = field(default_factory=dict)
    dominant_error_type: str = ''
    correct_streak: int = 0
    judged: bool = False

    @property
    def mastery_percent(self):
        return int(self.mastery * 100)


def _dec(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def mastery_level(mastery, settings: EngineSettings) -> str:
    mastery = _dec(mastery)
    if mastery < _dec(settings.low_threshold):
        return MasteryLevel.LOW
    if mastery < _dec(settings.high_threshold):
        return MasteryLevel.MEDIUM
    return MasteryLevel.HIGH


def dominant_error_type(frequency: dict) -> str:
    """Type d'erreur le plus fréquent ; égalité -> Careless > Procedure > Concept."""
    best, best_count = '', 0
    for category in TIE_BREAK_ORDER:
        count = frequency.get(category, 0)
        if count and count >= best_count:
            best, best_count = category, count
    return best


def correct_streak(results) -> int:
    streak = 0
    for is_correct in reversed(results):
        if not is_correct:
            break
        streak += 1
    return streak


def evaluate_results(results, error_types, settings: EngineSettings) -> EvaluationResult:
    """
    results     : liste ordonnée de booléens (réponse correcte ou non)
    error_types : types d'erreur des réponses fausses
    """
    total = len(results)
    correct = sum(1 for r in results if r)
    mastery = (Decimal(correct) / Decimal(total)).quantize(Decimal('0.01'), ROUND_HALF_UP) if total else Decimal('0')
    frequency = {c.value: 0 for c in ErrorCategory}
    for error in error_types:
        if error in frequency:
            frequency[error] += 1
    return EvaluationResult(
        total_attempts=total,
        correct_answers=correct,
        mastery=mastery,
        mastery_level=mastery_level(mastery, settings),
        error_frequency=frequency,
        dominant_error_type=dominant_error_type(frequency),
        correct_streak=correct_streak(results),
        judged=total >= settings.min_attempts,
    )


def evaluate_group(group, settings: EngineSettings = None) -> EvaluationResult:
    """Évalue un ExerciseGroup à partir de ses réponses (LogAnswer)."""
    settings = settings or EngineSettings.load()
    answers = list(
        LogAnswer.objects.filter(exercise_group=group).order_by('timestamp', 'id')
        .values_list('is_correct', 'error_type')
    )
    return evaluate_results(
        [a[0] for a in answers],
        [a[1] for a in answers if not a[0]],
        settings,
    )
