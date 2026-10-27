"""Doctor endpoints: a directory shared by all users, editable only by each doctor's creator."""

from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated

from .models import Doctor
from .permissions import IsCreatorOrReadOnly
from .serializers import DoctorSerializer


class DoctorInUse(APIException):
    """409 Conflict: the doctor is still assigned to at least one patient.

    The message says that assignments exist, never whose they are.
    """

    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        "This doctor is assigned to one or more patients. "
        "Remove those assignments before deleting the doctor."
    )
    default_code = "doctor_in_use"


class DoctorListCreateView(ListCreateAPIView):
    """GET /api/doctors/ → 200 with every doctor, whoever added them, ordered by id.
    POST /api/doctors/ → 201 with the new doctor, recorded as added by the caller.

    Any logged-in user (the global IsAuthenticated default).
    """

    queryset = Doctor.objects.all()
    serializer_class = DoctorSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class DoctorDetailView(RetrieveUpdateDestroyAPIView):
    """GET /api/doctors/<id>/ → 200 for any logged-in user.
    PUT → 200 and DELETE → 204 for the doctor's creator; 403 for anyone else.
    DELETE → 409 while the doctor is assigned to any patient.
    PATCH → 405.
    """

    queryset = Doctor.objects.all()
    serializer_class = DoctorSerializer
    permission_classes = [IsAuthenticated, IsCreatorOrReadOnly]
    http_method_names = ["get", "put", "delete", "head", "options"]

    def perform_destroy(self, instance):
        # PatientDoctorMapping.doctor uses PROTECT, so Django refuses the
        # delete before removing anything; nothing is half-deleted.
        try:
            instance.delete()
        except ProtectedError:
            raise DoctorInUse()
