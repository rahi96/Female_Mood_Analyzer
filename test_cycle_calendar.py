from datetime import date

from ai.services import cycle_engine_v1_service as service
from main import app


def _empty_snapshot():
    return {
        "profile": None,
        "current_cycle": None,
        "bbt_logs": [],
        "opk_logs": [],
        "mucus_logs": [],
        "period_logs": [],
    }


def test_calendar_route_requires_only_user_id():
    operation = app.openapi()["paths"]["/api/v1/cycle-engine/calendar/month"]["get"]
    parameters = operation["parameters"]

    assert [parameter["name"] for parameter in parameters] == ["user_id"]
    assert "/api/v1/cycle-engine/calendar/confirm-day" not in app.openapi()["paths"]


def test_fetch_cycle_calendar_periods_normalizes_backend_records(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "success": True,
                "data": [
                    {
                        "id": 1,
                        "user_id": 2,
                        "start_date": "2026-08-03T00:00:00.000000Z",
                        "end_date": None,
                    }
                ],
            }

    monkeypatch.setattr(service.httpx, "get", lambda *args, **kwargs: Response())

    periods, source = service._fetch_cycle_calendar_periods(2)

    assert source.endswith("/2")
    assert periods == [
        {
            "id": 1,
            "user_id": 2,
            "start_date": "2026-08-03",
            "end_date": None,
        }
    ]


def test_calendar_month_marks_only_confirmed_period_range(monkeypatch):
    periods = [
        {
            "id": 1,
            "user_id": 2,
            "start_date": "2026-08-03",
            "end_date": None,
        }
    ]
    monkeypatch.setattr(
        service,
        "_fetch_cycle_calendar_periods",
        lambda user_id: (periods, f"https://example.test/cycle-calendar-inputs/{user_id}"),
    )
    monkeypatch.setattr(service, "get_db_snapshot", lambda user_id: _empty_snapshot())
    monkeypatch.setattr(service, "_today", lambda: date(2026, 8, 3))
    service._USER_STATE.clear()

    result = service.calendar_month(2)
    by_date = {item["date"]: item for item in result["days"]}

    assert result["month"] == "2026-08"
    assert result["ai_generated"] is False
    assert by_date["2026-08-03"]["tag"] == "period"
    assert by_date["2026-08-03"]["cycle_day"] == 1
    assert by_date["2026-08-04"]["tag"] != "period"


def test_calendar_month_marks_full_period_range(monkeypatch):
    periods = [
        {
            "id": 1,
            "user_id": 2,
            "start_date": "2026-08-03",
            "end_date": "2026-08-05",
        }
    ]
    monkeypatch.setattr(
        service,
        "_fetch_cycle_calendar_periods",
        lambda user_id: (periods, f"https://example.test/cycle-calendar-inputs/{user_id}"),
    )
    monkeypatch.setattr(service, "get_db_snapshot", lambda user_id: _empty_snapshot())
    monkeypatch.setattr(service, "_today", lambda: date(2026, 8, 3))
    service._USER_STATE.clear()

    result = service.calendar_month(2)
    by_date = {item["date"]: item for item in result["days"]}

    assert [by_date[f"2026-08-0{day}"]["tag"] for day in range(3, 6)] == [
        "period",
        "period",
        "period",
    ]
