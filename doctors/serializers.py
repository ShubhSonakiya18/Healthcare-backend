"""Doctor serializer."""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import Doctor

DUPLICATE_EMAIL = "A doctor with this email already exists."


class DoctorSerializer(serializers.ModelSerializer):
    """Converts doctors to JSON and validates incoming data.

    `created_by` is deliberately not a field: the view sets it from the
    token's user, so a client can neither set it nor see it.
    """

    # lookup="iexact" because DRF runs this validator before validate_email()
    # lower-cases the value (same reasoning as for user emails).
    email = serializers.EmailField(
        max_length=254,
        validators=[
            UniqueValidator(queryset=Doctor.objects.all(), lookup="iexact", message=DUPLICATE_EMAIL)
        ],
    )

    class Meta:
        model = Doctor
        fields = ["id", "name", "specialization", "email", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_email(self, value):
        # The same normalisation as user emails: trim and lower-case it all.
        return get_user_model().objects.normalize_email(value)

    def save(self, **kwargs):
        # Two requests adding the same email at the same moment can both pass
        # the UniqueValidator; the database's unique index then rejects the
        # second. The savepoint keeps the connection usable for a clean 400.
        try:
            with transaction.atomic():
                return super().save(**kwargs)
        except IntegrityError:
            raise serializers.ValidationError({"email": [DUPLICATE_EMAIL]})
