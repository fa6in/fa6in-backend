"""
assessment/path.py

Parcours de l'étudiant (écrans S1 "الرئيسية", S2 "مساري" et S3 "خريطة
المهارات" du design) : calcule, pour un étudiant et une matière, l'état de
chaque unité / leçon / skill à partir de StudentProgress et du calendrier.

Règles d'ouverture (progression par SEMAINE du programme) :
- Une leçon est ouverte dès que sa semaine (Lesson.week, sinon la plus
  petite de Lesson.programme_weeks) est atteinte : semaine <= semaine
  courante (AcademicYear.current_week). Elle n'attend PAS la fin de la
  leçon précédente : deux leçons de la même semaine, même dans deux
  unités différentes, sont ouvertes en même temps.
- Une leçon sans semaine renseignée, ou l'absence de calendrier configuré,
  ne verrouille rien.
- Une unité est ouverte dès qu'au moins une de ses leçons est ouverte.
- Toutes les skills d'une leçon ouverte sont ouvertes. Les prérequis non
  maîtrisés sont seulement signalés (missing_prerequisites) : c'est le
  Decision Engine qui y redirige l'étudiant s'il bloque
  (engine.find_prerequisite_redirect).
- "Terminée" = toutes les skills maîtrisées.
"""

from collections import defaultdict

from django.db.models import Q

from curriculum.models import AcademicYear, Goal, Lesson, Subject
from skills.models import Prerequisite, Skill
from users.models import StudentProfile
from .models import StudentProgress

MASTERED = StudentProgress.Status.MASTERED


def student_subjects(student):
    """
    Matières visibles par l'étudiant : celles de son année (StudentProfile.level)
    ou, à défaut, toutes les matières actives ayant au moins une unité publiée.
    """
    qs = Subject.objects.filter(is_active=True).select_related('level')
    level_id = (
        StudentProfile.objects.filter(user=student).values_list('level_id', flat=True).first()
    )
    if level_id:
        return qs.filter(level_id=level_id).order_by('name')
    return qs.filter(units__is_published=True).distinct().order_by('level__order_index', 'name')


def _skill_sort_key(skill):
    # Le conceptuel précède l'opérationnel dans une leçon (règle → application).
    return (
        skill.goal.goal_type != Goal.GoalType.CONCEPTUAL,
        skill.goal.order_index,
        skill.order_index,
        skill.id,
    )


def lesson_week(lesson):
    """Semaine d'ouverture d'une leçon (None si non renseignée)."""
    if lesson.week:
        return lesson.week
    weeks = []
    for w in lesson.programme_weeks or []:
        try:
            weeks.append(int(w))
        except (TypeError, ValueError):
            continue
    return min(weeks) if weeks else None


def lesson_is_open(lesson, current_week):
    week = lesson_week(lesson)
    return current_week is None or week is None or week <= current_week


def skill_is_open(skill, current_week=None):
    """Vrai si la leçon de la skill est ouverte à la semaine courante."""
    if current_week is None:
        current_week = AcademicYear.current_week()
    return lesson_is_open(skill.goal.lesson, current_week)


_UNSET = object()


def build_subject_path(student, subject, current_week=_UNSET):
    """
    Retourne la structure complète du parcours d'une matière :

    {
      'subject': Subject,
      'units': [{
          'unit': Unit, 'status': 'done'|'in_progress'|'available'|'locked',
          'locked_by_unit': None (conservé pour compatibilité),
          'week', 'next_opening_week', 'skills_total', 'skills_mastered',
          'lessons': [{
              'lesson': Lesson, 'status': 'done'|'current'|'locked', 'week', 'is_open',
              'skills_total', 'skills_mastered',
              'skills': [{'skill', 'progress', 'status', 'locked_by': [],
                          'missing_prerequisites': [Skill]}],
          }],
      }],
      'current_week': int|None,
    }

    Statut d'une skill : 'mastered' | 'in_progress' | 'available' | 'locked'.
    """
    units = list(subject.units.filter(is_published=True).order_by('order_index', 'id'))
    lessons = list(
        Lesson.objects.filter(unit__in=units, is_published=True).order_by('order_index', 'id')
    )
    if current_week is _UNSET:
        current_week = AcademicYear.current_week()
    skills = list(
        Skill.objects.filter(goal__lesson__in=lessons).select_related('goal', 'goal__lesson')
    )
    skill_ids = [s.id for s in skills]

    progress_by_skill = {
        p.skill_id: p
        for p in StudentProgress.objects.filter(student=student, skill_id__in=skill_ids)
    }
    prereqs_by_skill = defaultdict(list)
    for p in Prerequisite.objects.filter(skill_id__in=skill_ids).select_related('prerequisite'):
        prereqs_by_skill[p.skill_id].append(p.prerequisite)

    lessons_by_unit = defaultdict(list)
    for lesson in lessons:
        lessons_by_unit[lesson.unit_id].append(lesson)
    skills_by_lesson = defaultdict(list)
    for skill in sorted(skills, key=_skill_sort_key):
        skills_by_lesson[skill.goal.lesson_id].append(skill)

    def is_mastered(skill_id):
        p = progress_by_skill.get(skill_id)
        return bool(p and p.status == MASTERED)

    path_units = []
    for unit in units:
        unit_lessons = []
        for lesson in lessons_by_unit[unit.id]:
            week = lesson_week(lesson)
            lesson_open = lesson_is_open(lesson, current_week)
            lesson_skills = []
            for skill in skills_by_lesson[lesson.id]:
                progress = progress_by_skill.get(skill.id)
                missing = [pre for pre in prereqs_by_skill[skill.id] if not is_mastered(pre.id)]
                if progress and progress.status == MASTERED:
                    status = 'mastered'
                elif not lesson_open:
                    status = 'locked'
                elif progress and progress.attempts > 0:
                    status = 'in_progress'
                else:
                    status = 'available'
                lesson_skills.append({
                    'skill': skill, 'progress': progress, 'status': status,
                    'locked_by': [], 'missing_prerequisites': missing,
                })

            mastered = sum(1 for s in lesson_skills if s['status'] == 'mastered')
            lesson_done = mastered == len(lesson_skills)
            if lesson_done and lesson_open:
                lesson_status = 'done'
            elif lesson_open:
                lesson_status = 'current'
            else:
                lesson_status = 'locked'
            unit_lessons.append({
                'lesson': lesson, 'status': lesson_status, 'skills': lesson_skills,
                'skills_total': len(lesson_skills), 'skills_mastered': mastered,
                'week': week, 'is_open': lesson_open,
            })

        total = sum(l['skills_total'] for l in unit_lessons)
        mastered = sum(l['skills_mastered'] for l in unit_lessons)
        unit_open = not unit_lessons or any(l['is_open'] for l in unit_lessons)
        unit_done = bool(unit_lessons) and all(l['status'] == 'done' for l in unit_lessons)
        started = any(
            s['progress'] and s['progress'].attempts > 0
            for l in unit_lessons for s in l['skills']
        )
        if not unit_open:
            unit_status = 'locked'
        elif unit_done:
            unit_status = 'done'
        elif started or mastered:
            unit_status = 'in_progress'
        else:
            unit_status = 'available'

        weeks = [l['week'] for l in unit_lessons if l['week'] is not None]
        locked_weeks = [l['week'] for l in unit_lessons if not l['is_open'] and l['week'] is not None]
        path_units.append({
            'unit': unit, 'status': unit_status, 'lessons': unit_lessons,
            'locked_by_unit': None,
            'week': min(weeks) if weeks else None,
            'next_opening_week': min(locked_weeks) if locked_weeks else None,
            'skills_total': total, 'skills_mastered': mastered,
        })

    return {'subject': subject, 'units': path_units, 'current_week': current_week}


def iter_skills(path):
    """Parcourt les skills d'un parcours dans l'ordre pédagogique."""
    for u in path['units']:
        for l in u['lessons']:
            for s in l['skills']:
                yield u, l, s


def first_open_skill(path, exclude_skill_id=None):
    """Première skill ouverte et non maîtrisée, dans l'ordre du parcours."""
    for u, l, s in iter_skills(path):
        if s['status'] in ('available', 'in_progress') and s['skill'].id != exclude_skill_id:
            return u, l, s
    return None


def find_skill(path, skill_id):
    for u, l, s in iter_skills(path):
        if s['skill'].id == skill_id:
            return u, l, s
    return None


def subject_of_skill(skill):
    return skill.goal.lesson.unit.subject


def serialize_skill_entry(entry):
    skill, progress = entry['skill'], entry['progress']
    return {
        'id': skill.id,
        'code': skill.code,
        'name': skill.name,
        'skill_type': skill.skill_type,
        'status': entry['status'],
        'mastery': float(progress.mastery) if progress else 0.0,
        'attempts': progress.attempts if progress else 0,
        'mastery_threshold': skill.mastery_threshold,
        'locked_by': [{'id': s.id, 'code': s.code, 'name': s.name} for s in entry['locked_by']],
        'missing_prerequisites': [
            {'id': s.id, 'code': s.code, 'name': s.name} for s in entry.get('missing_prerequisites', [])
        ],
    }


def serialize_path(path):
    """Version JSON du parcours (écran S2) : unités + leçons, sans le détail des skills."""
    subject = path['subject']
    units = []
    for u in path['units']:
        unit = u['unit']
        units.append({
            'id': unit.id,
            'code': unit.code,
            'title': unit.title,
            'central_question': unit.central_question,
            'thumbnail': unit.thumbnail.url if unit.thumbnail else None,
            'status': u['status'],
            'week': u['week'],
            'next_opening_week': u['next_opening_week'],
            'skills_total': u['skills_total'],
            'skills_mastered': u['skills_mastered'],
            'progress': round(u['skills_mastered'] / u['skills_total'], 2) if u['skills_total'] else 0.0,
            'locked_by_unit': (
                {'id': u['locked_by_unit'].id, 'code': u['locked_by_unit'].code}
                if u['locked_by_unit'] else None
            ),
            'lessons': [
                {
                    'id': l['lesson'].id,
                    'code': l['lesson'].code,
                    'title': l['lesson'].title,
                    'status': l['status'],
                    'week': l['week'],
                    'skills_total': l['skills_total'],
                    'skills_mastered': l['skills_mastered'],
                }
                for l in u['lessons']
            ],
        })
    return {
        'subject': {
            'id': subject.id, 'name': subject.name, 'color': subject.color, 'icon': subject.icon,
            'level_name': subject.level.name,
        },
        'units': units,
        'current_week': path.get('current_week'),
    }


def subjects_with_skills_query(student):
    """Skills (toutes matières confondues) du contenu publié visible par l'étudiant."""
    subjects = student_subjects(student)
    return Skill.objects.filter(
        Q(goal__lesson__is_published=True)
        & Q(goal__lesson__unit__is_published=True)
        & Q(goal__lesson__unit__subject__in=subjects)
    )
