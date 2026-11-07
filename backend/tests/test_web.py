"""Web app API: cookie auth, sessions, papers, members, streaming analysis and chat."""
import json

from fastapi.testclient import TestClient


def events(resp):
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


def client_for(email, password="password123", name=None, invite=None):
    from app.main import app
    c = TestClient(app)
    r = c.post("/api/v1/web/register", json={"email": email, "password": password, "full_name": name,
                                              "invite_code": invite})
    assert r.status_code == 201, r.text
    return c


def test_cookie_auth_flow(db, monkeypatch):
    from app.config import settings
    from app.main import app
    monkeypatch.setattr(settings, "INVITE_CODE", "abc123")
    c = TestClient(app)
    assert c.get("/api/v1/web/config").json()["invite_required"] is True
    assert c.post("/api/v1/web/register", json={"email": "a@x.com", "password": "password123"}).status_code == 403
    r = c.post("/api/v1/web/register", json={"email": "A@x.com", "password": "password123", "invite_code": "abc123"})
    assert r.status_code == 201 and "httponly" in r.headers["set-cookie"].lower()
    assert c.get("/api/v1/web/me").json()["email"] == "a@x.com"
    c.post("/api/v1/web/logout")
    assert c.get("/api/v1/web/me").status_code == 401
    assert c.post("/api/v1/web/login", json={"email": "a@x.com", "password": "wrong-pass"}).status_code == 401
    assert c.post("/api/v1/web/login", json={"email": "a@X.com", "password": "password123"}).status_code == 200
    assert c.get("/api/v1/research/sessions").json() == []


def test_session_lifecycle_and_streams(db):
    owner = client_for("o@x.com", name="Owner")
    viewer = client_for("v@x.com")
    s = owner.post("/api/v1/research/sessions", json={"topic": "LLMs for clinical decision support"}).json()
    assert s["role"] == "owner" and s["can_edit"] and s["paper_count"] == 0
    base = f"/api/v1/research/sessions/{s['id']}"

    r = owner.post(f"{base}/analyse/stream", json={"max_papers": 12})
    ev = events(r)
    assert ev[0]["type"] == "progress" and ev[-1]["type"] == "done"
    assert any("themes" in e.get("message", "") for e in ev)

    d = owner.get(base).json()
    assert d["paper_count"] == 12 and d["theme_count"] >= 2 and d["gap_count"] == 3 and d["discovery"]["added"] == 12
    papers = owner.get(f"{base}/papers").json()
    assert [p["n"] for p in papers] == list(range(1, 13)) and papers[0]["found_in"]

    r = owner.post(f"{base}/chat/stream", json={"question": "What do the studies find?"})
    ev = events(r)
    assert any(e["type"] == "token" for e in ev) and ev[-1]["type"] == "done"
    assert "[99]" not in ev[-1]["answer"]
    assert len(owner.get(f"{base}/messages").json()) == 2

    gap = owner.get(f"{base}/gaps").json()[0]
    owner.post(f"{base}/chat/stream", json={"question": "Is this real?", "gap_id": gap["id"]})
    assert len(owner.get(f"{base}/messages", params={"gap_id": gap["id"]}).json()) == 2
    assert len(owner.get(f"{base}/messages").json()) == 2  # main thread unchanged

    # sharing and members
    assert viewer.get(base).status_code == 404
    owner.post(f"{base}/share", json={"email": "v@x.com", "role": "viewer"})
    v = viewer.get(base).json()
    assert v["role"] == "viewer" and not v["can_edit"]
    assert viewer.post(f"{base}/chat/stream", json={"question": "hi there"}).status_code == 403
    assert viewer.post(f"{base}/analyse/stream", json={}).status_code == 403
    m = owner.get(f"{base}/members").json()
    assert [x["role"] for x in m] == ["owner", "viewer"]
    assert viewer.delete(f"{base}/members/{m[1]['user_id']}").status_code == 403
    assert owner.delete(f"{base}/members/{m[1]['user_id']}").status_code == 204
    assert viewer.get(base).status_code == 404

    # writing: sections, move, title, example
    secs = owner.post(f"{base}/writing/outline").json()
    new = owner.post(f"{base}/writing/sections", json={"heading": "Methods"}).json()
    order = owner.post(f"{base}/writing/sections/{new['id']}/move", json={"direction": -1}).json()
    assert order[-2]["id"] == new["id"]
    assert owner.put(f"{base}/writing/title", json={"title": "My review"}).json()["title"] == "My review"
    assert owner.get(f"{base}/writing").json()["title"] == "My review"
    assert owner.delete(f"{base}/writing/sections/{new['id']}").status_code == 204
    assert owner.get(f"{base}/writing/example").json() is None
    ex = owner.post(f"{base}/writing/example").json()
    assert ex["references"] and len(secs) == 4

    # user gaps can be deleted; delete session
    g = owner.post(f"{base}/gaps/custom", json={"title": "A gap of my own", "assess": False}).json()
    assert owner.delete(f"{base}/gaps/{g['id']}").status_code == 204
    assert owner.delete(base).status_code == 204
    assert owner.get("/api/v1/research/sessions").json() == []


def test_spa_fallback_and_api_404(db):
    """Unknown non-API paths return the web app; unknown API paths stay JSON 404s."""
    import pytest
    from app import main
    if main.WEB_DIR is None:
        pytest.skip("frontend not built")
    client = TestClient(main.app)
    r = client.get("/s/1/gaps")
    assert r.status_code == 200 and "<div id=\"root\">" in r.text
    assert r.headers.get("cache-control") == "no-cache"
    r = client.get("/api/v1/does-not-exist")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")
    assert "root:" not in client.get("/..%2F..%2Fetc%2Fpasswd").text
