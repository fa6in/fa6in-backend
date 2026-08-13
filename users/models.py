"""
users/models.py

Catégorie A - Gestion des utilisateurs
Tables : User, StudentProfile, TeacherProfile, Wilaya
(Group et Permission sont fournies nativement par Django - aucune redéfinition)

Basé sur : FATIN_Schema_Final_Complet.docx - Partie 3, Catégorie A
"""

import random
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Wilaya(models.Model):
    """
    Wilayas mauritaniennes pour la gestion régionale.
    """
    code = models.IntegerField(
        _('code'),
        unique=True,
        db_comment="Code wilaya officiel",
    )
    name = models.CharField(
        _('nom'),
        max_length=100,
        db_comment="Nom de la wilaya",
    )

    class Meta:
        verbose_name = _('ولاية')
        verbose_name_plural = _('الولايات')
        ordering = ['code']
        db_table_comment = "Régions administratives de Mauritanie"

    def __str__(self):
        return f"{self.code} - {self.name}"


class User(AbstractUser):
    """
    Table centrale qui représente tout utilisateur du système,
    quel que soit son rôle. Étend AbstractUser de Django.
    """

    class Role(models.TextChoices):
        STUDENT = 'student', _('طالب')
        TEACHER = 'teacher', _('معلم')
        REGIONAL_ADMIN = 'regional_admin', _('مدير جهوي')
        ADMIN = 'admin', _('مدير النظام')

    email = models.EmailField(
        _('البريد الإلكتروني'),
        unique=True,
        db_comment="Email de connexion",
    )
    role = models.CharField(
        _('الدور'),
        max_length=20,
        choices=Role.choices,
        default=Role.STUDENT,
        db_comment="student/teacher/regional_admin/admin",
    )
    wilaya = models.ForeignKey(
        Wilaya,
        on_delete=models.SET_NULL,
        verbose_name=_('الولاية'),
        null=True,
        blank=True,
        related_name='users',
        db_comment="FK vers Wilaya - Wilaya de l'utilisateur",
    )
    date_of_birth = models.DateField(
        _('تاريخ الميلاد'),
        null=True,
        blank=True,
    )
    phone_number = models.CharField(
        _('رقم الهاتف'),
        max_length=20,
        blank=True,
    )
    profile_image = models.ImageField(
        _('صورة الملف الشخصي'),
        upload_to='profiles/',
        null=True,
        blank=True,
    )
    school = models.CharField(
        _('المدرسة'),
        max_length=200,
        blank=True,
        db_comment="École de rattachement",
    )

    # username / password / first_name / last_name / is_active / is_staff /
    # date_joined / last_login sont hérités de AbstractUser.

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']

    class Meta:
        verbose_name = _('مستخدم')
        verbose_name_plural = _('المستخدمين')
        db_table_comment = "Compte utilisateur central - toutes les identités"

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT

    @property
    def is_teacher(self):
        return self.role == self.Role.TEACHER


class StudentProfile(models.Model):
    """
    Profil spécifique aux étudiants. Relation OneToOne avec User.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        verbose_name=_('المستخدم'),
        related_name='student_profile',
        db_comment="FK UNIQUE vers User",
    )
    level = models.ForeignKey(
        'curriculum.Level',
        on_delete=models.SET_NULL,
        verbose_name=_('الصف الدراسي الحالي'),
        null=True,
        blank=True,
        related_name='students',
        db_comment="Niveau scolaire actuel de l'étudiant",
    )
    address = models.TextField(_('العنوان'), blank=True, null=True)
    enrollment_date = models.DateField(_('تاريخ التسجيل'), auto_now_add=True)
    parent_name = models.CharField(_('اسم ولي الأمر'), max_length=200, blank=True)
    parent_phone = models.CharField(_('هاتف ولي الأمر'), max_length=20, blank=True)

    class Meta:
        verbose_name = _('ملف الطالب')
        verbose_name_plural = _('ملفات الطلاب')
        db_table_comment = "Profil étendu des étudiants"

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} - طالب"

    def clean(self):
        if self.user_id and self.user.role != User.Role.STUDENT:
            raise ValidationError(
                {'user': _("Ce profil ne peut être associé qu'à un utilisateur de rôle 'student'.")}
            )

    def save(self, *args, **kwargs):
        self.full_clean(exclude=None, validate_unique=False)
        super().save(*args, **kwargs)


class PasswordResetCode(models.Model):
    """
    Code à 4 chiffres envoyé par email pour la réinitialisation du mot de passe
    (flux "mot de passe oublié").
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='password_reset_codes',
        verbose_name=_('المستخدم'),
    )
    code = models.CharField(_('الرمز'), max_length=4)
    created_at = models.DateTimeField(_('تاريخ الإنشاء'), auto_now_add=True)
    expires_at = models.DateTimeField(_('تاريخ الانتهاء'))
    is_used = models.BooleanField(_('مستخدم'), default=False)
    attempts = models.PositiveSmallIntegerField(_('عدد المحاولات'), default=0)

    class Meta:
        verbose_name = _('رمز إعادة تعيين كلمة المرور')
        verbose_name_plural = _('رموز إعادة تعيين كلمة المرور')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email} - {self.code}"

    def is_valid(self):
        max_attempts = getattr(settings, 'PASSWORD_RESET_CODE_MAX_ATTEMPTS', 5)
        return (
            not self.is_used
            and self.attempts < max_attempts
            and timezone.now() <= self.expires_at
        )

    @staticmethod
    def generate_code():
        return f"{random.randint(0, 9999):04d}"

    @classmethod
    def create_for_user(cls, user):
        validity_minutes = getattr(settings, 'PASSWORD_RESET_CODE_VALIDITY_MINUTES', 10)
        user.password_reset_codes.filter(is_used=False).update(is_used=True)
        return cls.objects.create(
            user=user,
            code=cls.generate_code(),
            expires_at=timezone.now() + timedelta(minutes=validity_minutes),
        )


class TeacherProfile(models.Model):
    """
    Profil spécifique aux enseignants. Relation OneToOne avec User.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        verbose_name=_('المستخدم'),
        related_name='teacher_profile',
        db_comment="FK UNIQUE vers User",
    )
    qualification = models.CharField(_('المؤهل العلمي'), max_length=200, blank=True)
    subjects = models.CharField(_('المواد الدراسية'), max_length=500, blank=True)
    years_of_experience = models.IntegerField(_('سنوات الخبرة'), default=0)

    class Meta:
        verbose_name = _('ملف المعلم')
        verbose_name_plural = _('ملفات المعلمين')
        db_table_comment = "Profil étendu des enseignants"

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} - معلم"

    def clean(self):
        if self.user_id and self.user.role != User.Role.TEACHER:
            raise ValidationError(
                {'user': _("Ce profil ne peut être associé qu'à un utilisateur de rôle 'teacher'.")}
            )

    def save(self, *args, **kwargs):
        self.full_clean(exclude=None, validate_unique=False)
        super().save(*args, **kwargs)
