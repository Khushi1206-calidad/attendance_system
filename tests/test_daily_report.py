from datetime import UTC, date, datetime

from attendance_service.backend.daily_report import classify_daily_presence
from attendance_service.database.read_models import DailyPresenceRow


def row(employee_id, name, *, in_roster=True, first=None, count=0):
    return DailyPresenceRow(employee_id, name, in_roster, first, first, count)


def test_classifies_present_not_in_and_unregistered() -> None:
    rows = [
        row("2", "Zara"),
        row("1", "Amit", first=datetime(2026, 9, 24, 4, 0, tzinfo=UTC), count=2),
        row("9", "Guest", in_roster=False,
            first=datetime(2026, 9, 24, 3, 0, tzinfo=UTC), count=1),
        row("3", "bhavna"),
    ]

    present, not_in, label, warnings = classify_daily_presence(
        rows, selected_date=date(2026, 9, 24), today_local=date(2026, 9, 24)
    )

    assert [r.employee_id for r in present] == ["9", "1"]
    assert [r.employee_id for r in not_in] == ["3", "2"]
    assert label == "not_in_yet"
    assert [w.code for w in warnings] == ["unregistered_employees"]

    *_, past_label, _ = classify_daily_presence(
        rows, selected_date=date(2026, 9, 23), today_local=date(2026, 9, 24)
    )
    assert past_label == "absent"
