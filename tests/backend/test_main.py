def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_single_event_endpoint(client, monkeypatch):
    monkeypatch.setattr("backend.main.get_tokens", lambda request: {"token": "fake"})
    monkeypatch.setattr("backend.main.build_credentials", lambda tokens: object())
    monkeypatch.setattr(
        "backend.main.get_event",
        lambda creds, calendar_id, event_id: {
            "id": event_id,
            "calendarId": calendar_id,
            "title": "Sample",
        },
    )

    response = client.get("/api/event?calendarId=primary&eventId=evt-1")

    assert response.status_code == 200
    assert response.json()["id"] == "evt-1"


def test_patch_single_event_endpoint(client, monkeypatch):
    monkeypatch.setattr("backend.main.get_tokens", lambda request: {"token": "fake"})
    monkeypatch.setattr("backend.main.build_credentials", lambda tokens: object())
    monkeypatch.setattr(
        "backend.main.update_event",
        lambda creds, calendar_id, event_id, body: {
            "id": event_id,
            "calendarId": calendar_id,
            "title": body.get("summary", "Updated"),
        },
    )

    response = client.patch(
        "/api/event?calendarId=primary&eventId=evt-1",
        json={"body": {"summary": "Updated Sample"}},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Updated Sample"


def test_delete_single_event_endpoint(client, monkeypatch):
    monkeypatch.setattr("backend.main.get_tokens", lambda request: {"token": "fake"})
    monkeypatch.setattr("backend.main.build_credentials", lambda tokens: object())
    monkeypatch.setattr(
        "backend.main.delete_event", lambda creds, calendar_id, event_id: None
    )

    response = client.delete("/api/event?calendarId=primary&eventId=evt-1")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
