"""Mapping serializer."""

from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from doctors.serializers import DoctorSerializer
from patients.models import Patient

from .models import PatientDoctorMapping

DUPLICATE_ASSIGNMENT = "This doctor is already assigned to this patient."


class PatientDoctorMappingSerializer(serializers.ModelSerializer):
    """The mapping object returned by every mapping endpoint.

    `patient` and `doctor` are written as ids. `patient_name` and the nested
    `doctor_detail` are read-only extras, so a client needs no second call.
    """

    patient_name = serializers.CharField(source="patient.name", read_only=True)
    doctor_detail = DoctorSerializer(source="doctor", read_only=True)

    class Meta:
        model = PatientDoctorMapping
        fields = ["id", "patient", "patient_name", "doctor", "doctor_detail", "created_at"]
        read_only_fields = ["id", "created_at"]
        # Declared explicitly so the rule and its message are visible here;
        # the database's unique_patient_doctor constraint backs it up.
        validators = [
            UniqueTogetherValidator(
                queryset=PatientDoctorMapping.objects.all(),
                fields=["patient", "doctor"],
                message=DUPLICATE_ASSIGNMENT,
            )
        ]

    def get_fields(self):
        fields = super().get_fields()
        # Only the caller's own patients can be chosen. Another user's patient
        # then gets exactly the same "Invalid pk" error as an id that doesn't
        # exist, so the response reveals nothing. Any doctor in the
        # shared directory can be chosen.
        user = self.context["request"].user
        fields["patient"].queryset = Patient.objects.filter(created_by=user)
        return fields
