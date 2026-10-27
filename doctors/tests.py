"""Tests for the doctor API. Run with: python manage.py test doctors

Most tests use force_authenticate() to focus on the view's logic;
DoctorRealJwtTests sends a real token from the login endpoint.
"""

from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.validators import UniqueValidator

from .models import Doctor
from .permissions import IsCreatorOrReadOnly

User = get_user_model()

PASSWORD = "Clinic-Pass-2026"
LIST_URL = reverse("doctor-list")
RESPONSE_FIELDS = {"id", "name", "specialization", "email", "created_at", "updated_at"}
DUPLICATE_EMAIL = ["A doctor with this email already exists."]


def detail_url(pk):
    return reverse("doctor-detail", args=[pk])


def doctor_data(**overrides):
    data = {"name": "Dr. Neha Kapoor", "specialization": "Cardiology", "email": "Neha.Kapoor@citycare.example"}
    data.update(overrides)
    return data


class DoctorTestCase(APITestCase):
    """Two users with one doctor each. Requests run as `creator` unless a test changes that."""

    @classmethod
    def setUpTestData(cls):
        cls.creator = User.objects.create_user(email="creator@example.com", password=PASSWORD, name="Creator")
        cls.other = User.objects.create_user(email="other@example.com", password=PASSWORD, name="Other")
        cls.doctor = Doctor.objects.create(
            created_by=cls.creator, name="Dr. Arjun Rao", specialization="Neurology", email="arjun.rao@example.com"
        )
        cls.others_doctor = Doctor.objects.create(
            created_by=cls.other, name="Dr. Sara Khan", specialization="Dermatology", email="sara.khan@example.com"
        )

    def setUp(self):
        self.client.force_authenticate(self.creator)

    def assert_name(self, doctor, name):
        doctor.refresh_from_db()
        self.assertEqual(doctor.name, name)


class DoctorRequiresTokenTests(APITestCase):
    def test_every_doctor_endpoint_without_a_token_is_401(self):
        creator = User.objects.create_user(email="creator@example.com", password=PASSWORD, name="Creator")
        doctor = Doctor.objects.create(
            created_by=creator, name="Dr. Arjun Rao", specialization="Neurology", email="arjun.rao@example.com"
        )
        requests = [
            ("get", LIST_URL),
            ("post", LIST_URL),
            ("get", detail_url(doctor.id)),
            ("put", detail_url(doctor.id)),
            ("delete", detail_url(doctor.id)),
        ]
        for method, url in requests:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, doctor_data())
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(Doctor.objects.count(), 1)
        doctor.refresh_from_db()
        self.assertEqual(doctor.name, "Dr. Arjun Rao")


class DoctorRealJwtTests(APITestCase):
    """Through the real login endpoint and a Bearer token, with no force_authenticate."""

    def test_create_and_list_with_a_real_access_token(self):
        User.objects.create_user(email="creator@example.com", password=PASSWORD, name="Creator")
        login = self.client.post(reverse("auth-login"), {"email": "creator@example.com", "password": PASSWORD})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        created = self.client.post(LIST_URL, doctor_data())
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        listed = self.client.get(LIST_URL)
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual([d["id"] for d in listed.data], [created.data["id"]])


class DoctorCreateTests(DoctorTestCase):
    def test_create_returns_201_with_a_normalised_email(self):
        response = self.client.post(LIST_URL, doctor_data(email="  Neha.Kapoor@CityCare.example "))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(set(response.data), RESPONSE_FIELDS)
        self.assertEqual(response.data["email"], "neha.kapoor@citycare.example")
        self.assertEqual(Doctor.objects.get(id=response.data["id"]).created_by, self.creator)

    def test_creator_and_id_in_the_body_are_ignored(self):
        response = self.client.post(LIST_URL, doctor_data(created_by=self.other.id, id=999999))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        doctor = Doctor.objects.get(id=response.data["id"])
        self.assertEqual(doctor.created_by, self.creator)
        self.assertNotEqual(doctor.id, 999999)

    def test_duplicate_email_in_any_letter_case_from_any_user_is_400(self):
        self.client.force_authenticate(self.other)
        response = self.client.post(LIST_URL, doctor_data(email="ARJUN.RAO@example.com"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["email"], DUPLICATE_EMAIL)
        self.assertEqual(Doctor.objects.count(), 2)

    def test_duplicate_that_slips_past_the_validator_still_gets_a_400(self):
        # Simulates two simultaneous requests: the UniqueValidator check is
        # patched out, so only the database's unique index stops the insert.
        with mock.patch.object(UniqueValidator, "__call__", autospec=True, return_value=None) as check:
            response = self.client.post(LIST_URL, doctor_data(email="arjun.rao@example.com"))
        self.assertTrue(check.called)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["email"], DUPLICATE_EMAIL)
        self.assertEqual(Doctor.objects.count(), 2)

    def test_empty_body_lists_the_required_fields(self):
        response = self.client.post(LIST_URL, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(set(response.data), {"name", "specialization", "email"})

    def test_invalid_values_are_rejected(self):
        cases = {
            "name": ["   ", "x" * 151],
            "specialization": ["   ", "x" * 101],
            "email": ["not-an-email", ""],
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    response = self.client.post(LIST_URL, doctor_data(**{field: value}))
                    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                    self.assertEqual(set(response.data), {field})
        self.assertEqual(Doctor.objects.count(), 2)


class DoctorReadTests(DoctorTestCase):
    def test_list_shows_every_users_doctors_in_id_order(self):
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([d["id"] for d in response.data], [self.doctor.id, self.others_doctor.id])

    def test_any_user_can_retrieve_any_doctor(self):
        response = self.client.get(detail_url(self.others_doctor.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data), RESPONSE_FIELDS)

    def test_missing_and_huge_ids_are_404(self):
        for url in (detail_url(999999), "/api/doctors/99999999999999999999/"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, status.HTTP_404_NOT_FOUND)


class DoctorPermissionTests(DoctorTestCase):
    """Shared read, creator-only write."""

    def test_creator_can_update(self):
        response = self.client.put(detail_url(self.doctor.id), doctor_data(email="arjun.rao@example.com"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assert_name(self.doctor, "Dr. Neha Kapoor")

    def test_creator_can_delete(self):
        response = self.client.delete(detail_url(self.doctor.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Doctor.objects.filter(id=self.doctor.id).exists())

    def test_another_user_gets_403_and_the_doctor_is_unchanged(self):
        url = detail_url(self.others_doctor.id)
        put = self.client.put(url, doctor_data(name="Hijacked", email="sara.khan@example.com"))
        delete = self.client.delete(url)
        for method, response in (("PUT", put), ("DELETE", delete)):
            with self.subTest(method=method):
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assert_name(self.others_doctor, "Dr. Sara Khan")

    def test_put_to_another_doctors_email_is_400(self):
        response = self.client.put(detail_url(self.doctor.id), doctor_data(email="Sara.Khan@example.com"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["email"], DUPLICATE_EMAIL)
        self.assert_name(self.doctor, "Dr. Arjun Rao")

    def test_patch_is_not_allowed(self):
        response = self.client.patch(detail_url(self.doctor.id), {"name": "Changed"})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assert_name(self.doctor, "Dr. Arjun Rao")

    def test_doctor_whose_creator_was_deleted_stays_visible_but_read_only(self):
        self.other.delete()
        self.others_doctor.refresh_from_db()
        self.assertIsNone(self.others_doctor.created_by)

        url = detail_url(self.others_doctor.id)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.client.put(url, doctor_data(email="sara.khan@example.com")).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(self.client.delete(url).status_code, status.HTTP_403_FORBIDDEN)
        self.assert_name(self.others_doctor, "Dr. Sara Khan")


class IsCreatorOrReadOnlyTests(SimpleTestCase):
    def check(self, method, creator_id, user_id):
        request = SimpleNamespace(method=method, user=SimpleNamespace(id=user_id))
        return IsCreatorOrReadOnly().has_object_permission(request, None, SimpleNamespace(created_by_id=creator_id))

    def test_anyone_may_read(self):
        for method in ("GET", "HEAD", "OPTIONS"):
            with self.subTest(method=method):
                self.assertTrue(self.check(method, creator_id=1, user_id=2))

    def test_only_the_creator_may_write(self):
        for method in ("PUT", "DELETE"):
            with self.subTest(method=method):
                self.assertTrue(self.check(method, creator_id=1, user_id=1))
                self.assertFalse(self.check(method, creator_id=1, user_id=2))
                self.assertFalse(self.check(method, creator_id=None, user_id=1))
