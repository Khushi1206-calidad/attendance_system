# AttendanceSync.ps1 - standalone eSSL/ZKTeco device -> PostgreSQL sync for Windows.
# This one file is all that is needed; the rest of the project is not required.
#
# Requirements on the Windows machine:
#   - Python 3.9+ (python.org, tick "Add python.exe to PATH")
#   - a reachable PostgreSQL server (PG_* below; the user must be allowed to create databases)
#   - network access to the attendance device (DEVICE_* below)
#
# Usage (PowerShell):
#   powershell -ExecutionPolicy Bypass -File AttendanceSync.ps1              # sync once now
#   powershell -ExecutionPolicy Bypass -File AttendanceSync.ps1 -Install     # as administrator: sync every 5 minutes
#   powershell -ExecutionPolicy Bypass -File AttendanceSync.ps1 -Uninstall   # as administrator: remove the schedule
#
# The first run creates a Python environment, the database and its tables, then
# copies the full device history. Later runs add only new punches; nothing on the
# device is changed or deleted. Log: AttendanceSync-data\sync.log next to this file.
# This file contains passwords: share it only with people who may see them.
param([switch]$Install, [switch]$Uninstall)

# ---------------------------------------------------------------- configuration
$PG_HOST     = "localhost"
$PG_PORT     = "5432"
$PG_USER     = "postgres"
$PG_PASSWORD = "Asdfg@123"
$PG_DATABASE = "attendance_test"

$DEVICE_IP       = "10.0.0.4"
$DEVICE_PORT     = "4370"
$DEVICE_PASSWORD = "0"
$DEVICE_TIMEOUT  = "10"
$DEVICE_TIMEZONE = "Asia/Kolkata"
$SOURCE_KEY      = "main-office-device"
$SOURCE_NAME     = "Main office attendance device"

$SYNC_EVERY_MINUTES    = 5
$MIN_VALID_TIMESTAMP   = "2015-01-01T00:00:00"
$MAX_FUTURE_SECONDS    = "86400"
$SYNC_LOOKBACK_SECONDS = "86400"
$MAX_ATTEMPTS          = "3"
# ------------------------------------------------------------ end configuration

$TaskName = "Attendance Sync"
$ScriptPath = $MyInvocation.MyCommand.Path
$WorkDir = Join-Path (Split-Path -Parent $ScriptPath) "AttendanceSync-data"
$VenvDir = Join-Path $WorkDir "venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$PyFile = Join-Path $WorkDir "attendance_sync.py"
$LogFile = Join-Path $WorkDir "sync.log"
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -Path $LogFile -Encoding UTF8 -Value $line
    Write-Host $line
}

function Test-Admin {
    $identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    return $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if ($Uninstall) {
    if (-not (Test-Admin)) { Write-Host "Run PowerShell as administrator for -Uninstall."; exit 1 }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Scheduled task '$TaskName' removed."
    exit 0
}

if ($Install) {
    if (-not (Test-Admin)) { Write-Host "Run PowerShell as administrator for -Install."; exit 1 }
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory (Split-Path -Parent $ScriptPath) `
        -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`""
    $triggers = @(
        (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $SYNC_EVERY_MINUTES)),
        (New-ScheduledTaskTrigger -AtStartup)
    )
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask -TaskName $TaskName -Force -Action $action -Trigger $triggers `
        -Settings $settings -Principal $principal -ErrorAction Stop | Out-Null
    Write-Host "Scheduled task '$TaskName' installed: every $SYNC_EVERY_MINUTES minutes and at startup."
    Write-Host "Running the first sync now..."
}

# ------------------------------------------------- embedded sync program (Python)
$PythonCode = @'
import json, os, sys, time, uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from zk import ZK

E = os.environ

# Same schema as the Django migration (backend/attendance/migrations/0001_initial.py);
# `python manage.py migrate` adopts a database created here without changes.
SCHEMA = """
CREATE TABLE attendance_sources (
    id uuid PRIMARY KEY,
    source_key text NOT NULL CONSTRAINT uq_attendance_sources_source_key UNIQUE,
    display_name text,
    device_serial text,
    device_timezone text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE attendance_sync_runs (
    id uuid PRIMARY KEY,
    source_id uuid NOT NULL REFERENCES attendance_sources(id),
    mode text NOT NULL,
    status text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    received_count integer NOT NULL DEFAULT 0,
    valid_count integer NOT NULL DEFAULT 0,
    invalid_count integer NOT NULL DEFAULT 0,
    inserted_count integer NOT NULL DEFAULT 0,
    invalid_inserted_count integer NOT NULL DEFAULT 0,
    duplicate_count integer NOT NULL DEFAULT 0,
    error_message text,
    CONSTRAINT ck_attendance_sync_runs_status CHECK (status IN ('running', 'succeeded', 'failed')),
    CONSTRAINT ck_attendance_sync_runs_mode CHECK (mode IN ('initial', 'scheduled', 'manual'))
);
CREATE TABLE attendance_events (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    source_id uuid NOT NULL REFERENCES attendance_sources(id),
    vendor_event_id text,
    employee_id text NOT NULL,
    employee_name text,
    original_device_timestamp timestamp NOT NULL,
    occurred_at_utc timestamptz NOT NULL,
    status_raw text,
    punch_raw text,
    raw_payload jsonb,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    sync_run_id uuid NOT NULL REFERENCES attendance_sync_runs(id)
);
CREATE UNIQUE INDEX uq_attendance_events_vendor_event ON attendance_events (source_id, vendor_event_id)
    WHERE vendor_event_id IS NOT NULL;
CREATE UNIQUE INDEX uq_attendance_events_fallback ON attendance_events (source_id, employee_id, original_device_timestamp)
    WHERE vendor_event_id IS NULL;
CREATE INDEX ix_attendance_events_occurred_at_utc ON attendance_events (occurred_at_utc);
CREATE INDEX ix_attendance_events_source_occurred ON attendance_events (source_id, occurred_at_utc);
CREATE TABLE invalid_attendance_events (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    source_id uuid NOT NULL REFERENCES attendance_sources(id),
    vendor_event_id text,
    employee_id text NOT NULL,
    employee_name text,
    original_device_timestamp timestamp NOT NULL,
    status_raw text,
    punch_raw text,
    validation_error text NOT NULL,
    raw_payload jsonb,
    detected_at timestamptz NOT NULL DEFAULT now(),
    sync_run_id uuid NOT NULL REFERENCES attendance_sync_runs(id)
);
CREATE UNIQUE INDEX uq_invalid_attendance_vendor_event ON invalid_attendance_events (source_id, vendor_event_id)
    WHERE vendor_event_id IS NOT NULL;
CREATE UNIQUE INDEX uq_invalid_attendance_fallback ON invalid_attendance_events (source_id, employee_id, original_device_timestamp)
    WHERE vendor_event_id IS NULL;
CREATE TABLE employees (
    source_id uuid NOT NULL REFERENCES attendance_sources(id),
    employee_id text NOT NULL,
    name text,
    is_active boolean NOT NULL DEFAULT true,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    last_sync_run_id uuid NOT NULL REFERENCES attendance_sync_runs(id),
    CONSTRAINT pk_employees PRIMARY KEY (source_id, employee_id)
);
"""


def log(message, **fields):
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "message": message}
    entry.update(fields)
    print(json.dumps(entry, default=str), flush=True)


def connect(dbname):
    return psycopg.connect(
        host=E["PG_HOST"], port=E["PG_PORT"], user=E["PG_USER"],
        password=E["PG_PASSWORD"], dbname=dbname, connect_timeout=10,
    )


def ensure_database():
    with connect("postgres") as conn:
        conn.autocommit = True
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (E["PG_DATABASE"],)
        ).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(E["PG_DATABASE"])))
            log("database_created", database=E["PG_DATABASE"])


def ensure_schema(conn):
    with conn.transaction():
        if conn.execute("SELECT to_regclass('public.attendance_sources')").fetchone()[0]:
            return
        conn.execute(SCHEMA)
        log("tables_created")


def ensure_source(conn):
    with conn.transaction():
        conn.execute(
            """INSERT INTO attendance_sources (id, source_key, display_name, device_timezone)
               VALUES (%s, %s, %s, %s) ON CONFLICT (source_key) DO NOTHING""",
            (uuid.uuid4(), E["SOURCE_KEY"], E["SOURCE_NAME"], E["DEVICE_TIMEZONE"]),
        )
        source_id, tz_name = conn.execute(
            "SELECT id, device_timezone FROM attendance_sources WHERE source_key = %s",
            (E["SOURCE_KEY"],),
        ).fetchone()
    if tz_name != E["DEVICE_TIMEZONE"]:
        raise ValueError("DEVICE_TIMEZONE does not match the stored source timezone (%s)" % tz_name)
    return source_id


def read_device():
    attempts = int(E["MAX_ATTEMPTS"])
    for attempt in range(1, attempts + 1):
        connection = None
        try:
            zk = ZK(E["DEVICE_IP"], port=int(E["DEVICE_PORT"]), timeout=int(E["DEVICE_TIMEOUT"]),
                    password=int(E["DEVICE_PASSWORD"]), force_udp=False, ommit_ping=False)
            connection = zk.connect()
            users = connection.get_users()
            attendance = connection.get_attendance()
            try:
                serial = connection.get_serialnumber()
            except Exception:
                serial = None
            log("device_snapshot_read", records=len(attendance), users=len(users))
            return users, attendance, (str(serial) if serial else None)
        except Exception as exc:
            if attempt == attempts:
                raise RuntimeError("Could not read device: %s" % exc)
            log("device_read_retry", attempt=attempt, error=str(exc))
            time.sleep(min(2 ** (attempt - 1), 10))
        finally:
            if connection is not None:
                try:
                    connection.disconnect()
                except Exception:
                    pass


def main():
    started = time.monotonic()
    device_tz = ZoneInfo(E["DEVICE_TIMEZONE"])
    minimum = datetime.fromisoformat(E["MIN_VALID_TIMESTAMP"])
    future = timedelta(seconds=int(E["MAX_FUTURE_SECONDS"]))
    lookback = timedelta(seconds=int(E["SYNC_LOOKBACK_SECONDS"]))

    ensure_database()
    conn = connect(E["PG_DATABASE"])
    conn.autocommit = True
    ensure_schema(conn)
    source_id = ensure_source(conn)

    lock_key = "attendance-service:" + E["SOURCE_KEY"]  # same lock as the Django sync command
    if not conn.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", (lock_key,)).fetchone()[0]:
        log("sync_already_running")
        return 3

    run_id = None
    received = valid_count = invalid_count = 0
    try:
        has_records = conn.execute(
            """SELECT EXISTS (SELECT 1 FROM attendance_events WHERE source_id = %s
               UNION ALL SELECT 1 FROM invalid_attendance_events WHERE source_id = %s)""",
            (source_id, source_id),
        ).fetchone()[0]
        mode = "scheduled" if has_records else "initial"
        watermark = conn.execute(
            "SELECT max(original_device_timestamp) FROM attendance_events WHERE source_id = %s",
            (source_id,),
        ).fetchone()[0]
        threshold = watermark - lookback if watermark else None
        run_id = uuid.uuid4()
        conn.execute(
            "INSERT INTO attendance_sync_runs (id, source_id, mode, status) VALUES (%s, %s, %s, 'running')",
            (run_id, source_id, mode),
        )
        log("sync_started", run_id=run_id, mode=mode, watermark=watermark, threshold=threshold)

        users, attendance, serial = read_device()
        received = len(attendance)
        names = {str(u.user_id): u.name for u in users}
        local_now = datetime.now(timezone.utc).astimezone(device_tz).replace(tzinfo=None)

        valid_rows, invalid_rows, skipped_older = [], [], 0
        for item in attendance:
            employee_id = str(item.user_id)
            ts = item.timestamp.replace(tzinfo=None)
            status = getattr(item, "status", None)
            punch = getattr(item, "punch", None)
            payload = Jsonb({"employee_id": employee_id, "timestamp": item.timestamp.isoformat(),
                             "status": status, "punch": punch})
            common = (source_id, None, employee_id, names.get(employee_id), ts,
                      None if status is None else str(status), None if punch is None else str(punch))
            if ts < minimum:
                invalid_rows.append(common + ("before_minimum_timestamp", payload, run_id))
            elif ts > local_now + future:
                invalid_rows.append(common + ("future_timestamp", payload, run_id))
            elif threshold is not None and ts < threshold:
                skipped_older += 1
            else:
                occurred_utc = ts.replace(tzinfo=device_tz).astimezone(timezone.utc)
                valid_rows.append(common[:5] + (occurred_utc,) + common[5:] + (payload, run_id))
        valid_count = len(valid_rows) + skipped_older
        invalid_count = len(invalid_rows)

        inserted = invalid_inserted = 0
        deactivated = 0
        roster = {str(u.user_id): (u.name or None) for u in users}
        with conn.transaction(), conn.cursor() as cur:  # all-or-nothing
            if serial:
                stored = cur.execute("SELECT device_serial FROM attendance_sources WHERE id = %s",
                                     (source_id,)).fetchone()[0]
                if stored and stored != serial:
                    raise ValueError("Device serial %s does not match stored serial %s" % (serial, stored))
                cur.execute("UPDATE attendance_sources SET device_serial = %s, updated_at = now() "
                            "WHERE id = %s AND device_serial IS NULL", (serial, source_id))
            if roster:  # an empty user list must never wipe the roster
                cur.executemany(
                    """INSERT INTO employees (source_id, employee_id, name, last_sync_run_id)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (source_id, employee_id) DO UPDATE
                       SET name = EXCLUDED.name, is_active = true, last_seen_at = now(),
                           last_sync_run_id = EXCLUDED.last_sync_run_id""",
                    [(source_id, emp, name, run_id) for emp, name in roster.items()],
                )
                cur.execute("UPDATE employees SET is_active = false WHERE source_id = %s AND is_active "
                            "AND NOT (employee_id = ANY(%s))", (source_id, list(roster)))
                deactivated = cur.rowcount
            for start in range(0, len(valid_rows), 1000):
                cur.executemany(
                    """INSERT INTO attendance_events (source_id, vendor_event_id, employee_id, employee_name,
                           original_device_timestamp, occurred_at_utc, status_raw, punch_raw, raw_payload, sync_run_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    valid_rows[start:start + 1000],
                )
                inserted += cur.rowcount
            for start in range(0, len(invalid_rows), 1000):
                cur.executemany(
                    """INSERT INTO invalid_attendance_events (source_id, vendor_event_id, employee_id, employee_name,
                           original_device_timestamp, status_raw, punch_raw, validation_error, raw_payload, sync_run_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    invalid_rows[start:start + 1000],
                )
                invalid_inserted += cur.rowcount

        conn.execute(
            """UPDATE attendance_sync_runs SET status = 'succeeded', finished_at = now(),
                   received_count = %s, valid_count = %s, invalid_count = %s, inserted_count = %s,
                   invalid_inserted_count = %s, duplicate_count = %s WHERE id = %s""",
            (received, valid_count, invalid_count, inserted, invalid_inserted,
             max(received - inserted - invalid_inserted, 0), run_id),
        )
        log("sync_succeeded", run_id=run_id, mode=mode, fetched=received, valid=valid_count,
            invalid=invalid_count, skipped_older=skipped_older, inserted=inserted,
            invalid_inserted=invalid_inserted,
            duplicates=received - skipped_older - inserted - invalid_inserted,
            employees_upserted=len(roster), employees_deactivated=deactivated,
            duration_ms=round((time.monotonic() - started) * 1000))
        return 0
    except Exception as exc:
        error = ("%s: %s" % (type(exc).__name__, exc))[:2000]
        log("sync_failed", run_id=run_id, error=error,
            duration_ms=round((time.monotonic() - started) * 1000))
        if run_id is not None:
            try:
                conn.execute(
                    """UPDATE attendance_sync_runs SET status = 'failed', finished_at = now(),
                           received_count = %s, valid_count = %s, invalid_count = %s, error_message = %s
                       WHERE id = %s""",
                    (received, valid_count, invalid_count, error, run_id),
                )
            except Exception:
                pass
        return 1
    finally:
        try:
            conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (lock_key,))
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log("sync_failed", error="%s: %s" % (type(exc).__name__, exc))
        sys.exit(1)
'@
# ------------------------------------------------------------- end Python program

# One-time Python environment with the device and database libraries.
if (-not (Test-Path $VenvPython)) {
    Write-Log "creating Python environment in $VenvDir"
    $python = $null
    foreach ($candidate in @(@("py", "-3"), @("python"))) {
        if (-not (Get-Command $candidate[0] -ErrorAction SilentlyContinue)) { continue }
        $extra = @($candidate | Select-Object -Skip 1)
        $ok = & $candidate[0] @extra -c "import sys; print(sys.version_info >= (3, 9))" 2>$null
        if ($ok -eq "True") { $python = $candidate; break }
    }
    if (-not $python) { Write-Log "ERROR: Python 3.9+ not found. Install it from python.org (tick 'Add python.exe to PATH')."; exit 1 }
    $extra = @($python | Select-Object -Skip 1)
    & $python[0] @extra -m venv $VenvDir
    & $VenvPython -m pip install --quiet --disable-pip-version-check "pyzk>=0.9,<1" "psycopg[binary]>=3.1,<4" tzdata 2>&1 |
        ForEach-Object { Add-Content -Path $LogFile -Encoding UTF8 -Value "$_" }
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -Recurse -Force $VenvDir -ErrorAction SilentlyContinue
        Write-Log "ERROR: installing Python packages failed (internet access needed once); see $LogFile"
        exit 1
    }
}

# Keep the embedded program up to date with this file.
[IO.File]::WriteAllText($PyFile, $PythonCode, (New-Object Text.UTF8Encoding $false))

$env:PG_HOST = $PG_HOST; $env:PG_PORT = $PG_PORT; $env:PG_USER = $PG_USER
$env:PG_PASSWORD = $PG_PASSWORD; $env:PG_DATABASE = $PG_DATABASE
$env:DEVICE_IP = $DEVICE_IP; $env:DEVICE_PORT = $DEVICE_PORT; $env:DEVICE_PASSWORD = $DEVICE_PASSWORD
$env:DEVICE_TIMEOUT = $DEVICE_TIMEOUT; $env:DEVICE_TIMEZONE = $DEVICE_TIMEZONE
$env:SOURCE_KEY = $SOURCE_KEY; $env:SOURCE_NAME = $SOURCE_NAME
$env:MIN_VALID_TIMESTAMP = $MIN_VALID_TIMESTAMP; $env:MAX_FUTURE_SECONDS = $MAX_FUTURE_SECONDS
$env:SYNC_LOOKBACK_SECONDS = $SYNC_LOOKBACK_SECONDS; $env:MAX_ATTEMPTS = $MAX_ATTEMPTS
$env:PYTHONIOENCODING = "utf-8"

$OutFile = Join-Path $WorkDir ".stdout.tmp"
$ErrFile = Join-Path $WorkDir ".stderr.tmp"
$process = Start-Process -FilePath $VenvPython -ArgumentList "`"$PyFile`"" -NoNewWindow -Wait -PassThru `
    -RedirectStandardOutput $OutFile -RedirectStandardError $ErrFile
foreach ($file in $OutFile, $ErrFile) {
    $content = Get-Content $file -Encoding UTF8 -ErrorAction SilentlyContinue
    if ($content) {
        Add-Content -Path $LogFile -Encoding UTF8 -Value $content
        $content | ForEach-Object { Write-Host $_ }
    }
    Remove-Item $file -ErrorAction SilentlyContinue
}
exit $process.ExitCode
