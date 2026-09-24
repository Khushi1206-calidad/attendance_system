"""Generate a median working-hours graph from an attendance CSV/Excel report.

Examples:
    python attendance_median_graph.py attendance_report.xlsx
    python attendance_median_graph.py report.csv --date-column "Punch Date" --hours-column "Working Hours"
    python attendance_median_graph.py report.xlsx --period month
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


DATE_CANDIDATES = (
    "date",
    "attendance date",
    "punch date",
    "work date",
    "day",
)

HOURS_CANDIDATES = (
    "working hours",
    "work hours",
    "worked hours",
    "total hours",
    "hours worked",
    "duration",
)


def normalized(value: object) -> str:
    return " ".join(str(value).strip().lower().replace("_", " ").split())


def detect_column(columns: pd.Index, candidates: tuple[str, ...], kind: str) -> str:
    lookup = {normalized(column): str(column) for column in columns}
    for candidate in candidates:
        if candidate in lookup:
            return lookup[candidate]
    raise ValueError(
        f"Could not detect the {kind} column. Available columns: "
        + ", ".join(map(str, columns))
    )


def hours_as_number(series: pd.Series) -> pd.Series:
    """Convert numeric hours or values such as 09:30 / 09:30:00 to decimal hours."""
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() >= series.notna().sum() * 0.8:
        return numeric

    durations = pd.to_timedelta(series.astype(str).str.strip(), errors="coerce")
    return durations.dt.total_seconds() / 3600


def read_report(path: Path, sheet_name: str | int = 0) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, sheet_name=sheet_name)
    raise ValueError("The input report must be a .csv, .xlsx, or .xls file.")


def create_graph(
    input_path: Path,
    output_path: Path,
    date_column: str | None,
    hours_column: str | None,
    period: str,
    sheet_name: str | int,
) -> tuple[str, str, int]:
    df = read_report(input_path, sheet_name)
    if df.empty:
        raise ValueError("The attendance report contains no rows.")

    date_column = date_column or detect_column(df.columns, DATE_CANDIDATES, "date")
    hours_column = hours_column or detect_column(df.columns, HOURS_CANDIDATES, "working-hours")

    if date_column not in df.columns or hours_column not in df.columns:
        raise ValueError("The specified date or hours column does not exist in the report.")

    clean = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_column], errors="coerce", dayfirst=True),
            "hours": hours_as_number(df[hours_column]),
        }
    ).dropna()

    # Exclude impossible/invalid durations without altering valid flexible shifts.
    clean = clean[clean["hours"].between(0, 24)]
    if clean.empty:
        raise ValueError("No valid date and working-hours values were found.")

    if period == "day":
        clean["period"] = clean["date"].dt.normalize()
        x_label = "Date"
    elif period == "week":
        clean["period"] = clean["date"].dt.to_period("W").dt.start_time
        x_label = "Week starting"
    else:
        clean["period"] = clean["date"].dt.to_period("M").dt.to_timestamp()
        x_label = "Month"

    medians = clean.groupby("period", as_index=False)["hours"].median()

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(
        medians["period"],
        medians["hours"],
        marker="o",
        linewidth=2.2,
        color="#2563EB",
        label="Median working hours",
    )
    ax.axhline(9, color="#16A34A", linestyle="--", linewidth=1.5, label="9-hour reference")
    ax.set_title(f"Median Working Hours by {period.title()}", fontsize=15, weight="bold")
    ax.set_xlabel(x_label)
    ax.set_ylabel("Median working hours")
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)

    return date_column, hours_column, len(clean)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Path to the attendance CSV/Excel report")
    parser.add_argument("--date-column", help="Date column name; detected automatically if omitted")
    parser.add_argument("--hours-column", help="Working-hours column name; detected automatically if omitted")
    parser.add_argument("--period", choices=("day", "week", "month"), default="day")
    parser.add_argument("--sheet", default="0", help="Excel sheet name or zero-based sheet index")
    parser.add_argument("--output", type=Path, default=Path("attendance_median_graph.png"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sheet: str | int = int(args.sheet) if args.sheet.isdigit() else args.sheet
    date_col, hours_col, rows = create_graph(
        input_path=args.report,
        output_path=args.output,
        date_column=args.date_column,
        hours_column=args.hours_column,
        period=args.period,
        sheet_name=sheet,
    )
    print(f"Graph saved to: {args.output.resolve()}")
    print(f"Used columns: date='{date_col}', hours='{hours_col}' ({rows} valid rows)")


if __name__ == "__main__":
    main()
