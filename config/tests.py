"""Project-wide behaviour: error responses, the token lifecycle,
server-error logging, what responses expose, and the settings helpers.

Run with: python manage.py test config   (`python manage.py test` runs everything)
"""

import io
import logging
import os
from datetime import date, timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings
from django.urls import path, reverse
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.test import APITestCase
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import AccessToken

from config import settings as project_settings
from config import urls as project_urls
from doctors.models import Doctor
from patients.models import Patient

User = get_user_model()

PASSWORD = "Clinic-Pass-2026"


class CrashView(APIView):
    """Fails on purpose, to see what a client and the server log get for a 500."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        raise RuntimeError("deliberate test failure")


# Test-only URLconf, used through override_settings(ROOT_URLCONF=__name__):
# the real routes and error handlers, plus one route that crashes.
urlpatterns = project_urls.urlpatterns + [path("test-crash/", CrashView.as_view())]
handler400 = project_urls.handler400
handler404 = project_urls.handler404
handler500 = project_urls.handler500


class ErrorResponseTests(APITestCase):
    """Every error the API can return is JSON with the documented status."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email="owner@example.com", password=PASSWORD, name="Owner")

    def setUp(self):
        self.client.force_authenticate(self.user)

    def test_malformed_json_is_400(self):
        response = self.client.post(
            reverse("patient-list"), data='{"name": "Rahul",', content_type="application/json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(response.data["detail"].startswith("JSON parse error - "))
        self.assertFalse(Patient.objects.exists())

    def test_non_json_bodies_are_415(self):
        content_types = ("application/x-www-form-urlencoded", "multipart/form-data; boundary=XYZ", "text/plain")
        for url in (reverse("auth-register"), reverse("auth-login"), reverse("patient-list")):
            for content_type in content_types:
                with self.subTest(url=url, content_type=content_type):
                    response = self.client.post(url, data="name=Rahul", content_type=content_type)
                    self.assertEqual(response.status_code, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
                    self.assertEqual(
                        response.data["detail"], f'Unsupported media type "{content_type}" in request.'
                    )
        self.assertFalse(Patient.objects.exists())

    def test_wrong_methods_are_405(self):
        patient = Patient.objects.create(created_by=self.user, name="Rahul", date_of_birth=date(1990, 4, 12))
        doctor = Doctor.objects.create(
            created_by=self.user, name="Dr. Arjun Rao", specialization="Neurology", email="arjun@example.com"
        )
        cases = [
            ("get", reverse("auth-register")),
            ("get", reverse("auth-login")),
            ("get", reverse("auth-token-refresh")),
            ("put", reverse("patient-list")),
            ("delete", reverse("patient-list")),
            ("patch", reverse("patient-detail", args=[patient.id])),
            ("post", reverse("patient-detail", args=[patient.id])),
            ("put", reverse("doctor-list")),
            ("delete", reverse("doctor-list")),
            ("patch", reverse("doctor-detail", args=[doctor.id])),
            ("post", reverse("doctor-detail", args=[doctor.id])),
            ("put", reverse("mapping-list")),
            ("delete", reverse("mapping-list")),
            ("put", reverse("mapping-detail", args=[patient.id])),
            ("patch", reverse("mapping-detail", args=[patient.id])),
            ("post", reverse("mapping-detail", args=[patient.id])),
        ]
        for method, url in cases:
            with self.subTest(method=method.upper(), url=url):
                response = getattr(self.client, method)(url, {})
                self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
                self.assertEqual(response.data["detail"], f'Method "{method.upper()}" not allowed.')

    def test_unmatched_urls_get_a_json_404(self):
        for url in ("/", "/api/", "/api/patients/abc/", "/api/unknown/"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
                self.assertEqual(response.json(), {"detail": "Not found."})

    def test_a_missing_trailing_slash_redirects_and_saves_nothing(self):
        # With DEBUG off, Django redirects to the URL with a
        # slash, and the redirect drops the body. Clients must use the slash.
        response = self.client.post("/api/patients", {"name": "Rahul", "date_of_birth": "1990-04-12"})
        self.assertEqual(response.status_code, status.HTTP_301_MOVED_PERMANENTLY)
        self.assertEqual(response["Location"], "/api/patients/")
        self.assertFalse(Patient.objects.exists())

    def test_a_body_over_the_size_limit_is_rejected(self):
        # DRF parses JSON through request.body, where Django enforces
        # DATA_UPLOAD_MAX_MEMORY_SIZE (2.5 MB by default).
        name = "A" * settings.DATA_UPLOAD_MAX_MEMORY_SIZE
        body = '{"name": "%s", "date_of_birth": "1990-04-12"}' % name
        with self.assertLogs("django.security", "ERROR"):
            response = self.client.post(reverse("patient-list"), data=body, content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), {"detail": "Request body is too large."})
        self.assertFalse(Patient.objects.exists())


class TokenLifecycleTests(APITestCase):
    """Expired tokens, and tokens of users deactivated or deleted after login, over HTTP."""

    def setUp(self):
        self.user = User.objects.create_user(email="owner@example.com", password=PASSWORD, name="Owner")
        login = self.client.post(reverse("auth-login"), {"email": "owner@example.com", "password": PASSWORD})
        self.tokens = login.data

    def list_patients_with(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return self.client.get(reverse("patient-list"))

    def test_an_expired_access_token_is_401_until_the_client_refreshes(self):
        expired = AccessToken.for_user(self.user)
        expired.set_exp(lifetime=timedelta(seconds=-1))
        response = self.list_patients_with(str(expired))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "token_not_valid")

        self.client.credentials()
        refreshed = self.client.post(reverse("auth-token-refresh"), {"refresh": self.tokens["refresh"]})
        self.assertEqual(refreshed.status_code, status.HTTP_200_OK)
        self.assertEqual(self.list_patients_with(refreshed.data["access"]).status_code, status.HTTP_200_OK)

    def test_the_token_of_a_user_deactivated_after_login_is_401(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        response = self.list_patients_with(self.tokens["access"])
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "user_inactive")

    def test_the_token_of_a_user_deleted_after_login_is_401(self):
        User.objects.filter(pk=self.user.pk).delete()
        response = self.list_patients_with(self.tokens["access"])
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "user_not_found")


@override_settings(ROOT_URLCONF=__name__)
class ServerErrorTests(APITestCase):
    """An unexpected exception: a generic JSON 500 for the client, the full
    traceback in the server log."""

    def test_unexpected_error_returns_a_generic_500_and_logs_the_traceback(self):
        self.client.raise_request_exception = False
        console = next(
            h for h in logging.getLogger("django.request").handlers if isinstance(h, logging.StreamHandler)
        )
        log = io.StringIO()
        original_stream = console.setStream(log)
        try:
            response = self.client.get("/test-crash/")
        finally:
            console.setStream(original_stream)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.json(), {"detail": "A server error occurred."})
        self.assertNotIn("deliberate", response.content.decode())
        self.assertIn("Traceback", log.getvalue())
        self.assertIn("RuntimeError: deliberate test failure", log.getvalue())


class ResponseExposureTests(APITestCase):
    """No response body contains password data or an owner field."""

    def test_no_response_exposes_password_data_or_owner_ids(self):
        bodies = []

        def call(method, url, data=None):
            response = getattr(self.client, method)(url, data)
            bodies.append(response.content.decode())
            return response

        call("post", reverse("auth-register"), {"name": "Asha Verma", "email": "asha@example.com", "password": PASSWORD})
        login = call("post", reverse("auth-login"), {"email": "asha@example.com", "password": PASSWORD})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        patient = call("post", reverse("patient-list"), {"name": "Rahul", "date_of_birth": "1990-04-12"})
        doctor = call(
            "post", reverse("doctor-list"), {"name": "Dr. Neha Kapoor", "specialization": "Cardiology", "email": "neha@example.com"}
        )
        call("post", reverse("mapping-list"), {"patient": patient.data["id"], "doctor": doctor.data["id"]})
        for url in (
            reverse("patient-list"),
            reverse("doctor-list"),
            reverse("mapping-list"),
            reverse("mapping-detail", args=[patient.data["id"]]),
        ):
            call("get", url)

        everything = "\n".join(bodies)
        for forbidden in ("pbkdf2", '"password"', PASSWORD, "created_by"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, everything)


class SettingsHelperTests(SimpleTestCase):
    """The helpers in config/settings.py that read environment variables."""

    def test_a_missing_or_blank_boolean_falls_back_to_the_default(self):
        # This is why DEBUG is off unless DJANGO_DEBUG explicitly turns it on.
        with mock.patch.dict(os.environ, {"HC_TEST_FLAG": "  "}):
            self.assertFalse(project_settings.env_bool("HC_TEST_FLAG", default=False))
        with mock.patch.dict(os.environ, {}):
            os.environ.pop("HC_TEST_FLAG", None)
            self.assertFalse(project_settings.env_bool("HC_TEST_FLAG", default=False))

    def test_booleans_accept_the_usual_spellings_and_reject_typos(self):
        for value, expected in (("1", True), ("True", True), ("yes", True), ("ON", True),
                                ("0", False), ("false", False), ("No", False), ("off", False)):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"HC_TEST_FLAG": value}):
                self.assertIs(project_settings.env_bool("HC_TEST_FLAG", default=False), expected)
        with mock.patch.dict(os.environ, {"HC_TEST_FLAG": "maybe"}), self.assertRaises(ImproperlyConfigured):
            project_settings.env_bool("HC_TEST_FLAG", default=False)

    def test_required_variables_must_be_present_and_not_blank(self):
        with mock.patch.dict(os.environ, {"HC_TEST_SECRET": "   "}), self.assertRaises(ImproperlyConfigured):
            project_settings.env_required("HC_TEST_SECRET")
        with mock.patch.dict(os.environ, {}):
            os.environ.pop("HC_TEST_SECRET", None)
            with self.assertRaises(ImproperlyConfigured):
                project_settings.env_required("HC_TEST_SECRET")
        with mock.patch.dict(os.environ, {"HC_TEST_SECRET": "value"}):
            self.assertEqual(project_settings.env_required("HC_TEST_SECRET"), "value")

    def test_lists_are_split_on_commas_and_skip_blanks(self):
        with mock.patch.dict(os.environ, {"HC_TEST_HOSTS": " api.example.com, ,localhost, "}):
            self.assertEqual(project_settings.env_list("HC_TEST_HOSTS", "x"), ["api.example.com", "localhost"])
        with mock.patch.dict(os.environ, {}):
            os.environ.pop("HC_TEST_HOSTS", None)
            self.assertEqual(project_settings.env_list("HC_TEST_HOSTS", "localhost,127.0.0.1"), ["localhost", "127.0.0.1"])
