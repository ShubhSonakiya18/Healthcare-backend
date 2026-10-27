"""Tests for the mapping API. Run with: python manage.py test mappings

Most tests use force_authenticate() to focus on the view's logic;
MappingRealJwtTests sends a real token from the login endpoint.
"""

from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.validators import UniqueTogetherValidator

from doctors.models import Doctor
from patients.models import Patient

from .models import PatientDoctorMapping

User = get_user_model()

PASSWORD = "Clinic-Pass-2026"
LIST_URL = reverse("mapping-list")
MAPPING_FIELDS = {"id", "patient", "patient_name", "doctor", "doctor_detail", "created_at"}
DOCTOR_FIELDS = {"id", "name", "specialization", "email", "created_at", "updated_at"}
DUPLICATE = ["This doctor is already assigned to this patient."]


def detail_url(pk):
    return reverse("mapping-detail", args=[pk])


def does_not_exist(pk):
    return [f'Invalid pk "{pk}" - object does not exist.']


class MappingTestCase(APITestCase):
    """`owner` has two patients, the first assigned to `doctor`. `other` has one
    patient, also assigned to `doctor`. Requests run as `owner` unless a test
    changes that."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(email="owner@example.com", password=PASSWORD, name="Owner")
        cls.other = User.objects.create_user(email="other@example.com", password=PASSWORD, name="Other")
        cls.patient = Patient.objects.create(
            created_by=cls.owner, name="Rahul Mehta", date_of_birth=date(1990, 4, 12)
        )
        cls.second_patient = Patient.objects.create(
            created_by=cls.owner, name="Asha Verma", date_of_birth=date(1995, 6, 1)
        )
        cls.others_patient = Patient.objects.create(
            created_by=cls.other, name="Meera Iyer", date_of_birth=date(1985, 1, 1)
        )
        cls.doctor = Doctor.objects.create(
            created_by=cls.owner, name="Dr. Arjun Rao", specialization="Neurology", email="arjun.rao@example.com"
        )
        cls.others_doctor = Doctor.objects.create(
            created_by=cls.other, name="Dr. Sara Khan", specialization="Dermatology", email="sara.khan@example.com"
        )
        cls.mapping = PatientDoctorMapping.objects.create(patient=cls.patient, doctor=cls.doctor)
        cls.others_mapping = PatientDoctorMapping.objects.create(patient=cls.others_patient, doctor=cls.doctor)

    def setUp(self):
        self.client.force_authenticate(self.owner)

    def assign(self, patient_id, doctor_id):
        return self.client.post(LIST_URL, {"patient": patient_id, "doctor": doctor_id})


class MappingRequiresTokenTests(MappingTestCase):
    def test_every_mapping_endpoint_without_a_token_is_401(self):
        self.client.force_authenticate(None)
        requests = [
            ("get", LIST_URL),
            ("post", LIST_URL),
            ("get", detail_url(self.patient.id)),
            ("delete", detail_url(self.mapping.id)),
        ]
        for method, url in requests:
            with self.subTest(method=method, url=url):
                data = {"patient": self.second_patient.id, "doctor": self.doctor.id}
                response = getattr(self.client, method)(url, data)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(PatientDoctorMapping.objects.count(), 2)


class MappingRealJwtTests(MappingTestCase):
    """Through the real login endpoint and a Bearer token, with no force_authenticate."""

    def test_assign_list_and_remove_with_a_real_access_token(self):
        self.client.force_authenticate(None)
        login = self.client.post(reverse("auth-login"), {"email": "owner@example.com", "password": PASSWORD})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        created = self.assign(self.second_patient.id, self.doctor.id)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        listed = self.client.get(LIST_URL)
        self.assertEqual([m["id"] for m in listed.data], [self.mapping.id, created.data["id"]])
        removed = self.client.delete(detail_url(created.data["id"]))
        self.assertEqual(removed.status_code, status.HTTP_204_NO_CONTENT)


class MappingCreateTests(MappingTestCase):
    def test_assign_returns_201_with_the_mapping_object(self):
        response = self.assign(self.second_patient.id, self.doctor.id)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(set(response.data), MAPPING_FIELDS)
        self.assertEqual(response.data["patient"], self.second_patient.id)
        self.assertEqual(response.data["patient_name"], "Asha Verma")
        self.assertEqual(response.data["doctor"], self.doctor.id)
        self.assertEqual(set(response.data["doctor_detail"]), DOCTOR_FIELDS)
        self.assertEqual(response.data["doctor_detail"]["id"], self.doctor.id)
        self.assertTrue(
            PatientDoctorMapping.objects.filter(
                id=response.data["id"], patient=self.second_patient, doctor=self.doctor
            ).exists()
        )

    def test_any_doctor_in_the_shared_directory_can_be_assigned(self):
        response = self.assign(self.patient.id, self.others_doctor.id)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_the_same_pair_again_is_400_and_only_one_row_exists(self):
        response = self.assign(self.patient.id, self.doctor.id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["non_field_errors"], DUPLICATE)
        self.assertEqual(PatientDoctorMapping.objects.filter(patient=self.patient, doctor=self.doctor).count(), 1)

    def test_duplicate_that_slips_past_the_validator_still_gets_a_400(self):
        # Simulates two simultaneous requests: the serializer's duplicate check
        # is patched out, so only the database constraint stops the insert.
        with mock.patch.object(UniqueTogetherValidator, "__call__", autospec=True, return_value=None) as check:
            response = self.assign(self.patient.id, self.doctor.id)
        self.assertTrue(check.called)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["non_field_errors"], DUPLICATE)
        self.assertEqual(PatientDoctorMapping.objects.filter(patient=self.patient, doctor=self.doctor).count(), 1)

    def test_another_users_patient_gets_the_same_error_as_a_missing_one(self):
        for patient_id in (self.others_patient.id, 999999):
            with self.subTest(patient_id=patient_id):
                response = self.assign(patient_id, self.others_doctor.id)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data, {"patient": does_not_exist(patient_id)})
        self.assertEqual(PatientDoctorMapping.objects.filter(patient=self.others_patient).count(), 1)

    def test_unknown_doctor_is_400(self):
        response = self.assign(self.second_patient.id, 999999)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, {"doctor": does_not_exist(999999)})

    def test_missing_fields_are_listed(self):
        response = self.client.post(LIST_URL, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(set(response.data), {"patient", "doctor"})

    def test_id_and_unknown_fields_in_the_body_are_ignored(self):
        response = self.client.post(
            LIST_URL,
            {"patient": self.second_patient.id, "doctor": self.doctor.id, "id": 999999, "created_by": self.other.id},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(response.data["id"], 999999)


class MappingListTests(MappingTestCase):
    def test_list_returns_only_the_callers_mappings_in_id_order(self):
        second = PatientDoctorMapping.objects.create(patient=self.second_patient, doctor=self.others_doctor)
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([m["id"] for m in response.data], [self.mapping.id, second.id])

    def test_list_includes_the_patient_name_and_doctor_details(self):
        item = self.client.get(LIST_URL).data[0]
        self.assertEqual(set(item), MAPPING_FIELDS)
        self.assertEqual(item["patient_name"], "Rahul Mehta")
        self.assertEqual(item["doctor_detail"]["email"], "arjun.rao@example.com")

    def test_list_runs_one_query_however_many_mappings_exist(self):
        PatientDoctorMapping.objects.create(patient=self.second_patient, doctor=self.doctor)
        PatientDoctorMapping.objects.create(patient=self.second_patient, doctor=self.others_doctor)
        with self.assertNumQueries(1):
            response = self.client.get(LIST_URL)
        self.assertEqual(len(response.data), 3)


class MappingByPatientTests(MappingTestCase):
    """GET /api/mappings/<patient_id>/: the number is a patient id."""

    def test_returns_the_patients_mappings_with_doctor_details(self):
        response = self.client.get(detail_url(self.patient.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([m["id"] for m in response.data], [self.mapping.id])
        self.assertEqual(response.data[0]["doctor_detail"]["id"], self.doctor.id)

    def test_a_patient_without_doctors_gives_an_empty_list(self):
        response = self.client.get(detail_url(self.second_patient.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_another_users_or_a_missing_patient_is_404(self):
        theirs = self.client.get(detail_url(self.others_patient.id))
        missing = self.client.get(detail_url(999999))
        huge = self.client.get("/api/mappings/99999999999999999999/")
        for response in (theirs, missing, huge):
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(theirs.data, missing.data)

    def test_the_same_number_is_a_patient_id_for_get_and_a_mapping_id_for_delete(self):
        # A patient and a mapping that share the id n. GET must return patient
        # n's (empty) list, not mapping n; DELETE must remove mapping n.
        n = 900001
        Patient.objects.create(id=n, created_by=self.owner, name="Same Number", date_of_birth=date(2000, 1, 1))
        PatientDoctorMapping.objects.create(id=n, patient=self.second_patient, doctor=self.doctor)

        response = self.client.get(detail_url(n))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

        response = self.client.delete(detail_url(n))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(PatientDoctorMapping.objects.filter(id=n).exists())
        self.assertTrue(Patient.objects.filter(id=n).exists())


class MappingDeleteTests(MappingTestCase):
    """DELETE /api/mappings/<id>/: the number is a mapping id."""

    def test_delete_own_mapping(self):
        response = self.client.delete(detail_url(self.mapping.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(PatientDoctorMapping.objects.filter(id=self.mapping.id).exists())
        self.assertTrue(Patient.objects.filter(id=self.patient.id).exists())
        self.assertTrue(Doctor.objects.filter(id=self.doctor.id).exists())

    def test_another_users_mapping_is_404_and_kept(self):
        response = self.client.delete(detail_url(self.others_mapping.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(PatientDoctorMapping.objects.filter(id=self.others_mapping.id).exists())

    def test_missing_mapping_is_404(self):
        response = self.client.delete(detail_url(999999))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_other_methods_on_the_detail_url_are_405(self):
        url = detail_url(self.mapping.id)
        for method in ("put", "patch", "post"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(url, {"patient": self.second_patient.id, "doctor": self.doctor.id})
                self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(PatientDoctorMapping.objects.count(), 2)


class MappingCascadeTests(MappingTestCase):
    def test_deleting_a_patient_deletes_its_mappings(self):
        response = self.client.delete(reverse("patient-detail", args=[self.patient.id]))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(PatientDoctorMapping.objects.filter(patient_id=self.patient.id).exists())
        self.assertTrue(Doctor.objects.filter(id=self.doctor.id).exists())
        self.assertTrue(PatientDoctorMapping.objects.filter(id=self.others_mapping.id).exists())
