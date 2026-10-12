# Attendance Service

One-shot, read-only synchronization from an eSSL/ZKTeco attendance device to
PostgreSQL:

```text
external scheduler -> attendance-service sync -> device snapshot
                   -> validate -> insert new rows -> audit -> exit
```

The application contains no scheduler and no permanently running service loop.
Run it from Windows Task Scheduler, cron, or a deployment platform scheduler.
It never clears or changes device attendance data.

## Safety and data model

- Every device read is a complete snapshot of the attendance records currently
  available on the device. The first run therefore backfills history; later
  runs safely reconcile the same data plus new events.
- PostgreSQL uniqueness and `ON CONFLICT DO NOTHING` make retries idempotent.
- The installed `pyzk` library does not expose a reliable attendance-event ID.
  Current device records consequently use the fallback identity
  `(source_id, employee_id, original_device_timestamp)`.
- Employee IDs are stored as PostgreSQL `text`; leading zeroes are retained.
- Original device-local timestamps are preserved unchanged. Valid records also
  receive a UTC `timestamptz` derived with `ATTENDANCE_DEVICE_TIMEZONE`.
- Rejected timestamps, including the observed year-2119 values, are stored in
  `invalid_attendance_events` and receive the same duplicate protection.
- Raw `status` and `punch` values are stored as text without interpretation.
- Existing attendance events are never updated or deleted.
- A source-specific PostgreSQL advisory lock is acquired before connecting to
  the device. An overlapping invocation exits with code `3` without opening a
  device connection.

## Setup

Python 3.11 or newer and PostgreSQL are required.

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edit `.env` for an isolated local/test PostgreSQL database and the actual
device. Do not commit `.env`.

Required decisions are explicit environment values rather than hidden rules:

- `ATTENDANCE_SOURCE_KEY`: stable logical device identity
- `ATTENDANCE_DEVICE_TIMEZONE`: IANA name such as `Asia/Kolkata`
- `ATTENDANCE_MIN_VALID_TIMESTAMP`: earliest accepted device-local timestamp
- `ATTENDANCE_MAX_FUTURE_SECONDS`: tolerated device clock lead

Apply migrations before the first synchronization:

```powershell
.venv\Scripts\attendance-service --env-file .env migrate
```

## Synchronization

First run/backfill and all subsequent reconciliations use the same command:

```powershell
.venv\Scripts\attendance-service --env-file .env sync
```

The first run is automatically audited as `initial`. Later default runs are
audited as `scheduled`. A manual reconciliation uses the same idempotent code:

```powershell
.venv\Scripts\attendance-service --env-file .env sync --mode manual
```

Exit codes:

| Code | Meaning |
|---:|---|
| 0 | Synchronization completed, including a run containing only duplicates |
| 1 | Device, database, migration, report, or unexpected operational failure |
| 2 | Missing or invalid configuration |
| 3 | Another synchronization already owns the source lock |

Temporary device and PostgreSQL failures use bounded exponential-backoff
retries. The command always exits after the configured maximum attempts.
Each acquired synchronization is recorded in `attendance_sync_runs` as
`running`, `succeeded`, or `failed` where the database remains reachable.

The device protocol always returns the full attendance log, so each run still
downloads every record. Only punches newer than the newest stored valid punch
minus `ATTENDANCE_SYNC_LOOKBACK_SECONDS` (default 86400) are written; older ones
are counted as `skipped_older`. The first run has no stored punch and backfills
everything. The roster update and all inserts of a run share one database
transaction, so a failed run writes no attendance rows (its `failed` audit row is
still kept). Each run logs `sync_started`, then `sync_succeeded` (`fetched`,
`skipped_older`, `inserted`, `invalid_inserted`, `duplicates`, `duration_ms`) or
`sync_failed` (`error`, `duration_ms`) as JSON lines.

## External scheduling

Scheduling time and frequency are deliberately not configured in Python.

### Windows Task Scheduler

Create a task whose action has:

- Program/script: `D:\attendance-automation\.venv\Scripts\attendance-service.exe`
- Arguments: `--env-file D:\attendance-automation\.env sync --mode scheduled`
- Start in: `D:\attendance-automation`

Use a dedicated low-privilege account, select an appropriate fixed trigger,
and configure the task not to start a new instance when one is already running.
The PostgreSQL advisory lock remains the final overlap protection.

Every 5 minutes, from an elevated PowerShell (`/RU SYSTEM` runs it whether or
not anyone is logged on; use a dedicated account with `/RU <user> /RP` instead
if preferred):

```powershell
schtasks /Create /SC MINUTE /MO 5 /TN "Attendance PostgreSQL Sync" /RU SYSTEM /TR "\"D:\attendance-automation\.venv\Scripts\attendance-service.exe\" --env-file \"D:\attendance-automation\.env\" sync --mode scheduled"
schtasks /Run /TN "Attendance PostgreSQL Sync"
schtasks /Query /TN "Attendance PostgreSQL Sync" /V /FO LIST
```

A task created by `schtasks` defaults to "Do not start a new instance" if the
previous run is still going. To keep a log file, point `/TR` at a wrapper such
as `cmd /c "... sync --mode scheduled >> D:\attendance-automation\sync.log 2>&1"`.
The interval is only an example; it is not an application default.

### cron

Example external trigger every five minutes:

```cron
*/5 * * * * cd /opt/attendance-automation && .venv/bin/attendance-service --env-file /etc/attendance-service.env sync --mode scheduled >> /var/log/attendance-sync.log 2>&1
```

Use the interval appropriate for the deployment. Cron overlap is still guarded
by the database advisory lock.

## Optional PostgreSQL-based report

Excel is output only; it is never an ingestion source:

```powershell
.venv\Scripts\attendance-service --env-file .env report --output attendance_report_new.xlsx
```

The compatibility script `generate_attendance_report.py` now invokes this
database report path. The existing `attendance_report.xlsx` is retained as a
historical artifact.

## Read-only attendance API and web UI

Start the API/UI separately from scheduled synchronization:

```powershell
.venv\Scripts\attendance-service --env-file .env web
```

It binds to `127.0.0.1:8000` by default. Open `http://127.0.0.1:8000/`.
The bind address and port can be configured with `ATTENDANCE_API_HOST` and
`ATTENDANCE_API_PORT` or explicit `web --host`/`--port` options. Device and
database credentials are used only by the server and are never sent to browser
JavaScript.

Available read-only endpoints:

```text
GET /api/v1/employees?query=khushi
GET /api/v1/employees/{employee_id}/work-hours?date=YYYY-MM-DD
GET /api/v1/attendance/daily?date=YYYY-MM-DD   (date optional, defaults to the current working day)
```

The daily report (the **Summary** tab in the UI) lists who is **present**
(at least one punch that day) and who is **not in yet** (for past dates:
**absent**). The expected list of employees is the device's enrolled users.
Each `sync` stores them in the `employees` table: users missing from a
snapshot are marked inactive, and an empty user list from the device never
deactivates anyone. People who punched but are not on that list are still
shown as present, with an `unregistered_employees` warning. Future dates return
`422 future_date`. The response includes `data_as_of`, the time of the last
successful sync. The report is only as current as that sync, so schedule
`sync` frequently during office hours (for example every 5–15 minutes). Leave,
work-from-home, and late arrivals are not tracked.

Both employee operations are restricted to `ATTENDANCE_SOURCE_KEY`. Names are searched
case-insensitively but are not treated as identities; the selected string
`employee_id` is used together with the source.

A selected date D is a **working day**: from D at `ATTENDANCE_WORKING_DAY_CUTOFF`
(default `06:00`) to D+1 at the same time, in `ATTENDANCE_DEVICE_TIMEZONE`.
Its UTC boundaries are used to query `occurred_at_utc`. Night-shift punches after
midnight (for example 00:48) are therefore counted toward the previous day.
Both ends are built from local wall-clock time, so daylight-saving days are 23
or 25 hours long. `00:00` gives plain calendar days (the previous behaviour).
Before the cutoff, "today" is still the previous working day. Both endpoints
return `working_day_cutoff`, `window_start` and `window_end`, and the UI shows
the counted window. Limitations:

- A shift that runs past the cutoff (for example 22:00 → 07:00) is split across
  two working days; this needs shift definitions to resolve.
- Results are computed on read, so changing the cutoff changes every past day as
  well. Previously exported figures will no longer match.

The calculation method is `first_last_span`, displayed as **Total attendance
span (breaks included)**:

- zero punches: no duration and a `no_attendance` warning;
- one punch: no duration and an `insufficient_punches` warning;
- two or more: last punch minus first punch;
- odd counts of three or more: calculate normally and add `odd_punch_count`;
- spans over `ATTENDANCE_UNREASONABLE_SPAN_SECONDS`: preserve the result and add
  `unreasonable_span`.

`breaks_excluded` is always `false`. This is an attendance span, not paired or
net working time. Accurate net working hours require confirmed IN/OUT semantics
or a separately approved company break policy. Raw `status_raw` and
`punch_raw` values remain visible and uninterpreted.

### Deployment security

The current interface intentionally has no authentication and must remain bound
to localhost for local evaluation. **Authentication and authorization are
mandatory before company-wide, LAN, internet, reverse-proxy, or shared-host
deployment.** Use a dedicated PostgreSQL account with `SELECT` permission only
for the API. TLS, user access rules, audit requirements, and session management
must be established before changing the bind address from localhost.

Device diagnostics also use environment configuration:

```powershell
.venv\Scripts\attendance-service --env-file .env device-test
.venv\Scripts\attendance-service --env-file .env capacity
```

## Isolated test database

The included Compose file starts an ephemeral PostgreSQL instance bound only to
localhost. Its data directory is a temporary filesystem:

```powershell
docker compose -f compose.test.yml up -d --wait
$env:ATTENDANCE_TEST_DATABASE_URL = "postgresql://attendance_test:attendance_test@localhost:55432/attendance_test"
.venv\Scripts\pytest
docker compose -f compose.test.yml down
```

Integration tests create uniquely named sources and do not truncate or delete
attendance tables. If `ATTENDANCE_TEST_DATABASE_URL` is absent, PostgreSQL tests
are skipped while unit tests still run.

An optional populated-database API smoke test uses
`ATTENDANCE_READ_DATABASE_URL`. It opens a read-only transaction, selects an
existing employee-day, and verifies the API against real `attendance_events`
without inserting, updating, or deleting anything.

## Schema migrations

Migrations are versioned under `migrations/`. Apply them with
`attendance-service migrate`. Application startup does not modify schema
automatically. Never point development or test commands at a production DSN.
