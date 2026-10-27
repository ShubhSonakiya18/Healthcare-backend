"""Doctor endpoints: a directory shared by all users, editable only by each doctor's creator."""

from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated

from .models import Doctor
from .permissions import IsCreatorOrReadOnly
from .serializers import DoctorSerializer


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
    PATCH → 405.
    """

    queryset = Doctor.objects.all()
    serializer_class = DoctorSerializer
    permission_classes = [IsAuthenticated, IsCreatorOrReadOnly]
    http_method_names = ["get", "put", "delete", "head", "options"]
