# Healthcare Backend

A REST API for a small healthcare application, built with Django, Django REST Framework and PostgreSQL for the WhatBytes Backend Developer Intern assignment. Users register and log in with JWT authentication, manage their own patient records, share a directory of doctors, and assign doctors to their patients.

> [!IMPORTANT]
> **In `/api/mappings/<id>/`, the number means different things for GET and DELETE.** The assignment defines both routes this way, and the API keeps that URL contract unchanged:
>
> | Request | The number is a… | Meaning |
> |---|---|---|
> | `GET /api/mappings/7/` | **patient id** | list the doctors assigned to patient 7 |
> | `DELETE /api/mappings/7/` | **mapping id** | remove assignment 7 |
>
> To remove an assignment, use the mapping's own `id` from a mapping object, never the patient's id.

## Contents

- [Features](#features)
- [Assignment requirements and our design](#assignment-requirements-and-our-design)
- [Technology stack](#technology-stack)
- [Project structure](#project-structure)
- [Setup](#setup)
- [Environment variables](#environment-variables)
- [Authentication](#authentication)
- [API overview](#api-overview)
- [Running the tests](#running-the-tests)
- [Postman collection and Newman](#postman-collection-and-newman)
- [Troubleshooting](#troubleshooting)
- [Design decisions](#design-decisions)
- [Known limitations](#known-limitations)
- [Further documentation](#further-documentation)

## Features

- **Accounts:** register with a name, email and password, then log in with email and password to receive a JWT access token and refresh token. An extra endpoint exchanges a refresh token for a new access token.
- **Emails** are trimmed and stored in lower case, and uniqueness ignores letter case. **Passwords** must pass Django's password validators and are stored only as hashes.
- **Default deny:** every endpoint except register, login and token refresh requires a valid access token.
- **Patients** are private to the user who created them. Another user's patient returns 404, exactly like one that doesn't exist.
- **Doctors** form a shared directory. Every user can read them, but only the user who added a doctor can update or delete it (403 for anyone else). A doctor who is still assigned to a patient can't be deleted (409).
- **Mappings** assign any doctor to one of your own patients. Each patient–doctor pair can exist only once, enforced by the serializer and by a database constraint.
- **Consistent errors:** request bodies must be JSON, and errors come back as JSON with the matching status code. With `DEBUG` off, unknown URLs, oversized bodies and unexpected server errors also get JSON responses, and tracebacks go to the server log, never to the client.
- **Tested:** 133 automated tests run on PostgreSQL, and a Postman collection of 38 requests can be run automatically with Newman.

## Assignment requirements and our design

The assignment fixes the technology stack and, for each endpoint, only the HTTP method, the path and a one-line purpose. Everything else is our design: field definitions, request and response bodies, status codes, error messages, ownership rules, and the extra token-refresh endpoint. The main decisions are summarised under [Design decisions](#design-decisions). In particular, the response shapes of the mapping endpoints are our design, not an assignment requirement.

## Technology stack

| Component | Version | Role |
|---|---|---|
| Python | 3.12 or 3.13 | Runtime (avoid 3.14) |
| Django | 5.2.18 (LTS) | Web framework and ORM |
| Django REST Framework | 3.18.3 | REST API layer |
| djangorestframework-simplejwt | 5.5.1 (with PyJWT 2.15.1) | JWT login and authentication |
| psycopg | 3.3.6 (binary build) | PostgreSQL driver |
| python-dotenv | 1.2.4 | Loads `.env` into the environment |
| PostgreSQL | 14 or newer | Database, for development and for tests |

Every package, including the ones installed indirectly, is pinned in [requirements.txt](requirements.txt). The test suite was run on Windows 11 with Python 3.12 and PostgreSQL 18.6.

## Project structure

```text
healthcare-backend/
├── manage.py
├── requirements.txt          # pinned dependencies
├── .env.example              # template for .env, with placeholder values only
├── config/                   # project package
│   ├── settings.py           # all settings, read from environment variables
│   ├── urls.py               # mounts the four apps; JSON error handlers
│   ├── views.py              # JSON handler400, handler404 and handler500
│   ├── tests.py              # project-wide tests (errors, tokens, logging, settings)
│   ├── asgi.py
│   └── wsgi.py
├── accounts/                 # custom User model, register, login, token refresh
├── patients/                 # patient records, private to their creator
├── doctors/                  # shared doctor directory, creator-only writes
├── mappings/                 # patient–doctor assignments
├── postman/
│   └── healthcare-backend.postman_collection.json
└── docs/                     # requirements, design, architecture, API reference
```

Each app has `models.py`, `serializers.py`, `views.py`, `urls.py`, `tests.py` and `migrations/`. `patients` and `doctors` also have `permissions.py`, and `accounts` has `managers.py`.

| App | Responsibility |
|---|---|
| `accounts` | `User` (email login, a single `name` field, no username), `UserManager` (normalises emails, hashes passwords), registration and login serializers and views |
| `patients` | `Patient` with its owner (`created_by`); every query is filtered to the caller's patients |
| `doctors` | `Doctor` in a shared directory; `IsCreatorOrReadOnly` limits changes to the user who added the doctor; `DoctorInUse` (409) |
| `mappings` | `PatientDoctorMapping`, unique per patient–doctor pair; list, assign, list by patient, remove |

## Setup

Windows PowerShell is the primary path: these are the commands used on the Windows development machine. The macOS and Linux equivalents are provided for convenience but **were not tested**.

### Prerequisites

- Git
- Python 3.12 or 3.13
- PostgreSQL 14 or newer, with the `psql` client
- Optional: the Postman app, or Node.js 16 or newer (with npm) to run the collection with Newman

### 1. Clone the repository

```powershell
git clone <repository-url>
cd <repository-folder>
```

### 2. Create and activate a virtual environment

Create it with a supported Python version. On Windows, the `py` launcher selects the version explicitly, which matters when the default `python` is a newer, unsupported release (check with `python --version` and `py --list`):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version          # should print Python 3.12.x
```

If PowerShell refuses to run `Activate.ps1` ("running scripts is disabled on this system"), allow scripts for the current window only, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

macOS and Linux (not tested here):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

### 3. Install the dependencies

```powershell
python -m pip install -r requirements.txt
python -m pip check       # "No broken requirements found."
```

### 4. Create the PostgreSQL role and database

The application connects as a dedicated role, not as the `postgres` superuser. The role needs:

| Requirement | Why |
|---|---|
| `LOGIN` | Django connects as this role |
| `CREATEDB` | the test runner creates and drops a temporary `test_healthcare_db` |
| owner of `healthcare_db` | from PostgreSQL 15, only the database owner (or a role granted the right) can create tables in schema `public`; without it `migrate` fails |
| **not** a superuser | least privilege |

On Windows, `psql` is usually not on `PATH`. Call it by its full path, adjusting the version number to your installation:

```powershell
$psql = "C:\Program Files\PostgreSQL\18\bin\psql.exe"
& $psql -U postgres -c "CREATE ROLE healthcare_user WITH LOGIN CREATEDB;"
& $psql -U postgres -c "\password healthcare_user"
& $psql -U postgres -c "CREATE DATABASE healthcare_db OWNER healthcare_user;"
```

Run the three commands **one at a time**. Each first asks for the password of the `postgres` superuser (the one chosen when PostgreSQL was installed). The `\password` command then asks twice for the new password of `healthcare_user`; nothing is shown while you type, and the password doesn't end up in your shell history. Remember it for `DB_PASSWORD` in the next step. Don't paste several lines into an interactive `psql` prompt while it's waiting for a password, because the prompt consumes the pasted lines.

To check the result (expected: `healthcare_user | f | t | t`):

```powershell
& $psql -U postgres -c "SELECT rolname, rolsuper, rolcreatedb, rolcanlogin FROM pg_roles WHERE rolname = 'healthcare_user';"
```

macOS and Linux (not tested here): run the same three statements as a PostgreSQL superuser, for example `sudo -u postgres psql -c "..."` on most Linux distributions, or `psql postgres -c "..."` where your own account is the superuser (common with Homebrew).

### 5. Create your `.env` file

Copy the template **only if `.env` doesn't exist yet**. Never overwrite an existing `.env`, because it holds your secrets:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env } else { ".env already exists: edit it instead of replacing it" }
```

macOS and Linux (not tested here): `[ -f .env ] || cp .env.example .env`

Generate a secret key (the virtual environment must be active). It's printed only in your terminal:

```powershell
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

Open `.env` in an editor and replace the two placeholders. Wrap both values in single quotes, as `.env.example` advises: a generated key can contain characters such as `#` and `$`, and the quotes keep the value intact.

```dotenv
DJANGO_SECRET_KEY='<the key you just generated>'
DB_PASSWORD='<the password you set for healthcare_user>'
```

Keep the other values unless your PostgreSQL setup differs. `.env` is ignored by Git; never commit it, and never paste its values into issues, logs or documentation.

### 6. Check the configuration and apply the migrations

```powershell
python manage.py check       # System check identified no issues (0 silenced).
python manage.py migrate     # on an empty database, applies 22 migrations
```

### 7. Run the tests

```powershell
python manage.py test --noinput
```

Expected: `Ran 133 tests` followed by `OK`. See [Running the tests](#running-the-tests).

### 8. Start the development server

```powershell
python manage.py runserver
```

The API is now at `http://127.0.0.1:8000/api/`. There is no page at `/` or `/api/` itself; every endpoint is listed in the [API overview](#api-overview). Call them with Postman (see [below](#postman-collection-and-newman)) or any HTTP client that can send JSON and an `Authorization` header.

`/admin/` is Django's admin site. No project models are registered in it (an optional item that wasn't implemented).

## Environment variables

`config/settings.py` loads `.env` with python-dotenv. Variables already set in the real environment take precedence over `.env`.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DJANGO_SECRET_KEY` | yes | none: startup stops with `ImproperlyConfigured` | Signs sessions and JWTs. Changing it invalidates every issued token |
| `DJANGO_DEBUG` | no | `False` | Debug pages and detailed errors. Accepts true/false, 1/0, yes/no, on/off; anything else stops startup. `.env.example` sets `True` for local development only |
| `DJANGO_ALLOWED_HOSTS` | no | `localhost,127.0.0.1` | Comma-separated host names the server answers to |
| `DB_NAME` | yes | — | PostgreSQL database name (`healthcare_db`) |
| `DB_USER` | yes | — | PostgreSQL role (`healthcare_user`) |
| `DB_PASSWORD` | yes | — | That role's password |
| `DB_HOST` | no | `localhost` | Database host |
| `DB_PORT` | no | `5432` | Database port |

A required variable that is missing or blank stops startup with a message naming it, for example `DJANGO_SECRET_KEY is not set. Copy .env.example to .env and fill it in.`

## Authentication

1. `POST /api/auth/register/` with `name`, `email` and `password` → `201` with `{id, name, email}`. No tokens are returned on registration.
2. `POST /api/auth/login/` with `email` and `password` → `200` with `{refresh, access}`.
3. Send the access token on every other request: `Authorization: Bearer <access token>`.
4. When the access token expires, protected endpoints return `401` with `"code": "token_not_valid"`. `POST /api/auth/token/refresh/` with `{refresh}` returns a new `{access}`; when the refresh token has expired too, log in again.

| Setting | Value |
|---|---|
| Access token lifetime | 30 minutes |
| Refresh token lifetime | 1 day |
| Signing | HS256 with `DJANGO_SECRET_KEY` |
| Refresh token rotation | no: refresh returns only a new access token |
| Logout or token revocation | not available: a token stays valid until it expires |

Registration is public and ignores any `Authorization` header, so a stale token left in a client can't block it. Login gives the same `401` for a wrong password, an unknown email and an inactive account, so it doesn't reveal which emails are registered.

## API overview

The full reference, with request bodies, response shapes, validation rules and every error, is in **[docs/api.md](docs/api.md)**.

| # | Method | Path | Auth | Purpose |
|---|---|---|---|---|
| 1 | POST | `/api/auth/register/` | public | Register with name, email and password |
| 2 | POST | `/api/auth/login/` | public | Email and password → access and refresh tokens |
| 3 | POST | `/api/auth/token/refresh/` | public | Refresh token → new access token (our addition) |
| 4 | POST | `/api/patients/` | JWT | Create a patient |
| 5 | GET | `/api/patients/` | JWT | List your patients |
| 6 | GET | `/api/patients/<id>/` | JWT | Get one of your patients |
| 7 | PUT | `/api/patients/<id>/` | JWT | Update one of your patients |
| 8 | DELETE | `/api/patients/<id>/` | JWT | Delete one of your patients |
| 9 | POST | `/api/doctors/` | JWT | Add a doctor to the shared directory |
| 10 | GET | `/api/doctors/` | JWT | List all doctors |
| 11 | GET | `/api/doctors/<id>/` | JWT | Get a doctor |
| 12 | PUT | `/api/doctors/<id>/` | JWT | Update a doctor you added |
| 13 | DELETE | `/api/doctors/<id>/` | JWT | Delete a doctor you added (409 while assigned) |
| 14 | POST | `/api/mappings/` | JWT | Assign a doctor to one of your patients |
| 15 | GET | `/api/mappings/` | JWT | List the assignments of your patients |
| 16 | GET | `/api/mappings/<patient_id>/` | JWT | Doctors assigned to one of your patients (**patient id**) |
| 17 | DELETE | `/api/mappings/<id>/` | JWT | Remove an assignment (**mapping id**) |

Conventions:

- Every URL ends with `/`.
- Request bodies are JSON (`Content-Type: application/json`); any other body type gets `415`.
- `PATCH` isn't supported; updates use `PUT`, and `PATCH` returns `405`.
- Lists are returned in full, ordered by `id`. There is no pagination, filtering or search.
- Dates are `YYYY-MM-DD`; timestamps are ISO 8601 in UTC.

## Running the tests

The suite uses Django's test runner with DRF's `APITestCase`, always on PostgreSQL. Each run creates a temporary database, `test_healthcare_db`, applies every migration to it, and drops it at the end. The development database is never touched.

```powershell
python manage.py test --noinput               # everything: 133 tests
python manage.py test patients --noinput      # one app
```

`--noinput` matters after an interrupted run: if `test_healthcare_db` was left behind, Django would otherwise stop and ask whether to delete it; with `--noinput` it deletes it and continues.

| File | Tests | Covers |
|---|---|---|
| `accounts/tests.py` | 49 | user model and manager, password policy, registration, login, refresh, the real-JWT flow |
| `patients/tests.py` | 26 | CRUD and validation, no token, real JWT, isolation between two users |
| `doctors/tests.py` | 21 | CRUD and validation, creator-only writes, duplicate emails, 409 while assigned |
| `mappings/tests.py` | 22 | assign, list, list by patient, remove, duplicates, isolation, patient id vs mapping id |
| `config/tests.py` | 15 | JSON errors (400, 404, 405, 415, 500), oversized bodies, the token lifecycle, what responses expose, the settings helpers |

## Postman collection and Newman

[postman/healthcare-backend.postman_collection.json](postman/healthcare-backend.postman_collection.json) walks through every endpoint in 38 requests (six folders, 112 assertions). Each run registers two users, A and B, with unique emails, saves their tokens and the ids it creates in collection variables, checks status codes and response bodies, and finally deletes the patient, doctor and mapping it created.

The two users remain afterwards, because the API has no endpoint for deleting users. Every run therefore adds two users to the database the server uses. To keep them out of your development data, point that server at a separate database (created and migrated first), for example by setting `DB_NAME` for the server process only (real environment variables override `.env`).

### In the Postman app

1. Start the server (`python manage.py runserver`).
2. Import the collection file into Postman.
3. Check the collection variable `baseUrl` (default `http://127.0.0.1:8000`).
4. Run the whole collection, in order, with Postman's collection runner. Later requests depend on tokens and ids saved by earlier ones. A request whose prerequisite failed or was skipped stops with `Missing <name>: an earlier request in this run failed or was skipped.`

### With Newman

Newman 6.2.3 needs Node.js 16 or newer. With the server running, from the repository root:

```powershell
npx --yes newman@6.2.3 run postman/healthcare-backend.postman_collection.json --env-var "baseUrl=http://127.0.0.1:8000" --reporters cli --bail
```

On the development machine (npm 11.6.2), `npx` failed with `ECOMPROMISED: Lock compromised` before Newman started. The verified alternative installs Newman into a temporary folder **outside the repository** and runs it from there:

```powershell
$newmanDir = Join-Path $env:TEMP "newman-6.2.3"
npm install --prefix $newmanDir newman@6.2.3
& (Join-Path $newmanDir "node_modules\.bin\newman.cmd") run postman/healthcare-backend.postman_collection.json --env-var "baseUrl=http://127.0.0.1:8000" --reporters cli --bail
```

macOS and Linux (not tested here): `npm install --prefix /tmp/newman-6.2.3 newman@6.2.3`, then `/tmp/newman-6.2.3/node_modules/.bin/newman run ...` with the same arguments.

A successful run reports 38 requests and 112 assertions with 0 failures. Newman is a verification tool only; it isn't part of `requirements.txt`, and nothing it installs belongs in the repository.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ImproperlyConfigured: DJANGO_SECRET_KEY is not set. Copy .env.example to .env and fill it in.` (or the same for a `DB_` variable) | `.env` is missing, or the value is blank | Create `.env` (step 5) and fill in the value |
| `ImproperlyConfigured: DJANGO_DEBUG must be true or false, not '...'.` | A typo in `DJANGO_DEBUG` | Use true/false, 1/0, yes/no or on/off |
| `password authentication failed for user "healthcare_user"` | `DB_PASSWORD` doesn't match the role's password | Fix `.env`, or set a new password with `\password healthcare_user` |
| `Connection refused` on port 5432 | PostgreSQL isn't running, or listens on another port | Start the service (on Windows, `Get-Service postgresql*` shows it), or set `DB_PORT` |
| `permission denied for schema public` during `migrate` | The role doesn't own the database (PostgreSQL 15+) | As `postgres`: `ALTER DATABASE healthcare_db OWNER TO healthcare_user;` |
| `permission denied to create database` when the tests start | The role lacks `CREATEDB` | As `postgres`: `ALTER ROLE healthcare_user CREATEDB;` |
| The test run asks whether to delete `test_healthcare_db` | A previous run was interrupted | Run the tests with `--noinput` |
| `The term 'psql' is not recognized ...` | `psql` isn't on `PATH` (common on Windows) | Use its full path, as in step 4 |
| `Activate.ps1 cannot be loaded because running scripts is disabled on this system` | PowerShell's execution policy | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`, then activate again |
| `python --version` inside `.venv` shows 3.14 or another unsupported version | The environment was created with the default `python` | Delete `.venv` and recreate it with `py -3.12 -m venv .venv` (or 3.13) |
| `401` `Authentication credentials were not provided.` | No `Authorization` header | Send `Authorization: Bearer <access token>` |
| `401` `Given token not valid for any token type` (`token_not_valid`) | The access token expired (30 minutes), was altered, or is the refresh token | Refresh it, or log in again; send the **access** token as the Bearer token |
| `401` `No active account found with the given credentials` | Wrong email or password, or an inactive account | Check the credentials; the message is deliberately the same for every case |
| `415` `Unsupported media type ...` | The body isn't JSON | Send JSON with `Content-Type: application/json` (in Postman: Body → raw → JSON) |
| A POST without the trailing slash fails (an error page with `DEBUG` on, a redirect that drops the body with `DEBUG` off) | Every URL ends with `/` | Add the trailing slash |
| An HTML page instead of JSON for an unknown URL or a server error | `DJANGO_DEBUG=True` shows Django's debug pages; the JSON handlers apply only with `DEBUG` off | Expected locally. To see the production behaviour, start the server with `$env:DJANGO_DEBUG = "False"` set in that PowerShell window (remove it afterwards with `Remove-Item Env:DJANGO_DEBUG`) |
| A browser shows an HTML page for an API URL | DRF's browsable API renderer answers browsers; session login isn't enabled | Use Postman or another HTTP client with a Bearer token |
| `GET /api/mappings/<id>/` returns `404`, or a different patient's assignments | The number was a mapping id; GET expects a **patient** id | See the warning at the top of this file |
| `Missing accessA: an earlier request in this run failed or was skipped.` in Postman | A request was run without the earlier ones | Run the collection from the start, in order |

## Design decisions

The decisions that most affect API users:

| Area | Decision |
|---|---|
| Users and emails | Custom `User(AbstractUser)` with email login and one `name` field; emails trimmed and lower-cased everywhere, unique regardless of letter case |
| JWT | 30-minute access and 1-day refresh tokens; an extra refresh endpoint; no rotation, blacklist or logout |
| Default deny | Default deny: JWT authentication only, `IsAuthenticated` globally, JSON-only input |
| HTTP methods | Exactly the methods the assignment lists; `PATCH` returns 405 |
| Patient ownership | Patients are private; another user's patient returns 404, not 403, so its existence isn't revealed |
| Doctor directory | Shared doctor directory with creator-only writes (403); an assigned doctor can't be deleted (409, `PROTECT`) |
| Mappings | Mappings only for your own patients; duplicates blocked by the serializer, the database and a race-safe savepoint (400) |
| Mapping URLs and responses | One mapping detail route (patient id for GET, mapping id for DELETE); mapping objects include nested doctor details |
| Pagination | No pagination; lists ordered by `id` |
| Configuration and errors | Secrets only from the environment, `DEBUG` off by default; DRF's standard error shapes, JSON error handlers, tracebacks logged server-side |

## Known limitations

- **No logout or token revocation.** Tokens stay valid until they expire, and refresh tokens aren't rotated.
- **No pagination, filtering or search**; every list is returned in full.
- **No rate limiting** on register and login (optional; not implemented).
- **No HTTPS configuration.** `python manage.py check --deploy` with `DEBUG` off reports the four HTTPS-related warnings (W004, W008, W012, W016); they belong to a deployment, which is out of scope.
- **No Django admin pages** for the project's models, and no OpenAPI/Swagger UI; both were optional.
- **Passwords have no maximum length** beyond Django's 2.5 MB request-body limit.
- **No endpoint for deleting users**, so each Postman or Newman run leaves its two test users behind.
- **A doctor whose creator's account is deleted** stays in the directory but becomes read-only through the API.
- **"Today" for the date-of-birth check is the date in UTC**, not the client's local date.
- **No compliance claim** (HIPAA, India's DPDP Act or any other regulation). The project applies basic security practices only.

## Further documentation

| Document | Contents |
|---|---|
| [docs/api.md](docs/api.md) | API reference: every endpoint, field, status code and error |
| [docs/design.md](docs/design.md) | Data model, validation rules, ownership, deletion behaviour, the API contract and error conventions |
| [docs/architecture.md](docs/architecture.md) | Components, request lifecycle, authentication and authorization flows, configuration |
| [docs/class.md](docs/class.md) | Every class in the project and what it does |
