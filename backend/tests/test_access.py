"""Sharing and permissions, in the service layer and over the API."""
import pytest
from fastapi.testclient import TestClient

from app.services import access


def test_share_roles(db, make_user, make_session):
    owner, viewer, contrib = make_user("o@x.com"), make_user("v@x.com"), make_user("c@x.com")
    s = make_session(owner)
    access.share_session(db, s, owner, "V@X.com ", "viewer")  # case/space-insensitive
    access.share_session(db, s, owner, "c@x.com", "contributor")
    assert access.can_edit(db, s, owner) and access.can_manage(db, s, owner)
    assert access.can_view(db, s, viewer) and not access.can_edit(db, s, viewer)
    assert access.can_edit(db, s, contrib) and not access.can_manage(db, s, contrib)
    assert {x.id for x in access.list_user_sessions(db, viewer)} == {s.id}
    with pytest.raises(access.AccessError):
        access.share_session(db, s, contrib, "v@x.com", "contributor")  # only owner shares
    with pytest.raises(access.AccessError):
        access.share_session(db, s, owner, "nobody@x.com", "viewer")
    access.unshare_session(db, s, owner, viewer.id)
    assert not access.can_view(db, s, viewer)


def _token(client, email):
    r = client.post("/api/v1/auth/login", data={"username": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_api_viewer_is_read_only(db, make_user, make_session):
    from app.main import app
    owner, viewer = make_user("o@x.com"), make_user("v@x.com")
    s = make_session(owner)
    access.share_session(db, s, owner, "v@x.com", "viewer")
    with TestClient(app) as client:
        hv, ho = _token(client, "v@x.com"), _token(client, "o@x.com")
        assert client.get(f"/api/v1/research/sessions/{s.id}/analysis", headers=hv).status_code == 200
        assert client.post(f"/api/v1/research/sessions/{s.id}/discover", json={}, headers=hv).status_code == 403
        assert client.post("/api/v1/papers/ingest", headers=hv,
                           json={"source": "openalex", "source_id": "W1", "session_id": s.id}).status_code == 403
        assert client.post(f"/api/v1/knowledge-map/sessions/{s.id}/generate", headers=hv,
                           json={}).status_code == 403
        r = client.post(f"/api/v1/research/sessions/{s.id}/discover", json={"max_papers": 10}, headers=ho)
        assert r.status_code == 200 and r.json()["added"] == 10
        r = client.post(f"/api/v1/research/sessions/{s.id}/export", headers=hv, json={"style": "APA"})
        assert r.status_code == 403  # viewer cannot generate a new draft
        health = client.get("/health").json()
        assert health["status"] == "healthy" and health["llm_provider"] == "offline"


def test_invite_code_required_when_set(db, monkeypatch):
    from app.config import settings
    from app.main import app
    monkeypatch.setattr(settings, "INVITE_CODE", "letmein")
    body = {"email": "new@x.com", "password": "password123", "full_name": "New"}
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/register", json=body).status_code == 403
        assert client.post("/api/v1/auth/register?invite_code=wrong", json=body).status_code == 403
        assert client.post("/api/v1/auth/register?invite_code=letmein", json=body).status_code == 201
