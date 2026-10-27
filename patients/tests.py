"""Tests for the patient API. Run with: python manage.py test patients

Most tests use force_authenticate() to focus on the view's logic;
PatientRealJwtTests sends a real token from the login endpoint.
"""

from datetime import date, timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Patient
from .permissions import IsPatientOwner

User = get_user_model()

PASSWORD = "Clinic-Pass-2026"
LIST_URL = reverse("patient-list")
RESPONSE_FIELDS = {"id", "name", "date_of_birth", "gender", "phone", "address", "created_at", "updated_at"}


def detail_url(pk):
    return reverse("patient-detail", args=[pk])


def patient_data(**overrides):
    data = {
        "name": "Rahul Mehta",
        "date_of_birth": "1990-04-12",
        "gender": "male",
        "phone": "+919876543210",
        "address": "12 MG Road, Pune",
    }
    data.update(overrides)
    return data


class PatientTestCase(APITestCase):
    """Two users with one patient each. Requests run as `owner` unless a test changes that."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(email="owner@example.com", password=PASSWORD, name="Owner")
        cls.other = User.objects.create_user(email="other@example.com", password=PASSWORD, name="Other")
        cls.patient = Patient.objects.create(
            created_by=cls.owner, name="Rahul Mehta", date_of_birth=date(1990, 4, 12), gender="male"
        )
        cls.others_patient = Patient.objects.create(
            created_by=cls.other, name="Meera Iyer", date_of_birth=date(1985, 1, 1)
        )

    def setUp(self):
        self.client.force_authenticate(self.owner)


class PatientRequiresTokenTests(APITestCase):
    def test_every_patient_endpoint_without_a_token_is_401(self):
        owner = User.objects.create_user(email="owner@example.com", password=PASSWORD, name="Owner")
        patient = Patient.objects.create(created_by=owner, name="Rahul Mehta", date_of_birth=date(1990, 4, 12))
        requests = [
            ("get", LIST_URL),
            ("post", LIST_URL),
            ("get", detail_url(patient.id)),
            ("put", detail_url(patient.id)),
            ("delete", detail_url(patient.id)),
        ]
        for method, url in requests:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, patient_data())
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        # Nothing was created, changed or deleted.
        self.assertEqual(Patient.objects.count(), 1)
        patient.refresh_from_db()
        self.assertEqual(patient.name, "Rahul Mehta")


class PatientRealJwtTests(APITestCase):
    """Through the real login endpoint and a Bearer token, with no force_authenticate."""

    def setUp(self):
        User.objects.create_user(email="owner@example.com", password=PASSWORD, name="Owner")
        login = self.client.post(reverse("auth-login"), {"email": "owner@example.com", "password": PASSWORD})
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.tokens = login.data

    def test_create_and_list_with_a_real_access_token(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.tokens['access']}")
        created = self.client.post(LIST_URL, patient_data())
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        listed = self.client.get(LIST_URL)
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual([p["id"] for p in listed.data], [created.data["id"]])

    def test_tampered_or_refresh_token_is_401(self):
        access = self.tokens["access"]
        tampered = access[:-4] + ("AAAA" if not access.endswith("AAAA") else "BBBB")
        for label, token in (("tampered access token", tampered), ("refresh token", self.tokens["refresh"])):
            with self.subTest(label):
                self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
                response = self.client.get(LIST_URL)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class PatientCreateTests(PatientTestCase):
    def test_create_returns_201_with_the_documented_fields_only(self):
        response = self.client.post(LIST_URL, patient_data())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(set(response.data), RESPONSE_FIELDS)
        self.assertEqual(response.data["date_of_birth"], "1990-04-12")
        self.assertEqual(Patient.objects.get(id=response.data["id"]).created_by, self.owner)

    def test_owner_and_id_in_the_body_are_ignored(self):
        response = self.client.post(LIST_URL, patient_data(created_by=self.other.id, id=999999, unknown="x"))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        patient = Patient.objects.get(id=response.data["id"])
        self.assertEqual(patient.created_by, self.owner)
        self.assertNotEqual(patient.id, 999999)

    def test_only_name_and_date_of_birth_are_required(self):
        response = self.client.post(LIST_URL, {"name": "Asha", "date_of_birth": "2001-02-03"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual((response.data["gender"], response.data["phone"], response.data["address"]), ("", "", ""))

    def test_empty_body_lists_the_required_fields(self):
        response = self.client.post(LIST_URL, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(set(response.data), {"name", "date_of_birth"})

    def test_date_of_birth_today_is_allowed_but_tomorrow_is_not(self):
        today = timezone.localdate()
        response = self.client.post(LIST_URL, patient_data(date_of_birth=today.isoformat()))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.post(LIST_URL, patient_data(date_of_birth=(today + timedelta(days=1)).isoformat()))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["date_of_birth"], ["Date of birth cannot be in the future."])

    def test_invalid_values_are_rejected(self):
        cases = {
            "name": ["   ", "x" * 151],
            "date_of_birth": ["12-04-1990", "not-a-date"],
            "gender": ["unknown", "MALE"],
            "phone": ["12345", "+1234567890123456", "98765-43210", "phone"],
            "address": ["x" * 256],
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    response = self.client.post(LIST_URL, patient_data(**{field: value}))
                    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                    self.assertEqual(set(response.data), {field})
        self.assertEqual(Patient.objects.filter(created_by=self.owner).count(), 1)

    def test_valid_phone_formats_are_accepted(self):
        for phone in ("9876543", "+919876543210", "123456789012345"):
            with self.subTest(phone=phone):
                response = self.client.post(LIST_URL, patient_data(phone=phone))
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class PatientReadUpdateDeleteTests(PatientTestCase):
    def test_list_returns_exactly_the_callers_patients_in_id_order(self):
        second = Patient.objects.create(created_by=self.owner, name="Second", date_of_birth=date(2000, 1, 1))
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([p["id"] for p in response.data], [self.patient.id, second.id])

    def test_list_is_empty_for_a_user_without_patients(self):
        newcomer = User.objects.create_user(email="new@example.com", password=PASSWORD, name="New")
        self.client.force_authenticate(newcomer)
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_retrieve_own_patient(self):
        response = self.client.get(detail_url(self.patient.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.patient.id)
        self.assertEqual(set(response.data), RESPONSE_FIELDS)

    def test_put_updates_own_patient(self):
        response = self.client.put(
            detail_url(self.patient.id), patient_data(name="Rahul M.", address="New address")
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.patient.refresh_from_db()
        self.assertEqual((self.patient.name, self.patient.address), ("Rahul M.", "New address"))

    def test_put_keeps_optional_fields_that_are_left_out(self):
        response = self.client.put(detail_url(self.patient.id), {"name": "Rahul", "date_of_birth": "1990-04-12"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.gender, "male")

    def test_put_without_a_required_field_is_400(self):
        for missing in ("name", "date_of_birth"):
            with self.subTest(missing=missing):
                data = patient_data()
                del data[missing]
                response = self.client.put(detail_url(self.patient.id), data)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(missing, response.data)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.name, "Rahul Mehta")

    def test_put_cannot_change_the_owner_or_the_id(self):
        response = self.client.put(detail_url(self.patient.id), patient_data(created_by=self.other.id, id=999999))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.created_by, self.owner)
        self.assertEqual(response.data["id"], self.patient.id)

    def test_delete_own_patient(self):
        response = self.client.delete(detail_url(self.patient.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Patient.objects.filter(id=self.patient.id).exists())

    def test_patch_is_not_allowed(self):
        response = self.client.patch(detail_url(self.patient.id), {"name": "Changed"})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.name, "Rahul Mehta")

    def test_missing_huge_and_non_integer_ids_are_404(self):
        for url in (detail_url(999999), "/api/patients/99999999999999999999/", "/api/patients/abc/"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, status.HTTP_404_NOT_FOUND)


class PatientIsolationTests(PatientTestCase):
    """User A must never see or change user B's patients."""

    def test_list_never_contains_another_users_patients(self):
        ids = [p["id"] for p in self.client.get(LIST_URL).data]
        self.assertNotIn(self.others_patient.id, ids)

    def test_another_users_patient_is_404_and_unchanged(self):
        url = detail_url(self.others_patient.id)
        responses = {
            "GET": self.client.get(url),
            "PUT": self.client.put(url, patient_data(name="Hijacked")),
            "DELETE": self.client.delete(url),
        }
        for method, response in responses.items():
            with self.subTest(method=method):
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.others_patient.refresh_from_db()
        self.assertEqual(self.others_patient.name, "Meera Iyer")
        self.assertEqual(self.others_patient.created_by, self.other)

    def test_someone_elses_patient_looks_exactly_like_a_missing_one(self):
        theirs = self.client.get(detail_url(self.others_patient.id))
        missing = self.client.get(detail_url(999999))
        self.assertEqual(theirs.status_code, missing.status_code)
        self.assertEqual(theirs.data, missing.data)

    def test_deleting_a_user_deletes_their_patients(self):
        self.other.delete()
        self.assertFalse(Patient.objects.filter(id=self.others_patient.id).exists())
        self.assertTrue(Patient.objects.filter(id=self.patient.id).exists())


class IsPatientOwnerTests(SimpleTestCase):
    """The object-level backstop, tested directly: through the API the scoped
    queryset already turns another user's patient into a 404."""

    def check(self, owner_id, user_id):
        request = SimpleNamespace(user=SimpleNamespace(id=user_id))
        return IsPatientOwner().has_object_permission(request, None, SimpleNamespace(created_by_id=owner_id))

    def test_owner_is_allowed(self):
        self.assertTrue(self.check(owner_id=1, user_id=1))

    def test_anyone_else_is_refused(self):
        self.assertFalse(self.check(owner_id=1, user_id=2))
