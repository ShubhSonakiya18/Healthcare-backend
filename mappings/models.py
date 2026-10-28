"""Assignments of doctors to patients."""

from django.db import models

from doctors.models import Doctor
from patients.models import Patient


class PatientDoctorMapping(models.Model):
    """One doctor assigned to one patient. Each pair can exist only once.

    There is no `created_by`: only a patient's owner can create its mappings,
    so the owner is always `patient.created_by`.
    """

    # CASCADE: an assignment without its patient means nothing.
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="doctor_mappings")
    # PROTECT: deleting a doctor must never silently remove other users'
    # assignments. DoctorDetailView turns the refusal into a 409.
    doctor = models.ForeignKey(Doctor, on_delete=models.PROTECT, related_name="patient_mappings")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # The database's guarantee that a pair exists only once, even when
        # two identical requests arrive at the same moment.
        constraints = [
            models.UniqueConstraint(fields=["patient", "doctor"], name="unique_patient_doctor")
        ]
        ordering = ["id"]

    def __str__(self):
        return f"{self.patient} → {self.doctor}"
