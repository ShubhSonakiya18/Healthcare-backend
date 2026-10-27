"""Mapping URLs, mounted at /api/mappings/ in config/urls.py."""

from django.urls import path

from .views import MappingDetailView, MappingListCreateView

urlpatterns = [
    path("", MappingListCreateView.as_view(), name="mapping-list"),
    # One route for both GET (patient id) and DELETE (mapping id): Django
    # matches URLs by path only, never by HTTP method.
    path("<int:pk>/", MappingDetailView.as_view(), name="mapping-detail"),
]
