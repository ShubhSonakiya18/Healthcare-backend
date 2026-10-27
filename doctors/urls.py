"""Doctor URLs, mounted at /api/doctors/ in config/urls.py."""

from django.urls import path

from .views import DoctorDetailView, DoctorListCreateView

urlpatterns = [
    path("", DoctorListCreateView.as_view(), name="doctor-list"),
    path("<int:pk>/", DoctorDetailView.as_view(), name="doctor-detail"),
]
