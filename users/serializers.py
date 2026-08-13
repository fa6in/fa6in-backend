"""
users/serializers.py
"""

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import User, Wilaya, StudentProfile, TeacherProfile


class WilayaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wilaya
        fields = ['id', 'code', 'name']


class StudentProfileSerializer(serializers.ModelSerializer):
    level_name = serializers.CharField(source='level.name', read_only=True)

    class Meta:
        model = StudentProfile
        fields = [
            'id', 'user', 'level', 'level_name', 'address',
            'enrollment_date', 'parent_name', 'parent_phone',
        ]
        read_only_fields = ['enrollment_date']


class TeacherProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeacherProfile
        fields = ['id', 'user', 'qualification', 'subjects', 'years_of_experience']


class UserSerializer(serializers.ModelSerializer):
    """
    Serializer de lecture/mise à jour standard (sans mot de passe).
    """
    student_profile = StudentProfileSerializer(read_only=True)
    teacher_profile = TeacherProfileSerializer(read_only=True)
    wilaya_name = serializers.CharField(source='wilaya.name', read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'role',
            'wilaya', 'wilaya_name', 'phone_number', 'profile_image',
            'date_of_birth', 'school', 'is_active', 'date_joined', 'last_login',
            'student_profile', 'teacher_profile',
        ]
        read_only_fields = ['id', 'date_joined', 'last_login', 'is_active']


class UserRegistrationSerializer(serializers.ModelSerializer):
    """
    Serializer dédié à l'inscription : gère le hashage du mot de passe
    et la création du profil approprié (étudiant ou enseignant).
    """
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'password', 'password_confirm',
            'first_name', 'last_name', 'role', 'wilaya', 'phone_number',
            'date_of_birth', 'school',
        ]

    def validate(self, attrs):
        if attrs['password'] != attrs.pop('password_confirm'):
            raise serializers.ValidationError(
                {'password_confirm': 'Les mots de passe ne correspondent pas.'}
            )
        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()

        if user.role == User.Role.STUDENT:
            StudentProfile.objects.create(user=user)
        elif user.role == User.Role.TEACHER:
            TeacherProfile.objects.create(user=user)

        return user


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, validators=[validate_password])


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(max_length=4, min_length=4)
    new_password = serializers.CharField(write_only=True, validators=[validate_password])
    new_password_confirm = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError(
                {'new_password_confirm': 'Les mots de passe ne correspondent pas.'}
            )
        return attrs
