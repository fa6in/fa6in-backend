# assessment/student_urls.py
#
# Endpoints "intelligents" du Decision Engine, montés sous /api/students/
# (Revue de l'API REST, Problèmes 1, 2 et 3).

from django.urls import path
from .views import SubmitAnswerView, NextActionView

urlpatterns = [
    path('<int:student_id>/answer/', SubmitAnswerView.as_view(), name='student-submit-answer'),
    path('<int:student_id>/next-action/', NextActionView.as_view(), name='student-next-action'),
]
