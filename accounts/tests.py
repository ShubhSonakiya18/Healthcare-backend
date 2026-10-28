"""Tests for the custom user model, registration, login and token refresh.

Two kinds of test class live here:

* `SimpleTestCase` / `APISimpleTestCase` classes never touch a database.
  Django refuses any query they attempt, so they can run before PostgreSQL
  is set up (`python manage.py test accounts.tests.<ClassName>`).
* `TestCase` / `APITestCase` classes need PostgreSQL.

Run everything with: python manage.py test accounts
"""

from datetime import timedelta
from io import StringIO
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.test import APIRequestFactory, APISimpleTestCase, APITestCase
from rest_framework.validators import UniqueValidator
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from .views import RegisterView

User = get_user_model()

NAME = "Asha Verma"
EMAIL = "asha.verma@example.com"
PASSWORD = "Clinic-Pass-2026"

REGISTER_URL = reverse("auth-register")
LOGIN_URL = reverse("auth-login")
REFRESH_URL = reverse("auth-token-refresh")


def authenticate_bearer(access_token):
    """Authenticate a request carrying the token, exactly as protected views will.

    It calls SimpleJWT's JWTAuthentication (our DEFAULT_AUTHENTICATION_CLASSES)
    directly, so the token check is tested without going through a view.
    """
    request = APIRequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {access_token}")
    return JWTAuthentication().authenticate(request)


def tamper(token):
    """Change the last characters of the signature, keeping the token's shape."""
    return token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")


def unsaved_user(**fields):
    """An in-memory User for tests that must not touch the database."""
    return User(id=1, email=EMAIL, name=NAME, **fields)


# ---------------------------------------------------------------------------
# No database needed
# ---------------------------------------------------------------------------


class UserModelDefinitionTests(SimpleTestCase):
    def test_auth_user_model_is_the_custom_user(self):
        self.assertEqual(settings.AUTH_USER_MODEL, "accounts.User")
        self.assertEqual(User._meta.label, "accounts.User")
        self.assertEqual(User.USERNAME_FIELD, "email")
        self.assertEqual(User.REQUIRED_FIELDS, ["name"])

    def test_unused_abstractuser_fields_are_removed(self):
        for field in ("username", "first_name", "last_name"):
            with self.subTest(field=field), self.assertRaises(FieldDoesNotExist):
                User._meta.get_field(field)

    def test_email_is_declared_unique(self):
        # The database constraint itself is tested in UserManagerTests.
        self.assertTrue(User._meta.get_field("email").unique)

    def test_meta_keeps_inherited_names_and_sets_ordering(self):
        self.assertEqual(User._meta.ordering, ["id"])
        self.assertEqual(User._meta.verbose_name, "user")
        self.assertFalse(User._meta.abstract)

    def test_display_methods_use_email_and_name(self):
        user = unsaved_user()
        self.assertEqual(str(user), EMAIL)
        self.assertEqual(user.get_full_name(), NAME)
        self.assertEqual(user.get_short_name(), NAME)


class UserManagerUnitTests(SimpleTestCase):
    def test_normalize_email_trims_and_lower_cases_the_whole_address(self):
        self.assertEqual(User.objects.normalize_email("  Asha.Verma@EXAMPLE.com "), EMAIL)
        self.assertEqual(User.objects.normalize_email(None), "")

    def test_get_by_natural_key_normalises_before_the_lookup(self):
        with mock.patch.object(BaseUserManager, "get_by_natural_key") as base_lookup:
            User.objects.get_by_natural_key("  Asha.Verma@Example.COM ")
        base_lookup.assert_called_once_with(EMAIL)

    def test_create_user_requires_email_and_name(self):
        # Both checks run before anything is saved.
        with self.assertRaises(ValueError):
            User.objects.create_user(email="   ", password=PASSWORD, name=NAME)
        with self.assertRaises(ValueError):
            User.objects.create_user(email=EMAIL, password=PASSWORD, name="   ")

    def test_create_superuser_rejects_non_admin_flags(self):
        with self.assertRaises(ValueError):
            User.objects.create_superuser(email=EMAIL, password=PASSWORD, name=NAME, is_staff=False)
        with self.assertRaises(ValueError):
            User.objects.create_superuser(email=EMAIL, password=PASSWORD, name=NAME, is_superuser=False)


class PasswordPolicyTests(SimpleTestCase):
    """Django's validators, checked by error code rather than wording."""

    def error_codes(self, password, user):
        try:
            validate_password(password, user=user)
        except ValidationError as exc:
            return {error.code for error in exc.error_list}
        return set()

    def test_all_four_validators_are_enabled(self):
        names = [v["NAME"].rsplit(".", 1)[1] for v in settings.AUTH_PASSWORD_VALIDATORS]
        self.assertEqual(
            names,
            [
                "UserAttributeSimilarityValidator",
                "MinimumLengthValidator",
                "CommonPasswordValidator",
                "NumericPasswordValidator",
            ],
        )
        self.assertEqual(
            settings.AUTH_PASSWORD_VALIDATORS[0]["OPTIONS"], {"user_attributes": ("email", "name")}
        )

    def test_weak_passwords_fail_for_the_expected_reason(self):
        cases = {
            "Ab1-xyz": "password_too_short",
            "password": "password_too_common",
            "73946205": "password_entirely_numeric",
            EMAIL: "password_too_similar",
            "AshaVerma1": "password_too_similar",
        }
        for password, code in cases.items():
            with self.subTest(password=password):
                self.assertIn(code, self.error_codes(password, unsaved_user()))

    def test_similarity_to_the_name_is_what_rejects_ashaverma1(self):
        # Django's default attributes don't include `name`; ours do. With a
        # different name the same password is accepted, so the name is the reason.
        self.assertEqual(self.error_codes("AshaVerma1", unsaved_user()), {"password_too_similar"})
        other = User(id=2, email="someone@example.com", name="Ravi Kumar")
        self.assertEqual(self.error_codes("AshaVerma1", other), set())

    def test_a_strong_password_passes(self):
        self.assertEqual(self.error_codes(PASSWORD, unsaved_user()), set())


class RegisterEndpointWithoutDatabaseTests(APISimpleTestCase):
    """Requests whose body fails field validation never reach the database."""

    def test_register_is_public_and_ignores_the_authorization_header(self):
        self.assertEqual(RegisterView.authentication_classes, [])
        self.assertEqual(RegisterView.permission_classes, [AllowAny])

    def test_invalid_bearer_token_does_not_cause_a_401(self):
        # Regression test: before the fix this was a
        # 401 token_not_valid from JWT authentication.
        self.client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
        response = self.client.post(REGISTER_URL, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(set(response.data), {"name", "email", "password"})

    def test_missing_fields_are_listed(self):
        response = self.client.post(REGISTER_URL, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(set(response.data), {"name", "email", "password"})

    def test_get_is_not_allowed(self):
        response = self.client.get(REGISTER_URL)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class TokenWithoutDatabaseTests(APISimpleTestCase):
    """Token lifetimes and rejection, with a token for an unsaved user."""

    def test_refresh_token_lasts_one_day_and_access_token_30_minutes(self):
        refresh = RefreshToken.for_user(unsaved_user())
        # iat and exp are each rounded down to whole seconds, so allow 1 s.
        self.assertAlmostEqual(refresh["exp"] - refresh["iat"], 24 * 60 * 60, delta=1)
        access = refresh.access_token
        self.assertAlmostEqual(access["exp"] - access["iat"], 30 * 60, delta=1)

    def test_tampered_refresh_token_is_rejected(self):
        tampered = tamper(str(RefreshToken.for_user(unsaved_user())))
        with self.assertRaises(TokenError):
            RefreshToken(tampered)
        # The refresh view rejects it while decoding, before any user lookup.
        response = self.client.post(REFRESH_URL, {"refresh": tampered})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "token_not_valid")

    def test_expired_refresh_token_is_rejected(self):
        refresh = RefreshToken.for_user(unsaved_user())
        refresh.set_exp(lifetime=timedelta(seconds=-1))
        response = self.client.post(REFRESH_URL, {"refresh": str(refresh)})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "token_not_valid")

    def test_missing_refresh_field_is_400(self):
        response = self.client.post(REFRESH_URL, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_with_a_missing_field_is_400(self):
        response = self.client.post(LOGIN_URL, {"email": EMAIL})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)


# ---------------------------------------------------------------------------
# PostgreSQL needed
# ---------------------------------------------------------------------------


class UserManagerTests(TestCase):
    def test_create_user_normalises_email_and_hashes_password(self):
        user = User.objects.create_user(email="  Asha.Verma@Example.COM ", password=PASSWORD, name=NAME)
        self.assertEqual(user.email, EMAIL)
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.password.startswith("pbkdf2_sha256$"))
        self.assertTrue(user.check_password(PASSWORD))
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_user_without_password_gets_an_unusable_password(self):
        user = User.objects.create_user(email=EMAIL, name=NAME)
        self.assertFalse(user.has_usable_password())

    def test_create_superuser_sets_admin_flags(self):
        admin = User.objects.create_superuser(email="admin@example.com", password=PASSWORD, name="Admin")
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)

    def test_database_rejects_a_duplicate_email_in_another_letter_case(self):
        User.objects.create_user(email=EMAIL, password=PASSWORD, name=NAME)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            User.objects.create_user(email="ASHA.VERMA@example.com", password=PASSWORD, name="Copy")
        self.assertEqual(User.objects.count(), 1)

    def test_lookup_by_email_ignores_case_and_whitespace(self):
        user = User.objects.create_user(email=EMAIL, password=PASSWORD, name=NAME)
        self.assertEqual(User.objects.get_by_natural_key("  Asha.Verma@EXAMPLE.com "), user)

    def test_createsuperuser_command_normalises_and_refuses_a_case_variant(self):
        call_command(
            "createsuperuser", interactive=False, email="Admin@Example.COM", name="Admin", stdout=StringIO()
        )
        admin = User.objects.get()
        self.assertEqual(admin.email, "admin@example.com")
        self.assertTrue(admin.is_staff and admin.is_superuser)

        with self.assertRaisesMessage(CommandError, "already taken"):
            call_command(
                "createsuperuser", interactive=False, email="ADMIN@example.com", name="Twin", stdout=StringIO()
            )
        self.assertEqual(User.objects.count(), 1)


class RegisterTests(APITestCase):
    def register(self, **overrides):
        data = {"name": NAME, "email": EMAIL, "password": PASSWORD, **overrides}
        return self.client.post(REGISTER_URL, data)

    def test_register_returns_201_with_id_name_email_only(self):
        response = self.register()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get()
        self.assertEqual(response.data, {"id": user.id, "name": NAME, "email": EMAIL})

    def test_password_is_stored_only_as_a_hash(self):
        self.register()
        user = User.objects.get()
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))

    def test_password_never_appears_in_the_response(self):
        response = self.register()
        self.assertNotIn("password", response.data)
        self.assertNotIn(PASSWORD, response.content.decode())

    def test_email_is_trimmed_and_lower_cased(self):
        response = self.register(email="  Asha.Verma@Example.com  ")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["email"], EMAIL)

    def test_duplicate_email_in_another_letter_case_is_rejected(self):
        self.register(email="Asha.Verma@Example.com")
        response = self.register(email=EMAIL)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["email"], ["A user with this email already exists."])
        self.assertEqual(User.objects.count(), 1)

    def test_duplicate_that_slips_past_the_validator_still_gets_a_400(self):
        # Simulates two simultaneous registrations: the UniqueValidator check
        # passes (patched out), so only the database's unique index stops the
        # second insert. create() must turn that IntegrityError into a 400.
        User.objects.create_user(email=EMAIL, password=PASSWORD, name=NAME)
        with mock.patch.object(UniqueValidator, "__call__", autospec=True, return_value=None) as check:
            response = self.register(email="ASHA.VERMA@example.com")
        self.assertTrue(check.called)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["email"], ["A user with this email already exists."])
        self.assertEqual(User.objects.count(), 1)

    def test_privilege_fields_in_the_body_are_ignored(self):
        response = self.register(is_staff=True, is_superuser=True, is_active=False)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get()
        self.assertEqual(response.data, {"id": user.id, "name": NAME, "email": EMAIL})
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.is_active)

    def test_invalid_bearer_token_does_not_block_a_valid_registration(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
        response = self.register()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_invalid_email_is_rejected(self):
        response = self.register(email="not-an-email")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)

    def test_blank_or_whitespace_name_is_rejected(self):
        for name in ("", "   "):
            with self.subTest(name=repr(name)):
                response = self.register(name=name)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("name", response.data)
        self.assertFalse(User.objects.exists())

    def test_weak_password_is_rejected_through_the_api(self):
        # Which validator fires is covered in PasswordPolicyTests; this proves
        # the serializer passes the user's name and email to the validators.
        for password in ("Ab1-xyz", "AshaVerma1"):
            with self.subTest(password=password):
                response = self.register(password=password)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("password", response.data)
        self.assertFalse(User.objects.exists())


class LoginTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email=EMAIL, password=PASSWORD, name=NAME)

    def login(self, email=EMAIL, password=PASSWORD):
        return self.client.post(LOGIN_URL, {"email": email, "password": password})

    def test_correct_credentials_return_access_and_refresh(self):
        response = self.login()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data), {"access", "refresh"})

    def test_email_letter_case_and_whitespace_do_not_matter(self):
        response = self.login(email="  Asha.Verma@EXAMPLE.com ")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_failed_logins_all_get_the_same_401(self):
        inactive = User.objects.create_user(
            email="inactive@example.com", password=PASSWORD, name="Off", is_active=False
        )
        attempts = {
            "wrong password": (EMAIL, "Wrong-Pass-2026"),
            "unknown email": ("nobody@example.com", PASSWORD),
            "inactive user": (inactive.email, PASSWORD),
        }
        for reason, (email, password) in attempts.items():
            with self.subTest(reason):
                response = self.login(email=email, password=password)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
                self.assertEqual(
                    response.data["detail"], "No active account found with the given credentials"
                )

    def test_issued_access_token_lasts_30_minutes(self):
        access = AccessToken(self.login().data["access"])
        self.assertAlmostEqual(access["exp"] - access["iat"], 30 * 60, delta=1)


class RealJwtFlowTests(APITestCase):
    """End to end through our own endpoints, with no force_authenticate."""

    def login(self):
        User.objects.create_user(email=EMAIL, password=PASSWORD, name=NAME)
        return self.client.post(LOGIN_URL, {"email": EMAIL, "password": PASSWORD}).data

    def test_register_login_then_authenticate_with_the_bearer_token(self):
        register = self.client.post(REGISTER_URL, {"name": NAME, "email": EMAIL, "password": PASSWORD})
        self.assertEqual(register.status_code, status.HTTP_201_CREATED)

        login = self.client.post(LOGIN_URL, {"email": EMAIL, "password": PASSWORD})
        self.assertEqual(login.status_code, status.HTTP_200_OK)

        user, _ = authenticate_bearer(login.data["access"])
        self.assertEqual(user.id, register.data["id"])
        self.assertEqual(user.email, EMAIL)

    def test_refresh_token_is_not_accepted_as_a_bearer_token(self):
        with self.assertRaises(InvalidToken):
            authenticate_bearer(self.login()["refresh"])

    def test_tampered_access_token_is_rejected(self):
        with self.assertRaises(InvalidToken):
            authenticate_bearer(tamper(self.login()["access"]))

    def test_token_of_a_user_deactivated_after_login_is_rejected(self):
        access = self.login()["access"]
        User.objects.filter(email=EMAIL).update(is_active=False)
        with self.assertRaises(AuthenticationFailed):
            authenticate_bearer(access)


class TokenRefreshTests(APITestCase):
    def setUp(self):
        User.objects.create_user(email=EMAIL, password=PASSWORD, name=NAME)
        self.tokens = self.client.post(LOGIN_URL, {"email": EMAIL, "password": PASSWORD}).data

    def test_valid_refresh_token_returns_a_new_access_token(self):
        response = self.client.post(REFRESH_URL, {"refresh": self.tokens["refresh"]})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # No rotation, so only a new access token comes back.
        self.assertEqual(set(response.data), {"access"})
        user, _ = authenticate_bearer(response.data["access"])
        self.assertEqual(user.email, EMAIL)

    def test_access_token_sent_to_refresh_is_401(self):
        response = self.client.post(REFRESH_URL, {"refresh": self.tokens["access"]})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "token_not_valid")
