// JSON contracts of the Django Ninja API (backend/attendance/schemas.py).
// Dates are "YYYY-MM-DD"; datetimes are ISO-8601 strings.

export interface ApiWarning {
  code: string;
  message: string;
}

export interface Employee {
  employee_id: string;
  name: string | null;
}

export interface EmployeeSearchResponse {
  source_key: string;
  query: string;
  count: number;
  employees: Employee[];
  warnings: ApiWarning[];
}

export interface Punch {
  original_device_timestamp: string;
  timestamp_local: string;
  timestamp_utc: string;
  status_raw: string | null;
  punch_raw: string | null;
}

export interface WorkHoursResponse {
  source_key: string;
  employee_id: string;
  name: string | null;
  date: string;
  timezone: string;
  punches: Punch[];
  punch_count: number;
  first_punch: string | null;
  last_punch: string | null;
  calculation_method: string;
  calculation_label: string;
  calculated_duration_seconds: number | null;
  calculated_duration: string | null;
  breaks_excluded: boolean;
  working_day_cutoff: string;
  window_start: string;
  window_end: string;
  warnings: ApiWarning[];
}

export interface PresentEmployee extends Employee {
  first_punch: string;
  last_punch: string;
  punch_count: number;
  registered: boolean;
}

export interface DailyAttendanceResponse {
  source_key: string;
  date: string;
  timezone: string;
  generated_at: string;
  data_as_of: string | null;
  absence_label: "not_in_yet" | "absent";
  totals: { roster: number; present: number; not_in: number };
  present: PresentEmployee[];
  not_in: Employee[];
  working_day_cutoff: string;
  current_working_day: string;
  window_start: string;
  window_end: string;
  warnings: ApiWarning[];
}

export interface ApiErrorBody {
  error?: { code: string; message: string };
}
