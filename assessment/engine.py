"""
assessment/engine.py

Correction des réponses et Error Mapping (guide MVP, section 4.1).

- evaluate_answer    : compare la réponse de l'étudiant à correct_answer
                       (avec équivalence de fractions)
- selected_option    : retrouve l'option QCM choisie par l'étudiant
- resolve_error_type : type d'erreur d'une réponse fausse, d'après la
                       classification préalable faite par l'administrateur
                       (options[].error_category, puis
                       chunk.default_error_category). Le système ne
                       "devine" pas la pensée de l'élève ; l'heuristique
                       classify_error ne sert que de repli pour le contenu
                       pas encore mappé (error_source='heuristic').
- answer_feedback    : feedback immédiat d'une réponse fausse

La logique d'évaluation / décision est dans evaluation.py et decision.py.
"""

from fractions import Fraction

from skills.models import Chunk
from .models import ErrorCategory, Error, StudentProgress

CARELESS_TIME_RATIO = 0.2

# Valeurs acceptées dans options[].error_category / default_error_category.
_CATEGORY_ALIASES = {
    'concept': ErrorCategory.CONCEPT, 'conceptual': ErrorCategory.CONCEPT, 'مفاهيمي': ErrorCategory.CONCEPT,
    'procedure': ErrorCategory.PROCEDURE, 'procedural': ErrorCategory.PROCEDURE, 'إجرائي': ErrorCategory.PROCEDURE,
    'careless': ErrorCategory.CARELESS, 'إهمالي': ErrorCategory.CARELESS,
}

# Feedback par défaut quand ni l'option ni le catalogue Error n'en fournissent.
DEFAULT_ERROR_FEEDBACK = {
    ErrorCategory.CONCEPT: "يبدو أن الفكرة الأساسية تحتاج إلى مراجعة. أعد قراءة القاعدة ثم حاول مرة أخرى.",
    ErrorCategory.PROCEDURE: "فهمت الفكرة لكن خطوات الحل غير صحيحة. راجع المثال خطوة بخطوة.",
    ErrorCategory.CARELESS: "انتبه إلى التفاصيل وتحقق من إجابتك قبل الإرسال.",
}


def _normalize(text):
    return (text or '').strip().lower()


def normalize_category(value):
    return _CATEGORY_ALIASES.get(_normalize(value)) if value else None


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


def selected_option(chunk: Chunk, answer: str):
    """Option riche (dict) correspondant à la réponse (par id ou par texte), sinon None."""
    given = _normalize(answer)
    for option in chunk.options or []:
        if not isinstance(option, dict):
            continue
        if given and given in (_normalize(str(option.get('id', ''))), _normalize(option.get('text'))):
            return option
    return None


def classify_error(progress: StudentProgress, time_taken, chunk: Chunk) -> str:
    """
    Repli heuristique pour le contenu non mappé :
    - CARELESS  : réponse très rapide par rapport à la limite de temps ;
    - PROCEDURE : l'étudiant a déjà réussi sur cette skill ;
    - CONCEPT   : sinon.
    """
    if time_taken is not None and chunk.time_limit:
        if time_taken < chunk.time_limit * CARELESS_TIME_RATIO:
            return ErrorCategory.CARELESS
    if progress.correct_count > 0:
        return ErrorCategory.PROCEDURE
    return ErrorCategory.CONCEPT


def resolve_error_type(chunk: Chunk, option, progress: StudentProgress, time_taken):
    """Retourne (error_type, error_source) pour une réponse fausse."""
    if option is not None:
        category = normalize_category(option.get('error_category'))
        if category:
            return category, 'option'
    category = normalize_category(chunk.default_error_category)
    if category:
        return category, 'chunk'
    return classify_error(progress, time_taken, chunk), 'heuristic'


def pick_error_detail(skill_id, category: str):
    return Error.objects.filter(skill_id=skill_id, category=category).order_by('id').first()


def answer_feedback(skill, error_type, option=None, error_detail=None):
    """
    Fiche d'erreur (écran S5) : message (feedback de l'option choisie,
    sinon catalogue Error, sinon message par défaut) + règle + exemple.
    """
    if error_detail is None and error_type:
        error_detail = pick_error_detail(skill.id, error_type)
    message = (option or {}).get('feedback') if option else None
    if not message and error_detail is not None:
        message = error_detail.feedback_message or error_detail.root_cause
    if not message:
        message = DEFAULT_ERROR_FEEDBACK.get(error_type)
    example = skill.chunks.filter(chunk_type=Chunk.ChunkType.EXAMPLE).order_by('order_index').first()
    rule = skill.chunks.filter(chunk_type=Chunk.ChunkType.RULE).order_by('order_index').first()
    return {
        'category': error_type,
        'message': message,
        'example': example.content if example else None,
        'rule': rule.content if rule else None,
    }
