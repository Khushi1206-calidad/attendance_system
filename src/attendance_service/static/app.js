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

const today = new Date();
dateInput.value = [
  today.getFullYear(),
  String(today.getMonth() + 1).padStart(2, "0"),
  String(today.getDate()).padStart(2, "0")
].join("-");

function localTime(value, timeZone) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    hour: "2-digit", minute: "2-digit", hour12: false, timeZone
  }).format(new Date(value));
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
    document.querySelector("#first-punch").textContent = localTime(data.first_punch, data.timezone);
    document.querySelector("#last-punch").textContent = localTime(data.last_punch, data.timezone);
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
      for (const value of [localTime(punch.timestamp_local, data.timezone), punch.status_raw ?? "—", punch.punch_raw ?? "—"]) {
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
