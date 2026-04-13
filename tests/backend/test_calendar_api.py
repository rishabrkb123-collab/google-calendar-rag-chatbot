from unittest.mock import patch, MagicMock
from backend.calendar_api import build_credentials, fetch_events, list_calendars


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
    mock_service.events.return_value.list.return_value.execute.return_value = mock_events_result

    with patch("backend.calendar_api.build", return_value=mock_service):
        events, next_token = fetch_events(mock_creds, calendar_id="primary")

    assert len(events) == 1
    assert events[0]["id"] == "abc123"
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
    mock_service.calendarList.return_value.list.return_value.execute.return_value = mock_cal_result

    with patch("backend.calendar_api.build", return_value=mock_service):
        calendars = list_calendars(mock_creds)

    assert len(calendars) == 1
    assert calendars[0]["id"] == "primary"
    assert calendars[0]["name"] == "My Calendar"
    assert calendars[0]["color"] == "#4285F4"
