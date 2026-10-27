"""Patient endpoints. Every query is filtered by the logged-in user."""

from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated

from .models import Patient
from .permissions import IsPatientOwner
from .serializers import PatientSerializer


class PatientListCreateView(ListCreateAPIView):
    """GET /api/patients/ → 200 with the caller's patients only, ordered by id.
    POST /api/patients/ → 201 with the new patient, owned by the caller.

    Any logged-in user (the global IsAuthenticated default).
    """

    serializer_class = PatientSerializer

    def get_queryset(self):
        return Patient.objects.filter(created_by=self.request.user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class PatientDetailView(RetrieveUpdateDestroyAPIView):
    """GET, PUT and DELETE /api/patients/<id>/, for the patient's owner only.

    Another user's patient isn't in the queryset, so it gets the same 404 as
    an id that doesn't exist: the response reveals nothing.
    PUT → 200, DELETE → 204, PATCH → 405.
    """

    serializer_class = PatientSerializer
    permission_classes = [IsAuthenticated, IsPatientOwner]
    http_method_names = ["get", "put", "delete", "head", "options"]

    def get_queryset(self):
        return Patient.objects.filter(created_by=self.request.user)
