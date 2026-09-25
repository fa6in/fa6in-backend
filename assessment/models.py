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
        Applique les règles métier du document (Partie 4.3, Règles 6 et 7) :

        Règle 6 - Calcul du mastery :
          - Si attempts < 3 : mastery = 0.00 (non fiable)
          - Si attempts >= 3 : mastery = correct_count / attempts

        Règle 7 - Status :
          - not_started : attempts = 0
          - in_progress : attempts > 0 et mastery < mastery_threshold
          - mastered : mastery >= mastery_threshold ET
                       consecutive_correct >= required_consecutive_correct
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

        self.mastery = round(self.correct_count / self.attempts, 2) if self.attempts >= 3 else 0.00

        threshold = float(self.skill.mastery_threshold)
        required_consecutive = self.skill.required_consecutive_correct

        if self.attempts == 0:
            self.status = self.Status.NOT_STARTED
        elif float(self.mastery) >= threshold and self.consecutive_correct >= required_consecutive:
            if self.status != self.Status.MASTERED:
                self.mastered_at = timezone.now()
            self.status = self.Status.MASTERED
        else:
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
