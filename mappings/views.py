"""Mapping endpoints. Every query is limited to the caller's patients."""

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.generics import ListCreateAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from patients.models import Patient

from .models import PatientDoctorMapping
from .serializers import DUPLICATE_ASSIGNMENT, PatientDoctorMappingSerializer


class MappingListCreateView(ListCreateAPIView):
    """GET /api/mappings/ → 200 with the mappings of the caller's patients only, ordered by id.
    POST /api/mappings/ → 201, assigning any doctor to one of the caller's patients;
    400 if the patient isn't theirs, the doctor doesn't exist or the pair already exists.

    Any logged-in user (the global IsAuthenticated default).
    """

    serializer_class = PatientDoctorMappingSerializer

    def get_queryset(self):
        # select_related fetches each mapping's patient and doctor in the same
        # query, so the list costs one query however long it is (no N+1).
        return PatientDoctorMapping.objects.filter(
            patient__created_by=self.request.user
        ).select_related("patient", "doctor")

    def perform_create(self, serializer):
        # Two identical requests at the same moment can both pass the
        # serializer's duplicate check; the database constraint then rejects
        # the second. The savepoint keeps the connection usable.
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            raise serializers.ValidationError({"non_field_errors": [DUPLICATE_ASSIGNMENT]})


class MappingDetailView(APIView):
    """One URL, two meanings. The number is a PATIENT id for GET
    and a MAPPING id for DELETE, exactly as the assignment defines the routes.

    GET /api/mappings/<patient_id>/ → 200 with that patient's mappings, each
    with the doctor's details and the mapping id DELETE needs; [] if none.
    DELETE /api/mappings/<mapping_id>/ → 204.
    Both → 404 if the patient or mapping doesn't exist or isn't the caller's.
    Any other method → 405. Any logged-in user (global IsAuthenticated).
    """

    def get(self, request, pk):
        # pk is a PATIENT id.
        patient = get_object_or_404(Patient, pk=pk, created_by=request.user)
        mappings = patient.doctor_mappings.select_related("doctor")
        serializer = PatientDoctorMappingSerializer(mappings, many=True, context={"request": request})
        return Response(serializer.data)

    def delete(self, request, pk):
        # pk is a MAPPING id.
        mapping = get_object_or_404(PatientDoctorMapping, pk=pk, patient__created_by=request.user)
        mapping.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
