const searchInput = document.querySelector("#employee-search");
const searchStatus = document.querySelector("#search-status");
const results = document.querySelector("#employee-results");
const selectedLabel = document.querySelector("#selected-employee");
const dateInput = document.querySelector("#attendance-date");
const viewButton = document.querySelector("#view-button");
const form = document.querySelector("#attendance-form");
const resultPanel = document.querySelector("#attendance-result");
const pageError = document.querySelector("#page-error");
let selectedEmployee = null;
let debounceTimer = null;

function localTime(value, timeZone) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    hour: "2-digit", minute: "2-digit", hour12: false, timeZone
  }).format(new Date(value));
}

// Same as localTime, but prefixes the day when it differs from the working day
// (after-midnight punches belong to the previous working day).
function punchTime(value, workingDay, timeZone) {
  if (!value) return "—";
  const day = new Intl.DateTimeFormat("en-CA", { timeZone }).format(new Date(value));
  if (day === workingDay) return localTime(value, timeZone);
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone
  }).format(new Date(value));
}

function windowLabel(start, end, timeZone) {
  const format = new Intl.DateTimeFormat("en-IN", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone
  });
  return `${format.format(new Date(start))} – ${format.format(new Date(end))}`;
}

function displayDate(value) {
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric", month: "long", year: "numeric"
  }).format(new Date(year, month - 1, day));
}

function setEmployee(employee) {
  selectedEmployee = employee;
  selectedLabel.textContent = `${employee.name || "Unnamed employee"} — ${employee.employee_id}`;
  viewButton.disabled = false;
  results.replaceChildren();
  searchStatus.textContent = "Employee selected.";
}

async function searchEmployees() {
  const query = searchInput.value.trim();
  results.replaceChildren();
  selectedEmployee = null;
  selectedLabel.textContent = "No employee selected";
  viewButton.disabled = true;
  if (!query) {
    searchStatus.textContent = "";
    return;
  }
  searchStatus.textContent = "Searching…";
  try {
    const response = await fetch(`/api/v1/employees?query=${encodeURIComponent(query)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || "Search failed.");
    searchStatus.textContent = data.count ? "Select using name and employee ID." : "No employees found.";
    for (const employee of data.employees) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "employee-option";
      button.textContent = `${employee.name || "Unnamed employee"} — ${employee.employee_id}`;
      button.addEventListener("click", () => setEmployee(employee));
      results.append(button);
    }
  } catch (error) {
    searchStatus.textContent = error.message;
  }
}

searchInput.addEventListener("input", () => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(searchEmployees, 250);
});

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => {
    for (const other of document.querySelectorAll(".tab")) {
      const active = other === tab;
      other.classList.toggle("active", active);
      other.setAttribute("aria-selected", String(active));
      document.getElementById(other.dataset.tab).classList.toggle("hidden", !active);
    }
  });
}

const summaryDate = document.querySelector("#summary-date");
const STALE_SYNC_MS = 60 * 60 * 1000;

function renderPeople(list, people, withTime, timeZone, workingDay) {
  list.replaceChildren();
  for (const person of people) {
    const item = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = `${person.name || "Unnamed employee"} — ${person.employee_id}`;
    item.append(name);
    if (withTime) {
      const time = document.createElement("span");
      time.className = "muted";
      time.textContent = `in ${punchTime(person.first_punch, workingDay, timeZone)}` +
        (person.registered ? "" : " · not in roster");
      item.append(time);
    }
    list.append(item);
  }
}

async function loadDailySummary() {
  const summaryError = document.querySelector("#summary-error");
  summaryError.textContent = "";
  try {
    const query = summaryDate.value ? `?date=${summaryDate.value}` : "";
    const response = await fetch(`/api/v1/attendance/daily${query}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || "Daily summary failed.");
    // The server decides the current working day (before the cutoff it is still yesterday).
    summaryDate.max = data.current_working_day;
    if (!summaryDate.value) summaryDate.value = data.date;
    if (!dateInput.value) dateInput.value = data.current_working_day;
    document.querySelector("#summary-window").textContent =
      `Counted window: ${windowLabel(data.window_start, data.window_end, data.timezone)}`;

    const isToday = data.absence_label === "not_in_yet";
    for (const word of document.querySelectorAll(".day-word")) {
      word.textContent = isToday ? "today" : `on ${displayDate(data.date)}`;
    }
    document.querySelector("#absent-heading").firstChild.textContent = isToday ? "Not in yet " : "Absent ";
    document.querySelector("#present-count").textContent = String(data.totals.present);
    document.querySelector("#absent-count").textContent = String(data.totals.not_in);
    document.querySelector("#present-empty").classList.toggle("hidden", data.present.length > 0);
    document.querySelector("#absent-empty").textContent = isToday
      ? "All employees are already in." : "No employee was absent.";
    document.querySelector("#absent-empty").classList.toggle("hidden", data.not_in.length > 0);
    renderPeople(document.querySelector("#present-list"), data.present, true, data.timezone, data.date);
    renderPeople(document.querySelector("#absent-list"), data.not_in, false, data.timezone, data.date);

    const asOf = document.querySelector("#data-as-of");
    if (data.data_as_of) {
      const stale = Date.now() - new Date(data.data_as_of).getTime() > STALE_SYNC_MS;
      asOf.textContent = `Data as of ${new Intl.DateTimeFormat("en-IN", {
        dateStyle: "medium", timeStyle: "short", timeZone: data.timezone
      }).format(new Date(data.data_as_of))}` + (stale ? " — last sync is over an hour old" : "");
      asOf.classList.toggle("stale", stale);
    } else {
      asOf.textContent = "No successful sync recorded yet.";
      asOf.classList.add("stale");
    }

    const warningBox = document.querySelector("#summary-warnings");
    warningBox.replaceChildren();
    for (const warning of data.warnings) {
      const item = document.createElement("p");
      item.className = "warning";
      item.textContent = warning.message;
      warningBox.append(item);
    }
  } catch (error) {
    summaryError.textContent = error.message;
  }
}

summaryDate.addEventListener("change", loadDailySummary);
document.querySelector("#summary-refresh").addEventListener("click", loadDailySummary);
loadDailySummary();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  pageError.textContent = "";
  if (!selectedEmployee || !dateInput.value) return;
  viewButton.disabled = true;
  try {
    const employeeId = encodeURIComponent(selectedEmployee.employee_id);
    const response = await fetch(`/api/v1/employees/${employeeId}/work-hours?date=${dateInput.value}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || "Attendance lookup failed.");
    document.querySelector("#result-employee").textContent = `${data.name || "Unnamed employee"} — ${data.employee_id}`;
    document.querySelector("#result-date").textContent = displayDate(data.date);
    document.querySelector("#result-window").textContent =
      windowLabel(data.window_start, data.window_end, data.timezone);
    document.querySelector("#first-punch").textContent = punchTime(data.first_punch, data.date, data.timezone);
    document.querySelector("#last-punch").textContent = punchTime(data.last_punch, data.date, data.timezone);
    document.querySelector("#attendance-span").textContent = data.calculated_duration || "Not available";
    document.querySelector("#punch-count").textContent = String(data.punch_count);

    const warningBox = document.querySelector("#warnings");
    warningBox.replaceChildren();
    for (const warning of data.warnings) {
      const item = document.createElement("p");
      item.className = "warning";
      item.textContent = warning.message;
      warningBox.append(item);
    }

    const punchList = document.querySelector("#punch-list");
    punchList.replaceChildren();
    for (const punch of data.punches) {
      const row = document.createElement("tr");
      for (const value of [punchTime(punch.timestamp_local, data.date, data.timezone), punch.status_raw ?? "—", punch.punch_raw ?? "—"]) {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.append(cell);
      }
      punchList.append(row);
    }
    resultPanel.classList.remove("hidden");
  } catch (error) {
    pageError.textContent = error.message;
  } finally {
    viewButton.disabled = false;
  }
});
