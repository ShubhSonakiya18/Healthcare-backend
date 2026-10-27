"""Patient URLs, mounted at /api/patients/ in config/urls.py."""

from django.urls import path

from .views import PatientDetailView, PatientListCreateView

urlpatterns = [
    path("", PatientListCreateView.as_view(), name="patient-list"),
    path("<int:pk>/", PatientDetailView.as_view(), name="patient-detail"),
]
