# assessment/student_urls.py
#
# Endpoints "intelligents" du Decision Engine, montés sous /api/students/
# (Revue de l'API REST, Problèmes 1, 2 et 3), et parcours de l'étudiant
# (écrans S1, S2, S3 et S8 du design).

from django.urls import path
from .views import (
    SubmitAnswerView,
    NextActionView,
    StudentHomeView,
    StudentPathView,
    StudentSkillMapView,
    StudentProgressSummaryView,
)

urlpatterns = [
    path('<int:student_id>/answer/', SubmitAnswerView.as_view(), name='student-submit-answer'),
    path('<int:student_id>/next-action/', NextActionView.as_view(), name='student-next-action'),
    path('<int:student_id>/home/', StudentHomeView.as_view(), name='student-home'),
    path('<int:student_id>/path/', StudentPathView.as_view(), name='student-path'),
    path('<int:student_id>/skill-map/', StudentSkillMapView.as_view(), name='student-skill-map'),
    path('<int:student_id>/progress-summary/', StudentProgressSummaryView.as_view(), name='student-progress-summary'),
]
