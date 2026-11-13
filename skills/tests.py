"""
skills/tests.py

Scenario d'import de contenu (IMPORT_ENDPOINTS.md) : les champs du
fichier source (term, programme_ref, week, image, options riches...)
doivent etre conserves par l'API, sans exposer les reponses aux etudiants.
"""

import shutil
import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from curriculum.models import Stage, Level, Subject
from users.models import User

MEDIA_ROOT = tempfile.mkdtemp()

RICH_OPTIONS = [
    {'id': 'a', 'text': 'نعم', 'is_correct': True, 'error_category': None, 'feedback': 'أحسنت'},
    {'id': 'b', 'text': 'لا', 'is_correct': False, 'error_category': 'conceptual', 'feedback': 'انظر إلى الشجرة'},
]


def make_user(username, role):
    return User.objects.create_user(
        username=username, email=f"{username}@fatin.test", password="pass1234", role=role,
    )


def png_file(name='chunk.png'):
    buffer = BytesIO()
    Image.new('RGB', (2, 2), 'white').save(buffer, format='PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class ContentImportTestCase(APITestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.teacher = make_user('zeinab', User.Role.TEACHER)
        self.student = make_user('ahmed', User.Role.STUDENT)
        stage = Stage.objects.create(name='المرحلة الابتدائية', code='PRIM', order_index=1)
        level = Level.objects.create(stage=stage, name='السنة الأولى', code='PRIM-1', order_index=1)
        self.subject = Subject.objects.create(level=level, name='الرياضيات')

    def _import_up_to_chunk(self):
        self.client.force_authenticate(self.teacher)
        unit = self.client.post(reverse('unit-list'), {
            'subject': self.subject.id, 'code': 'U11', 'title': 'المواقع',
            'description': 'وصف', 'main_skill_domain': 'الهندسة',
            'term': '1', 'competency_ref': 'C1.2',
        }, format='json')
        self.assertEqual(unit.status_code, status.HTTP_201_CREATED, unit.data)

        lesson = self.client.post(reverse('lesson-list'), {
            'unit': unit.data['id'], 'code': 'U11-L01', 'title': 'أمام وخلف',
            'programme_ref': 'P-M1-07', 'week': 3,
            'programme_weeks': [3, 4], 'book_exercises': ['ص 12 ت 1', 'ص 12 ت 2'],
        }, format='json')
        self.assertEqual(lesson.status_code, status.HTTP_201_CREATED, lesson.data)

        goal = self.client.post(reverse('goal-list'), {
            'lesson': lesson.data['id'], 'goal_type': 'conceptual', 'title': 'فهم المواقع', 'order_index': 1,
        }, format='json')
        skill = self.client.post(reverse('skill-list'), {
            'goal': goal.data['id'], 'skill_type': 'conceptual', 'code': 'SK-U11-L01-C01', 'name': 'خلف',
        }, format='json')
        chunk = self.client.post(reverse('chunk-list'), {
            'skill': skill.data['id'], 'code': 'SK-U11-L01-C01-CH01', 'chunk_type': 'practice',
            'content': 'هل سيدي خلف الشجرة؟', 'correct_answer': 'نعم', 'options': RICH_OPTIONS,
            'needs_image': True, 'image_note': 'سيدي واقف خلف شجرة',
        }, format='json')
        self.assertEqual(chunk.status_code, status.HTTP_201_CREATED, chunk.data)
        return unit.data, lesson.data, chunk.data

    def test_unit_and_lesson_keep_programme_fields(self):
        unit, lesson, _chunk = self._import_up_to_chunk()

        self.assertEqual(unit['term'], '1')
        self.assertEqual(unit['competency_ref'], 'C1.2')
        self.assertEqual(unit['main_skill_domain'], 'الهندسة')
        self.assertEqual(lesson['programme_ref'], 'P-M1-07')
        self.assertEqual(lesson['week'], 3)
        self.assertEqual(lesson['programme_weeks'], [3, 4])
        self.assertEqual(lesson['book_exercises'], ['ص 12 ت 1', 'ص 12 ت 2'])

    def test_teacher_keeps_rich_options_and_uploads_image(self):
        _unit, _lesson, chunk = self._import_up_to_chunk()
        self.assertEqual(chunk['options'], RICH_OPTIONS)
        self.assertTrue(chunk['needs_image'])
        self.assertEqual(chunk['image_note'], 'سيدي واقف خلف شجرة')
        self.assertIsNone(chunk['image'])

        upload = self.client.patch(
            reverse('chunk-detail', args=[chunk['id']]), {'image': png_file()}, format='multipart',
        )
        self.assertEqual(upload.status_code, status.HTTP_200_OK, upload.data)
        self.assertIn('/media/chunks/', upload.data['image'])
        self.assertEqual(upload.data['options'], RICH_OPTIONS)

    def test_student_only_sees_option_texts(self):
        _unit, _lesson, chunk = self._import_up_to_chunk()

        self.client.force_authenticate(self.student)
        resp = self.client.get(reverse('chunk-detail', args=[chunk['id']]))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['options'], ['نعم', 'لا'])
        self.assertNotIn('correct_answer', resp.data)

    def test_malformed_option_is_rejected(self):
        self.client.force_authenticate(self.teacher)
        _unit, _lesson, chunk = self._import_up_to_chunk()

        resp = self.client.patch(
            reverse('chunk-detail', args=[chunk['id']]),
            {'options': [{'id': 'a', 'is_correct': 'yes'}]}, format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
