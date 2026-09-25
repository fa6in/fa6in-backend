"""
curriculum/tests.py

Scenario riche couvrant la hierarchie pedagogique complete :
Stage -> Level -> Subject -> Unit -> Lesson -> Goal.

L'authentification (login/JWT) n'est pas testee ici : on utilise
force_authenticate pour se placer directement dans la peau d'un
enseignant ou d'un etudiant.
"""

from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from users.models import User
from .models import Stage, Level, Subject, Unit, Lesson, Goal


def make_user(username, role):
    return User.objects.create_user(
        username=username, email=f"{username}@fatin.test", password="pass1234", role=role,
    )


class CurriculumScenarioTestCase(APITestCase):
    """
    Scenario : Mme Zeinab (enseignante) construit la hierarchie
    Primaire -> Annee 1 -> Mathematiques -> Unite 'Fractions' -> Lecon
    'Comparer des fractions', puis Ahmed (etudiant) consulte le contenu.
    """

    def setUp(self):
        self.teacher = make_user('zeinab', User.Role.TEACHER)
        self.student = make_user('ahmed', User.Role.STUDENT)

        self.stage = Stage.objects.create(name='المرحلة الابتدائية', code='PRIM', order_index=1)
        self.level = Level.objects.create(stage=self.stage, name='السنة الأولى', code='PRIM-1', order_index=1)
        self.subject = Subject.objects.create(level=self.level, name='الرياضيات')

    def test_teacher_builds_full_hierarchy_down_to_unit(self):
        self.client.force_authenticate(self.teacher)

        unit_resp = self.client.post(reverse('unit-list'), {
            'subject': self.subject.id, 'code': 'U01', 'title': 'الكسور',
            'central_question': 'كيف نقارن الكسور؟',
        })
        self.assertEqual(unit_resp.status_code, status.HTTP_201_CREATED, unit_resp.data)
        unit_id = unit_resp.data['id']

        self.assertEqual(unit_resp.data['created_by'], self.teacher.id)
        self.assertFalse(unit_resp.data['is_published'])

        lesson_resp = self.client.post(reverse('lesson-list'), {
            'unit': unit_id, 'code': 'U01-L01', 'title': 'مقارنة الكسور',
        })
        self.assertEqual(lesson_resp.status_code, status.HTTP_201_CREATED, lesson_resp.data)

    def test_student_has_read_only_access(self):
        self.client.force_authenticate(self.student)

        list_resp = self.client.get(reverse('unit-list'))
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)

        create_resp = self.client.post(reverse('unit-list'), {
            'subject': self.subject.id, 'code': 'U99', 'title': 'Tentative interdite',
        })
        self.assertEqual(create_resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_user_is_rejected(self):
        resp = self.client.get(reverse('unit-list'))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class LessonPublishRuleTestCase(APITestCase):
    """
    Regle metier (Partie 4, Regle 1) : une lecon ne peut etre publiee
    que si elle possede EXACTEMENT un Goal Conceptual et un Goal
    Operational - ni plus, ni moins.
    """

    def setUp(self):
        self.teacher = make_user('zeinab', User.Role.TEACHER)
        stage = Stage.objects.create(name='الابتدائية', code='PRIM', order_index=1)
        level = Level.objects.create(stage=stage, name='السنة 1', code='PRIM-1', order_index=1)
        subject = Subject.objects.create(level=level, name='الرياضيات')
        unit = Unit.objects.create(subject=subject, code='U01', title='الكسور')
        self.lesson = Lesson.objects.create(unit=unit, code='U01-L01', title='مقارنة الكسور')
        self.client.force_authenticate(self.teacher)

    def _publish(self):
        return self.client.post(reverse('lesson-publish', args=[self.lesson.id]))

    def test_publish_rejected_when_no_goals(self):
        resp = self._publish()
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data['conceptual_count'], 0)
        self.assertEqual(resp.data['operational_count'], 0)
        self.lesson.refresh_from_db()
        self.assertFalse(self.lesson.is_published)

    def test_publish_rejected_with_only_conceptual_goal(self):
        Goal.objects.create(lesson=self.lesson, goal_type=Goal.GoalType.CONCEPTUAL, title='فهم الكسور')
        resp = self._publish()
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data['conceptual_count'], 1)
        self.assertEqual(resp.data['operational_count'], 0)

    def test_publish_succeeds_with_exactly_one_of_each_goal(self):
        Goal.objects.create(lesson=self.lesson, goal_type=Goal.GoalType.CONCEPTUAL, title='فهم الكسور')
        Goal.objects.create(lesson=self.lesson, goal_type=Goal.GoalType.OPERATIONAL, title='تطبيق الكسور')

        resp = self._publish()
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertTrue(resp.data['is_published'])
        self.lesson.refresh_from_db()
        self.assertTrue(self.lesson.is_published)

    def test_cannot_create_two_goals_of_same_type_via_api(self):
        Goal.objects.create(lesson=self.lesson, goal_type=Goal.GoalType.CONCEPTUAL, title='فهم الكسور')

        resp = self.client.post(reverse('goal-list'), {
            'lesson': self.lesson.id, 'goal_type': Goal.GoalType.CONCEPTUAL, 'title': 'دوبلون',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.lesson.goals.filter(goal_type=Goal.GoalType.CONCEPTUAL).count(), 1)

    def test_model_level_clean_enforces_same_rule_on_direct_save(self):
        Goal.objects.create(lesson=self.lesson, goal_type=Goal.GoalType.CONCEPTUAL, title='فهم الكسور')
        Goal.objects.create(lesson=self.lesson, goal_type=Goal.GoalType.OPERATIONAL, title='تطبيق الكسور')
        self.lesson.is_published = True
        self.lesson.save()

        duplicate = Goal(lesson=self.lesson, goal_type=Goal.GoalType.OPERATIONAL, title='تكرار')
        with self.assertRaises(ValidationError):
            duplicate.save()


class UnitSectionsTestCase(APITestCase):
    """L'action /units/<id>/sections/ expose les lecons comme "sections"."""

    def setUp(self):
        self.teacher = make_user('zeinab', User.Role.TEACHER)
        stage = Stage.objects.create(name='الابتدائية', code='PRIM', order_index=1)
        level = Level.objects.create(stage=stage, name='السنة 1', code='PRIM-1', order_index=1)
        subject = Subject.objects.create(level=level, name='الرياضيات')
        self.unit = Unit.objects.create(subject=subject, code='U01', title='الكسور')
        Lesson.objects.create(unit=self.unit, code='U01-L01', title='مقارنة الكسور', order_index=1)
        Lesson.objects.create(unit=self.unit, code='U01-L02', title='جمع الكسور', order_index=2)
        self.client.force_authenticate(self.teacher)

    def test_sections_returns_lessons_in_order(self):
        resp = self.client.get(reverse('unit-sections', args=[self.unit.id]))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 2)
        self.assertEqual(resp.data[0]['code'], 'U01-L01')
        self.assertEqual(resp.data[1]['code'], 'U01-L02')
