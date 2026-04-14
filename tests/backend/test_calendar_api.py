import json
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
from fastapi import HTTPException
from googleapiclient.errors import HttpError

from backend.calendar_api import (
    build_credentials,
    fetch_all_events,
    fetch_events,
    list_calendars,
    translate_google_api_error,
)


def test_fetch_events_returns_list():
    mock_creds = MagicMock()
    mock_service = MagicMock()
    mock_events_result = {
        "items": [
            {
                "id": "abc123",
                "summary": "Team standup",
                "start": {"dateTime": "2026-04-14T09:00:00Z"},
                "end": {"dateTime": "2026-04-14T09:30:00Z"},
                "description": "Daily sync",
                "location": "Zoom",
                "organizer": {"email": "boss@example.com"},
                "htmlLink": "https://calendar.google.com/event?id=abc123",
                "colorId": None,
            }
        ],
        "nextPageToken": None,
    }
    mock_service.events.return_value.list.return_value.execute.return_value = (
        mock_events_result
    )

    with patch("backend.calendar_api.build", return_value=mock_service):
        events, next_token = fetch_events(mock_creds, calendar_id="primary")

    assert len(events) == 1
    assert events[0]["id"] == "abc123"
    assert events[0]["calendarId"] == "primary"
    assert events[0]["title"] == "Team standup"
    assert next_token is None


def test_list_calendars_returns_list():
    mock_creds = MagicMock()
    mock_service = MagicMock()
    mock_cal_result = {
        "items": [
            {"id": "primary", "summary": "My Calendar", "backgroundColor": "#4285F4"}
        ]
    }
    mock_service.calendarList.return_value.list.return_value.execute.return_value = (
        mock_cal_result
    )

    with patch("backend.calendar_api.build", return_value=mock_service):
        calendars = list_calendars(mock_creds)

    assert len(calendars) == 1
    assert calendars[0]["id"] == "primary"
    assert calendars[0]["name"] == "My Calendar"
    assert calendars[0]["color"] == "#4285F4"
    assert calendars[0]["primary"] is False
    assert calendars[0]["isHoliday"] is False


def test_translate_google_api_error_for_disabled_calendar_api():
    payload = {
        "error": {
            "errors": [
                {
                    "message": "Google Calendar API has not been used in project 900942781004 before or it is disabled.",
                    "reason": "accessNotConfigured",
                    "extendedHelp": "https://console.developers.google.com",
                }
            ]
        }
    }
    exc = HttpError(
        SimpleNamespace(status=403, reason="Forbidden"),
        json.dumps(payload).encode("utf-8"),
    )

    with pytest.raises(HTTPException) as caught:
        translate_google_api_error(exc)

    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "google_calendar_api_not_enabled"
    assert "Enable the Google Calendar API" in caught.value.detail["resolution"]


def test_fetch_all_events_collects_all_pages_and_calendars():
    mock_creds = MagicMock()

    with (
        patch(
            "backend.calendar_api.list_calendars",
            return_value=[{"id": "primary"}, {"id": "work"}],
        ),
        patch(
            "backend.calendar_api.fetch_events",
            side_effect=[
                (
                    [
                        {
                            "id": "p1",
                            "calendarId": "primary",
                            "start": {"dateTime": "2026-04-14T09:00:00Z"},
                        }
                    ],
                    "page-2",
                ),
                (
                    [
                        {
                            "id": "p2",
                            "calendarId": "primary",
                            "start": {"dateTime": "2026-04-14T10:00:00Z"},
                        }
                    ],
                    None,
                ),
                (
                    [
                        {
                            "id": "w1",
                            "calendarId": "work",
                            "start": {"dateTime": "2026-04-14T11:00:00Z"},
                        }
                    ],
                    None,
                ),
            ],
        ),
    ):
        events, scanned_calendar_ids = fetch_all_events(mock_creds)

    assert scanned_calendar_ids == ["primary", "work"]
    assert [event["id"] for event in events] == ["p1", "p2", "w1"]


def test_fetch_all_events_limits_special_calendars_to_recent_years_when_unbounded():
    mock_creds = MagicMock()

    with patch(
        "backend.calendar_api.fetch_events",
        return_value=([], None),
    ) as fetch_events_mock:
        fetch_all_events(
            mock_creds,
            calendar_ids=["en.indian#holiday@group.v.calendar.google.com"],
        )

    kwargs = fetch_events_mock.call_args.kwargs
    assert kwargs["time_min"] is not None
    assert kwargs["time_max"] is not None
