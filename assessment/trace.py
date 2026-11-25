"""
assessment/trace.py

Student Learning Trace (guide MVP, section 9 / 12.3) : historique des
évaluations, décisions, interventions et retours aux prérequis.
Rien n'est jamais supprimé : une nouvelle évaluation complète la ligne
précédente (mastery_after, error_type_after) puis en crée une nouvelle.
"""

from django.utils import timezone

from .models import LearningTrace, PrerequisiteReturn


def record_evaluation(group, result, decision, intervention=None):
    """
    Enregistre l'évaluation d'un groupe. Si le groupe a déjà une ligne
    (réévaluation pendant la vérification de la maîtrise), elle est mise
    à jour ; sinon la ligne précédente de la skill reçoit ses valeurs
    "après" et une nouvelle ligne est créée.
    """
    now = timezone.now()
    values = dict(
        student=group.student,
        skill=group.skill,
        evaluation_date=now,
        total_attempts=result.total_attempts,
        correct_answers=result.correct_answers,
        mastery_before=result.mastery,
        mastery_level=result.mastery_level,
        error_frequency=result.error_frequency,
        dominant_error_type=result.dominant_error_type,
        decision=decision,
        intervention=intervention,
        intervention_sequence=[
            {k: step.get(k) for k in ('step', 'kind', 'chunk_id')} for step in (intervention.sequence if intervention else [])
        ],
        intervention_status=intervention.status if intervention else '',
    )

    existing = LearningTrace.objects.filter(exercise_group=group).first()
    if existing is not None:
        for key, value in values.items():
            setattr(existing, key, value)
        existing.save()
        return existing

    previous = (
        LearningTrace.objects.filter(student=group.student, skill=group.skill, evaluation_after_date__isnull=True)
        .order_by('-evaluation_date').first()
    )
    if previous is not None:
        previous.mastery_after = result.mastery
        previous.error_type_after = result.dominant_error_type
        previous.evaluation_after_date = now
        previous.save(update_fields=['mastery_after', 'error_type_after', 'evaluation_after_date'])

    _record_prerequisite_results(group, result)
    return LearningTrace.objects.create(exercise_group=group, **values)


def update_intervention_status(intervention):
    LearningTrace.objects.filter(intervention=intervention).update(intervention_status=intervention.status)


def _record_prerequisite_results(group, result):
    """Résultats de l'étudiant après un retour à une skill préalable (section 9.1)."""
    # Évaluation sur la skill préalable pendant le retour.
    PrerequisiteReturn.objects.filter(
        student=group.student, to_skill=group.skill, status=PrerequisiteReturn.Status.ACTIVE,
    ).update(prerequisite_mastery_after=result.mastery)
    # Première évaluation sur la skill d'origine après le retour.
    back = (
        PrerequisiteReturn.objects.filter(
            student=group.student, from_skill=group.skill,
            status=PrerequisiteReturn.Status.COMPLETED, skill_mastery_after__isnull=True,
        ).order_by('-created_at').first()
    )
    if back is not None:
        back.skill_mastery_after = result.mastery
        back.save(update_fields=['skill_mastery_after'])
