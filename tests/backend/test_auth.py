def test_auth_status_unauthenticated(client):
    response = client.get("/auth/status")
    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    assert response.json()["email"] is None


def test_logout_clears_session(client):
    response = client.post("/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"message": "Logged out"}


def test_login_redirects(client):
    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code in (302, 307)
    location = response.headers.get("location", "")
    assert "accounts.google.com" in location
