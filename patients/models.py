"""Patient records, each private to the user who created it."""

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models


class Patient(models.Model):
    """A patient record. Only the user in `created_by` can see or change it.

    Deliberately minimal: no diagnoses, medical history or ID numbers.
    """

    class Gender(models.TextChoices):
        MALE = "male", "Male"
        FEMALE = "female", "Female"
        OTHER = "other", "Other"

    # CASCADE: patients are private to their creator, so they go when the
    # user goes.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="patients"
    )
    name = models.CharField(max_length=150)
    # A date of birth instead of an age, because an age goes out of date.
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=10, choices=Gender.choices, blank=True)
    phone = models.CharField(
        max_length=16,
        blank=True,
        validators=[
            RegexValidator(r"^\+?[0-9]{7,15}$", "Enter 7–15 digits, optionally starting with +.")
        ],
    )
    address = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name
