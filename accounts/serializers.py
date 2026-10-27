"""Registration and login serializers."""

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework.validators import UniqueValidator
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()

DUPLICATE_EMAIL = "A user with this email already exists."


class RegisterSerializer(serializers.ModelSerializer):
    """Validates `{name, email, password}` and creates the user.

    The response contains only `id`, `name` and `email`: the password is
    write-only and never comes back out.
    """

    # DRF runs field validators (including UniqueValidator) before
    # validate_email() lower-cases the value, so the uniqueness check itself
    # must ignore case: that is what lookup="iexact" does.
    email = serializers.EmailField(
        max_length=254,
        validators=[
            UniqueValidator(
                queryset=User.objects.all(),
                lookup="iexact",
                message=DUPLICATE_EMAIL,
            )
        ],
    )
    # trim_whitespace=False: a password is used exactly as typed.
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    class Meta:
        model = User
        fields = ["id", "name", "email", "password"]
        read_only_fields = ["id"]

    def validate_email(self, value):
        return User.objects.normalize_email(value)

    def validate(self, attrs):
        # Django's password validators compare the password with the user's
        # email and name, so give them an unsaved User holding those values.
        candidate = User(email=attrs["email"], name=attrs["name"])
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs

    def create(self, validated_data):
        # Two identical registrations at the same moment can both pass the
        # UniqueValidator; the database's unique index then rejects the second.
        # The savepoint keeps the connection usable so we can return a 400.
        try:
            with transaction.atomic():
                return User.objects.create_user(**validated_data)
        except IntegrityError:
            raise serializers.ValidationError({"email": [DUPLICATE_EMAIL]})


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """SimpleJWT's login serializer, plus email normalisation.

    The field is called `email` because SimpleJWT reads USERNAME_FIELD.
    Lower-casing first lets `Asha@Example.com` log in to the account stored
    as `asha@example.com`.
    """

    def validate(self, attrs):
        attrs[self.username_field] = User.objects.normalize_email(attrs[self.username_field])
        return super().validate(attrs)
