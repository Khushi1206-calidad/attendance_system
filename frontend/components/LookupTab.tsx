"use client";

import { type FormEvent, useEffect, useState } from "react";

import { Warnings } from "@/components/Warnings";
import { getWorkHours, searchEmployees } from "@/lib/api";
import { displayDate, employeeLabel, punchTime, windowLabel } from "@/lib/format";
import type { Employee, WorkHoursResponse } from "@/lib/types";

const SEARCH_DEBOUNCE_MS = 250;

interface Props {
  hidden: boolean;
  defaultDate: string;
}

export function LookupTab({ hidden, defaultDate }: Props) {
  const [searchText, setSearchText] = useState("");
  const [searchStatus, setSearchStatus] = useState("");
  const [results, setResults] = useState<Employee[]>([]);
  const [selected, setSelected] = useState<Employee | null>(null);
  const [date, setDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<WorkHoursResponse | null>(null);
  const [pageError, setPageError] = useState("");

  // Default the date to the current working day once the summary reports it.
  useEffect(() => {
    if (!date && defaultDate) setDate(defaultDate);
  }, [date, defaultDate]);

  useEffect(() => {
    const query = searchText.trim();
    if (!query) {
      setResults([]);
      setSearchStatus("");
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setResults([]);
      setSelected(null);
      setSearchStatus("Searching…");
      try {
        const data = await searchEmployees(query, controller.signal);
        setResults(data.employees);
        setSearchStatus(data.count ? "Select using name and employee ID." : "No employees found.");
      } catch (err) {
        if (!controller.signal.aborted) setSearchStatus((err as Error).message);
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [searchText]);

  function selectEmployee(employee: Employee) {
    setSelected(employee);
    setResults([]);
    setSearchStatus("Employee selected.");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPageError("");
    if (!selected || !date) return;
    setBusy(true);
    try {
      setResult(await getWorkHours(selected.employee_id, date));
    } catch (err) {
      setPageError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div id="lookup-panel" className={hidden ? "tab-panel hidden" : "tab-panel"}>
      <p>Find an employee, choose a date, and view the total attendance span.</p>
      <section className="card" aria-labelledby="search-heading">
        <h2 id="search-heading">1. Select employee</h2>
        <label htmlFor="employee-search">Employee name</label>
        <input
          id="employee-search"
          type="search"
          maxLength={100}
          autoComplete="off"
          placeholder="Start typing a name"
          value={searchText}
          onChange={(event) => {
            setSearchText(event.target.value);
            setSelected(null);
          }}
        />
        <p className="muted" aria-live="polite">
          {searchStatus}
        </p>
        <div className="results">
          {results.map((employee) => (
            <button
              key={employee.employee_id}
              type="button"
              className="employee-option"
              onClick={() => selectEmployee(employee)}
            >
              {employeeLabel(employee)}
            </button>
          ))}
        </div>
      </section>

      <section className="card" aria-labelledby="date-heading">
        <h2 id="date-heading">2. Select date</h2>
        <p className="selection">{selected ? employeeLabel(selected) : "No employee selected"}</p>
        <form onSubmit={submit}>
          <label htmlFor="attendance-date">Date</label>
          <input
            id="attendance-date"
            type="date"
            required
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
          <button type="submit" disabled={!selected || busy}>
            View attendance
          </button>
        </form>
      </section>

      {result && (
        <section className="card" aria-live="polite">
          <h2>Attendance result</h2>
          <dl className="summary">
            <div>
              <dt>Employee</dt>
              <dd>{employeeLabel(result)}</dd>
            </div>
            <div>
              <dt>Date</dt>
              <dd>{displayDate(result.date)}</dd>
            </div>
            <div>
              <dt>Counted window</dt>
              <dd>{windowLabel(result.window_start, result.window_end, result.timezone)}</dd>
            </div>
            <div>
              <dt>First punch</dt>
              <dd>{punchTime(result.first_punch, result.date, result.timezone)}</dd>
            </div>
            <div>
              <dt>Last punch</dt>
              <dd>{punchTime(result.last_punch, result.date, result.timezone)}</dd>
            </div>
            <div>
              <dt>{result.calculation_label}</dt>
              <dd>{result.calculated_duration || "Not available"}</dd>
            </div>
            <div>
              <dt>Breaks excluded</dt>
              <dd>{result.breaks_excluded ? "Yes" : "No"}</dd>
            </div>
            <div>
              <dt>Punches recorded</dt>
              <dd>{result.punch_count}</dd>
            </div>
          </dl>
          <Warnings warnings={result.warnings} />
          <h3>Ordered punches</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Raw status</th>
                  <th>Raw punch</th>
                </tr>
              </thead>
              <tbody>
                {result.punches.map((punch) => (
                  <tr key={punch.timestamp_utc}>
                    <td>{punchTime(punch.timestamp_local, result.date, result.timezone)}</td>
                    <td>{punch.status_raw ?? "—"}</td>
                    <td>{punch.punch_raw ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <p className="error" role="alert">
        {pageError}
      </p>
    </div>
  );
}
