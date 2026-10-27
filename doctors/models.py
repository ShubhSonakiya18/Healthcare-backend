"""The shared doctor directory."""

from django.conf import settings
from django.db import models


class Doctor(models.Model):
    """A doctor in the directory every user can see. Only `created_by` may change it."""

    # SET_NULL: the shared directory keeps a doctor when the user who added
    # it is deleted; the doctor then becomes read-only through the API.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="doctors"
    )
    name = models.CharField(max_length=150)
    specialization = models.CharField(max_length=100)
    # Stored trimmed and lower-case (see DoctorSerializer); unique=True also
    # gives PostgreSQL a unique index, so no doctor is listed twice.
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name
