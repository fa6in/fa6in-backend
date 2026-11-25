"""
assessment/tests.py

Scénario du design FATIN côté étudiant (S1 → S8) et côté enseignant
(T7, T9) :

- Parcours : les leçons s'ouvrent selon leur semaine du programme (deux
  leçons de la même semaine, même dans deux unités, sont ouvertes en même
  temps) ; un prérequis non maîtrisé est signalé mais ne verrouille pas.
- Séance (guide "Evaluation & Decision-Making Engine – MVP") : règle →
  exemple → groupe d'exercices ; une erreur ne bloque pas ; évaluation en
  fin de groupe, matrice de décision, interventions par type d'erreur,
  vérification du streak, retour au prérequis après épuisement des
  exercices, cas à revoir par l'enseignant, Learning Trace.
- Publication : liste de contrôle d'une leçon, publication d'unité,
  candidats prérequis avec détection de cycle.
"""

from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from curriculum.models import AcademicYear, Stage, Level, Subject, Unit, Lesson, Goal
from skills.models import Skill, Prerequisite, Chunk
from users.models import User, StudentProfile
from .evaluation import dominant_error_type, evaluate_results
from .models import EngineSettings, PrerequisiteReturn, StudentProgress


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

    def set_week(self, week):
        """Fixe la semaine courante du programme à `week`."""
        AcademicYear.objects.create(
            name='2026-2027', is_current=True,
            start_date=timezone.localdate() - timedelta(days=7 * (week - 1)),
        )

    def test_lessons_open_by_week_not_by_completion(self):
        # L01 (U01) et L03 (U02) sont en semaine 1, L02 (U01) en semaine 2.
        Lesson.objects.filter(pk__in=[self.l1.pk, self.l3.pk]).update(week=1)
        Lesson.objects.filter(pk=self.l2.pk).update(programme_weeks=[2, 3])
        self.set_week(1)
        self.client.force_authenticate(self.student)
        data = self.client.get(self.url('student-path')).data

        self.assertEqual(data['current_week'], 1)
        u1, u2 = data['units']
        # Même semaine, unités différentes : les deux leçons sont ouvertes
        # sans que U01 soit terminée.
        self.assertEqual([l['status'] for l in u1['lessons']], ['current', 'locked'])
        self.assertEqual(u1['lessons'][1]['week'], 2)
        self.assertEqual(u1['next_opening_week'], 2)
        self.assertEqual(u2['status'], 'available')
        self.assertEqual(u2['lessons'][0]['status'], 'current')

        # Une leçon de la semaine suivante reste fermée côté séance.
        resp = self.client.get(self.url('student-next-action'), {'skill': self.s_add_same.id})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data['opens_week'], 2)

        # Semaine 2 : L02 s'ouvre même si L01 n'est pas maîtrisée.
        AcademicYear.objects.all().delete()
        self.set_week(2)
        u1 = self.client.get(self.url('student-path')).data['units'][0]
        self.assertEqual([l['status'] for l in u1['lessons']], ['current', 'current'])

    def test_prerequisite_is_reported_but_does_not_lock(self):
        self.client.force_authenticate(self.student)
        data = self.client.get(self.url('student-skill-map'), {'unit': self.u1.id}).data

        l2_skills = {s['code']: s for s in data['lessons'][1]['skills']}
        skill = l2_skills['SK-U01-L02-O01']
        self.assertEqual(skill['status'], 'available')
        self.assertEqual(skill['locked_by'], [])
        self.assertEqual(skill['missing_prerequisites'][0]['code'], 'SK-U01-L02-C01')

    def test_student_cannot_read_another_student_path(self):
        other = make_user('mariem', User.Role.STUDENT)
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get(self.url('student-path')).status_code, status.HTTP_403_FORBIDDEN)

    # ---- S4 → S7 : séance ---------------------------------------------

    def test_wrong_answer_returns_feedback_sheet(self):
        self.client.force_authenticate(self.student)
        p1 = self.s_add_same.chunks.get(code__endswith='-P1')
        data = self.answer(p1, '5/14').data

        self.assertFalse(data['is_correct'])
        self.assertEqual(data['error_type'], 'concept')
        self.assertTrue(data['feedback']['message'])
        self.assertEqual(data['feedback']['example'], '1/5 + 2/5 = 3/5')
        self.assertIsNone(data['redirect'])

    # ---- Evaluation & Decision Engine (guide MVP) ---------------------

    def exercises(self, skill, categories, guided=()):
        """
        Remplace les exercices de `skill` par des QCM dont le mauvais choix
        est mappé (Error Mapping) sur la catégorie donnée.
        """
        skill.chunks.filter(chunk_type='practice').delete()
        made = []
        for i, category in enumerate(categories):
            made.append(Chunk.objects.create(
                skill=skill, code=f'{skill.code}-X{i}', chunk_type='practice', content=f'سؤال {i}',
                correct_answer='صح', difficulty=1, order_index=10 + i, is_guided=i in guided,
                options=[
                    {'id': 'a', 'text': 'صح', 'is_correct': True},
                    {'id': 'b', 'text': 'خطأ', 'is_correct': False,
                     'error_category': category, 'feedback': f'تغذية راجعة {category}'},
                ],
            ))
        return made

    def nxt(self, skill):
        return self.client.get(self.url('student-next-action'), {'skill': skill.id}).data

    def play(self, skill, outcomes):
        """Répond aux exercices servis par next-action (True = juste)."""
        served, results = [], []
        for ok in outcomes:
            step = self.nxt(skill)
            self.assertIsNotNone(step['chunk'], step)
            served.append(step['chunk']['id'])
            results.append(self.answer(Chunk.objects.get(pk=step['chunk']['id']), 'صح' if ok else 'خطأ').data)
        return served, results

    def start(self, skill):
        self.client.force_authenticate(self.student)
        self.assertEqual(self.nxt(skill)['chunk']['chunk_type'], 'rule')
        self.assertEqual(self.nxt(skill)['chunk']['chunk_type'], 'example')

    def test_evaluation_engine_rules_from_the_guide(self):
        settings = EngineSettings.load()
        r = evaluate_results([True] * 6 + [False] * 4, [], settings)
        self.assertEqual((r.mastery, r.mastery_level), (Decimal('0.60'), 'medium'))
        self.assertEqual(evaluate_results([True] * 4 + [False] * 6, [], settings).mastery_level, 'low')
        self.assertFalse(evaluate_results([True, True, True], [], settings).judged)

        # 4.2 / 4.3 : type dominant et égalités (Careless > Procedure > Concept).
        for concept, procedure, careless, expected in (
            (2, 4, 1, 'procedure'), (3, 3, 1, 'procedure'), (2, 4, 4, 'careless'),
            (3, 3, 3, 'careless'), (4, 2, 4, 'careless'), (4, 1, 1, 'concept'),
        ):
            freq = {'concept': concept, 'procedure': procedure, 'careless': careless}
            self.assertEqual(dominant_error_type(freq), expected, freq)

        # 6.4 : C W C C C -> 80 % et streak 3.
        r = evaluate_results([True, False, True, True, True], ['concept'], settings)
        self.assertEqual((r.mastery, r.mastery_level, r.correct_streak), (Decimal('0.80'), 'high', 3))

    def test_wrong_answer_does_not_block_then_procedure_intervention_and_new_group(self):
        skill = self.s_concept
        made = self.exercises(skill, ['procedural'] * 11, guided={10})
        self.start(skill)

        # Groupe de 5 : une erreur ne bloque pas, aucune décision en cours de groupe.
        served, results = self.play(skill, [False, True, False, True, True])
        self.assertEqual(len(set(served)), 5)
        self.assertNotIn(made[10].id, served)  # l'exercice guidé est réservé à l'intervention
        first = results[0]
        self.assertFalse(first['is_correct'])
        self.assertEqual(first['error_type'], 'procedure')
        self.assertEqual(first['error_source'], 'option')
        self.assertEqual(first['feedback']['message'], 'تغذية راجعة procedural')
        self.assertTrue(first['feedback']['continue'])
        self.assertIsNone(first['evaluation'])

        # Fin de groupe : 3/5 = 60 % Medium, Procedure -> intervention.
        evaluation = results[-1]['evaluation']
        self.assertEqual(evaluation['mastery'], 0.6)
        self.assertEqual(evaluation['mastery_level'], 'medium')
        self.assertEqual(evaluation['dominant_error_type'], 'procedure')
        self.assertEqual(evaluation['decision'], 'intervention')
        self.assertEqual(len(evaluation['mistakes']), 2)  # retour sur les erreurs du groupe

        # 6.2 : étapes -> exemple résolu -> exercice guidé -> exercice indépendant.
        steps = [self.nxt(skill), self.nxt(skill), self.nxt(skill)]
        self.assertEqual([s['mode'] for s in steps], ['intervention'] * 3)
        self.assertEqual([s['intervention']['step'] for s in steps],
                         ['steps_explanation', 'worked_example', 'guided_exercise'])
        self.assertEqual(steps[2]['chunk']['id'], made[10].id)
        self.assertTrue(steps[2]['instruction'])
        self.assertEqual(self.answer(made[10], 'صح').data['answer_context'], 'intervention')
        independent = self.nxt(skill)
        self.assertEqual(independent['intervention']['step'], 'independent_exercise')
        # Pas de réévaluation au milieu de l'intervention (section 7).
        self.assertIsNone(self.answer(Chunk.objects.get(pk=independent['chunk']['id']), 'خطأ').data['evaluation'])

        # Nouveau groupe, sans jamais reproposer un exercice du cycle (section 10).
        step = self.nxt(skill)
        self.assertEqual(step['mode'], 'group')
        used = set(served) | {made[10].id, independent['chunk']['id']}
        served2, results2 = self.play(skill, [True] * step['group']['total'])
        self.assertFalse(used & set(served2))

        # Learning Trace : mastery avant / après l'intervention.
        trace = self.client.get(self.url('student-learning-trace'), {'skill': skill.id}).data
        first_eval = trace['evaluations'][-1]
        self.assertEqual(first_eval['mastery_before'], '0.60')
        self.assertEqual(first_eval['intervention_status'], 'completed')
        self.assertEqual(first_eval['mastery_after'], '1.00')
        self.assertEqual(first_eval['mastery_improvement'], 0.4)

    def test_high_mastery_requires_correct_streak_before_mastered(self):
        skill = self.s_concept
        self.exercises(skill, ['concept'] * 8)
        self.start(skill)

        _served, results = self.play(skill, [True, True, True, False, True])
        evaluation = results[-1]['evaluation']
        self.assertEqual((evaluation['mastery_level'], evaluation['correct_streak']), ('high', 1))
        self.assertEqual(evaluation['decision'], 'verify_streak')
        self.assertFalse(results[-1]['mastered_now'])

        self.assertEqual(self.nxt(skill)['mode'], 'verify')
        _served, results = self.play(skill, [True, True])
        self.assertEqual(results[0]['decision'], 'verify_streak')
        self.assertTrue(results[1]['mastered_now'])
        self.assertEqual(results[1]['progress']['status'], 'mastered')
        self.assertEqual(results[1]['next_skill']['code'], 'SK-U01-L01-O01')

    def test_concept_intervention_sequence(self):
        skill = self.s_concept
        Chunk.objects.create(skill=skill, code='SK-R2', chunk_type='rule', content='شرح آخر', order_index=5)
        self.exercises(skill, ['concept'] * 10)
        self.start(skill)
        results = self.play(skill, [False, False, False, True, True])[1]
        self.assertEqual(results[-1]['evaluation']['intervention']['error_type'], 'concept')

        re_explain = self.nxt(skill)
        self.assertEqual(re_explain['intervention']['step'], 're_explain')
        self.assertEqual(re_explain['chunk']['content'], 'شرح آخر')  # explication différente
        self.assertEqual(self.nxt(skill)['intervention']['step'], 'example')
        simple = self.nxt(skill)
        self.assertEqual(simple['intervention']['step'], 'simple_exercise')
        self.answer(Chunk.objects.get(pk=simple['chunk']['id']), 'صح')
        self.assertEqual(self.nxt(skill)['intervention']['step'], 'applied_exercise')

    def test_exhausted_exercises_return_to_related_prerequisite(self):
        skill = self.s_add_diff
        self.exercises(skill, ['concept'] * 4)
        self.start(skill)
        results = self.play(skill, [False] * 4)[1]
        self.assertEqual(results[-1]['decision'], 'prerequisite_return')
        self.assertEqual(results[-1]['redirect']['skill']['code'], 'SK-U01-L02-C01')

        nxt = self.nxt(skill)
        self.assertEqual(nxt['action'], 'redirect_to_prerequisite')
        self.assertEqual(nxt['chunk']['chunk_type'], 'rule')
        self.assertEqual(nxt['session']['skill']['code'], 'SK-U01-L02-C01')

        # Prérequis maîtrisé : retour sur la skill avec un nouveau cycle.
        self.master(self.s_add_same)
        nxt = self.nxt(skill)
        self.assertEqual((nxt['action'], nxt['mode']), ('show_chunk', 'group'))
        ret = PrerequisiteReturn.objects.get(from_skill=skill)
        self.assertEqual(ret.status, PrerequisiteReturn.Status.COMPLETED)

    def test_careless_errors_never_trigger_a_prerequisite_return(self):
        skill = self.s_add_diff  # a un prérequis non maîtrisé
        self.exercises(skill, ['careless', 'concept', 'careless', 'concept'])
        self.start(skill)
        results = self.play(skill, [False] * 4)[1]
        evaluation = results[-1]['evaluation']
        self.assertEqual(evaluation['dominant_error_type'], 'careless')  # égalité 2/2
        self.assertEqual(evaluation['decision'], 'teacher_review')
        self.assertTrue(evaluation['teacher_review'])
        self.assertIsNone(results[-1]['redirect'])
        step = self.nxt(skill)
        self.assertEqual((step['mode'], step['intervention']['step']), ('intervention', 'careless_exercise'))

    def test_no_suitable_prerequisite_is_logged_for_teacher_review(self):
        skill = self.s_concept  # aucun prérequis
        self.exercises(skill, ['concept'] * 4)
        self.start(skill)
        self.play(skill, [False] * 4)

        self.client.force_authenticate(self.teacher)
        cases = self.client.get(reverse('review-case-list')).data
        rows = cases['results'] if isinstance(cases, dict) else cases
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['from_skill_code'], skill.code)
        self.assertIsNone(rows[0]['to_skill'])

        # Un nouvel épuisement ne crée pas de doublon tant que le cas est ouvert.
        self.client.force_authenticate(self.student)
        for _ in range(10):  # termine l'intervention (réponses fausses)
            step = self.nxt(skill)
            if step['mode'] != 'intervention':
                break
            if step['chunk']['chunk_type'] == 'practice':
                self.answer(Chunk.objects.get(pk=step['chunk']['id']), 'خطأ')
        self.play(skill, [False] * 4)
        self.assertEqual(PrerequisiteReturn.objects.filter(from_skill=skill).count(), 1)
        self.client.force_authenticate(self.teacher)

        resp = self.client.patch(reverse('review-case-detail', kwargs={'pk': rows[0]['id']}),
                                 {'review_note': 'تمت المتابعة'}, format='json')
        self.assertEqual(resp.data['status'], 'reviewed')
        self.assertEqual(resp.data['reviewed_by'], self.teacher.id)

    def test_engine_settings_are_configurable_by_admin_only(self):
        self.client.force_authenticate(self.teacher)
        self.assertEqual(self.client.get(reverse('engine-settings')).data['min_attempts'], 4)
        self.assertEqual(self.client.patch(reverse('engine-settings'), {'group_size': 6}).status_code,
                         status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(make_user('admin1', User.Role.ADMIN))
        self.assertEqual(self.client.patch(reverse('engine-settings'), {'group_size': 6}).data['group_size'], 6)
        resp = self.client.patch(reverse('engine-settings'), {'low_threshold': '0.90'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

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
