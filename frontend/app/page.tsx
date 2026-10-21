"use client";

import { useCallback, useState } from "react";

import { LookupTab } from "@/components/LookupTab";
import { SummaryTab } from "@/components/SummaryTab";
import type { DailyAttendanceResponse } from "@/lib/types";

const TABS = [
  { id: "summary", label: "Summary" },
  { id: "lookup", label: "Employee lookup" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function HomePage() {
  const [activeTab, setActiveTab] = useState<TabId>("summary");
  const [sourceKey, setSourceKey] = useState("");
  const [currentWorkingDay, setCurrentWorkingDay] = useState("");

  const onSummaryLoaded = useCallback((data: DailyAttendanceResponse) => {
    setSourceKey(data.source_key);
    setCurrentWorkingDay(data.current_working_day);
  }, []);

  return (
    <main className="page">
      <header>
        <p className="eyebrow">
          Source: <span>{sourceKey || "—"}</span>
        </p>
        <h1>Attendance</h1>
      </header>

      <nav className="tabs" role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            className={tab.id === activeTab ? "tab active" : "tab"}
            aria-selected={tab.id === activeTab}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {/* Both tabs stay mounted so their state survives switching. */}
      <SummaryTab hidden={activeTab !== "summary"} onLoaded={onSummaryLoaded} />
      <LookupTab hidden={activeTab !== "lookup"} defaultDate={currentWorkingDay} />
    </main>
  );
}
