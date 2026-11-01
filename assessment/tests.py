"""
assessment/tests.py

Scénario du design FATIN côté étudiant (S1 → S8) et côté enseignant
(T7, T9) :

- Parcours : U01 (L01, L02) puis U02 verrouillée tant que U01 n'est pas
  terminée ; une skill dont le prérequis de la même unité n'est pas
  maîtrisé est verrouillée.
- Séance : règle → exemple → exercices, fiche d'erreur, redirection vers
  le prérequis après 3 échecs, puis "أتقنت المهارة" avec skill suivante.
- Publication : liste de contrôle d'une leçon, publication d'unité,
  candidats prérequis avec détection de cycle.
"""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from curriculum.models import Stage, Level, Subject, Unit, Lesson, Goal
from skills.models import Skill, Prerequisite, Chunk
from users.models import User, StudentProfile
from .models import StudentProgress


def make_user(username, role):
    return User.objects.create_user(
        username=username, email=f"{username}@fatin.test", password="pass1234", role=role,
    )


def make_skill(goal, code, name, order=0):
    skill = Skill.objects.create(
        goal=goal, code=code, name=name, skill_type=goal.goal_type,
        order_index=order, mastery_threshold=0.8, required_consecutive_correct=3,
    )
    Chunk.objects.create(skill=skill, code=f'{code}-R', chunk_type='rule', content='قاعدة', order_index=1)
    Chunk.objects.create(skill=skill, code=f'{code}-E', chunk_type='example', content='1/5 + 2/5 = 3/5', order_index=2)
    Chunk.objects.create(skill=skill, code=f'{code}-P1', chunk_type='practice', content='3/7 + 2/7',
                         correct_answer='5/7', difficulty=1, order_index=3, time_limit=60)
    Chunk.objects.create(skill=skill, code=f'{code}-P2', chunk_type='practice', content='4/9 + 3/9',
                         correct_answer='7/9', difficulty=2, order_index=4, time_limit=60)
    return skill


class FatinFlowTestCase(APITestCase):

    def setUp(self):
        self.teacher = make_user('zeinab', User.Role.TEACHER)
        self.student = make_user('ahmed', User.Role.STUDENT)

        stage = Stage.objects.create(name='المتوسطة', code='MID', order_index=1)
        self.level = Level.objects.create(stage=stage, name='الأولى متوسط', code='MID-1', order_index=1)
        StudentProfile.objects.create(user=self.student, level=self.level)
        self.subject = Subject.objects.create(level=self.level, name='الرياضيات')

        self.u1 = Unit.objects.create(subject=self.subject, code='U01', title='الكسور', order_index=1, is_published=True)
        self.u2 = Unit.objects.create(subject=self.subject, code='U02', title='العمليات', order_index=2, is_published=True)
        self.l1 = Lesson.objects.create(unit=self.u1, code='U01-L01', title='مفهوم الكسر', order_index=1)
        self.l2 = Lesson.objects.create(unit=self.u1, code='U01-L02', title='جمع الكسور', order_index=2)
        self.l3 = Lesson.objects.create(unit=self.u2, code='U02-L01', title='الضرب', order_index=1)

        def goals(lesson):
            return (
                Goal.objects.create(lesson=lesson, goal_type='conceptual', title='مفاهيمي', order_index=1),
                Goal.objects.create(lesson=lesson, goal_type='operational', title='عملياتي', order_index=2),
            )
        g1c, g1o = goals(self.l1)
        g2c, g2o = goals(self.l2)
        g3c, _g3o = goals(self.l3)

        self.s_concept = make_skill(g1c, 'SK-U01-L01-C01', 'مفهوم الكسر')
        self.s_repr = make_skill(g1o, 'SK-U01-L01-O01', 'تمثيل الكسور')
        self.s_add_same = make_skill(g2c, 'SK-U01-L02-C01', 'جمع المتشابهة')
        self.s_add_diff = make_skill(g2o, 'SK-U01-L02-O01', 'جمع المختلفة')
        self.s_mult = make_skill(g3c, 'SK-U02-L01-C01', 'الضرب')
        Prerequisite.objects.create(skill=self.s_add_diff, prerequisite=self.s_add_same)

        for lesson in (self.l1, self.l2, self.l3):
            lesson.is_published = True
            lesson.save()

    # ---- helpers -------------------------------------------------------

    def url(self, name, **kwargs):
        return reverse(name, kwargs={'student_id': self.student.id, **kwargs})

    def master(self, skill):
        StudentProgress.objects.update_or_create(
            student=self.student, skill=skill,
            defaults={'attempts': 3, 'correct_count': 3, 'mastery': 1, 'consecutive_correct': 3,
                      'status': StudentProgress.Status.MASTERED},
        )

    def answer(self, chunk, value, time_taken=30):
        return self.client.post(self.url('student-submit-answer'),
                                {'chunk_id': chunk.id, 'answer': value, 'time_taken': time_taken})

    # ---- S2 / S3 : parcours et verrouillage --------------------------

    def test_path_locks_next_lesson_and_unit_until_mastered(self):
        self.client.force_authenticate(self.student)
        data = self.client.get(self.url('student-path')).data

        self.assertEqual(data['subject']['name'], 'الرياضيات')
        u1, u2 = data['units']
        self.assertEqual(u1['status'], 'available')
        self.assertEqual([l['status'] for l in u1['lessons']], ['current', 'locked'])
        self.assertEqual(u2['status'], 'locked')
        self.assertEqual(u2['locked_by_unit']['code'], 'U01')

        self.master(self.s_concept)
        self.master(self.s_repr)
        u1 = self.client.get(self.url('student-path')).data['units'][0]
        self.assertEqual([l['status'] for l in u1['lessons']], ['done', 'current'])
        self.assertEqual(u1['status'], 'in_progress')

    def test_skill_map_locks_skill_behind_same_unit_prerequisite(self):
        self.master(self.s_concept)
        self.master(self.s_repr)
        self.client.force_authenticate(self.student)
        data = self.client.get(self.url('student-skill-map'), {'unit': self.u1.id}).data

        l2_skills = {s['code']: s for s in data['lessons'][1]['skills']}
        self.assertEqual(l2_skills['SK-U01-L02-C01']['status'], 'available')
        locked = l2_skills['SK-U01-L02-O01']
        self.assertEqual(locked['status'], 'locked')
        self.assertEqual(locked['locked_by'][0]['code'], 'SK-U01-L02-C01')

    def test_student_cannot_read_another_student_path(self):
        other = make_user('mariem', User.Role.STUDENT)
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get(self.url('student-path')).status_code, status.HTTP_403_FORBIDDEN)

    # ---- S4 → S7 : séance ---------------------------------------------

    def test_session_rule_example_practice_then_mastered_unlocks_next_skill(self):
        self.client.force_authenticate(self.student)
        skill = self.s_concept

        types = []
        for _ in range(3):
            resp = self.client.get(self.url('student-next-action'), {'skill': skill.id})
            self.assertEqual(resp.data['action'], 'show_chunk')
            types.append(resp.data['chunk']['chunk_type'])
        self.assertEqual(types, ['rule', 'example', 'practice'])
        self.assertNotIn('correct_answer', resp.data['chunk'])
        self.assertTrue(resp.data['session']['progress']['rule_seen'])
        self.assertEqual(resp.data['session']['breadcrumb']['lesson_code'], 'U01-L01')

        p1 = skill.chunks.get(code__endswith='-P1')
        results = [self.answer(p1, '5/7').data for _ in range(3)]
        self.assertFalse(results[1]['mastered_now'])
        last = results[2]
        self.assertTrue(last['mastered_now'])
        self.assertEqual(last['progress']['status'], 'mastered')
        self.assertEqual(last['points'], 3)
        self.assertEqual(last['next_skill']['code'], 'SK-U01-L01-O01')

    def test_wrong_answer_returns_feedback_sheet(self):
        self.client.force_authenticate(self.student)
        p1 = self.s_add_same.chunks.get(code__endswith='-P1')
        data = self.answer(p1, '5/14').data

        self.assertFalse(data['is_correct'])
        self.assertEqual(data['error_type'], 'concept')
        self.assertTrue(data['feedback']['message'])
        self.assertEqual(data['feedback']['example'], '1/5 + 2/5 = 3/5')
        self.assertIsNone(data['redirect'])

    def test_three_failures_redirect_to_unmastered_prerequisite_only(self):
        self.client.force_authenticate(self.student)
        p1 = self.s_add_diff.chunks.get(code__endswith='-P1')
        for _ in range(2):
            self.answer(p1, 'x')
        data = self.answer(p1, 'x').data
        self.assertEqual(data['redirect']['skill']['code'], 'SK-U01-L02-C01')

        nxt = self.client.get(self.url('student-next-action'), {'skill': self.s_add_diff.id}).data
        self.assertEqual(nxt['action'], 'redirect_to_prerequisite')
        self.assertEqual(nxt['chunk']['chunk_type'], 'rule')
        self.assertEqual(nxt['session']['skill']['code'], 'SK-U01-L02-C01')

        # Une fois le prérequis maîtrisé, plus de redirection en boucle.
        self.master(self.s_add_same)
        nxt = self.client.get(self.url('student-next-action'), {'skill': self.s_add_diff.id}).data
        self.assertEqual(nxt['action'], 'show_chunk')

    # ---- S1 / S8 -------------------------------------------------------

    def test_home_and_progress_summary(self):
        self.client.force_authenticate(self.student)
        p1 = self.s_concept.chunks.get(code__endswith='-P1')
        self.answer(p1, '5/7')
        self.answer(p1, 'x')

        home = self.client.get(self.url('student-home')).data
        self.assertEqual(home['resume']['skill']['code'], 'SK-U01-L01-C01')
        self.assertEqual(home['stats']['attempts_today'], 2)
        self.assertEqual(home['stats']['streak_days'], 1)
        self.assertEqual(home['subjects'][0]['skills_total'], 5)

        summary = self.client.get(self.url('student-progress-summary')).data
        self.assertEqual(summary['skills_total'], 5)
        self.assertEqual(summary['skills_in_progress'], 1)
        self.assertEqual(summary['skills_not_started'], 4)
        self.assertEqual(len(summary['weekly_activity']), 7)
        self.assertEqual(summary['weekly_activity'][-1]['attempts'], 2)
        self.assertEqual(sum(summary['errors_by_category'].values()), 1)

    # ---- T7 / T9 : éditeur de contenu ---------------------------------

    def test_prerequisite_candidates_flag_cycles(self):
        self.client.force_authenticate(self.teacher)
        url = reverse('skill-prerequisite-candidates', kwargs={'pk': self.s_add_same.id})
        states = {c['code']: c['state'] for c in self.client.get(url).data}
        self.assertEqual(states['SK-U01-L02-O01'], 'cycle')
        self.assertEqual(states['SK-U01-L01-C01'], 'available')

        url = reverse('skill-prerequisite-candidates', kwargs={'pk': self.s_add_diff.id})
        states = {c['code']: c['state'] for c in self.client.get(url).data}
        self.assertEqual(states['SK-U01-L02-C01'], 'linked')

    def test_lesson_publication_checklist_and_publish(self):
        self.client.force_authenticate(self.teacher)
        lesson = Lesson.objects.create(unit=self.u2, code='U02-L02', title='القسمة', order_index=2)
        goal = Goal.objects.create(lesson=lesson, goal_type='conceptual', title='مفاهيمي')
        Skill.objects.create(goal=goal, code='SK-U02-L02-C01', name='القسمة', skill_type='conceptual')

        check = self.client.get(reverse('lesson-publication-check', kwargs={'pk': lesson.id})).data
        self.assertFalse(check['ready'])
        by_key = {c['key']: c for c in check['checks']}
        self.assertFalse(by_key['goals']['ok'])
        self.assertTrue(by_key['no_cycles']['ok'])
        self.assertFalse(by_key['chunks']['ok'])

        resp = self.client.post(reverse('lesson-publish', kwargs={'pk': lesson.id}))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        check = self.client.get(reverse('lesson-publication-check', kwargs={'pk': self.l1.id})).data
        self.assertTrue(check['ready'], check)

    def test_unit_publish_requires_published_lesson(self):
        self.client.force_authenticate(self.teacher)
        unit = Unit.objects.create(subject=self.subject, code='U03', title='الهندسة', order_index=3)
        resp = self.client.post(reverse('unit-publish', kwargs={'pk': unit.id}))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        Lesson.objects.create(unit=unit, code='U03-L01', title='الأشكال', is_published=True)
        resp = self.client.post(reverse('unit-publish', kwargs={'pk': unit.id}))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['is_published'])

    # ---- Teacher / Admin dashboards -----------------------------------

    def test_teacher_sees_students_needing_follow_up_and_summary(self):
        self.client.force_authenticate(self.student)
        p1 = self.s_add_diff.chunks.get(code__endswith='-P1')
        for _ in range(3):
            self.answer(p1, 'x')

        self.client.force_authenticate(self.teacher)
        rows = self.client.get(reverse('teacher-dashboard-students-progress')).data
        row = next(r for r in rows if r['student_id'] == self.student.id)
        self.assertTrue(row['needs_attention'])
        self.assertIn(row['attention_reason'], ('concept_errors', 'redirects'))

        summary = self.client.get(reverse('student-summary', kwargs={'student_id': self.student.id})).data
        self.assertEqual(summary['attempts'], 3)
        self.assertEqual(sum(summary['errors_by_category'].values()), 3)

    def test_admin_attention_and_wilaya_reports(self):
        admin = make_user('boss', User.Role.ADMIN)
        self.client.force_authenticate(admin)
        unit = Unit.objects.create(subject=self.subject, code='U03', title='الهندسة', order_index=3)
        lesson = Lesson.objects.create(unit=unit, code='U03-L01', title='الأشكال')
        Goal.objects.create(lesson=lesson, goal_type='conceptual', title='مفاهيمي')

        items = self.client.get(reverse('reports-attention')).data
        kinds = {(i['kind'], i['code']) for i in items}
        self.assertIn(('unit_unpublished', 'U03'), kinds)
        missing = next(i for i in items if i['kind'] == 'lesson_missing_goal')
        self.assertEqual((missing['code'], missing['missing']), ('U03-L01', 'operational'))
        self.assertEqual(self.client.get(reverse('reports-by-wilaya')).status_code, status.HTTP_200_OK)
        usage = self.client.get(reverse('reports-usage'), {'days': 7}).data
        self.assertEqual(len(usage['daily']), 7)


class AccountFlowTestCase(APITestCase):

    def test_public_registration_cannot_create_admin_and_stores_level(self):
        stage = Stage.objects.create(name='المتوسطة', code='MID', order_index=1)
        level = Level.objects.create(stage=stage, name='الأولى متوسط', code='MID-1', order_index=1)
        payload = {
            'username': 'ahmed', 'email': 'a@fatin.test', 'password': 'Str0ng!pass',
            'password_confirm': 'Str0ng!pass', 'role': 'admin',
        }
        resp = self.client.post(reverse('register'), payload)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        resp = self.client.post(reverse('register'), {**payload, 'role': 'student', 'level': level.id})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(User.objects.get(username='ahmed').student_profile.level, level)

    def test_admin_creates_user_with_temporary_password(self):
        admin = make_user('boss', User.Role.ADMIN)
        teacher = make_user('zeinab', User.Role.TEACHER)
        payload = {'username': 'khadija', 'email': 'kh@fatin.test', 'password': 'Tmp!pass123',
                   'role': 'regional_admin', 'first_name': 'خديجة'}

        self.client.force_authenticate(teacher)
        self.assertEqual(self.client.post(reverse('user-list'), payload).status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(admin)
        resp = self.client.post(reverse('user-list'), payload)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertNotIn('password', resp.data)
        self.assertTrue(User.objects.get(username='khadija').check_password('Tmp!pass123'))

    def test_verify_reset_code_counts_attempts(self):
        from users.models import PasswordResetCode
        user = make_user('ahmed', User.Role.STUDENT)
        code = PasswordResetCode.create_for_user(user)
        wrong = '0000' if code.code != '0000' else '1111'

        resp = self.client.post(reverse('verify-reset-code'), {'email': user.email, 'code': wrong})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data['remaining_attempts'], 4)

        resp = self.client.post(reverse('verify-reset-code'), {'email': user.email, 'code': code.code})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['valid'])

    def test_student_cannot_escalate_role_but_admin_can_disable(self):
        student = make_user('ahmed', User.Role.STUDENT)
        admin = make_user('boss', User.Role.ADMIN)

        self.client.force_authenticate(student)
        self.client.patch(reverse('profile'), {'role': 'admin'})
        self.client.patch(reverse('user-detail', kwargs={'pk': student.id}), {'role': 'admin'})
        student.refresh_from_db()
        self.assertEqual(student.role, User.Role.STUDENT)
        self.assertEqual(self.client.delete(reverse('user-detail', kwargs={'pk': student.id})).status_code,
                         status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(admin)
        resp = self.client.patch(reverse('user-detail', kwargs={'pk': student.id}), {'is_active': False, 'role': 'teacher'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        student.refresh_from_db()
        self.assertFalse(student.is_active)
        self.assertEqual(student.role, User.Role.TEACHER)
