"use client";

import { useCallback, useEffect, useState } from "react";

import { Warnings } from "@/components/Warnings";
import { getDailyAttendance } from "@/lib/api";
import { dateTime, displayDate, employeeLabel, punchTime, windowLabel } from "@/lib/format";
import type { DailyAttendanceResponse } from "@/lib/types";

const STALE_SYNC_MS = 60 * 60 * 1000;

interface Props {
  hidden: boolean;
  onLoaded: (data: DailyAttendanceResponse) => void;
}

export function SummaryTab({ hidden, onLoaded }: Props) {
  const [date, setDate] = useState("");
  const [data, setData] = useState<DailyAttendanceResponse | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(
    async (selected: string) => {
      setError("");
      try {
        const result = await getDailyAttendance(selected || undefined);
        setData(result);
        // The server decides the current working day (before the cutoff it is still yesterday).
        if (!selected) setDate(result.date);
        onLoaded(result);
      } catch (err) {
        setError((err as Error).message);
      }
    },
    [onLoaded],
  );

  useEffect(() => {
    void load("");
  }, [load]);

  const isToday = data ? data.absence_label === "not_in_yet" : true;
  const dayWord = !data || isToday ? "today" : `on ${displayDate(data.date)}`;
  const stale = data?.data_as_of
    ? Date.now() - new Date(data.data_as_of).getTime() > STALE_SYNC_MS
    : Boolean(data);

  return (
    <div id="summary-panel" className={hidden ? "tab-panel hidden" : "tab-panel"}>
      <section className="card toolbar">
        <div>
          <label htmlFor="summary-date">Date</label>
          <input
            id="summary-date"
            type="date"
            value={date}
            max={data?.current_working_day}
            onChange={(event) => {
              setDate(event.target.value);
              void load(event.target.value);
            }}
          />
        </div>
        <button type="button" onClick={() => void load(date)}>
          Refresh
        </button>
        <p className={stale ? "muted stale" : "muted"}>
          {data &&
            (data.data_as_of
              ? `Data as of ${dateTime(data.data_as_of, data.timezone)}` +
                (stale ? " — last sync is over an hour old" : "")
              : "No successful sync recorded yet.")}
        </p>
        <p className="muted">
          {data && `Counted window: ${windowLabel(data.window_start, data.window_end, data.timezone)}`}
        </p>
      </section>
      <Warnings warnings={data?.warnings ?? []} />

      <div className="tiles">
        <section className="card tile tile-present">
          <h2>
            Present <span className="day-word">{dayWord}</span>
          </h2>
          <p className="count">{data ? data.totals.present : "—"}</p>
          {data && data.present.length === 0 && <p className="empty">No one has punched in yet.</p>}
          <ul className="people">
            {data?.present.map((person) => (
              <li key={person.employee_id}>
                <span>{employeeLabel(person)}</span>
                <span className="muted">
                  {`in ${punchTime(person.first_punch, data.date, data.timezone)}` +
                    (person.registered ? "" : " · not in roster")}
                </span>
              </li>
            ))}
          </ul>
        </section>
        <section className="card tile tile-absent">
          <h2>
            {isToday ? "Not in yet " : "Absent "}
            <span className="day-word">{dayWord}</span>
          </h2>
          <p className="count">{data ? data.totals.not_in : "—"}</p>
          {data && data.not_in.length === 0 && (
            <p className="empty">{isToday ? "All employees are already in." : "No employee was absent."}</p>
          )}
          <ul className="people">
            {data?.not_in.map((person) => (
              <li key={person.employee_id}>
                <span>{employeeLabel(person)}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
      <p className="error" role="alert">
        {error}
      </p>
    </div>
  );
}
