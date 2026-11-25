"""
skills/models.py

Catégorie B - Structure pédagogique (partie 2/2)
Tables : Skill, Prerequisites, Chunk

Basé sur : FATIN_Schema_Final_Complet.docx - Partie 3, Catégorie B
"""

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from curriculum.models import Goal


class Skill(models.Model):
    """
    Compétence précise à acquérir. Cœur du système d'apprentissage.
    Liée à un Goal parent dont elle DOIT hériter le type
    (skill_type == goal.goal_type).
    """

    class SkillType(models.TextChoices):
        CONCEPTUAL = 'conceptual', _('مفاهيمي')
        OPERATIONAL = 'operational', _('عملياتي')

    goal = models.ForeignKey(
        Goal,
        on_delete=models.CASCADE,
        verbose_name=_('الهدف'),
        related_name='skills',
        db_comment="Goal parent",
    )
    code = models.CharField(_('رمز المهارة'), max_length=30, unique=True, db_comment="Ex: 'SK-U01-L01-C01'")
    name = models.CharField(_('اسم المهارة'), max_length=255)
    description = models.TextField(_('وصف المهارة'), blank=True, null=True)
    skill_type = models.CharField(
        _('نوع المهارة'), max_length=20, choices=SkillType.choices,
        db_comment="Conceptual OU Operational - DOIT correspondre au goal_type parent",
    )
    difficulty = models.IntegerField(
        _('مستوى الصعوبة'),
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        default=1,
        db_comment="CHECK (1-5)",
    )
    mastery_threshold = models.FloatField(_('عتبة الإتقان'), default=0.80)
    required_consecutive_correct = models.IntegerField(_('عدد المحاولات الصحيحة المتتالية المطلوبة'), default=3)
    order_index = models.IntegerField(_('الترتيب داخل الهدف'), default=0)
    created_at = models.DateTimeField(_('تاريخ الإنشاء'), auto_now_add=True)
    updated_at = models.DateTimeField(_('تاريخ التحديث'), auto_now=True)

    class Meta:
        verbose_name = _('مهارة')
        verbose_name_plural = _('المهارات')
        ordering = ['goal', 'order_index']
        db_table_comment = "Compétence précise - hérite du type de son Goal parent"

    def __str__(self):
        return f"{self.code} - {self.name}"

    def clean(self):
        """
        Règle métier critique (Partie 4, Règle 2) :
        le skill_type DOIT correspondre au goal_type du Goal parent.
        """
        if self.goal_id and self.skill_type and self.skill_type != self.goal.goal_type:
            raise ValidationError(
                {'skill_type': _(
                    "Le skill_type ('%(skill_type)s') doit correspondre au goal_type "
                    "du Goal parent ('%(goal_type)s')."
                ) % {'skill_type': self.skill_type, 'goal_type': self.goal.goal_type}}
            )

    def save(self, *args, **kwargs):
        self.full_clean(exclude=None, validate_unique=False)
        super().save(*args, **kwargs)

    def chunks_meet_minimum(self):
        """
        Vérifie la règle CMS (Partie 4, Règle 3) : au moins 1 'rule',
        1 'example' et 2 'practice' avant publication.
        """
        counts = self.chunks.values('chunk_type').annotate(n=models.Count('id'))
        counts_map = {c['chunk_type']: c['n'] for c in counts}
        return (
            counts_map.get(Chunk.ChunkType.RULE, 0) >= 1
            and counts_map.get(Chunk.ChunkType.EXAMPLE, 0) >= 1
            and counts_map.get(Chunk.ChunkType.PRACTICE, 0) >= 2
        )


class Prerequisite(models.Model):
    """
    Relation de dépendance entre deux Skills.
    Utilisée par le Decision Engine pour rediriger les étudiants
    vers la compétence manquante.
    """
    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        verbose_name=_('المهارة'),
        related_name='prerequisites_required',
        db_comment="Skill ayant des prérequis",
    )
    prerequisite = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        verbose_name=_('المهارة المطلوبة'),
        related_name='required_for_skills',
        db_comment="Skill prérequise",
    )
    related_error_types = models.JSONField(
        _('أنواع الأخطاء المرتبطة'), default=list, blank=True,
        db_comment="Types d'erreur que ce prérequis peut traiter (concept/procedure). Vide = concept et procedure.",
    )

    class Meta:
        verbose_name = _('متطلب سابق')
        verbose_name_plural = _('المتطلبات السابقة')
        unique_together = [['skill', 'prerequisite']]
        ordering = ['skill', 'prerequisite']
        db_table_comment = "Dépendances entre compétences (PK composite skill_id, prerequisite_id)"
        indexes = [
            models.Index(fields=['skill']),
            models.Index(fields=['prerequisite']),
        ]

    def __str__(self):
        return f"{self.skill.code} ← {self.prerequisite.code}"

    def clean(self):
        """
        - CHECK (skill_id != prerequisite_id)
        - Pas de doublon inverse direct
        - Pas de cycle dans le graphe de prérequis (Partie 4, Règle 4)
        """
        if self.skill_id == self.prerequisite_id:
            raise ValidationError(
                {'prerequisite': _("Une compétence ne peut pas être son propre prérequis.")}
            )

        if Prerequisite.objects.filter(
            skill=self.prerequisite, prerequisite=self.skill
        ).exclude(pk=self.pk).exists():
            raise ValidationError(
                _("La relation inverse existe déjà (%(a)s → %(b)s).") % {
                    'a': self.prerequisite.code, 'b': self.skill.code,
                }
            )

        if self._creates_cycle():
            raise ValidationError(
                _("Cette relation créerait un cycle dans le graphe des prérequis.")
            )

    def _creates_cycle(self):
        """
        Parcours en profondeur : si en partant de `prerequisite` on peut
        atteindre `skill`, alors ajouter (skill -> prerequisite) crée un cycle.
        """
        visited = set()
        stack = [self.prerequisite_id]
        while stack:
            current = stack.pop()
            if current == self.skill_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            next_ids = Prerequisite.objects.filter(skill_id=current).values_list(
                'prerequisite_id', flat=True
            )
            stack.extend(next_ids)
        return False

    def save(self, *args, **kwargs):
        self.full_clean(exclude=None, validate_unique=False)
        super().save(*args, **kwargs)


class Chunk(models.Model):
    """
    Plus petite unité de contenu vue par l'étudiant.
    Une Skill contient plusieurs Chunks de différents types.
    """

    class ChunkType(models.TextChoices):
        RULE = 'rule', _('قاعدة')
        EXAMPLE = 'example', _('مثال')
        PRACTICE = 'practice', _('تمرين')
        ERROR = 'error', _('خطأ')
        HINT = 'hint', _('تلميح')
        REAL_LIFE = 'real_life', _('تطبيق')

    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        verbose_name=_('المهارة'),
        related_name='chunks',
        db_comment="Skill parente",
    )
    code = models.CharField(_('رمز القطعة'), max_length=30, unique=True, db_comment="Ex: 'CH-U01-L01-C01'")
    chunk_type = models.CharField(
        _('نوع القطعة'), max_length=20, choices=ChunkType.choices,
        db_comment="rule/example/practice/error/hint/real_life",
    )
    title = models.CharField(_('العنوان'), max_length=255, blank=True, null=True)
    content = models.TextField(_('المحتوى'), help_text=_('Contenu textuel (HTML autorisé)'))
    correct_answer = models.TextField(_('الإجابة الصحيحة'), blank=True, null=True, help_text=_('Requis si practice'))
    options = models.JSONField(_('خيارات الإجابة (QCM)'), default=list, blank=True, null=True)
    difficulty = models.IntegerField(
        _('الصعوبة'),
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        default=1,
    )
    order_index = models.IntegerField(_('ترتيب العرض المقترح'), default=0)
    is_guided = models.BooleanField(
        _('تمرين موجّه'), default=False,
        db_comment="Exercice où l'élève complète des étapes manquantes (intervention 'procedure')",
    )
    default_error_category = models.CharField(
        _('نوع الخطأ الافتراضي'), max_length=20, blank=True, default='',
        choices=[('concept', _('خطأ مفاهيمي')), ('procedure', _('خطأ إجرائي')), ('careless', _('خطأ إهمالي'))],
        db_comment="Error Mapping pour une réponse fausse non couverte par options[].error_category",
    )
    points = models.IntegerField(_('النقاط'), default=1)
    time_limit = models.IntegerField(_('الحد الزمني بالثواني'), null=True, blank=True)
    image = models.ImageField(
        _('الصورة'), upload_to='chunks/', null=True, blank=True,
        db_comment="Illustration du manuel - fait souvent partie de la question",
    )
    needs_image = models.BooleanField(
        _('يحتاج إلى صورة'), default=False,
        db_comment="Métadonnée de relecture : le chunk n'a pas de sens sans image",
    )
    image_note = models.TextField(
        _('ملاحظة الصورة'), blank=True, null=True,
        db_comment="Métadonnée de relecture : description de l'image attendue",
    )
    created_at = models.DateTimeField(_('تاريخ الإنشاء'), auto_now_add=True)
    updated_at = models.DateTimeField(_('تاريخ التحديث'), auto_now=True)

    class Meta:
        verbose_name = _('قطعة محتوى')
        verbose_name_plural = _('قطع المحتوى')
        ordering = ['skill', 'order_index']
        db_table_comment = "Plus petite unité de contenu (rule/example/practice/error/hint/real_life)"

    def __str__(self):
        return f"{self.code} - {self.get_chunk_type_display()}"

    def clean(self):
        if self.chunk_type == self.ChunkType.PRACTICE and not self.correct_answer:
            raise ValidationError(
                {'correct_answer': _("Un chunk de type 'practice' doit avoir une réponse correcte.")}
            )
