"""
assessment/decision.py

Decision Engine (guide MVP, sections 5 à 8, 10 et 12.2) et orchestration
de la séance d'apprentissage :

    Exercise Group -> Evaluation -> Decision -> Intervention
                   -> New Exercise Group -> Re-evaluation

Règles appliquées :
- Pendant un groupe d'exercices, aucune décision : une réponse fausse
  reçoit un feedback immédiat et l'étudiant passe à l'exercice suivant.
- À la fin du groupe : évaluation (evaluation.py) puis matrice de décision
    Low / Medium + Concept   -> intervention conceptuelle
    Low / Medium + Procedure -> intervention sur les étapes de résolution
    Low / Medium + Careless  -> intervention sur la précision
    High                     -> vérification de la stabilité (streak)
- Les séquences d'intervention sont fixes (section 6) ; la réévaluation
  n'a lieu qu'après la séquence complète (section 7).
- Un exercice n'est jamais reproposé pendant le cycle d'apprentissage
  de la skill (section 10).
- Retour à une skill préalable seulement si les exercices de la skill
  sont épuisés ET la maîtrise non atteinte, et si un prérequis lié à la
  difficulté existe ; sinon le cas est enregistré pour l'enseignant (8).
"""

from decimal import Decimal

from django.utils import timezone

from curriculum.models import AcademicYear
from skills.models import Chunk, Prerequisite
from . import engine, trace
from .evaluation import evaluate_group
from .models import (
    Decision, EngineSettings, ErrorCategory, ExerciseGroup, Intervention, LogAnswer,
    MasteryLevel, PrerequisiteReturn, StudentProgress,
)
from .path import skill_is_open

MASTERED = StudentProgress.Status.MASTERED

INSTRUCTIONS = {
    'simple_exercise': "تمرين بسيط للتحقق من فهمك.",
    'applied_exercise': "تمرين تطبيقي على المهارة.",
    'guided_exercise': "أكمل الخطوات الناقصة في الحل.",
    'independent_exercise': "حل هذا التمرين بمفردك دون مساعدة.",
    'careless_exercise': "راجع كل خطوة من خطوات الحل قبل إرسال الإجابة.",
}

STEP_LABELS = {
    're_explain': "إعادة شرح المفهوم بطريقة مختلفة",
    'example': "مثال توضيحي",
    'simple_exercise': "تمرين بسيط للتحقق من الفهم",
    'applied_exercise': "تمرين تطبيقي",
    'steps_explanation': "شرح خطوات الحل بالتفصيل",
    'worked_example': "مثال محلول خطوة بخطوة",
    'guided_exercise': "تمرين بإكمال خطوات ناقصة",
    'independent_exercise': "تمرين مستقل",
    'careless_exercise': "تمرين جديد مع مراجعة كل خطوة",
}

INTERVENTION_REASON = {
    ErrorCategory.CONCEPT: "تدخل لمعالجة الفهم المفاهيمي",
    ErrorCategory.PROCEDURE: "تدخل لمعالجة خطوات الحل",
    ErrorCategory.CARELESS: "تدخل لتحسين الدقة والمراجعة",
}


# ---------------------------------------------------------------------------
# Sélection des exercices (section 10)
# ---------------------------------------------------------------------------

def _ensure_cycle(progress):
    if progress.cycle_started_at is None:
        progress.cycle_started_at = timezone.now()
        progress.save(update_fields=['cycle_started_at'])


def start_new_cycle(progress):
    """Nouveau cycle d'apprentissage : les exercices redeviennent disponibles."""
    progress.cycle_started_at = timezone.now()
    progress.active_group = None
    progress.save(update_fields=['cycle_started_at', 'active_group'])


def used_exercise_ids(progress):
    """Exercices déjà faits (ou réservés) pendant le cycle courant."""
    qs = LogAnswer.objects.filter(
        student=progress.student, skill=progress.skill, chunk__chunk_type=Chunk.ChunkType.PRACTICE,
    )
    if progress.cycle_started_at:
        qs = qs.filter(timestamp__gte=progress.cycle_started_at)
    used = set(qs.values_list('chunk_id', flat=True))
    group = progress.active_group
    if group is not None and group.status != ExerciseGroup.Status.COMPLETED:
        used |= set(group.exercise_ids)
    intervention = progress.active_intervention
    if intervention is not None and intervention.status == Intervention.Status.IN_PROGRESS:
        used |= {s['chunk_id'] for s in intervention.sequence if s.get('kind') == 'exercise' and s.get('chunk_id')}
    return used


def available_exercises(skill, progress, exclude=()):
    used = used_exercise_ids(progress) | set(exclude)
    return [
        c for c in skill.chunks.filter(chunk_type=Chunk.ChunkType.PRACTICE).order_by('order_index', 'id')
        if c.id not in used
    ]


def target_difficulty(level, dominant_error):
    """Difficulté visée selon le dernier niveau de maîtrise et le type d'erreur dominant."""
    target = {MasteryLevel.LOW: 1, MasteryLevel.MEDIUM: 2, MasteryLevel.HIGH: 3}.get(level, 1)
    if dominant_error == ErrorCategory.CONCEPT:
        target = max(1, target - 1)
    return target


def pick_exercises(skill, progress, count, target, prefer_guided=False, exclude=()):
    candidates = available_exercises(skill, progress, exclude)

    def key(chunk):
        guided_rank = (0 if chunk.is_guided else 1) if prefer_guided else (1 if chunk.is_guided else 0)
        if prefer_guided:
            return (guided_rank, abs(chunk.difficulty - target), chunk.order_index, chunk.id)
        return (abs(chunk.difficulty - target), guided_rank, chunk.order_index, chunk.id)

    return sorted(candidates, key=key)[:count]


def last_evaluated_group(student, skill):
    return (
        ExerciseGroup.objects.filter(student=student, skill=skill, evaluated_at__isnull=False)
        .order_by('-evaluated_at', '-id').first()
    )


def _new_group(progress, settings):
    skill = progress.skill
    last = last_evaluated_group(progress.student, skill)
    target = target_difficulty(
        last.mastery_level if last else MasteryLevel.LOW,
        last.dominant_error_type if last else '',
    )
    picks = pick_exercises(skill, progress, settings.group_size, target)
    if not picks:
        return None
    group = ExerciseGroup.objects.create(
        student=progress.student, skill=skill, exercise_ids=[c.id for c in picks],
    )
    progress.active_group = group
    progress.save(update_fields=['active_group'])
    return group


def group_answered_ids(group):
    return set(LogAnswer.objects.filter(exercise_group=group).values_list('chunk_id', flat=True))


def next_group_exercise_id(group):
    answered = group_answered_ids(group)
    return next((cid for cid in group.exercise_ids if cid not in answered), None)


# ---------------------------------------------------------------------------
# Interventions (section 6)
# ---------------------------------------------------------------------------

def _rotating_chunk(skill, chunk_types, nth, skip_first=False):
    """Contenu à afficher ; change à chaque nouvelle intervention du même type."""
    for chunk_type in chunk_types:
        chunks = list(skill.chunks.filter(chunk_type=chunk_type).order_by('order_index', 'id'))
        if not chunks:
            continue
        if skip_first and len(chunks) > 1:
            chunks = chunks[1:]
        return chunks[nth % len(chunks)]
    return None


def build_intervention_sequence(progress, error_type, level, dominant_for_target):
    skill = progress.skill
    nth = Intervention.objects.filter(student=progress.student, skill=skill, error_type=error_type).count()
    target = target_difficulty(level, dominant_for_target)
    chosen = []
    steps = []

    def content(step, chunk_types, skip_first=False):
        chunk = _rotating_chunk(skill, chunk_types, nth, skip_first)
        if chunk is not None:
            steps.append({'step': step, 'kind': 'content', 'chunk_id': chunk.id, 'instruction': None, 'status': 'pending'})

    def exercise(step, difficulty, prefer_guided=False):
        picks = pick_exercises(skill, progress, 1, difficulty, prefer_guided=prefer_guided, exclude=chosen)
        if picks:
            chosen.append(picks[0].id)
            steps.append({
                'step': step, 'kind': 'exercise', 'chunk_id': picks[0].id,
                'instruction': INSTRUCTIONS[step], 'status': 'pending',
            })

    if error_type == ErrorCategory.CONCEPT:
        content('re_explain', [Chunk.ChunkType.RULE], skip_first=True)
        content('example', [Chunk.ChunkType.EXAMPLE])
        exercise('simple_exercise', 1)
        exercise('applied_exercise', 5)
    elif error_type == ErrorCategory.PROCEDURE:
        content('steps_explanation', [Chunk.ChunkType.HINT, Chunk.ChunkType.RULE])
        content('worked_example', [Chunk.ChunkType.EXAMPLE])
        exercise('guided_exercise', target, prefer_guided=True)
        exercise('independent_exercise', target)
    else:  # CARELESS : exercice + consigne de relecture, feedback, nouvel exercice
        exercise('careless_exercise', target)
        exercise('careless_exercise', target)
    return steps


def _start_intervention(progress, group, error_type, level):
    sequence = build_intervention_sequence(progress, error_type, level, error_type)
    intervention = Intervention.objects.create(
        student=progress.student, skill=progress.skill, group=group,
        error_type=error_type, mastery_level=level, sequence=sequence,
    )
    if not sequence:
        _complete_intervention(progress, intervention)
    else:
        progress.active_intervention = intervention
        progress.save(update_fields=['active_intervention'])
    return intervention


def _complete_intervention(progress, intervention):
    intervention.status = Intervention.Status.COMPLETED
    intervention.completed_at = timezone.now()
    intervention.save(update_fields=['status', 'completed_at', 'sequence', 'current_step'])
    if progress.active_intervention_id == intervention.id:
        progress.active_intervention = None
        progress.save(update_fields=['active_intervention'])
    trace.update_intervention_status(intervention)


def _current_exercise_step(intervention):
    if intervention is None or intervention.status != Intervention.Status.IN_PROGRESS:
        return None
    if intervention.current_step >= len(intervention.sequence):
        return None
    step = intervention.sequence[intervention.current_step]
    return step if step.get('kind') == 'exercise' else None


# ---------------------------------------------------------------------------
# Retour aux skills préalables (section 8)
# ---------------------------------------------------------------------------

def find_prerequisite(student, skill, dominant_error):
    """
    Retourne (skill_préalable, mastery_actuelle, raison) ; skill_préalable
    vaut None si aucune n'est adaptée (la raison explique pourquoi).
    """
    if dominant_error == ErrorCategory.CARELESS:
        return None, None, "الخطأ الغالب ناتج عن عدم الانتباه، وهذا لا يعني الحاجة إلى مهارة سابقة."
    if not dominant_error:
        return None, None, "لم يُحدَّد نوع خطأ غالب يربط الصعوبة بمهارة سابقة."

    prereqs = list(
        Prerequisite.objects.filter(skill=skill)
        .select_related('prerequisite__goal__lesson')
        .order_by('prerequisite__order_index', 'prerequisite_id')
    )
    if not prereqs:
        return None, None, "لا توجد مهارة سابقة مرتبطة بهذه المهارة."

    week = AcademicYear.current_week()
    progress_by_skill = {
        p.skill_id: p for p in StudentProgress.objects.filter(
            student=student, skill_id__in=[p.prerequisite_id for p in prereqs],
        )
    }
    candidates = []
    for p in prereqs:
        related = [engine.normalize_category(t) for t in (p.related_error_types or [])]
        related = [t for t in related if t] or [ErrorCategory.CONCEPT, ErrorCategory.PROCEDURE]
        if dominant_error not in related:
            continue
        if not skill_is_open(p.prerequisite, week):
            continue
        pre_progress = progress_by_skill.get(p.prerequisite_id)
        if pre_progress and pre_progress.status == MASTERED:
            continue
        candidates.append((pre_progress.mastery if pre_progress else 0, p.prerequisite))

    if not candidates:
        return None, None, "لا توجد مهارة سابقة غير متقنة مرتبطة بالصعوبة التي ظهرت."
    mastery, prerequisite = min(candidates, key=lambda c: c[0])
    return prerequisite, mastery, (
        f"استُنفدت تمارين المهارة دون بلوغ الإتقان، والخطأ الغالب "
        f"({dominant_error}) مرتبط بالمهارة السابقة {prerequisite.code}."
    )


def active_return(student, skill):
    return (
        PrerequisiteReturn.objects.filter(student=student, from_skill=skill, status=PrerequisiteReturn.Status.ACTIVE)
        .select_related('to_skill').order_by('-created_at').first()
    )


def _complete_return(ret, prerequisite_mastery=None):
    ret.status = PrerequisiteReturn.Status.COMPLETED
    ret.resolved_at = timezone.now()
    if prerequisite_mastery is not None:
        ret.prerequisite_mastery_after = prerequisite_mastery
    ret.save(update_fields=['status', 'resolved_at', 'prerequisite_mastery_after'])
    # De retour sur la skill d'origine : nouveau cycle d'apprentissage.
    from_progress = StudentProgress.objects.filter(student=ret.student, skill=ret.from_skill).first()
    if from_progress is not None:
        start_new_cycle(from_progress)


def _handle_exhaustion(progress, group, mastery, dominant_error):
    """
    Exercices épuisés sans maîtrise : retour à une skill préalable adaptée,
    sinon enregistrement du cas pour l'enseignant et nouveau cycle.
    Retourne (decision, PrerequisiteReturn).
    """
    prerequisite, pre_mastery, reason = find_prerequisite(progress.student, progress.skill, dominant_error)
    if prerequisite is None:
        # Un seul cas ouvert par (étudiant, skill) : on le met à jour.
        open_case = PrerequisiteReturn.objects.filter(
            student=progress.student, from_skill=progress.skill,
            status=PrerequisiteReturn.Status.TEACHER_REVIEW,
        ).first()
        if open_case is not None:
            open_case.reason = reason
            open_case.exercise_group = group
            open_case.dominant_error_type = dominant_error or ''
            open_case.skill_mastery_before = mastery
            open_case.save(update_fields=['reason', 'exercise_group', 'dominant_error_type', 'skill_mastery_before'])
            start_new_cycle(progress)
            return Decision.TEACHER_REVIEW, open_case
    ret = PrerequisiteReturn.objects.create(
        student=progress.student, from_skill=progress.skill, to_skill=prerequisite,
        exercise_group=group, dominant_error_type=dominant_error or '',
        status=PrerequisiteReturn.Status.ACTIVE if prerequisite else PrerequisiteReturn.Status.TEACHER_REVIEW,
        reason=reason, skill_mastery_before=mastery, prerequisite_mastery_before=pre_mastery,
    )
    if prerequisite is not None:
        return Decision.PREREQUISITE_RETURN, ret
    start_new_cycle(progress)
    return Decision.TEACHER_REVIEW, ret


# ---------------------------------------------------------------------------
# Évaluation de fin de groupe + matrice de décision (section 5)
# ---------------------------------------------------------------------------

def evaluate_and_decide(progress, group):
    settings = EngineSettings.load()
    result = evaluate_group(group, settings)
    outcome = {'result': result, 'decision': None, 'new_intervention': None, 'prerequisite_return': None}

    # 3.2 : pas de jugement avant le minimum de tentatives -> on complète
    # le groupe avec d'autres exercices s'il en reste.
    if not result.judged:
        need = settings.min_attempts - result.total_attempts
        extra = pick_exercises(progress.skill, progress, need, target_difficulty(MasteryLevel.LOW, ''))
        if extra:
            group.exercise_ids = group.exercise_ids + [c.id for c in extra]
            group.save(update_fields=['exercise_ids'])
            outcome['decision'] = Decision.CONTINUE
            return outcome

    now = timezone.now()
    level = result.mastery_level
    intervention = None
    ret = None

    if level == MasteryLevel.HIGH:
        # 6.4 : mastery >= seuil requis ET streak >= streak requis.
        if result.mastery >= Decimal(str(settings.high_threshold)) \
                and result.correct_streak >= settings.required_correct_streak:
            decision = Decision.MASTERED
        else:
            decision = Decision.VERIFY_STREAK
    else:
        decision = Decision.INTERVENTION
        if not available_exercises(progress.skill, progress, exclude=group.exercise_ids):
            decision, ret = _handle_exhaustion(progress, group, result.mastery, result.dominant_error_type)

    # Mise à jour du groupe.
    group.total_attempts = result.total_attempts
    group.correct_answers = result.correct_answers
    group.mastery = result.mastery
    group.mastery_level = level
    group.error_frequency = result.error_frequency
    group.dominant_error_type = result.dominant_error_type
    group.correct_streak = result.correct_streak
    group.judged = result.judged
    group.decision = decision
    group.evaluated_at = now
    group.status = (
        ExerciseGroup.Status.VERIFYING if decision == Decision.VERIFY_STREAK else ExerciseGroup.Status.COMPLETED
    )
    group.save()

    # Le mastery affiché est celui de la dernière évaluation (section 3).
    progress.mastery = result.mastery
    update_fields = ['mastery']
    if decision != Decision.VERIFY_STREAK and progress.active_group_id == group.id:
        progress.active_group = None
        update_fields.append('active_group')
    if decision == Decision.MASTERED and progress.status != MASTERED:
        progress.status = MASTERED
        progress.mastered_at = now
        update_fields += ['status', 'mastered_at']
    progress.save(update_fields=update_fields)

    if decision in (Decision.INTERVENTION, Decision.TEACHER_REVIEW):
        error_type = result.dominant_error_type or ErrorCategory.CONCEPT
        intervention = _start_intervention(progress, group, error_type, level)

    if decision == Decision.MASTERED:
        # Une skill préalable maîtrisée clôt les retours qui y menaient.
        for pending in PrerequisiteReturn.objects.filter(
            student=progress.student, to_skill=progress.skill, status=PrerequisiteReturn.Status.ACTIVE,
        ):
            _complete_return(pending, result.mastery)

    trace.record_evaluation(group, result, decision, intervention)
    outcome.update(decision=decision, new_intervention=intervention, prerequisite_return=ret)
    return outcome


# ---------------------------------------------------------------------------
# Orchestration : prochain contenu à afficher
# ---------------------------------------------------------------------------

def _step(mode, chunk, reason, **extra):
    return {'action': 'show_chunk', 'mode': mode, 'chunk': chunk, 'reason': reason, **extra}


def _serve_intervention(progress):
    intervention = progress.active_intervention
    if intervention is None or intervention.status != Intervention.Status.IN_PROGRESS:
        return None
    sequence = intervention.sequence
    while intervention.current_step < len(sequence):
        index = intervention.current_step
        step = sequence[index]
        chunk = Chunk.objects.filter(pk=step.get('chunk_id')).first()
        if chunk is None:
            step['status'] = 'skipped'
            intervention.current_step += 1
            continue
        info = {
            'id': intervention.id,
            'error_type': intervention.error_type,
            'reason': INTERVENTION_REASON.get(intervention.error_type),
            'step': step['step'],
            'step_label': STEP_LABELS.get(step['step']),
            'step_index': index + 1,
            'steps_total': len(sequence),
        }
        if step['kind'] == 'content':
            # Un contenu est considéré vu dès qu'il est servi.
            step['status'] = 'done'
            intervention.current_step += 1
            intervention.sequence = sequence
            intervention.save(update_fields=['sequence', 'current_step'])
        else:
            intervention.save(update_fields=['sequence', 'current_step'])
        return _step('intervention', chunk, info['reason'], intervention=info, instruction=step.get('instruction'))
    _complete_intervention(progress, intervention)
    return None


def next_step(student, skill):
    """
    Décide le prochain contenu pour (student, skill). Retourne soit
    {'action': 'redirect', 'return': PrerequisiteReturn}, soit
    {'action': 'show_chunk', 'mode': learn|intervention|group|verify, 'chunk', ...}.
    """
    progress, _created = StudentProgress.objects.get_or_create(student=student, skill=skill)

    # Retour en cours vers une skill préalable.
    ret = active_return(student, skill)
    if ret is not None:
        pre_progress = StudentProgress.objects.filter(student=student, skill=ret.to_skill).first()
        if pre_progress and pre_progress.status == MASTERED:
            _complete_return(ret, pre_progress.mastery)
            progress.refresh_from_db()
        else:
            return {'action': 'redirect', 'return': ret, 'progress': progress}

    # Découverte : règle puis exemple (une seule fois).
    for flag, chunk_type, reason in (
        ('rule_seen', Chunk.ChunkType.RULE, "Première visite : découverte de la règle"),
        ('example_seen', Chunk.ChunkType.EXAMPLE, "Première visite : découverte de l'exemple"),
    ):
        if not getattr(progress, flag):
            chunk = skill.chunks.filter(chunk_type=chunk_type).order_by('order_index').first()
            setattr(progress, flag, True)
            progress.save(update_fields=[flag])
            if chunk is not None:
                return {**_step('learn', chunk, reason), 'progress': progress}

    # Intervention en cours : on la termine avant toute réévaluation.
    served = _serve_intervention(progress)
    if served is not None:
        return {**served, 'progress': progress}

    settings = EngineSettings.load()
    _ensure_cycle(progress)
    group = progress.active_group
    if group is None or group.status == ExerciseGroup.Status.COMPLETED:
        group = _new_group(progress, settings)
        if group is None:
            # Exercices épuisés hors groupe (ex. après une intervention).
            last = last_evaluated_group(student, skill)
            if progress.status != MASTERED and last is not None and last.mastery_level != MasteryLevel.HIGH:
                decision, ret = _handle_exhaustion(progress, None, last.mastery, last.dominant_error_type)
                if decision == Decision.PREREQUISITE_RETURN:
                    return {'action': 'redirect', 'return': ret, 'progress': progress}
            else:
                start_new_cycle(progress)
            group = _new_group(progress, settings)
        if group is None:
            return {**_step('group', None, "Aucun exercice disponible pour cette skill"), 'progress': progress}

    next_id = next_group_exercise_id(group)
    if next_id is None and group.status == ExerciseGroup.Status.VERIFYING:
        # 6.4 : streak pas encore atteint -> un nouvel exercice.
        target = target_difficulty(group.mastery_level, group.dominant_error_type)
        extra = pick_exercises(skill, progress, 1, target)
        if not extra:
            start_new_cycle(progress)
            progress.active_group = group
            progress.save(update_fields=['active_group'])
            extra = pick_exercises(skill, progress, 1, target)
        if extra:
            group.exercise_ids = group.exercise_ids + [extra[0].id]
            group.save(update_fields=['exercise_ids'])
            next_id = extra[0].id
    if next_id is None:
        return {**_step('group', None, "Aucun exercice disponible pour cette skill"), 'progress': progress}

    verifying = group.status == ExerciseGroup.Status.VERIFYING
    answered = len(group_answered_ids(group))
    return {
        **_step(
            'verify' if verifying else 'group',
            Chunk.objects.get(pk=next_id),
            "التحقق من استقرار الإتقان" if verifying else "مجموعة تمارين",
            group={'id': group.id, 'answered': answered, 'total': len(group.exercise_ids)},
        ),
        'progress': progress,
    }


# ---------------------------------------------------------------------------
# Orchestration : réponse à un exercice
# ---------------------------------------------------------------------------

def handle_answer(student, chunk, answer, time_taken=None):
    skill = chunk.skill
    progress, _created = StudentProgress.objects.get_or_create(student=student, skill=skill)
    was_mastered = progress.status == MASTERED

    option = engine.selected_option(chunk, answer)
    is_correct = engine.evaluate_answer(chunk, answer)
    error_type = error_source = None
    error_detail = None
    if not is_correct:
        error_type, error_source = engine.resolve_error_type(chunk, option, progress, time_taken)
        error_detail = engine.pick_error_detail(skill.id, error_type)

    # Contexte de la réponse : pas d'intervention, groupe en cours, ou libre.
    intervention = progress.active_intervention
    step = _current_exercise_step(intervention)
    if step is None or step.get('chunk_id') != chunk.id:
        intervention = None
    group = progress.active_group
    if (
        intervention is not None or group is None or group.status == ExerciseGroup.Status.COMPLETED
        or chunk.id not in group.exercise_ids or chunk.id in group_answered_ids(group)
    ):
        group = None

    log = LogAnswer(
        student=student, skill=skill, chunk=chunk, answer=answer,
        is_correct=is_correct, error_type=error_type, error_detail=error_detail,
        time_taken=time_taken, exercise_group=group, intervention=intervention,
        selected_option=str(option.get('id', '')) if option else '',
        error_source=error_source or '',
    )
    log.save()
    progress.register_attempt(is_correct=is_correct, error_category=error_type)

    outcome = {'decision': None, 'result': None, 'new_intervention': None, 'prerequisite_return': None}
    if intervention is not None:
        step['status'] = 'done'
        step['is_correct'] = is_correct
        intervention.current_step += 1
        intervention.save(update_fields=['sequence', 'current_step'])
        if intervention.current_step >= len(intervention.sequence):
            _complete_intervention(progress, intervention)
    elif group is not None:
        if group.status == ExerciseGroup.Status.VERIFYING or next_group_exercise_id(group) is None:
            outcome = evaluate_and_decide(progress, group)
        progress.refresh_from_db()

    feedback = None
    if not is_correct:
        feedback = engine.answer_feedback(skill, error_type, option, error_detail)

    return {
        'log': log,
        'progress': progress,
        'is_correct': is_correct,
        'error_type': error_type,
        'error_source': error_source,
        'error_detail': error_detail,
        'feedback': feedback,
        'group': group,
        'intervention': intervention,
        'mastered_now': not was_mastered and progress.status == MASTERED,
        **outcome,
    }
