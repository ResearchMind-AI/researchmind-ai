"""Links between parts of a session: themes/guide know what changed, chat knows themes and gap checks."""
from tests.test_web import client_for, events


def test_guide_and_themes_track_changes(db):
    owner = client_for("l@x.com")
    s = owner.post("/api/v1/research/sessions", json={"topic": "LLMs for clinical decision support"}).json()
    base = f"/api/v1/research/sessions/{s['id']}"
    events(owner.post(f"{base}/analyse/stream", json={"max_papers": 10}))
    a = owner.get(f"{base}/analysis").json()
    assert a["changes"] is None and a["refresh_due"] is False

    secs = owner.post(f"{base}/writing/outline").json()
    owner.put(f"{base}/writing/sections/{secs[0]['id']}", json={"user_text": "My own words stay. [1]", "heading": "My intro"})
    assert owner.get(f"{base}/writing").json()["guide_changes"] is None

    papers = owner.get(f"{base}/papers").json()
    for p in papers[:3]:
        owner.patch(f"{base}/papers/{p['id']}", json={"status": "removed"})
    owner.patch(f"{base}/papers/{papers[4]['id']}", json={"is_key": True})
    gap = owner.get(f"{base}/gaps").json()[0]
    owner.patch(f"{base}/gaps/{gap['id']}", json={"pinned": True})
    owner.post(f"{base}/gaps/{gap['id']}/assess")

    a = owner.get(f"{base}/analysis").json()
    assert a["changes"]["papers_removed"] == 3 and a["refresh_due"] is True
    ch = owner.get(f"{base}/writing").json()["guide_changes"]
    assert ch["papers_removed"] == 3 and ch["key_changed"] == 1 and ch["gaps_tracked"] == 1
    assert "3 papers were removed" in ch["summary"] and "a gap was tracked" in ch["summary"]

    r = owner.post(f"{base}/writing/guidance/refresh").json()
    assert "3 papers were removed" in r["summary"]
    first = r["sections"][0]
    # outline and the user's text are untouched; guidance now uses key papers and the gap check
    assert first["heading"] == "My intro" and first["user_text"] == "My own words stay. [1]"
    assert [x["heading"] for x in r["sections"]] == ["My intro"] + [x["heading"] for x in secs[1:]]
    pts = " ".join(p["text"] for x in r["sections"] for p in x["guidance"]["points"])
    assert "leads with key papers" in pts and "positions against closest work" in pts
    removed_ns = {p["n"] for p in papers[:3]}
    assert not removed_ns & {n for x in r["sections"] for p in x["guidance"]["points"] for n in p["refs"]}
    assert owner.get(f"{base}/writing").json()["guide_changes"] is None

    owner.post(f"{base}/themes")
    a = owner.get(f"{base}/analysis").json()
    assert a["changes"] is None and a["refresh_due"] is False


def test_chat_context_includes_themes_and_gap_check(db, monkeypatch):
    from app.services import chat_service
    owner = client_for("c@x.com")
    s = owner.post("/api/v1/research/sessions", json={"topic": "LLMs for clinical decision support"}).json()
    base = f"/api/v1/research/sessions/{s['id']}"
    events(owner.post(f"{base}/analyse/stream", json={"max_papers": 8}))
    gap = owner.get(f"{base}/gaps").json()[0]
    owner.post(f"{base}/gaps/{gap['id']}/assess")
    owner.patch(f"{base}/gaps/{gap['id']}", json={"notes": "Ask the regional health board"})

    seen = []
    real = chat_service.build_context
    async def spy(*a, **k):
        ctx = await real(*a, **k)
        seen.append(ctx.system)
        return ctx
    monkeypatch.setattr(chat_service, "build_context", spy)
    from app.api.v1 import research
    monkeypatch.setattr(research, "build_context", spy, raising=False)
    events(owner.post(f"{base}/chat/stream", json={"question": "Where do they disagree?"}))
    events(owner.post(f"{base}/chat/stream", json={"question": "How could I study it?", "gap_id": gap["id"]}))
    assert seen and "Themes in this session" in seen[0]
    assert "Novelty check:" in seen[-1] and "regional health board" in seen[-1]
