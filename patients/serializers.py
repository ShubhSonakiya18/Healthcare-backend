"""Patient serializer."""

from django.utils import timezone
from rest_framework import serializers

from .models import Patient


class PatientSerializer(serializers.ModelSerializer):
    """Converts patients to JSON and validates incoming data.

    `created_by` is deliberately not a field: the view sets it from the
    token's user, so a client can neither set it nor see it.
    """

    class Meta:
        model = Patient
        fields = [
            "id",
            "name",
            "date_of_birth",
            "gender",
            "phone",
            "address",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_date_of_birth(self, value):
        # Today is allowed; tomorrow isn't. "Today" is the date in TIME_ZONE (UTC).
        if value > timezone.localdate():
            raise serializers.ValidationError("Date of birth cannot be in the future.")
        return value
