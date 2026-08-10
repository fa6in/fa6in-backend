"""
core/management/commands/generate_sample_data.py

أمر Django لإنشاء بيانات نموذجية للنظام التعليمي
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from curriculum.models import Subject, Unit, Lesson
from assessment.models import Chunk, StudentAttempt, StudentProgress
from users.models import TeacherProfile, StudentProfile
from analytics.models import LearningAnalytics, TeacherDashboard, SystemLog
import random
from datetime import datetime, timedelta
import json

User = get_user_model()

class Command(BaseCommand):
    help = 'إنشاء بيانات نموذجية شاملة لنظام Ed-Tech'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='حذف البيانات الحالية قبل إنشاء الجديدة'
        )
        parser.add_argument(
            '--students',
            type=int,
            default=20,
            help='عدد الطلاب المراد إنشاؤهم'
        )
        parser.add_argument(
            '--teachers',
            type=int,
            default=5,
            help='عدد المعلمين المراد إنشاؤهم'
        )
        parser.add_argument(
            '--units',
            type=int,
            default=15,
            help='عدد الوحدات التعليمية المراد إنشاؤها'
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('بدء إنشاء البيانات النموذجية...'))
        
        # حذف البيانات القديمة إذا طُلب
        if options['clear']:
            self.clear_existing_data()
        
        # إنشاء المستخدمين
        admin_user = self.create_admin_user()
        teachers = self.create_teachers(options['teachers'])
        students = self.create_students(options['students'])
        
        # إنشاء المواد الدراسية
        subjects = self.create_subjects()
        
        # إنشاء الوحدات التعليمية
        units = self.create_units(subjects, teachers, options['units'])
        
        # إنشاء محتوى الوحدات
        self.create_content_sections(units)
        
        # إنشاء الأنشطة
        activities = self.create_activities(units)
        
        # إنشاء محاولات الطلاب وتقدمهم
        self.create_student_attempts_and_progress(students, activities, units)
        
        # إنشاء تحليلات التعلم
        self.create_learning_analytics(students)
        
        # إنشاء لوحات تحكم المعلمين
        self.create_teacher_dashboards(teachers)
        
        # إنشاء سجلات النظام
        self.create_system_logs(admin_user, teachers, students)
        
        self.stdout.write(self.style.SUCCESS('✅ تم إنشاء البيانات النموذجية بنجاح!'))
        self.print_summary(admin_user, teachers, students, subjects, units, activities)

    def clear_existing_data(self):
        """حذف جميع البيانات الحالية"""
        self.stdout.write('🗑️  جاري حذف البيانات الحالية...')
        
        models_to_clear = [
            SystemLog, LearningAnalytics, TeacherDashboard,
            StudentAttempt, StudentProgress, Chunk,
            Lesson, Unit, Subject,
            TeacherProfile, StudentProfile, User
        ]
        
        for model in models_to_clear:
            try:
                count = model.objects.count()
                model.objects.all().delete()
                self.stdout.write(f'   حذف {count} سجل من {model.__name__}')
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'   خطأ في حذف {model.__name__}: {str(e)}'))
        
        self.stdout.write('✅ تم حذف جميع البيانات')

    def create_admin_user(self):
        """إنشاء مستخدم مدير النظام"""
        self.stdout.write('👑 جاري إنشاء مدير النظام...')
        
        admin, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@edtech.edu',
                'first_name': 'أحمد',
                'last_name': 'المدير',
                'role': 'admin',
                'is_staff': True,
                'is_superuser': True,
                'phone_number': '+966501234567',
                'school': 'مدرسة النموذج الرقمي'
            }
        )
        
        if created:
            admin.set_password('Admin123!')
            admin.save()
            self.stdout.write(f'   ✅ تم إنشاء المدير: {admin.username}')
        else:
            self.stdout.write(f'   ⚠️  المدير موجود بالفعل: {admin.username}')
        
        return admin

    def create_teachers(self, count):
        """إنشاء معلمين"""
        self.stdout.write(f'👨‍🏫 جاري إنشاء {count} معلم...')
        
        teachers_data = [
            {
                'username': 'teacher_math',
                'first_name': 'محمد',
                'last_name': 'الرياضيات',
                'email': 'math.teacher@edtech.edu',
                'role': 'teacher',
                'phone_number': '+966502345678',
                'school': 'مدرسة النخبة'
            },
            {
                'username': 'teacher_science',
                'first_name': 'فاطمة',
                'last_name': 'العلوم',
                'email': 'science.teacher@edtech.edu',
                'role': 'teacher',
                'phone_number': '+966503456789',
                'school': 'مدرسة الأفق'
            },
            {
                'username': 'teacher_arabic',
                'first_name': 'خالد',
                'last_name': 'العربي',
                'email': 'arabic.teacher@edtech.edu',
                'role': 'teacher',
                'phone_number': '+966504567890',
                'school': 'مدرسة اللغة العربية'
            },
            {
                'username': 'teacher_english',
                'first_name': 'سارة',
                'last_name': 'الإنجليزية',
                'email': 'english.teacher@edtech.edu',
                'role': 'teacher',
                'phone_number': '+966505678901',
                'school': 'مدرسة المستقبل'
            },
            {
                'username': 'teacher_art',
                'first_name': 'ليلى',
                'last_name': 'الفنون',
                'email': 'art.teacher@edtech.edu',
                'role': 'teacher',
                'phone_number': '+966506789012',
                'school': 'مدرسة الإبداع'
            }
        ]
        
        teachers = []
        for i, teacher_data in enumerate(teachers_data[:count]):
            teacher, created = User.objects.get_or_create(
                username=teacher_data['username'],
                defaults=teacher_data
            )
            
            if created:
                teacher.set_password('Teacher123!')
                teacher.save()
                
                # إنشاء ملف المعلم
                TeacherProfile.objects.create(
                    user=teacher,
                    subjects=self.get_teacher_subjects(teacher_data['username']),
                    years_of_experience=random.randint(3, 15),
                    qualification=self.get_teacher_qualification(),
                    is_active=True
                )
                
                self.stdout.write(f'   ✅ تم إنشاء المعلم: {teacher.get_full_name()}')
            else:
                self.stdout.write(f'   ⚠️  المعلم موجود بالفعل: {teacher.get_full_name()}')
            
            teachers.append(teacher)
        
        # إنشاء معلمين إضافيين إذا طُلب عدد أكبر
        if count > len(teachers_data):
            for i in range(len(teachers_data), count):
                teacher_num = i + 1
                teacher = User.objects.create(
                    username=f'teacher_{teacher_num}',
                    email=f'teacher{teacher_num}@edtech.edu',
                    first_name=f'معلم{teacher_num}',
                    last_name='النموذجي',
                    role='teacher',
                    phone_number=f'+96650{7000000 + teacher_num}',
                    school=random.choice(['مدرسة النموذج', 'مدرسة التجريب', 'مدرسة الابتكار'])
                )
                teacher.set_password('Teacher123!')
                teacher.save()
                
                TeacherProfile.objects.create(
                    user=teacher,
                    subjects='رياضيات, علوم',
                    years_of_experience=random.randint(1, 10),
                    qualification='بكالوريوس تربية',
                    is_active=True
                )
                
                teachers.append(teacher)
                self.stdout.write(f'   ✅ تم إنشاء المعلم الإضافي: {teacher.username}')
        
        return teachers

    def get_teacher_subjects(self, username):
        """الحصول على مواد المعلم حسب اسم المستخدم"""
        subjects_map = {
            'teacher_math': 'رياضيات',
            'teacher_science': 'علوم, فيزياء, كيمياء',
            'teacher_arabic': 'لغة عربية, تربية إسلامية',
            'teacher_english': 'لغة إنجليزية, فرنسية',
            'teacher_art': 'تربية فنية, موسيقى, رياضة'
        }
        return subjects_map.get(username, 'رياضيات, علوم')

    def get_teacher_qualification(self):
        """الحصول على مؤهل تعليمي عشوائي"""
        qualifications = [
            'بكالوريوس تربية',
            'ماجستير في المناهج وطرق التدريس',
            'دكتوراه في التربية',
            'دبلوم عالي في التعليم',
            'بكالوريوس علوم + دبلوم تربوي'
        ]
        return random.choice(qualifications)

    def create_students(self, count):
        """إنشاء طلاب"""
        self.stdout.write(f'👨‍🎓 جاري إنشاء {count} طالب...')
        
        first_names = [
            'أحمد', 'محمد', 'علي', 'خالد', 'عمر', 'يوسف', 'عبدالله', 'محمود',
            'فاطمة', 'سارة', 'مريم', 'نورة', 'لينا', 'ريم', 'هدى', 'آلاء'
        ]
        
        last_names = [
            'الزيد', 'العلي', 'المحمد', 'السعيد', 'الفهيد',
            'القحطاني', 'العتيبي', 'الغامدي', 'الحربي', 'الشمراني'
        ]
        
        schools = [
            'مدرسة النخبة الابتدائية',
            'مدرسة الأفق الدولية',
            'مدرسة المستقبل النموذجية',
            'مدرسة الإبداع العلمي',
            'مدرسة التميز التعليمية'
        ]
        
        students = []
        for i in range(1, count + 1):
            first_name = random.choice(first_names)
            last_name = random.choice(last_names)
            
            student, created = User.objects.get_or_create(
                username=f'student_{i:03d}',
                defaults={
                    'email': f'student{i:03d}@edtech.edu',
                    'first_name': first_name,
                    'last_name': last_name,
                    'role': 'student',
                    'grade': random.randint(1, 6),
                    'school': random.choice(schools),
                    'phone_number': f'+96655{random.randint(1000000, 9999999)}',
                    'date_of_birth': self.generate_random_date(2008, 2015)
                }
            )
            
            if created:
                student.set_password('Student123!')
                student.save()
                
                # إنشاء ملف الطالب
                StudentProfile.objects.create(
                    user=student,
                    parent_name=f'والد {first_name}',
                    parent_phone=f'+96654{random.randint(1000000, 9999999)}',
                    address=f'حي {random.choice(["النخيل", "الروضة", "الرياض", "الغرابي"])}, المدينة'
                )
                
                self.stdout.write(f'   ✅ تم إنشاء الطالب: {student.get_full_name()} - الصف {student.grade}')
            else:
                self.stdout.write(f'   ⚠️  الطالب موجود بالفعل: {student.get_full_name()}')
            
            students.append(student)
        
        return students

    def generate_random_date(self, start_year, end_year):
        """إنشاء تاريخ عشوائي بين سنة البداية والنهاية"""
        year = random.randint(start_year, end_year)
        month = random.randint(1, 12)
        day = random.randint(1, 28)  # لتجنب مشاكل فبراير
        return datetime(year, month, day).date()

    def create_subjects(self):
        """إنشاء مواد دراسية"""
        self.stdout.write('📚 جاري إنشاء المواد الدراسية...')
        
        subjects_data = [
            {
                'name': 'الرياضيات',
                'grade': 1,
                'description': 'مادة الرياضيات للصف الأول الابتدائي - تعلم الأعداد والعمليات الأساسية',
                'icon': 'calculator',
                'color': '#4CAF50',
                'is_active': True
            },
            {
                'name': 'الرياضيات',
                'grade': 2,
                'description': 'مادة الرياضيات للصف الثاني الابتدائي - الجمع والطرح ضمن المئة',
                'icon': 'calculator',
                'color': '#4CAF50',
                'is_active': True
            },
            {
                'name': 'اللغة العربية',
                'grade': 1,
                'description': 'مادة اللغة العربية للصف الأول - القراءة والكتابة الأساسية',
                'icon': 'book',
                'color': '#2196F3',
                'is_active': True
            },
            {
                'name': 'اللغة العربية',
                'grade': 2,
                'description': 'مادة اللغة العربية للصف الثاني - قواعد اللغة والمفردات',
                'icon': 'book',
                'color': '#2196F3',
                'is_active': True
            },
            {
                'name': 'العلوم',
                'grade': 1,
                'description': 'مادة العلوم للصف الأول - التعرف على البيئة والمخلوقات',
                'icon': 'flask',
                'color': '#FF9800',
                'is_active': True
            },
            {
                'name': 'العلوم',
                'grade': 2,
                'description': 'مادة العلوم للصف الثاني - التجارب العلمية البسيطة',
                'icon': 'flask',
                'color': '#FF9800',
                'is_active': True
            },
            {
                'name': 'اللغة الإنجليزية',
                'grade': 1,
                'description': 'مادة اللغة الإنجليزية للصف الأول - الحروف والكلمات الأساسية',
                'icon': 'language',
                'color': '#E91E63',
                'is_active': True
            },
            {
                'name': 'التربية الإسلامية',
                'grade': 1,
                'description': 'مادة التربية الإسلامية - القرآن الكريم والأحكام الأساسية',
                'icon': 'mosque',
                'color': '#9C27B0',
                'is_active': True
            },
            {
                'name': 'التربية الفنية',
                'grade': 1,
                'description': 'مادة التربية الفنية - الرسم والأشغال اليدوية',
                'icon': 'palette',
                'color': '#FF5722',
                'is_active': True
            }
        ]
        
        subjects = []
        for subject_data in subjects_data:
            subject, created = Subject.objects.get_or_create(
                name=subject_data['name'],
                grade=subject_data['grade'],
                defaults=subject_data
            )
            
            if created:
                self.stdout.write(f'   ✅ تم إنشاء المادة: {subject.name} - الصف {subject.grade}')
            else:
                self.stdout.write(f'   ⚠️  المادة موجودة بالفعل: {subject.name} - الصف {subject.grade}')
            
            subjects.append(subject)
        
        return subjects

    def create_units(self, subjects, teachers, count):
        """إنشاء وحدات تعليمية"""
        self.stdout.write(f'📖 جاري إنشاء {count} وحدة تعليمية...')
        
        math_topics = [
            'الأعداد من 1 إلى 10',
            'الجمع البسيط',
            'الطرح البسيط',
            'الأعداد من 11 إلى 20',
            'الجمع مع التجميع',
            'الطرح مع الاستلاف',
            'القياس والطول',
            'الأشكال الهندسية',
            'الوقت والساعة',
            'النقود والعملات'
        ]
        
        arabic_topics = [
            'الحروف الهجائية',
            'الحركات (الفتحة، الضمة، الكسرة)',
            'القراءة بالتشكيل',
            'كتابة الجمل البسيطة',
            'المفرد والجمع',
            'أسماء الإشارة',
            'أدوات الاستفهام',
            'قصص مصورة',
            'الخط العربي',
            'الإملاء البسيط'
        ]
        
        science_topics = [
            'أجزاء النبات',
            'دورة حياة الفراشة',
            'أعضاء الجسم',
            'الفصول الأربعة',
            'الطقس والمناخ',
            'المغناطيس',
            'مصادر الطاقة',
            'الكائنات الحية',
            'دورة الماء',
            'النظام الشمسي'
        ]
        
        english_topics = [
            'English Alphabets',
            'Basic Vocabulary',
            'Colors and Numbers',
            'Family Members',
            'Days of the Week',
            'Simple Sentences',
            'Animals Names',
            'Fruits and Vegetables',
            'My School',
            'Greetings'
        ]
        
        units = []
        unit_id = 1
        
        for subject in subjects:
            if subject.name == 'الرياضيات':
                topics = math_topics
            elif subject.name == 'اللغة العربية':
                topics = arabic_topics
            elif subject.name == 'العلوم':
                topics = science_topics
            elif subject.name == 'اللغة الإنجليزية':
                topics = english_topics
            else:
                topics = [f'موضوع {i}' for i in range(1, 6)]
            
            # إنشاء وحدات لهذه المادة
            for i, topic in enumerate(topics[:3]):  # 3 وحدات لكل مادة كحد أقصى
                if len(units) >= count:
                    break
                
                teacher = random.choice(teachers)
                
                unit, created = Unit.objects.get_or_create(
                    subject=subject,
                    title=f'{topic} - الصف {subject.grade}',
                    defaults={
                        'description': f'وحدة تعليمية عن {topic} للصف {subject.grade}',
                        'learning_objective': self.generate_learning_objective(subject.name, topic),
                        'duration_minutes': random.choice([15, 20, 25, 30]),
                        'difficulty': random.choice(['easy', 'medium', 'hard']),
                        'order': i + 1,
                        'thumbnail': self.generate_thumbnail_url(subject.name),
                        'video_url': self.generate_video_url(topic),
                        'audio_url': self.generate_audio_url(topic) if random.random() > 0.5 else '',
                        'is_published': random.random() > 0.2,  # 80% منشورة
                        'created_by': teacher
                    }
                )
                
                if created:
                    self.stdout.write(f'   ✅ وحدة {unit_id:03d}: {unit.title}')
                    unit_id += 1
                else:
                    self.stdout.write(f'   ⚠️  الوحدة موجودة: {unit.title}')
                
                units.append(unit)
        
        # إذا لم نصل إلى العدد المطلوب، ننشئ وحدات إضافية
        while len(units) < count:
            subject = random.choice(subjects)
            teacher = random.choice(teachers)
            
            unit = Unit.objects.create(
                subject=subject,
                title=f'وحدة إضافية {len(units) + 1} - {subject.name}',
                description=f'وحدة تعليمية إضافية في {subject.name}',
                learning_objective=f'تعلم مفاهيم جديدة في {subject.name}',
                duration_minutes=20,
                difficulty='medium',
                order=len(units) + 1,
                is_published=True,
                created_by=teacher
            )
            
            units.append(unit)
            self.stdout.write(f'   ➕ وحدة إضافية {unit_id:03d}: {unit.title}')
            unit_id += 1
        
        return units

    def generate_learning_objective(self, subject, topic):
        """إنشاء هدف تعليمي"""
        objectives = {
            'الرياضيات': [
                f'فهم مفهوم {topic} وتطبيقه في مسائل حياتية',
                f'حل مسائل {topic} بدقة وسرعة',
                f'ربط {topic} بالمواقف اليومية'
            ],
            'اللغة العربية': [
                f'قراءة نصوص عن {topic} بطلاقة',
                f'كتابة فقرة عن {topic} بإتقان',
                f'فهم معاني الكلمات المتعلقة بـ{topic}'
            ],
            'العلوم': [
                f'استكشاف ظواهر {topic} العلمية',
                f'إجراء تجارب بسيطة عن {topic}',
                f'فهم أهمية {topic} في الحياة'
            ],
            'اللغة الإنجليزية': [
                f'Learn vocabulary related to {topic}',
                f'Practice speaking about {topic}',
                f'Write simple sentences about {topic}'
            ]
        }
        
        default_objectives = [
            f'فهم مفهوم {topic}',
            f'تطبيق {topic} في مواقف مختلفة',
            f'تحليل عناصر {topic}'
        ]
        
        return random.choice(objectives.get(subject, default_objectives))

    def generate_thumbnail_url(self, subject):
        """إنشاء رابط صورة مصغرة"""
        thumbnails = {
            'الرياضيات': 'https://example.com/math_thumb.jpg',
            'اللغة العربية': 'https://example.com/arabic_thumb.jpg',
            'العلوم': 'https://example.com/science_thumb.jpg',
            'اللغة الإنجليزية': 'https://example.com/english_thumb.jpg',
            'التربية الإسلامية': 'https://example.com/islamic_thumb.jpg',
            'التربية الفنية': 'https://example.com/art_thumb.jpg'
        }
        return thumbnails.get(subject, 'https://example.com/default_thumb.jpg')

    def generate_video_url(self, topic):
        """إنشاء رابط فيديو"""
        video_id = hash(topic) % 1000000
        return f'https://www.youtube.com/watch?v={video_id:06d}'

    def generate_audio_url(self, topic):
        """إنشاء رابط صوتي"""
        audio_id = hash(topic) % 1000
        return f'https://audio.edtech.edu/{audio_id:03d}.mp3'

    def create_content_sections(self, units):
        """إنشاء أقسام المحتوى للوحدات"""
        self.stdout.write('📄 جاري إنشاء أقسام المحتوى...')
        
        content_sections_created = 0
        
        for unit in units:
            # إنشاء 3-5 أقسام لكل وحدة
            num_sections = random.randint(3, 5)
            
            for i in range(num_sections):
                section_type = random.choice(['text', 'image', 'video', 'audio', 'interactive'])
                
                if section_type == 'text':
                    content = self.generate_text_content(unit.title, i+1)
                    metadata = {}
                elif section_type == 'image':
                    content = self.generate_image_url(unit.subject.name)
                    metadata = {'caption': f'صورة توضيحية للقسم {i+1}'}
                elif section_type == 'video':
                    content = self.generate_video_url(unit.title)
                    metadata = {'duration': random.randint(60, 300)}
                elif section_type == 'audio':
                    content = self.generate_audio_url(unit.title)
                    metadata = {'duration': random.randint(30, 180)}
                else:  # interactive
                    content = self.generate_interactive_content()
                    metadata = {'type': 'quiz', 'questions': 3}
                
                Lesson.objects.create(
                    unit=unit,
                    title=f'القسم {i+1}: {self.get_section_title(section_type, unit.subject.name)}',
                    content_type=section_type,
                    content=content,
                    order=i+1,
                    metadata=metadata
                )
                
                content_sections_created += 1
        
        self.stdout.write(f'   ✅ تم إنشاء {content_sections_created} قسم محتوى')

    def generate_text_content(self, unit_title, section_num):
        """إنشاء محتوى نصي"""
        contents = [
            f'مرحباً بك في قسم {section_num} من وحدة "{unit_title}".',
            f'في هذا القسم، سنتعلم مفاهيم جديدة ومهمة.',
            f'نبدأ رحلتنا التعليمية في هذا القسم بشرح مبسط.',
            f'هذا المحتوى مصمم خصيصاً لفهم {unit_title} بشكل أفضل.',
            f'انطلق معنا في رحلة تعلم {unit_title} من خلال هذا القسم.'
        ]
        return '\n\n'.join(random.sample(contents, 3))

    def generate_image_url(self, subject):
        """إنشاء رابط صورة"""
        images = {
            'الرياضيات': [
                'https://example.com/math1.jpg',
                'https://example.com/math2.jpg',
                'https://example.com/math3.jpg'
            ],
            'اللغة العربية': [
                'https://example.com/arabic1.jpg',
                'https://example.com/arabic2.jpg',
                'https://example.com/arabic3.jpg'
            ],
            'العلوم': [
                'https://example.com/science1.jpg',
                'https://example.com/science2.jpg',
                'https://example.com/science3.jpg'
            ]
        }
        return random.choice(images.get(subject, ['https://example.com/default.jpg']))

    def generate_interactive_content(self):
        """إنشاء محتوى تفاعلي"""
        return json.dumps({
            'type': 'interactive_quiz',
            'questions': [
                {
                    'id': 1,
                    'question': 'ما هو الجواب الصحيح؟',
                    'options': ['الخيار أ', 'الخيار ب', 'الخيار ج', 'الخيار د'],
                    'correct': 0
                }
            ]
        })

    def get_section_title(self, section_type, subject):
        """الحصول على عنوان القسم"""
        titles = {
            'text': {'الرياضيات': 'شرح المفاهيم', 'اللغة العربية': 'نص القراءة', 'default': 'الشرح النصي'},
            'image': {'default': 'الصور التوضيحية'},
            'video': {'default': 'الفيديو التعليمي'},
            'audio': {'default': 'التسجيل الصوتي'},
            'interactive': {'default': 'النشاط التفاعلي'}
        }
        
        type_titles = titles.get(section_type, {'default': 'قسم المحتوى'})
        return type_titles.get(subject, type_titles.get('default', 'قسم المحتوى'))

    def create_activities(self, units):
        """إنشاء أنشطة تقييم"""
        self.stdout.write('🎯 جاري إنشاء الأنشطة...')
        
        activities = []
        Chunk_id = 1
        
        for unit in units:
            # إنشاء 4-8 أنشطة لكل وحدة
            num_activities = random.randint(4, 8)
            
            for i in range(num_activities):
                Chunk_type = random.choice([
                    'multiple_choice', 'true_false', 'fill_blank',
                    'matching', 'drag_drop', 'short_answer'
                ])
                
                Chunk = Chunk.objects.create(
                    unit=unit,
                    title=f'نشاط {i+1}: {self.get_Chunk_title(Chunk_type, unit.title)}',
                    Chunk_type=Chunk_type,
                    question=self.generate_question(unit.subject.name, Chunk_type, i+1),
                    options=self.generate_options(Chunk_type),
                    correct_answer=self.generate_correct_answer(Chunk_type),
                    points=random.choice([5, 10, 15, 20]),
                    explanation=self.generate_explanation(unit.subject.name),
                    time_limit=random.choice([None, 60, 90, 120]),
                    order=i+1,
                    is_active=True
                )
                
                activities.append(Chunk)
                Chunk_id += 1
        
        self.stdout.write(f'   ✅ تم إنشاء {len(activities)} نشاط')
        return activities

    def get_Chunk_title(self, Chunk_type, unit_title):
        """الحصول على عنوان النشاط"""
        titles = {
            'multiple_choice': 'اختيار من متعدد',
            'true_false': 'صح أو خطأ',
            'fill_blank': 'ملء الفراغات',
            'matching': 'توصيل',
            'drag_drop': 'سحب وإفلات',
            'short_answer': 'إجابة قصيرة'
        }
        return titles.get(Chunk_type, 'نشاط تفاعلي')

    def generate_question(self, subject, Chunk_type, question_num):
        """إنشاء سؤال"""
        math_questions = [
            'ما نتيجة جمع 5 + 3؟',
            'ما العدد الذي يلي 9؟',
            'كم يساوي 10 - 4؟',
            'أي الأعداد هو الأكبر: 7 أم 9؟',
            'ما الشكل الذي له 3 أضلاع؟'
        ]
        
        arabic_questions = [
            'ما حرف (ب) في أول الكلمة؟',
            'ما الحركة المناسبة تحت الحرف؟',
            'أي كلمة تبدأ بحرف (س)؟',
            'ما جمع كلمة "كتاب"؟',
            'ما ضد كلمة "كبير"؟'
        ]
        
        science_questions = [
            'كم عدد أرجل الفراشة؟',
            'ما لون الشمس؟',
            'أي الحيوانات تبيض؟',
            'ما مصدر الطاقة للشجرة؟',
            'كم عدد الفصول في السنة؟'
        ]
        
        english_questions = [
            'What is the color of apple?',
            'How many days in a week?',
            'What is opposite of "hot"?',
            'Which animal says "meow"?',
            'What is 5 + 3 in English?'
        ]
        
        questions_map = {
            'الرياضيات': math_questions,
            'اللغة العربية': arabic_questions,
            'العلوم': science_questions,
            'اللغة الإنجليزية': english_questions
        }
        
        default_questions = [
            f'السؤال {question_num}: اختر الإجابة الصحيحة',
            f'ما هو الجواب المناسب؟',
            f'أكمل الجملة التالية:',
            f'صح أم خطأ:',
            f'صل بين العمودين التاليين:'
        ]
        
        subject_questions = questions_map.get(subject, default_questions)
        return random.choice(subject_questions)

    def generate_options(self, Chunk_type):
        """إنشاء خيارات النشاط"""
        if Chunk_type == 'multiple_choice':
            return ['الخيار الأول', 'الخيار الثاني', 'الخيار الثالث', 'الخيار الرابع']
        elif Chunk_type == 'true_false':
            return ['صح', 'خطأ']
        elif Chunk_type == 'matching':
            return {'أ': '1', 'ب': '2', 'ج': '3'}
        elif Chunk_type == 'drag_drop':
            return ['عنصر 1', 'عنصر 2', 'عنصر 3', 'عنصر 4']
        else:
            return []

    def generate_correct_answer(self, Chunk_type):
        """إنشاء الإجابة الصحيحة"""
        if Chunk_type in ['multiple_choice', 'true_false']:
            return random.randint(0, 1 if Chunk_type == 'true_false' else 3)
        elif Chunk_type == 'fill_blank':
            return 'الجواب الصحيح'
        elif Chunk_type == 'matching':
            return {'أ': '1', 'ب': '2', 'ج': '3'}
        elif Chunk_type == 'drag_drop':
            return ['عنصر 1', 'عنصر 2']
        else:  # short_answer
            return 'هذه هي الإجابة النموذجية'

    def generate_explanation(self, subject):
        """إنشاء تفسير للإجابة"""
        explanations = {
            'الرياضيات': 'الشرح الرياضي يعتمد على القواعد الأساسية للعمليات الحسابية.',
            'اللغة العربية': 'التفسير اللغوي مبني على قواعد النحو والصرف.',
            'العلوم': 'الشرح العلمي يستند إلى الحقائق والملاحظات التجريبية.',
            'اللغة الإنجليزية': 'The explanation is based on English grammar rules.'
        }
        return explanations.get(subject, 'هذا هو التفسير المناسب للإجابة الصحيحة.')

    def create_student_attempts_and_progress(self, students, activities, units):
        """إنشاء محاولات الطلاب وتقدمهم"""
        self.stdout.write('📊 جاري إنشاء محاولات الطلاب وتقدمهم...')
        
        attempts_created = 0
        progress_created = 0
        
        for student in students:
            # تحديد الوحدات التي سيدرسها الطالب (2-6 وحدات)
            student_units = random.sample(units, min(len(units), random.randint(2, 6)))
            
            for unit in student_units:
                # إنشاء تقدم الطالب في الوحدة
                progress, created = StudentProgress.objects.get_or_create(
                    student=student,
                    unit=unit,
                    defaults={
                        'total_score': 0,
                        'mastery_level': 'not_started',
                        'completion_percentage': 0,
                        'last_accessed': timezone.now() - timedelta(days=random.randint(0, 30))
                    }
                )
                
                if created:
                    progress_created += 1
                
                # الحصول على أنشطة الوحدة
                unit_activities = [a for a in activities if a.unit == unit]
                
                if not unit_activities:
                    continue
                
                # تحديد عدد الأنشطة التي سيحاولها الطالب (2-كل الأنشطة)
                num_attempts = random.randint(2, len(unit_activities))
                attempted_activities = random.sample(unit_activities, num_attempts)
                
                completed_activities = []
                total_score = 0
                
                for Chunk in attempted_activities:
                    # إنشاء 1-3 محاولات لكل نشاط
                    num_tries = random.randint(1, 3)
                    
                    for try_num in range(num_tries):
                        # نسبة النجاح: 60-90%
                        is_correct = random.random() < random.uniform(0.6, 0.9)
                        score = Chunk.points if is_correct else 0
                        
                        attempt = StudentAttempt.objects.create(
                            student=student,
                            Chunk=Chunk,
                            answer=self.generate_student_answer(Chunk, is_correct),
                            is_correct=is_correct,
                            score=score,
                            time_taken=random.randint(30, 300),
                            attempted_at=timezone.now() - timedelta(
                                days=random.randint(0, 30),
                                hours=random.randint(0, 23),
                                minutes=random.randint(0, 59)
                            )
                        )
                        
                        attempts_created += 1
                        
                        # إذا كانت المحاولة صحيحة في المحاولة الأخيرة، نعتبر النشاط مكتملاً
                        if try_num == num_tries - 1 and is_correct:
                            completed_activities.append(Chunk)
                            total_score += score
                
                # تحديث تقدم الطالب
                if completed_activities:
                    progress.completed_activities.set(completed_activities)
                    progress.total_score = total_score
                    progress.last_accessed = timezone.now()
                    
                    # حساب نسبة الإنجاز
                    completion_percentage = (len(completed_activities) / len(unit_activities)) * 100
                    progress.completion_percentage = completion_percentage
                    
                    # تحديث مستوى الإتقان
                    if completion_percentage >= 90:
                        progress.mastery_level = 'mastered'
                    elif completion_percentage >= 70:
                        progress.mastery_level = 'advanced'
                    elif completion_percentage >= 50:
                        progress.mastery_level = 'intermediate'
                    elif completion_percentage > 0:
                        progress.mastery_level = 'beginner'
                    
                    # إذا أكمل جميع الأنشطة
                    if len(completed_activities) == len(unit_activities):
                        progress.completed_at = timezone.now()
                    
                    progress.save()
        
        self.stdout.write(f'   ✅ تم إنشاء {attempts_created} محاولة طالب')
        self.stdout.write(f'   ✅ تم إنشاء/تحديث {progress_created} تقدم طالب')

    def generate_student_answer(self, Chunk, is_correct):
        """إنشاء إجابة الطالب"""
        if Chunk.Chunk_type in ['multiple_choice', 'true_false']:
            if is_correct:
                return Chunk.correct_answer
            else:
                # إجابة خاطئة
                if Chunk.Chunk_type == 'true_false':
                    return 1 if Chunk.correct_answer == 0 else 0
                else:
                    wrong_answers = [i for i in range(len(Chunk.options)) if i != Chunk.correct_answer]
                    return random.choice(wrong_answers) if wrong_answers else 0
        
        elif Chunk.Chunk_type == 'fill_blank':
            if is_correct:
                return Chunk.correct_answer
            else:
                return 'إجابة خاطئة'
        
        elif Chunk.Chunk_type == 'matching':
            if is_correct:
                return Chunk.correct_answer
            else:
                return {'أ': '2', 'ب': '3', 'ج': '1'}  # مطابقة خاطئة
        
        else:
            return 'إجابة الطالب' if is_correct else 'إجابة غير صحيحة'

    def create_learning_analytics(self, students):
        """إنشاء تحليلات التعلم"""
        self.stdout.write('📈 جاري إنشاء تحليلات التعلم...')
        
        analytics_created = 0
        
        for student in students:
            # إنشاء تحليلات للـ 30 يوم الماضية
            for days_ago in range(30):
                date = (timezone.now() - timedelta(days=days_ago)).date()
                
                # محاولات الطالب في هذا اليوم
                daily_attempts = StudentAttempt.objects.filter(
                    student=student,
                    attempted_at__date=date
                )
                
                if daily_attempts.exists():
                    total_time = sum(attempt.time_taken for attempt in daily_attempts) // 60  # تحويل إلى دقائق
                    total_score = sum(attempt.score for attempt in daily_attempts)
                    
                    # تقدم الطالب في هذا اليوم
                    daily_progress = StudentProgress.objects.filter(
                        student=student,
                        last_accessed__date=date
                    )
                    
                    completed_units = daily_progress.filter(completion_percentage=100).count()
                    avg_mastery = daily_progress.aggregate(
                        avg=Avg('completion_percentage')
                    )['avg'] or 0
                    
                    LearningAnalytics.objects.create(
                        student=student,
                        date=date,
                        total_time_spent=total_time,
                        completed_units=completed_units,
                        total_score=total_score,
                        avg_mastery_level=avg_mastery
                    )
                    
                    analytics_created += 1
        
        self.stdout.write(f'   ✅ تم إنشاء {analytics_created} سجل تحليلات تعلم')

    def create_teacher_dashboards(self, teachers):
        """إنشاء لوحات تحكم المعلمين"""
        self.stdout.write('📋 جاري إنشاء لوحات تحكم المعلمين...')
        
        for teacher in teachers:
            teacher_units = Unit.objects.filter(created_by=teacher)
            
            if teacher_units.exists():
                # طلاب درسوا وحدات المعلم
                student_progress = StudentProgress.objects.filter(unit__in=teacher_units)
                unique_students = student_progress.values('student').distinct().count()
                
                # الطلاب النشطين في آخر 7 أيام
                last_week = timezone.now() - timedelta(days=7)
                active_students = student_progress.filter(
                    last_accessed__gte=last_week
                ).values('student').distinct().count()
                
                # حساب معدل التفاعل
                total_activities = sum(unit.activities.count() for unit in teacher_units)
                total_attempts = StudentAttempt.objects.filter(
                    Chunk__unit__in=teacher_units
                ).count()
                
                engagement_rate = (total_attempts / total_activities * 100) if total_activities > 0 else 0
                
                # متوسط تقدم الطلاب
                avg_progress = student_progress.aggregate(
                    avg=Avg('completion_percentage')
                )['avg'] or 0
                
                TeacherDashboard.objects.create(
                    teacher=teacher,
                    total_students=unique_students,
                    active_students=active_students,
                    total_units_created=teacher_units.count(),
                    student_engagement_rate=engagement_rate,
                    avg_student_progress=avg_progress,
                    last_updated=timezone.now()
                )
                
                self.stdout.write(f'   ✅ لوحة تحكم لـ {teacher.get_full_name()}: {unique_students} طالب')

    def create_system_logs(self, admin_user, teachers, students):
        """إنشاء سجلات النظام"""
        self.stdout.write('📝 جاري إنشاء سجلات النظام...')
        
        # سجلات معلومات
        for i in range(20):
            SystemLog.objects.create(
                level='info',
                category=random.choice(['user', 'content', 'system']),
                message=f'حدث نظام عادي #{i+1}: {self.get_random_log_message()}',
                user=random.choice([admin_user] + teachers + students) if random.random() > 0.3 else None,
                ip_address=f'192.168.1.{random.randint(1, 254)}',
                user_agent=self.get_random_user_agent(),
                created_at=timezone.now() - timedelta(days=random.randint(0, 30))
            )
        
        # سجلات تحذير
        for i in range(10):
            SystemLog.objects.create(
                level='warning',
                category=random.choice(['user', 'content']),
                message=f'تحذير #{i+1}: {self.get_warning_message()}',
                user=random.choice(teachers + students) if random.random() > 0.5 else None,
                ip_address=f'10.0.0.{random.randint(1, 254)}',
                user_agent=self.get_random_user_agent(),
                created_at=timezone.now() - timedelta(days=random.randint(0, 15))
            )
        
        # سجلات أمنية (فشل تسجيل دخول)
        for i in range(15):
            username = random.choice(['hacker', 'unknown', 'test', 'guest'])
            SystemLog.objects.create(
                level='security',
                category='user',
                message=f'فشل تسجيل الدخول للمستخدم: {username}',
                user=None,
                ip_address=f'203.0.113.{random.randint(1, 254)}',
                user_agent=self.get_random_user_agent(),
                created_at=timezone.now() - timedelta(days=random.randint(0, 7))
            )
        
        # سجلات أخطاء
        for i in range(5):
            SystemLog.objects.create(
                level='error',
                category='system',
                message=f'خطأ في النظام #{i+1}: {self.get_error_message()}',
                user=admin_user if random.random() > 0.7 else None,
                ip_address='127.0.0.1',
                user_agent='Django Server',
                created_at=timezone.now() - timedelta(days=random.randint(0, 3))
            )
        
        self.stdout.write(f'   ✅ تم إنشاء {SystemLog.objects.count()} سجل نظام')

    def get_random_log_message(self):
        """الحصول على رسالة سجل عشوائية"""
        messages = [
            'تم تسجيل دخول المستخدم',
            'تم إنشاء وحدة تعليمية جديدة',
            'تم تقديم نشاط بنجاح',
            'تم تحديث ملف المستخدم',
            'تم نشر وحدة تعليمية',
            'تم إنشاء تقرير تحليلي',
            'تم تصدير البيانات',
            'تم استيراد المحتوى',
            'تم إرسال إشعار',
            'تم تحديث النظام'
        ]
        return random.choice(messages)

    def get_warning_message(self):
        """الحصول على رسالة تحذير"""
        messages = [
            'محاولة وصول إلى صفحة غير مصرحة',
            'مستخدم حاول حذف محتوى بدون صلاحية',
            'محتوى لم يتم تحديثه منذ فترة طويلة',
            'عدد كبير من المحاولات الفاشلة',
            'مساحة التخزين تقترب من الحد الأقصى',
            'نسخة احتياطية قديمة',
            'مستخدم غير نشط لفترة طويلة',
            'تحميل ملف كبير الحجم'
        ]
        return random.choice(messages)

    def get_error_message(self):
        """الحصول على رسالة خطأ"""
        messages = [
            'فشل في الاتصال بقاعدة البيانات',
            'خطأ في معالجة الدفع',
            'فشل في إرسال البريد الإلكتروني',
            'خطأ في تحميل الملف',
            'تعارض في البيانات',
            'فشل في المصادقة',
            'خطأ في إنشاء النسخة الاحتياطية',
            'مشكلة في خدمة الطرف الثالث'
        ]
        return random.choice(messages)

    def get_random_user_agent(self):
        """الحصول على وكيل مستخدم عشوائي"""
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/537.36',
            'Mozilla/5.0 (Android 10; Mobile) AppleWebKit/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
            'PostmanRuntime/7.26.8',
            'curl/7.68.0'
        ]
        return random.choice(user_agents)

    def print_summary(self, admin_user, teachers, students, subjects, units, activities):
        """طباعة ملخص البيانات المنشأة"""
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS('📊 ملخص البيانات المنشأة:'))
        self.stdout.write('='*60)
        
        self.stdout.write(f'👑  المديرون: 1 (admin)')
        self.stdout.write(f'👨‍🏫  المعلمون: {len(teachers)}')
        self.stdout.write(f'👨‍🎓  الطلاب: {len(students)}')
        self.stdout.write(f'📚  المواد الدراسية: {len(subjects)}')
        self.stdout.write(f'📖  الوحدات التعليمية: {len(units)}')
        self.stdout.write(f'📄  أقسام المحتوى: {Lesson.objects.count()}')
        self.stdout.write(f'🎯  الأنشطة: {len(activities)}')
        self.stdout.write(f'📝  محاولات الطلاب: {StudentAttempt.objects.count()}')
        self.stdout.write(f'📊  تقدم الطلاب: {StudentProgress.objects.count()}')
        self.stdout.write(f'📈  تحليلات التعلم: {LearningAnalytics.objects.count()}')
        self.stdout.write(f'📋  لوحات تحكم المعلمين: {TeacherDashboard.objects.count()}')
        self.stdout.write(f'📝  سجلات النظام: {SystemLog.objects.count()}')
        
        self.stdout.write('\n🔑 بيانات الدخول الافتراضية:')
        self.stdout.write(f'   المدير: admin / Admin123!')
        self.stdout.write(f'   المعلمون: teacher_* / Teacher123!')
        self.stdout.write(f'   الطلاب: student_001 / Student123!')
        
        self.stdout.write('\n🌐 روابط مهمة:')
        self.stdout.write(f'   Admin Panel: http://localhost:8000/admin')
        self.stdout.write(f'   API Root: http://localhost:8000/api/')
        self.stdout.write(f'   API Auth: http://localhost:8000/api/auth/')
        
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS('✅ جاهز للاستخدام!'))
        self.stdout.write('='*60)