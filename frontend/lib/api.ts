import type {
  ApiErrorBody,
  DailyAttendanceResponse,
  EmployeeSearchResponse,
  WorkHoursResponse,
} from "@/lib/types";

async function getJson<T>(path: string, fallbackError: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Non-JSON body (for example the API server is down behind the proxy).
  }
  if (!response.ok) {
    throw new Error((body as ApiErrorBody | null)?.error?.message || fallbackError);
  }
  return body as T;
}

export function searchEmployees(query: string, signal?: AbortSignal) {
  return getJson<EmployeeSearchResponse>(
    `/api/v1/employees?query=${encodeURIComponent(query)}`,
    "Search failed.",
    signal,
  );
}

export function getWorkHours(employeeId: string, date: string) {
  return getJson<WorkHoursResponse>(
    `/api/v1/employees/${encodeURIComponent(employeeId)}/work-hours?date=${encodeURIComponent(date)}`,
    "Attendance lookup failed.",
  );
}

export function getDailyAttendance(date?: string) {
  const query = date ? `?date=${encodeURIComponent(date)}` : "";
  return getJson<DailyAttendanceResponse>(`/api/v1/attendance/daily${query}`, "Daily summary failed.");
}
