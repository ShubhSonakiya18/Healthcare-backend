# API Reference

This is the reference for clients of the Healthcare Backend API: every endpoint, its fields, its responses and its errors. Setup instructions are in the [README](../README.md). The design record behind these choices is [design.md](design.md).

**Assignment requirement or our design?** For each endpoint the assignment specifies only the method, the path and a one-line purpose. Everything else on this page is our design: request and response bodies, field names, validation rules, status codes and error messages. In particular, the mapping object returned by the mapping endpoints is our design, not an assignment requirement.

**About the examples:** ids, names, timestamps and tokens are illustrative; yours will differ. Field names, status codes and error messages are exact: they were taken from the project's code and the installed libraries. Every status code is covered by an automated test; [design.md section 8](design.md#8-error-response-conventions) names the tests.

## Contents

- [Conventions](#conventions)
- [Endpoint index](#endpoint-index)
- [Errors that apply to many endpoints](#errors-that-apply-to-many-endpoints)
- [1. Authentication](#1-authentication)
- [2. Patients](#2-patients)
- [3. Doctors](#3-doctors)
- [4. Patient–doctor mappings](#4-patientdoctor-mappings)
- [5. Status codes](#5-status-codes)
- [6. Behaviour with DEBUG on and off](#6-behaviour-with-debug-on-and-off)
- [7. Not available](#7-not-available)

## Conventions

| Topic | Rule |
|---|---|
| Base URL | `http://127.0.0.1:8000` when running locally with `python manage.py runserver` |
| Trailing slash | Every URL ends with `/`. Without it, a POST, PUT or DELETE fails: with `DEBUG` off Django redirects to the URL with the slash and the redirect drops the body; with `DEBUG` on it raises an error |
| Request bodies | JSON only, sent with `Content-Type: application/json`. Any other body type gets 415 |
| Authentication | `Authorization: Bearer <access token>` on every endpoint except register, login and token refresh |
| Ids | Positive integers in the URL path. A non-integer such as `/api/patients/abc/` matches no route and gets 404 |
| Dates | `YYYY-MM-DD` |
| Timestamps | ISO 8601 in UTC, for example `2026-10-28T05:30:00.123456Z`; always read-only |
| Lists | A JSON array of every matching object, ordered by `id` ascending. There is no pagination, filtering or search |
| Unknown fields | Ignored |
| Server-controlled fields | `id`, the timestamps and the owner are set by the server. Values sent for them are ignored |
| Text values | Leading and trailing spaces are trimmed from text fields such as names (never from `password`). A value made only of spaces counts as blank |
| Updates | `PUT` only; `PATCH` returns 405. A PUT must include the required fields; optional fields that are left out keep their current values |
| Responses | JSON. A browser that asks for HTML gets DRF's browsable API page instead; use an HTTP client such as Postman |

## Endpoint index

| # | Method | Path | Auth | Success |
|---|---|---|---|---|
| 1 | POST | [`/api/auth/register/`](#11-register) | public | 201 |
| 2 | POST | [`/api/auth/login/`](#12-log-in) | public | 200 |
| 3 | POST | [`/api/auth/token/refresh/`](#13-refresh-the-access-token) | public | 200 |
| 4 | POST | [`/api/patients/`](#21-create-a-patient) | JWT | 201 |
| 5 | GET | [`/api/patients/`](#22-list-your-patients) | JWT | 200 |
| 6 | GET | [`/api/patients/<id>/`](#23-get-a-patient) | JWT | 200 |
| 7 | PUT | [`/api/patients/<id>/`](#24-update-a-patient) | JWT | 200 |
| 8 | DELETE | [`/api/patients/<id>/`](#25-delete-a-patient) | JWT | 204 |
| 9 | POST | [`/api/doctors/`](#31-add-a-doctor) | JWT | 201 |
| 10 | GET | [`/api/doctors/`](#32-list-all-doctors) | JWT | 200 |
| 11 | GET | [`/api/doctors/<id>/`](#33-get-a-doctor) | JWT | 200 |
| 12 | PUT | [`/api/doctors/<id>/`](#34-update-a-doctor) | JWT, creator only | 200 |
| 13 | DELETE | [`/api/doctors/<id>/`](#35-delete-a-doctor) | JWT, creator only | 204 |
| 14 | POST | [`/api/mappings/`](#41-assign-a-doctor-to-a-patient) | JWT | 201 |
| 15 | GET | [`/api/mappings/`](#42-list-your-assignments) | JWT | 200 |
| 16 | GET | [`/api/mappings/<patient_id>/`](#43-list-a-patients-doctors) | JWT | 200 |
| 17 | DELETE | [`/api/mappings/<mapping_id>/`](#44-remove-an-assignment) | JWT | 204 |

Endpoint 3 is our addition; the other sixteen are the assignment's.

## Errors that apply to many endpoints

### Missing or invalid token (every protected endpoint)

| Situation | Status | Body |
|---|---|---|
| No `Authorization` header | 401 | `{"detail": "Authentication credentials were not provided."}` |
| An expired, altered or wrong-type token (for example the refresh token sent as the Bearer token) | 401 | `{"detail": "Given token not valid for any token type", "code": "token_not_valid", "messages": [...]}` |
| The token's user was deactivated after logging in | 401 | `{"detail": "User is inactive", "code": "user_inactive"}` |
| The token's user was deleted after logging in | 401 | `{"detail": "User not found", "code": "user_not_found"}` |

### Request problems (any endpoint)

| Situation | Status | Body |
|---|---|---|
| Malformed JSON | 400 | `{"detail": "JSON parse error - <parser message>"}` |
| A body that isn't JSON | 415 | `{"detail": "Unsupported media type \"<content type>\" in request."}`, for example `"application/x-www-form-urlencoded"` |
| A method the endpoint doesn't support | 405 | `{"detail": "Method \"PATCH\" not allowed."}`, naming the method |
| A body larger than 2.5 MB (Django's `DATA_UPLOAD_MAX_MEMORY_SIZE`) | 400 | `{"detail": "Request body is too large."}` (with `DEBUG` off) |
| A URL that matches no route | 404 | `{"detail": "Not found."}` (with `DEBUG` off) |
| An unexpected server error | 500 | `{"detail": "A server error occurred."}` (with `DEBUG` off; the traceback goes to the server log, never to the client) |

### Validation errors

A failed validation returns **400** with an object that maps each problem field to a list of messages, for example `{"name": ["This field is required."]}`. Problems that involve more than one field are listed under `non_field_errors`. All field-level problems are reported together. Checks on the object as a whole, such as password strength or a duplicate assignment, run only once the individual fields are valid.

---

## 1. Authentication

| Token | Lifetime | Used for |
|---|---|---|
| Access token | 30 minutes | the `Authorization: Bearer` header of every protected request |
| Refresh token | 1 day | only `POST /api/auth/token/refresh/` |

Both are signed with HS256 using the server's `DJANGO_SECRET_KEY`. There is no logout endpoint and no token revocation: a token stays valid until it expires.

### 1.1 Register

`POST /api/auth/register/` · public

The endpoint ignores any `Authorization` header, so a stale or invalid token left in a client doesn't turn a registration into a 401.

| Field | Type | Required | Rules |
|---|---|---|---|
| `name` | string | yes | 1–150 characters after trimming |
| `email` | string | yes | a valid email address, at most 254 characters. Trimmed and stored in lower case. Must not already be registered, in any letter case |
| `password` | string | yes | Write-only: never returned. Used exactly as typed (not trimmed). Must pass Django's password validators: at least 8 characters, not too similar to the email or name, not a common password, not entirely numeric |

Fields such as `is_staff`, `is_superuser` or `is_active` in the body are ignored. Registration doesn't return tokens; log in next.

Request:

```http
POST /api/auth/register/ HTTP/1.1
Content-Type: application/json

{"name": "Asha Verma", "email": "  Asha.Verma@Example.com ", "password": "Clinic-Pass-2026"}
```

`201 Created`:

```json
{"id": 1, "name": "Asha Verma", "email": "asha.verma@example.com"}
```

Errors:

| Status | When | Body |
|---|---|---|
| 400 | Fields missing | `{"name": ["This field is required."], "email": ["This field is required."], "password": ["This field is required."]}` (only the missing ones are listed) |
| 400 | Blank name | `{"name": ["This field may not be blank."]}` |
| 400 | Name too long | `{"name": ["Ensure this field has no more than 150 characters."]}` |
| 400 | Invalid email | `{"email": ["Enter a valid email address."]}` |
| 400 | Email already registered, in any letter case | `{"email": ["A user with this email already exists."]}` |
| 400 | Weak password | `{"password": [...]}` with one or more of: `"This password is too short. It must contain at least 8 characters."`, `"This password is too common."`, `"This password is entirely numeric."`, `"The password is too similar to the email address."`, `"The password is too similar to the name."` |
| 405 | A method the endpoint doesn't support, such as GET | `{"detail": "Method \"GET\" not allowed."}` |
| 415 | The body isn't JSON | see [Request problems](#request-problems-any-endpoint) |

If two identical registrations arrive at the same moment, one succeeds and the other gets the same "already exists" 400; the database's unique index backs up the check.

### 1.2 Log in

`POST /api/auth/login/` · public

| Field | Type | Required | Rules |
|---|---|---|---|
| `email` | string | yes | trimmed and lower-cased before the check, so `Asha.Verma@EXAMPLE.com` logs in to `asha.verma@example.com` |
| `password` | string | yes | |

Request:

```http
POST /api/auth/login/ HTTP/1.1
Content-Type: application/json

{"email": "asha.verma@example.com", "password": "Clinic-Pass-2026"}
```

`200 OK`:

```json
{"refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6...", "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6..."}
```

Errors:

| Status | When | Body |
|---|---|---|
| 400 | A field is missing | for example `{"password": ["This field is required."]}` |
| 401 | Wrong password, unknown email, or an inactive account | `{"detail": "No active account found with the given credentials"}` |
| 405 | A method the endpoint doesn't support, such as GET | `{"detail": "Method \"GET\" not allowed."}` |

The 401 is identical in all three cases, so the response doesn't reveal which emails are registered.

### 1.3 Refresh the access token

`POST /api/auth/token/refresh/` · public · our addition

| Field | Type | Required | Rules |
|---|---|---|---|
| `refresh` | string | yes | the refresh token from login |

Request:

```http
POST /api/auth/token/refresh/ HTTP/1.1
Content-Type: application/json

{"refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6..."}
```

`200 OK`, with a new access token only. The refresh token isn't rotated: it stays valid until its own expiry, one day after login.

```json
{"access": "eyJhbGciOiJIUzI1NiIsInR5cCI6..."}
```

Errors:

| Status | When | Body |
|---|---|---|
| 400 | `refresh` is missing | `{"refresh": ["This field is required."]}` |
| 401 | The token was altered or isn't a valid token | `{"detail": "Token is invalid", "code": "token_not_valid"}` |
| 401 | The refresh token has expired | `{"detail": "Token is expired", "code": "token_not_valid"}` |
| 401 | An access token was sent instead | `{"detail": "Token has wrong type", "code": "token_not_valid"}` |
| 405 | A method the endpoint doesn't support, such as GET | `{"detail": "Method \"GET\" not allowed."}` |

---

## 2. Patients

Every patient endpoint requires a valid access token, and every one of them sees **only the caller's own patients**. Another user's patient behaves exactly like one that doesn't exist: 404 with `{"detail": "No Patient matches the given query."}`. The response never reveals whether the id exists.

**The patient object:**

```json
{
  "id": 7,
  "name": "Rahul Mehta",
  "date_of_birth": "1990-04-12",
  "gender": "male",
  "phone": "+919876543210",
  "address": "12 MG Road, Pune",
  "created_at": "2026-10-28T05:30:00.123456Z",
  "updated_at": "2026-10-28T05:30:00.123456Z"
}
```

| Field | Type | Required | Rules |
|---|---|---|---|
| `id` | integer | read-only | |
| `name` | string | yes | 1–150 characters after trimming |
| `date_of_birth` | date | yes | `YYYY-MM-DD`; not later than today. "Today" is the current date in UTC |
| `gender` | string | no | `"male"`, `"female"`, `"other"`, or `""`. Exactly in lower case: `"MALE"` is rejected |
| `phone` | string | no | `""`, or 7–15 digits with an optional leading `+` (pattern `^\+?[0-9]{7,15}$`). No spaces or dashes |
| `address` | string | no | at most 255 characters |
| `created_at`, `updated_at` | timestamp | read-only | |

The owner is recorded by the server from the token and is never part of the object. Optional fields left out on create are stored as `""`.

### 2.1 Create a patient

`POST /api/patients/` · JWT

Request:

```http
POST /api/patients/ HTTP/1.1
Authorization: Bearer <access token>
Content-Type: application/json

{"name": "Rahul Mehta", "date_of_birth": "1990-04-12", "gender": "male", "phone": "+919876543210", "address": "12 MG Road, Pune"}
```

`201 Created` with the patient object, owned by the caller. Only `name` and `date_of_birth` are required.

Errors:

| Status | When | Body |
|---|---|---|
| 400 | Required fields missing (for example an empty body `{}`) | `{"name": ["This field is required."], "date_of_birth": ["This field is required."]}` |
| 400 | Blank or too-long name | `{"name": ["This field may not be blank."]}` or `{"name": ["Ensure this field has no more than 150 characters."]}` |
| 400 | Wrong date format | `{"date_of_birth": ["Date has wrong format. Use one of these formats instead: YYYY-MM-DD."]}` |
| 400 | Date of birth in the future | `{"date_of_birth": ["Date of birth cannot be in the future."]}` |
| 400 | Gender not one of the choices | `{"gender": ["\"MALE\" is not a valid choice."]}` |
| 400 | Phone format | `{"phone": ["Enter 7–15 digits, optionally starting with +."]}` |
| 400 | Address too long | `{"address": ["Ensure this field has no more than 255 characters."]}` |
| 401 | No or invalid token | see [Missing or invalid token](#missing-or-invalid-token-every-protected-endpoint) |

### 2.2 List your patients

`GET /api/patients/` · JWT

`200 OK` with an array of the caller's patient objects, ordered by `id`; `[]` if there are none. Other users' patients never appear.

### 2.3 Get a patient

`GET /api/patients/<id>/` · JWT

`200 OK` with the patient object. **404** `{"detail": "No Patient matches the given query."}` if it doesn't exist or belongs to another user.

### 2.4 Update a patient

`PUT /api/patients/<id>/` · JWT

The body has the same fields as create. `name` and `date_of_birth` must be included; optional fields that are left out keep their current values. The owner and the `id` can't be changed: values sent for them are ignored.

Request:

```http
PUT /api/patients/7/ HTTP/1.1
Authorization: Bearer <access token>
Content-Type: application/json

{"name": "Rahul Mehta", "date_of_birth": "1990-04-12", "address": "14 MG Road, Pune"}
```

`200 OK` with the updated patient object (here `gender` and `phone` keep their earlier values).

Errors: **400** with the same validation messages as create; **404** as for GET. `PATCH` or `POST` on this URL → **405**.

### 2.5 Delete a patient

`DELETE /api/patients/<id>/` · JWT

`204 No Content`, with an empty body. The patient's doctor assignments are deleted with it; the doctors themselves stay. **404** as for GET.

---

## 3. Doctors

Doctors form a **shared directory**:

- Any authenticated user can list, retrieve and add doctors.
- Only the user who added a doctor can update or delete it. Anyone else gets **403** `{"detail": "You do not have permission to perform this action."}`.
- If the account of the user who added a doctor is deleted, the doctor stays in the directory but becomes read-only for everyone through the API.

**The doctor object:**

```json
{
  "id": 3,
  "name": "Dr. Neha Kapoor",
  "specialization": "Cardiology",
  "email": "neha.kapoor@citycare.example",
  "created_at": "2026-10-28T05:35:00.123456Z",
  "updated_at": "2026-10-28T05:35:00.123456Z"
}
```

| Field | Type | Required | Rules |
|---|---|---|---|
| `id` | integer | read-only | |
| `name` | string | yes | 1–150 characters after trimming |
| `specialization` | string | yes | 1–100 characters after trimming; free text |
| `email` | string | yes | a valid email address, at most 254 characters. Trimmed and stored in lower case. Unique across the whole directory, in any letter case |
| `created_at`, `updated_at` | timestamp | read-only | |

Who added the doctor is recorded by the server and is never part of the object.

### 3.1 Add a doctor

`POST /api/doctors/` · JWT

Request:

```http
POST /api/doctors/ HTTP/1.1
Authorization: Bearer <access token>
Content-Type: application/json

{"name": "Dr. Neha Kapoor", "specialization": "Cardiology", "email": "Neha.Kapoor@CityCare.example"}
```

`201 Created` with the doctor object (its email stored as `neha.kapoor@citycare.example`). The caller is recorded as the doctor's creator.

Errors:

| Status | When | Body |
|---|---|---|
| 400 | Required fields missing | `{"name": ["This field is required."], "specialization": ["This field is required."], "email": ["This field is required."]}` (only the missing ones are listed) |
| 400 | Blank or too-long value | for example `{"specialization": ["Ensure this field has no more than 100 characters."]}` |
| 400 | Invalid email | `{"email": ["Enter a valid email address."]}` |
| 400 | Email already in the directory, in any letter case, added by anyone | `{"email": ["A doctor with this email already exists."]}` |
| 401 | No or invalid token | see [Missing or invalid token](#missing-or-invalid-token-every-protected-endpoint) |

Two identical requests arriving at the same moment also end with one doctor and a 400 for the second.

### 3.2 List all doctors

`GET /api/doctors/` · JWT

`200 OK` with an array of **every** doctor, whoever added them, ordered by `id`.

### 3.3 Get a doctor

`GET /api/doctors/<id>/` · JWT

`200 OK` with the doctor object, for any authenticated user. **404** `{"detail": "No Doctor matches the given query."}` if it doesn't exist.

### 3.4 Update a doctor

`PUT /api/doctors/<id>/` · JWT · creator only

The body has the same fields as create, and all three are required. Keeping the doctor's own email is fine; another doctor's email gets the duplicate 400.

`200 OK` with the updated doctor object.

Errors: **400** with the same validation messages as create; **403** if the caller didn't add this doctor; **404** if it doesn't exist. `PATCH` or `POST` on this URL → **405**.

### 3.5 Delete a doctor

`DELETE /api/doctors/<id>/` · JWT · creator only

`204 No Content`, with an empty body.

Errors:

| Status | When | Body |
|---|---|---|
| 403 | The caller didn't add this doctor | `{"detail": "You do not have permission to perform this action."}` |
| 404 | The doctor doesn't exist | `{"detail": "No Doctor matches the given query."}` |
| 409 | The doctor is still assigned to at least one patient, anyone's | `{"detail": "This doctor is assigned to one or more patients. Remove those assignments before deleting the doctor."}` |

On a 409 nothing is deleted. The message doesn't say whose patients they are; the owners of those patients have to remove the assignments first.

---

## 4. Patient–doctor mappings

> [!IMPORTANT]
> **In `/api/mappings/<id>/`, the number means different things for GET and DELETE.** The assignment defines both routes this way, and the API keeps that URL contract unchanged:
>
> | Request | The number is a… | Meaning |
> |---|---|---|
> | `GET /api/mappings/7/` | **patient id** | list the doctors assigned to patient 7 |
> | `DELETE /api/mappings/7/` | **mapping id** | remove assignment 7 |
>
> To remove an assignment, use the mapping's own `id` from a mapping object, never the patient's id.

Every mapping endpoint works only with **the caller's own patients**. Any doctor in the shared directory can be assigned.

**The mapping object** (our design):

```json
{
  "id": 12,
  "patient": 7,
  "patient_name": "Rahul Mehta",
  "doctor": 3,
  "doctor_detail": {
    "id": 3,
    "name": "Dr. Neha Kapoor",
    "specialization": "Cardiology",
    "email": "neha.kapoor@citycare.example",
    "created_at": "2026-10-28T05:35:00.123456Z",
    "updated_at": "2026-10-28T05:35:00.123456Z"
  },
  "created_at": "2026-10-28T05:40:00.123456Z"
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | integer | the **mapping id**: use it for `DELETE /api/mappings/<id>/` |
| `patient` | integer | the patient's id; writable on create |
| `patient_name` | string | read-only |
| `doctor` | integer | the doctor's id; writable on create |
| `doctor_detail` | object | read-only; the full [doctor object](#3-doctors) |
| `created_at` | timestamp | read-only |

### 4.1 Assign a doctor to a patient

`POST /api/mappings/` · JWT

| Field | Type | Required | Rules |
|---|---|---|---|
| `patient` | integer | yes | the id of one of **the caller's** patients |
| `doctor` | integer | yes | the id of any doctor in the directory |

Request:

```http
POST /api/mappings/ HTTP/1.1
Authorization: Bearer <access token>
Content-Type: application/json

{"patient": 7, "doctor": 3}
```

`201 Created` with the mapping object. An `id` or other unknown fields in the body are ignored.

Errors:

| Status | When | Body |
|---|---|---|
| 400 | Fields missing | `{"patient": ["This field is required."], "doctor": ["This field is required."]}` (only the missing ones are listed) |
| 400 | The patient doesn't exist **or belongs to another user** (the same message for both) | `{"patient": ["Invalid pk \"9\" - object does not exist."]}` |
| 400 | The doctor doesn't exist | `{"doctor": ["Invalid pk \"99\" - object does not exist."]}` |
| 400 | This doctor is already assigned to this patient | `{"non_field_errors": ["This doctor is already assigned to this patient."]}` |
| 401 | No or invalid token | see [Missing or invalid token](#missing-or-invalid-token-every-protected-endpoint) |

Duplicates are blocked by the serializer and by a database constraint. Two identical requests arriving at the same moment also end with exactly one mapping and the same 400 for the second.

### 4.2 List your assignments

`GET /api/mappings/` · JWT

`200 OK` with an array of mapping objects for **the caller's patients only**, ordered by `id`. Assignments of other users' patients never appear, even when they use a doctor the caller added.

### 4.3 List a patient's doctors

`GET /api/mappings/<patient_id>/` · JWT · **the number is a patient id**

The assignment specifies only the purpose: "Get all doctors assigned to a specific patient".

`200 OK` with an array of that patient's mapping objects, ordered by `id`. Each contains the doctor's details in `doctor_detail` and the mapping `id` that DELETE needs. `[]` if no doctors are assigned.

**404** `{"detail": "No Patient matches the given query."}` if the patient doesn't exist or belongs to another user. A mapping id sent here is still read as a patient id.

### 4.4 Remove an assignment

`DELETE /api/mappings/<mapping_id>/` · JWT · **the number is a mapping id**

`204 No Content`, with an empty body. Only the assignment is removed; the patient and the doctor stay.

**404** `{"detail": "No PatientDoctorMapping matches the given query."}` if the mapping doesn't exist or its patient belongs to another user.

`PUT`, `PATCH` or `POST` on `/api/mappings/<id>/` → **405**. `PUT` or `DELETE` on `/api/mappings/` → **405**.

---

## 5. Status codes

| Status | Meaning in this API |
|---|---|
| 200 OK | A successful GET, PUT, login or token refresh |
| 201 Created | A successful registration, or a patient, doctor or mapping was created |
| 204 No Content | A successful DELETE; the body is empty |
| 400 Bad Request | Validation failed, a duplicate, malformed JSON, or a body over 2.5 MB |
| 401 Unauthorized | No token, an invalid or expired token, or a failed login |
| 403 Forbidden | Updating or deleting a doctor the caller didn't add |
| 404 Not Found | The object doesn't exist or isn't the caller's, or the URL matches no route |
| 405 Method Not Allowed | A method outside the contract, such as `PATCH` |
| 409 Conflict | Deleting a doctor who is still assigned |
| 415 Unsupported Media Type | The body isn't JSON |
| 500 Internal Server Error | An unexpected server error; the body never contains internal details |

**Why 404 for patients but 403 for doctors?** Another user's patients are invisible to you, so "not found" is the honest answer and reveals nothing. Doctors are visible to everyone, so "you can see it, but you may not change it" is a 403. Creating a mapping for another user's patient is a 400 rather than a 404, because the patient id is in the request body rather than the URL.

## 6. Behaviour with DEBUG on and off

`DEBUG` is off unless `DJANGO_DEBUG` turns it on; `.env.example` turns it on for local development. Errors raised inside the API's views (validation, 401, 403, 404 for a missing object, 405, 409 and 415) are JSON either way. The differences are in what Django itself answers:

| Situation | `DEBUG` off (the default) | `DEBUG` on (local development) |
|---|---|---|
| A URL that matches no route | 404 `{"detail": "Not found."}` | Django's HTML debug page (404) |
| An unexpected exception | 500 `{"detail": "A server error occurred."}`; the traceback is written to the server log | Django's HTML debug page with the traceback |
| A body over 2.5 MB | 400 `{"detail": "Request body is too large."}` | Django's HTML debug page (400) |
| A POST, PUT or DELETE without the trailing slash | 301 redirect to the URL with the slash; the body is dropped and nothing is saved | an error page explaining that the URL must end with a slash |

## 7. Not available

- Logout, token revocation and refresh-token rotation
- Endpoints for listing, updating or deleting users, or for changing or resetting a password
- `PATCH` (partial updates)
- Pagination, filtering and search
- An OpenAPI schema or Swagger UI; this page and the Postman collection document the API instead
