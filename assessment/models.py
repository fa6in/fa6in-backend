"""
assessment/models.py

Catégorie C - Suivi et tracking
Tables : StudentProgress (student_progress), LogAnswer (log_answers), Error

Basé sur : FATIN_Schema_Final_Complet.docx - Partie 3, Catégorie C
et Partie 4.3 (Contraintes de tracking)
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from skills.models import Skill, Chunk


class ErrorCategory(models.TextChoices):
    CONCEPT = 'concept', _('خطأ مفاهيمي')
    PROCEDURE = 'procedure', _('خطأ إجرائي')
    CARELESS = 'careless', _('خطأ إهمالي')


class Error(models.Model):
    """
    Catalogue d'erreurs spécifiques associées aux skills.
    Principe pédagogique : 'خطأ = ضعف مهارة' -> chaque Error DOIT
    être liée à une Skill (skill NOT NULL).
    """

    class Severity(models.TextChoices):
        LOW = 'low', _('منخفضة')
        MEDIUM = 'medium', _('متوسطة')
        HIGH = 'high', _('عالية')

    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        verbose_name=_('المهارة'),
        related_name='error_catalog',
        db_comment="Skill associée (obligatoire)",
    )
    code = models.CharField(_('رمز الخطأ'), max_length=30, unique=True, db_comment="Ex: 'ERR-U01-L01-001'")
    category = models.CharField(_('فئة الخطأ'), max_length=20, choices=ErrorCategory.choices)
    error_type = models.CharField(_('وصف الخطأ المختصر'), max_length=500)
    root_cause = models.TextField(_('السبب الجذري'))
    severity_level = models.CharField(_('مستوى الخطورة'), max_length=20, choices=Severity.choices)
    feedback_message = models.TextField(_('رسالة المساعدة'), blank=True, null=True)
    created_at = models.DateTimeField(_('تاريخ الإنشاء'), auto_now_add=True)

    class Meta:
        verbose_name = _('نوع الخطأ')
        verbose_name_plural = _('أنواع الأخطاء')
        db_table_comment = "Catalogue d'erreurs - toujours liée à une Skill"

    def __str__(self):
        return f"{self.code} - {self.error_type}"


class StudentProgress(models.Model):
    """
    État actuel de progression de chaque étudiant sur chaque skill.
    Une seule ligne par couple (student, skill).
    """

    class Status(models.TextChoices):
        NOT_STARTED = 'not_started', _('لم يبدأ')
        IN_PROGRESS = 'in_progress', _('قيد التقدم')
        MASTERED = 'mastered', _('أتقن')

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name=_('الطالب'),
        related_name='progress',
        db_comment="L'étudiant",
    )
    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        verbose_name=_('المهارة'),
        related_name='student_progress',
        db_comment="La skill suivie",
    )
    attempts = models.IntegerField(_('عدد المحاولات'), default=0)
    correct_count = models.IntegerField(_('عدد الإجابات الصحيحة'), default=0)
    mastery = models.DecimalField(_('نسبة الإتقان'), max_digits=3, decimal_places=2, default=0.00)
    rule_seen = models.BooleanField(
        _('تمت مشاهدة القاعدة'), default=False,
        db_comment="True dès que NextActionView a servi un chunk 'rule' de cette skill à cet étudiant.",
    )
    example_seen = models.BooleanField(
        _('تمت مشاهدة المثال'), default=False,
        db_comment="True dès que NextActionView a servi un chunk 'example' de cette skill à cet étudiant.",
    )
    consecutive_correct = models.IntegerField(_('الإجابات الصحيحة المتتالية'), default=0)
    last_error_type = models.CharField(
        _('نوع آخر خطأ'), max_length=20, choices=ErrorCategory.choices,
        null=True, blank=True,
    )
    # État du moteur (Evaluation & Decision Engine MVP) pour ce couple
    # (étudiant, skill) : groupe d'exercices en cours, intervention en
    # cours, début du cycle d'apprentissage (un exercice n'est jamais
    # reproposé pendant un même cycle).
    cycle_started_at = models.DateTimeField(
        _('بداية دورة التعلم'), null=True, blank=True,
        db_comment="Début du cycle d'apprentissage courant de la skill",
    )
    active_group = models.ForeignKey(
        'ExerciseGroup', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name=_('مجموعة التمارين الحالية'),
    )
    active_intervention = models.ForeignKey(
        'Intervention', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name=_('التدخل الحالي'),
    )
    status = models.CharField(_('الحالة'), max_length=20, choices=Status.choices, default=Status.NOT_STARTED)
    started_at = models.DateTimeField(_('تاريخ البدء'), null=True, blank=True)
    mastered_at = models.DateTimeField(_('تاريخ الإتقان'), null=True, blank=True)
    last_activity = models.DateTimeField(_('آخر نشاط'), auto_now=True)

    class Meta:
        verbose_name = _('تقدم الطالب')
        verbose_name_plural = _('تقدم الطلاب')
        constraints = [
            models.UniqueConstraint(fields=['student', 'skill'], name='unique_student_skill_progress')
        ]
        db_table_comment = "Progression courante - PK composite (student_id, skill_id)"

    def __str__(self):
        return f"{self.student.username} - {self.skill.code} - {self.get_status_display()}"

    def register_attempt(self, is_correct: bool, error_category: str = None):
        """
        Enregistre une tentative : compteurs, série de réponses correctes
        (Correct Streak) et dernier type d'erreur.

        Le mastery et le statut 'mastered' ne sont PLUS calculés ici : selon
        le guide MVP (section 3), le mastery se calcule sur la DERNIÈRE
        mise en œuvre d'un groupe d'exercices uniquement, et la maîtrise
        est déclarée par le Decision Engine (assessment/decision.py).
        """
        if self.attempts == 0:
            self.started_at = timezone.now()

        self.attempts += 1

        if is_correct:
            self.correct_count += 1
            self.consecutive_correct += 1
            self.last_error_type = None
        else:
            self.consecutive_correct = 0
            self.last_error_type = error_category

        if self.status == self.Status.NOT_STARTED:
            self.status = self.Status.IN_PROGRESS

        self.save()
        return self.status


class LogAnswer(models.Model):
    """
    log_answers - Enregistrement de chaque réponse d'étudiant.
    OBLIGATOIRE et append-only : jamais UPDATE, jamais DELETE
    (Partie 4.3, Règle 8). Pour corriger, on ajoute une nouvelle ligne.
    """
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name=_('الطالب'),
        related_name='answer_logs',
        db_comment="L'étudiant",
    )
    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        verbose_name=_('المهارة'),
        related_name='answer_logs',
        db_comment="La skill",
    )
    chunk = models.ForeignKey(
        Chunk,
        on_delete=models.CASCADE,
        verbose_name=_('القطعة'),
        related_name='answer_logs',
        db_comment="Le chunk pratiqué",
    )
    answer = models.TextField(_('إجابة الطالب'))
    is_correct = models.BooleanField(_('إجابة صحيحة'))
    error_type = models.CharField(
        _('فئة الخطأ'), max_length=20, choices=ErrorCategory.choices,
        null=True, blank=True,
    )
    error_detail = models.ForeignKey(
        Error,
        on_delete=models.SET_NULL,
        verbose_name=_('تفاصيل الخطأ'),
        null=True, blank=True,
        related_name='occurrences',
        db_comment="Détail de l'erreur",
    )
    selected_option = models.CharField(
        _('الاختيار المقدم'), max_length=100, blank=True, default='',
        db_comment="Identifiant de l'option choisie (QCM riche), si reconnue",
    )
    error_source = models.CharField(
        _('مصدر تصنيف الخطأ'), max_length=20, blank=True, default='',
        db_comment="option (Error Mapping du choix) / chunk (catégorie par défaut de l'exercice) / heuristic",
    )
    exercise_group = models.ForeignKey(
        'ExerciseGroup', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='answers', verbose_name=_('مجموعة التمارين'),
    )
    intervention = models.ForeignKey(
        'Intervention', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='answers', verbose_name=_('التدخل'),
    )
    time_taken = models.IntegerField(_('الوقت المستغرق بالثواني'), null=True, blank=True)
    timestamp = models.DateTimeField(_('التاريخ والوقت'), auto_now_add=True)

    class Meta:
        verbose_name = _('سجل إجابة')
        verbose_name_plural = _('سجلات الإجابات')
        ordering = ['-timestamp']
        db_table_comment = "Historique append-only des réponses des étudiants"

    def __str__(self):
        return f"{self.student.username} - {self.chunk.code} - {'✔' if self.is_correct else '✘'}"

    def clean(self):
        """
        Contrainte critique (Partie 4.3, Règle 5) :
        CHECK (is_correct = TRUE OR error_type IS NOT NULL).
        """
        if not self.is_correct and not self.error_type:
            raise ValidationError(
                {'error_type': _("error_type est obligatoire lorsque la réponse est incorrecte.")}
            )

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError(_("log_answers est append-only : la modification est interdite."))
        self.full_clean(exclude=None, validate_unique=False)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("log_answers est append-only : la suppression est interdite."))


# ---------------------------------------------------------------------------
# Evaluation & Decision-Making Engine - MVP
# (FATIN_Evaluation_Decision_Making_Engine_MVP.docx)
# ---------------------------------------------------------------------------

class MasteryLevel(models.TextChoices):
    LOW = 'low', _('منخفض')
    MEDIUM = 'medium', _('متوسط')
    HIGH = 'high', _('مرتفع')


class Decision(models.TextChoices):
    CONTINUE = 'continue', _('متابعة التمارين')
    INTERVENTION = 'intervention', _('تدخل تعليمي')
    VERIFY_STREAK = 'verify_streak', _('التحقق من استقرار الإتقان')
    MASTERED = 'mastered', _('إعلان الإتقان')
    PREREQUISITE_RETURN = 'prerequisite_return', _('العودة إلى مهارة سابقة')
    TEACHER_REVIEW = 'teacher_review', _('إحالة إلى المعلم')


class EngineSettings(models.Model):
    """
    Section 11 du guide : les valeurs numériques ne sont pas codées en dur,
    elles sont modifiables ici (ligne unique, pk=1).
    """
    low_threshold = models.DecimalField(
        _('حد المستوى المنخفض'), max_digits=3, decimal_places=2, default=0.50,
        help_text=_('Low < low_threshold <= Medium'),
    )
    high_threshold = models.DecimalField(
        _('حد المستوى المرتفع'), max_digits=3, decimal_places=2, default=0.80,
        help_text=_('Medium < high_threshold <= High (aussi le mastery requis)'),
    )
    required_correct_streak = models.PositiveSmallIntegerField(
        _('عدد الإجابات الصحيحة المتتالية المطلوبة'), default=3,
    )
    min_attempts = models.PositiveSmallIntegerField(
        _('الحد الأدنى للمحاولات قبل الحكم على الإتقان'), default=4,
    )
    group_size = models.PositiveSmallIntegerField(
        _('عدد التمارين في المجموعة'), default=5,
        help_text=_("Nombre d'exercices d'un groupe d'évaluation (>= min_attempts)"),
    )
    updated_at = models.DateTimeField(_('تاريخ التحديث'), auto_now=True)

    class Meta:
        verbose_name = _('إعدادات محرك التقييم')
        verbose_name_plural = _('إعدادات محرك التقييم')

    def __str__(self):
        return str(_('إعدادات محرك التقييم'))

    def clean(self):
        if not (0 < self.low_threshold < self.high_threshold <= 1):
            raise ValidationError(_("Il faut 0 < low_threshold < high_threshold <= 1."))
        if self.group_size < self.min_attempts:
            raise ValidationError({'group_size': _("group_size doit être >= min_attempts.")})

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        if created:
            obj.refresh_from_db()  # valeurs Decimal (et non float) pour les comparaisons
        return obj


class ExerciseGroup(models.Model):
    """
    Groupe d'exercices présenté à l'étudiant puis évalué en bloc
    (Exercise Group ID du Learning Trace). Les résultats de l'évaluation
    sont stockés sur le groupe.
    """

    class Status(models.TextChoices):
        IN_PROGRESS = 'in_progress', _('قيد الإنجاز')
        VERIFYING = 'verifying', _('التحقق من الإتقان')
        COMPLETED = 'completed', _('مكتملة')

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='exercise_groups', verbose_name=_('الطالب'),
    )
    skill = models.ForeignKey(
        Skill, on_delete=models.CASCADE, related_name='exercise_groups', verbose_name=_('المهارة'),
    )
    exercise_ids = models.JSONField(_('التمارين'), default=list, db_comment="IDs des chunks 'practice' du groupe, dans l'ordre")
    status = models.CharField(_('الحالة'), max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)

    total_attempts = models.PositiveIntegerField(_('عدد المحاولات'), default=0)
    correct_answers = models.PositiveIntegerField(_('عدد الإجابات الصحيحة'), default=0)
    mastery = models.DecimalField(_('نسبة الإتقان'), max_digits=3, decimal_places=2, null=True, blank=True)
    mastery_level = models.CharField(_('مستوى الإتقان'), max_length=10, choices=MasteryLevel.choices, blank=True, default='')
    error_frequency = models.JSONField(_('تكرار أنواع الأخطاء'), default=dict, blank=True)
    dominant_error_type = models.CharField(
        _('نوع الخطأ الغالب'), max_length=20, choices=ErrorCategory.choices, blank=True, default='',
    )
    correct_streak = models.PositiveIntegerField(_('الإجابات الصحيحة المتتالية'), default=0)
    judged = models.BooleanField(
        _('حكم موثوق'), default=False,
        db_comment="True si le groupe atteint le minimum de tentatives (section 3.2)",
    )
    decision = models.CharField(_('القرار'), max_length=30, choices=Decision.choices, blank=True, default='')

    created_at = models.DateTimeField(_('تاريخ الإنشاء'), auto_now_add=True)
    evaluated_at = models.DateTimeField(_('تاريخ التقييم'), null=True, blank=True)

    class Meta:
        verbose_name = _('مجموعة تمارين')
        verbose_name_plural = _('مجموعات التمارين')
        ordering = ['-created_at']

    def __str__(self):
        return f"G{self.pk} {self.student} / {self.skill.code}"


class Intervention(models.Model):
    """
    Séquence d'intervention pédagogique (section 6) : séquence fixe de
    pas selon le type d'erreur dominant. La réévaluation n'a lieu
    qu'une fois la séquence complètement terminée (section 7).
    """

    class Status(models.TextChoices):
        IN_PROGRESS = 'in_progress', _('قيد التنفيذ')
        COMPLETED = 'completed', _('مكتمل')
        CANCELLED = 'cancelled', _('ملغى')

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='interventions', verbose_name=_('الطالب'),
    )
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name='interventions', verbose_name=_('المهارة'))
    group = models.ForeignKey(
        ExerciseGroup, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='interventions', verbose_name=_('مجموعة التقييم'),
    )
    error_type = models.CharField(_('نوع الخطأ المستهدف'), max_length=20, choices=ErrorCategory.choices)
    mastery_level = models.CharField(_('مستوى الإتقان'), max_length=10, choices=MasteryLevel.choices)
    sequence = models.JSONField(
        _('تسلسل الإجراءات'), default=list,
        db_comment="[{step, kind: content|exercise, chunk_id, instruction, status}]",
    )
    current_step = models.PositiveSmallIntegerField(_('الخطوة الحالية'), default=0)
    status = models.CharField(_('الحالة'), max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)
    created_at = models.DateTimeField(_('تاريخ الإنشاء'), auto_now_add=True)
    completed_at = models.DateTimeField(_('تاريخ الانتهاء'), null=True, blank=True)

    class Meta:
        verbose_name = _('تدخل تعليمي')
        verbose_name_plural = _('التدخلات التعليمية')
        ordering = ['-created_at']

    def __str__(self):
        return f"I{self.pk} {self.error_type} / {self.skill.code}"


class LearningTrace(models.Model):
    """
    Student Learning Trace (section 9) : une ligne par cycle
    évaluation -> décision -> intervention, complétée par la réévaluation
    suivante (mastery_after, error_type_after). Historique : jamais supprimé.
    """
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='learning_traces', verbose_name=_('الطالب'),
    )
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name='learning_traces', verbose_name=_('المهارة'))
    exercise_group = models.OneToOneField(
        ExerciseGroup, on_delete=models.CASCADE, related_name='trace', verbose_name=_('مجموعة التمارين'),
    )
    evaluation_date = models.DateTimeField(_('تاريخ التقييم'))
    total_attempts = models.PositiveIntegerField(_('عدد المحاولات'))
    correct_answers = models.PositiveIntegerField(_('عدد الإجابات الصحيحة'))
    mastery_before = models.DecimalField(_('الإتقان قبل التدخل'), max_digits=3, decimal_places=2)
    mastery_level = models.CharField(_('مستوى الإتقان'), max_length=10, choices=MasteryLevel.choices)
    error_frequency = models.JSONField(_('تكرار أنواع الأخطاء'), default=dict)
    dominant_error_type = models.CharField(
        _('نوع الخطأ الغالب'), max_length=20, choices=ErrorCategory.choices, blank=True, default='',
    )
    decision = models.CharField(_('القرار'), max_length=30, choices=Decision.choices)
    intervention = models.ForeignKey(
        Intervention, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='traces', verbose_name=_('التدخل'),
    )
    intervention_sequence = models.JSONField(_('تسلسل التدخل'), default=list, blank=True)
    intervention_status = models.CharField(_('حالة التدخل'), max_length=20, blank=True, default='')
    mastery_after = models.DecimalField(_('الإتقان بعد التدخل'), max_digits=3, decimal_places=2, null=True, blank=True)
    error_type_after = models.CharField(
        _('نوع الخطأ الغالب بعد التدخل'), max_length=20, choices=ErrorCategory.choices, blank=True, default='',
    )
    evaluation_after_date = models.DateTimeField(_('تاريخ التقييم اللاحق'), null=True, blank=True)

    class Meta:
        verbose_name = _('سجل تعلم')
        verbose_name_plural = _('سجل تعلم التلميذ')
        ordering = ['-evaluation_date']

    def __str__(self):
        return f"{self.student} / {self.skill.code} / {self.evaluation_date:%Y-%m-%d}"

    @property
    def mastery_improvement(self):
        if self.mastery_after is None:
            return None
        return round(float(self.mastery_after) - float(self.mastery_before), 2)


class PrerequisiteReturn(models.Model):
    """
    Section 8 : retour vers une skill préalable, ou cas sans prérequis
    adapté, enregistré pour revue par l'enseignant / l'administrateur.
    """

    class Status(models.TextChoices):
        ACTIVE = 'active', _('قيد المعالجة')
        COMPLETED = 'completed', _('مكتملة')
        TEACHER_REVIEW = 'teacher_review', _('بانتظار مراجعة المعلم')
        REVIEWED = 'reviewed', _('تمت المراجعة')

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='prerequisite_returns', verbose_name=_('الطالب'),
    )
    from_skill = models.ForeignKey(
        Skill, on_delete=models.CASCADE, related_name='returns_from', verbose_name=_('المهارة الحالية'),
    )
    to_skill = models.ForeignKey(
        Skill, on_delete=models.CASCADE, null=True, blank=True,
        related_name='returns_to', verbose_name=_('المهارة السابقة'),
    )
    exercise_group = models.ForeignKey(
        ExerciseGroup, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='prerequisite_returns', verbose_name=_('مجموعة التقييم'),
    )
    status = models.CharField(_('الحالة'), max_length=20, choices=Status.choices)
    reason = models.TextField(_('سبب القرار'))
    dominant_error_type = models.CharField(
        _('نوع الخطأ الغالب'), max_length=20, choices=ErrorCategory.choices, blank=True, default='',
    )
    skill_mastery_before = models.DecimalField(_('إتقان المهارة قبل العودة'), max_digits=3, decimal_places=2, null=True)
    prerequisite_mastery_before = models.DecimalField(
        _('إتقان المهارة السابقة قبل العودة'), max_digits=3, decimal_places=2, null=True, blank=True,
    )
    prerequisite_mastery_after = models.DecimalField(
        _('إتقان المهارة السابقة بعد العودة'), max_digits=3, decimal_places=2, null=True, blank=True,
    )
    skill_mastery_after = models.DecimalField(
        _('إتقان المهارة بعد العودة'), max_digits=3, decimal_places=2, null=True, blank=True,
    )
    review_note = models.TextField(_('ملاحظة المراجعة'), blank=True, default='')
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name=_('راجعه'),
    )
    created_at = models.DateTimeField(_('تاريخ الإنشاء'), auto_now_add=True)
    resolved_at = models.DateTimeField(_('تاريخ الإغلاق'), null=True, blank=True)

    class Meta:
        verbose_name = _('عودة إلى مهارة سابقة')
        verbose_name_plural = _('العودة إلى المهارات السابقة')
        ordering = ['-created_at']

    def __str__(self):
        target = self.to_skill.code if self.to_skill else '—'
        return f"{self.student} : {self.from_skill.code} -> {target} ({self.status})"
