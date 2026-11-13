"""
curriculum/models.py

Catégorie B - Structure pédagogique (partie 1/2)
Hiérarchie : Stage -> Level -> Subject -> Unit -> Lesson -> Goal
(Skill, Prerequisites, Chunk sont dans l'app `skills`)

Basé sur : FATIN_Schema_Final_Complet.docx - Partie 2 et Partie 3 (Catégorie B)
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class Stage(models.Model):
    """
    Étape scolaire globale du système éducatif mauritanien.
    Ex : Primaire, Secondaire, Lycée.
    """
    name = models.CharField(
        _('اسم المرحلة'),
        max_length=100,
        db_comment="Ex: 'المرحلة الابتدائية'",
    )
    code = models.CharField(
        _('الرمز'),
        max_length=20,
        unique=True,
        db_comment="Code court (ex: 'PRIM')",
    )
    order_index = models.IntegerField(_('ترتيب المراحل'), db_comment="Ordre des étapes")
    description = models.TextField(_('الوصف'), blank=True, null=True)

    class Meta:
        verbose_name = _('مرحلة')
        verbose_name_plural = _('المراحل')
        ordering = ['order_index']
        db_table_comment = "Étape scolaire globale (Primaire, Secondaire, Lycée)"

    def __str__(self):
        return self.name


class Level(models.Model):
    """
    Année scolaire au sein d'une étape (ex: Première année primaire).
    """
    stage = models.ForeignKey(
        Stage,
        on_delete=models.CASCADE,
        verbose_name=_('المرحلة'),
        related_name='levels',
        db_comment="Étape parente",
    )
    name = models.CharField(_('اسم السنة'), max_length=100, db_comment="Ex: 'السنة الأولى ابتدائية'")
    code = models.CharField(_('الرمز'), max_length=20, unique=True, db_comment="Code court (ex: 'PRIM-1')")
    order_index = models.IntegerField(_('الترتيب داخل المرحلة'))
    description = models.TextField(_('الوصف'), blank=True, null=True)

    class Meta:
        verbose_name = _('سنة دراسية')
        verbose_name_plural = _('السنوات الدراسية')
        ordering = ['stage__order_index', 'order_index']
        db_table_comment = "Année scolaire au sein d'une étape"

    def __str__(self):
        return f"{self.name} ({self.stage.name})"


class Subject(models.Model):
    """
    Matière scolaire au sein d'une année (ex: Mathématiques).
    """
    level = models.ForeignKey(
        Level,
        on_delete=models.CASCADE,
        verbose_name=_('السنة الدراسية'),
        related_name='subjects',
        db_comment="Année scolaire",
    )
    name = models.CharField(_('اسم المادة'), max_length=100)
    description = models.TextField(_('الوصف'), blank=True, null=True)
    color = models.CharField(_('اللون'), max_length=7, blank=True, help_text=_('Code couleur hexadécimal, ex: #3498db'))
    icon = models.CharField(_('الأيقونة'), max_length=50, blank=True)
    is_active = models.BooleanField(_('نشط'), default=True)
    created_at = models.DateTimeField(_('تاريخ الإنشاء'), auto_now_add=True)
    updated_at = models.DateTimeField(_('تاريخ التحديث'), auto_now=True)

    class Meta:
        verbose_name = _('مادة')
        verbose_name_plural = _('المواد')
        unique_together = [['name', 'level']]
        ordering = ['level', 'name']
        db_table_comment = "Matière scolaire au sein d'une année"

    def __str__(self):
        return f"{self.name} - {self.level.name}"


class Unit(models.Model):
    """
    Unité d'apprentissage au sein d'une matière.
    Contient l'objectif global et la question centrale.
    """
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        verbose_name=_('المادة'),
        related_name='units',
        db_comment="Matière parente",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_('أنشئت بواسطة'),
        related_name='created_units',
        db_comment="Créateur",
    )
    code = models.CharField(_('رمز الوحدة'), max_length=20, unique=True, db_comment="Ex: 'U01'")
    title = models.CharField(_('عنوان الوحدة'), max_length=255)
    description = models.TextField(_('الوصف'), blank=True, null=True)
    main_goal_description = models.TextField(
        _('الهدف الرئيسي'), blank=True, null=True,
        db_comment="Objectif global (texte descriptif)",
    )
    central_question = models.TextField(
        _('السؤال المركزي'), blank=True, null=True,
        db_comment="Question centrale qui guide l'apprentissage",
    )
    main_skill_domain = models.CharField(_('مجال الكفاءة الرئيسي'), max_length=200, blank=True)
    term = models.CharField(
        _('الفصل الدراسي'), max_length=50, blank=True, default='',
        db_comment="Trimestre / période du programme (import)",
    )
    competency_ref = models.CharField(
        _('مرجع الكفاية'), max_length=100, blank=True, default='',
        db_comment="Référence de la compétence dans le programme officiel (import)",
    )
    order_index = models.IntegerField(_('الترتيب'), default=0)
    is_published = models.BooleanField(_('منشورة'), default=False)
    thumbnail = models.ImageField(_('الصورة المصغرة'), upload_to='units/', null=True, blank=True)
    created_at = models.DateTimeField(_('تاريخ الإنشاء'), auto_now_add=True)

    class Meta:
        verbose_name = _('وحدة تعليمية')
        verbose_name_plural = _('الوحدات التعليمية')
        ordering = ['subject', 'order_index']
        db_table_comment = "Unité d'apprentissage - contient objectif et question centrale"

    def __str__(self):
        return f"{self.code} - {self.title}"


class Lesson(models.Model):
    """
    Leçon au sein d'une unité.
    Chaque leçon possède obligatoirement deux Goals (Conceptual + Operational).
    """
    unit = models.ForeignKey(
        Unit,
        on_delete=models.CASCADE,
        verbose_name=_('الوحدة'),
        related_name='lessons',
        db_comment="Unité parente",
    )
    code = models.CharField(_('رمز الدرس'), max_length=30, unique=True, db_comment="Ex: 'U01-L01'")
    title = models.CharField(_('عنوان الدرس'), max_length=255)
    description = models.TextField(_('الوصف'), blank=True, null=True)
    order_index = models.IntegerField(_('الترتيب داخل الوحدة'), default=0)
    programme_ref = models.CharField(
        _('مرجع البرنامج'), max_length=100, blank=True, default='',
        db_comment="Référence de la leçon dans le programme officiel (import)",
    )
    week = models.PositiveSmallIntegerField(
        _('الأسبوع'), null=True, blank=True,
        db_comment="Semaine du programme où la leçon est enseignée (import)",
    )
    programme_weeks = models.JSONField(
        _('أسابيع البرنامج'), default=list, blank=True,
        db_comment="Semaines du programme couvertes par la leçon (import)",
    )
    book_exercises = models.JSONField(
        _('تمارين الكتاب'), default=list, blank=True,
        db_comment="Exercices du manuel associés à la leçon (import)",
    )
    is_published = models.BooleanField(_('منشور'), default=False)
    created_at = models.DateTimeField(_('تاريخ الإنشاء'), auto_now_add=True)

    class Meta:
        verbose_name = _('درس')
        verbose_name_plural = _('الدروس')
        ordering = ['unit', 'order_index']
        db_table_comment = "Leçon au sein d'une unité"

    def __str__(self):
        return f"{self.code} - {self.title}"

    def clean(self):
        """
        Règle métier : ne pas publier une leçon qui n'a pas exactement
        un Goal Conceptual et un Goal Operational (Partie 4, Règle 1).
        """
        if self.is_published and self.pk:
            c_count = self.goals.filter(goal_type=Goal.GoalType.CONCEPTUAL).count()
            o_count = self.goals.filter(goal_type=Goal.GoalType.OPERATIONAL).count()
            if c_count != 1 or o_count != 1:
                raise ValidationError(
                    _("Une leçon publiée doit avoir exactement un Goal Conceptual "
                      "et un Goal Operational (actuellement %(c)s conceptual, %(o)s operational).")
                    % {'c': c_count, 'o': o_count}
                )


class Goal(models.Model):
    """
    Objectif pédagogique au sein d'une leçon.
    Distinction essentielle entre Conceptual (compréhension) et
    Operational (application), qui détermine le type des Skills liées.
    """

    class GoalType(models.TextChoices):
        CONCEPTUAL = 'conceptual', _('مفاهيمي')
        OPERATIONAL = 'operational', _('عملياتي')

    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        verbose_name=_('الدرس'),
        related_name='goals',
        db_comment="Leçon parente",
    )
    goal_type = models.CharField(
        _('نوع الهدف'), max_length=20, choices=GoalType.choices,
        db_comment="Conceptual OU Operational",
    )
    title = models.CharField(_('عنوان الهدف'), max_length=500)
    description = models.TextField(_('وصف الهدف'), blank=True, null=True)
    order_index = models.IntegerField(_('الترتيب'), default=0)
    created_at = models.DateTimeField(_('تاريخ الإنشاء'), auto_now_add=True)

    class Meta:
        verbose_name = _('هدف تعليمي')
        verbose_name_plural = _('الأهداف التعليمية')
        ordering = ['lesson', 'order_index']
        db_table_comment = "Objectif pédagogique Conceptual/Operational"
        constraints = [
            models.UniqueConstraint(
                fields=['lesson', 'goal_type'],
                name='unique_goal_type_per_lesson',
            )
        ]

    def __str__(self):
        return f"{self.title} - {self.get_goal_type_display()}"

    def clean(self):
        """
        Une leçon ne peut avoir plus d'un Goal du même type
        (contrainte structurelle : exactement 2 goals par lesson au final).
        """
        if self.lesson_id:
            qs = Goal.objects.filter(lesson=self.lesson, goal_type=self.goal_type)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    _("Cette leçon a déjà un Goal de type '%(type)s'.")
                    % {'type': self.get_goal_type_display()}
                )

    def save(self, *args, **kwargs):
        self.full_clean(exclude=None, validate_unique=False)
        super().save(*args, **kwargs)
