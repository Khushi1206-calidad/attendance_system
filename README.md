# Attendance Service

Reads attendance from an eSSL/ZKTeco device into PostgreSQL and shows it in a
web UI.

- **Backend**: Django 5.2 + Django Ninja — REST API (JSON), models, migrations,
  and the `sync` command.
- **Frontend**: Next.js 15 + React 19 + TypeScript — calls the backend's REST API.

```text
external scheduler -> python manage.py sync -> device snapshot
                   -> validate -> insert new rows -> audit -> exit
browser -> Next.js (:3000) -> /api/* -> Django Ninja (:8000) -> PostgreSQL (read-only)
```

The sync never clears or changes device attendance data. It contains no
scheduler of its own; run it from cron or Windows Task Scheduler.

## Project structure

```text
attendance_system/
├── backend/                       Django + Django Ninja
│   ├── manage.py
│   ├── requirements.txt
│   ├── .env.example               copy to .env
│   ├── config/                    settings.py, urls.py, asgi.py, wsgi.py
│   └── attendance/                Django app
│       ├── api.py                 REST endpoints (Django Ninja)
│       ├── schemas.py             API response schemas
│       ├── models.py              database tables
│       ├── migrations/
│       ├── middleware.py          request logging and x-request-id
│       ├── dependencies.py        API configuration and read-only repository
│       ├── management/commands/   sync, report, device-test, capacity, web
│       └── services/              device access, validation, sync, work-hours
│                                  and daily-report calculations, Excel report
├── frontend/                      Next.js
│   ├── app/                       layout.tsx, page.tsx, globals.css
│   ├── components/                SummaryTab, LookupTab, Warnings
│   ├── lib/                       api.ts, types.ts, format.ts
│   └── next.config.ts             forwards /api/* to the backend
└── scripts/                       run_sync.sh, run_web.sh (cron), AttendanceSync.ps1
```

## Setup

Requirements: Python 3.11+, PostgreSQL, Node.js 20+.

Backend (Linux/macOS; on Windows use `.venv\Scripts\` instead of `.venv/bin/`):

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env              # then edit .env
.venv/bin/python manage.py migrate
```

Edit `.env` for the PostgreSQL database and the device. Do not commit `.env`.
Required decisions are explicit settings rather than hidden rules:

- `ATTENDANCE_SOURCE_KEY`: stable logical device identity
- `ATTENDANCE_DEVICE_TIMEZONE`: IANA name such as `Asia/Kolkata`
- `ATTENDANCE_MIN_VALID_TIMESTAMP`: earliest accepted device-local timestamp
- `ATTENDANCE_MAX_FUTURE_SECONDS`: tolerated device clock lead

A `@` in the database password must be written as `%40` in
`ATTENDANCE_DATABASE_URL`.

Frontend:

```bash
cd frontend
npm ci
npm run build
```

## Commands

Run from `backend/` (shown with an activated virtual environment). Settings are
read from `backend/.env`; `python manage.py --env-file PATH <command>` uses
another file. Variables already set in the environment take precedence.

| Command | Purpose |
|---|---|
| `python manage.py migrate` | Create or update the database schema |
| `python manage.py sync [--mode manual]` | One device-to-PostgreSQL sync |
| `python manage.py web [--host H] [--port P]` | Start the REST API (uvicorn) |
| `python manage.py report --output attendance_report.xlsx` | Excel report from PostgreSQL |
| `python manage.py device-test` | Read the device without storing anything |
| `python manage.py capacity` | Device storage and biometric capacity |
| `python manage.py check` | Django configuration check |

## Synchronization

```bash
python manage.py sync
```

The first run backfills the device history and is audited as `initial`. Later
runs are audited as `scheduled` (or `manual` with `--mode manual`) and use the
same idempotent code.

Exit codes:

| Code | Meaning |
|---:|---|
| 0 | Synchronization completed, including a run containing only duplicates |
| 1 | Device, database, report, or unexpected operational failure |
| 2 | Missing or invalid configuration |
| 3 | Another synchronization already owns the source lock |

Safety and data model:

- Every device read is a complete snapshot of the records on the device.
  PostgreSQL uniqueness and `ON CONFLICT DO NOTHING` make retries idempotent.
- `pyzk` exposes no reliable event ID, so records are identified by
  `(source_id, employee_id, original_device_timestamp)`.
- Employee IDs are stored as text (leading zeroes kept). Device-local
  timestamps are kept unchanged; valid records also get a UTC `occurred_at_utc`
  derived with `ATTENDANCE_DEVICE_TIMEZONE`.
- Rejected timestamps (for example the observed year-2119 values) go to
  `invalid_attendance_events` with the same duplicate protection.
- Raw `status` and `punch` values are stored as text without interpretation.
  Attendance events are never updated or deleted.
- A source-specific PostgreSQL advisory lock is taken before connecting to the
  device; an overlapping run exits with code `3` without contacting the device.
- Temporary device and database failures are retried with bounded exponential
  backoff. Each run is recorded in `attendance_sync_runs` as `running`,
  `succeeded`, or `failed`.
- The device always returns its full log. Only punches newer than the newest
  stored punch minus `ATTENDANCE_SYNC_LOOKBACK_SECONDS` (default 86400) are
  written; older ones are counted as `skipped_older`. The roster update and all
  inserts of a run share one transaction, so a failed run writes no attendance
  rows.
- Each run logs `sync_started`, then `sync_succeeded` (`fetched`,
  `skipped_older`, `inserted`, `invalid_inserted`, `duplicates`, `duration_ms`)
  or `sync_failed` as JSON lines.

## Scheduling

### cron (Linux)

`scripts/run_sync.sh` checks every minute whether the device is reachable,
syncs as soon as it becomes reachable, and otherwise every 5 minutes.
`scripts/run_web.sh` starts the API and the UI unless they are already running.

```cron
* * * * * /path/to/attendance_system/scripts/run_sync.sh
@reboot sleep 30 && /path/to/attendance_system/scripts/run_web.sh
```

Logs are written to `logs/`. Overlap is guarded by the database advisory lock.

### Windows Task Scheduler

Every 5 minutes, from an elevated PowerShell (`/RU SYSTEM` runs whether or not
anyone is logged on):

```powershell
schtasks /Create /SC MINUTE /MO 5 /TN "Attendance PostgreSQL Sync" /RU SYSTEM /TR "\"D:\attendance_system\backend\.venv\Scripts\python.exe\" \"D:\attendance_system\backend\manage.py\" sync --mode scheduled"
```

`scripts/AttendanceSync.ps1` is a standalone single-file alternative for a
Windows machine without this project; a database it creates is adopted by
`python manage.py migrate` unchanged.

## REST API

```bash
python manage.py web          # http://127.0.0.1:8000
```

Configure with `ATTENDANCE_API_HOST`, `ATTENDANCE_API_PORT` (or `--host`/`--port`)
and `ATTENDANCE_API_ALLOWED_HOSTS`. Interactive documentation is at
`http://127.0.0.1:8000/docs` (OpenAPI schema at `/openapi.json`). The API reads
through a pooled, read-only database connection
(`ATTENDANCE_API_DB_POOL_MIN_SIZE`/`MAX_SIZE`); the commands use a separate
read-write connection.

```text
GET /api/v1/employees?query=khushi
GET /api/v1/employees/{employee_id}/work-hours?date=YYYY-MM-DD
GET /api/v1/attendance/daily?date=YYYY-MM-DD   (date optional, defaults to the current working day)
```

Errors use `{"error": {"code": "...", "message": "..."}}` with status 404
(`employee_not_found`), 422 (`invalid_request`, `invalid_query`,
`future_date`), 503 (`database_unavailable`), or 500 (`internal_error`). Every
response carries an `x-request-id` header.

## Web UI

```bash
cd frontend
npm run start                 # http://127.0.0.1:3000  (npm run dev while developing)
```

The browser only calls same-origin `/api/*`; Next.js forwards those requests to
the API at `ATTENDANCE_API_URL` (default `http://127.0.0.1:8000`, read at build
time). Database and device credentials stay in the backend. `npm run typecheck`
checks the TypeScript.

The **Summary** tab lists who is **present** (at least one punch that day) and
who is **not in yet** (for past dates: **absent**). The expected employees are
the device's enrolled users, which each `sync` stores in the `employees` table:
users missing from a snapshot are marked inactive, and an empty user list never
deactivates anyone. People who punched but are not enrolled are still shown as
present, with an `unregistered_employees` warning. Future dates return
`422 future_date`. `data_as_of` is the time of the last successful sync. Leave,
work-from-home, and late arrivals are not tracked.

The **Employee lookup** tab searches names case-insensitively within
`ATTENDANCE_SOURCE_KEY` and then uses the selected `employee_id`.

A selected date D is a **working day**: from D at `ATTENDANCE_WORKING_DAY_CUTOFF`
(default `06:00`) to D+1 at the same time, in `ATTENDANCE_DEVICE_TIMEZONE`, so
after-midnight night-shift punches count toward the previous day. Both ends use
local wall-clock time (daylight-saving days are 23 or 25 hours); `00:00` gives
plain calendar days. Before the cutoff, "today" is still the previous working
day. Limitations:

- A shift that runs past the cutoff (for example 22:00 → 07:00) is split across
  two working days; this needs shift definitions to resolve.
- Results are computed on read, so changing the cutoff changes every past day.

The calculation method is `first_last_span`, shown as **Total attendance span
(breaks included)**:

- zero punches: no duration and a `no_attendance` warning;
- one punch: no duration and an `insufficient_punches` warning;
- two or more: last punch minus first punch;
- odd counts of three or more: calculated normally plus `odd_punch_count`;
- spans over `ATTENDANCE_UNREASONABLE_SPAN_SECONDS`: kept, plus
  `unreasonable_span`.

`breaks_excluded` is always `false`: this is an attendance span, not net working
time, which would need confirmed IN/OUT semantics or a company break policy.

## Deployment security

The API and UI have no authentication and must stay bound to localhost.
**Authentication and authorization are mandatory before company-wide, LAN,
internet, reverse-proxy, or shared-host deployment.** Use a PostgreSQL account
with `SELECT` permission only for the API, and set up TLS, access rules, and
audit requirements before changing the bind address.

## Schema migrations

The schema is defined in `backend/attendance/models.py` and versioned under
`backend/attendance/migrations/`. Apply with `python manage.py migrate`; after
changing a model, create a migration with `python manage.py makemigrations`.
The initial migration uses idempotent SQL, so it creates the schema on a new
database and adopts an existing one (created by the earlier Alembic setup or
`scripts/AttendanceSync.ps1`) without changing it. Startup never modifies the
schema. Never point development commands at a production database.
