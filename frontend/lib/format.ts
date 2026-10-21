import type { Employee } from "@/lib/types";

export function employeeLabel(employee: Employee): string {
  return `${employee.name || "Unnamed employee"} — ${employee.employee_id}`;
}

export function localTime(value: string | null, timeZone: string): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    hour: "2-digit", minute: "2-digit", hour12: false, timeZone,
  }).format(new Date(value));
}

// Same as localTime, but prefixes the day when it differs from the working day
// (after-midnight punches belong to the previous working day).
export function punchTime(value: string | null, workingDay: string, timeZone: string): string {
  if (!value) return "—";
  const day = new Intl.DateTimeFormat("en-CA", { timeZone }).format(new Date(value));
  if (day === workingDay) return localTime(value, timeZone);
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone,
  }).format(new Date(value));
}

export function windowLabel(start: string, end: string, timeZone: string): string {
  const format = new Intl.DateTimeFormat("en-IN", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone,
  });
  return `${format.format(new Date(start))} – ${format.format(new Date(end))}`;
}

export function displayDate(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric", month: "long", year: "numeric",
  }).format(new Date(year, month - 1, day));
}

export function dateTime(value: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium", timeStyle: "short", timeZone,
  }).format(new Date(value));
}
