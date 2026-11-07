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


def test_partner_focus_and_notices(db, monkeypatch):
    from app.services import chat_service
    owner = client_for("p@x.com")
    s = owner.post("/api/v1/research/sessions", json={"topic": "LLMs for clinical decision support"}).json()
    base = f"/api/v1/research/sessions/{s['id']}"
    events(owner.post(f"{base}/analyse/stream", json={"max_papers": 12}))
    assert [n["id"] for n in owner.get(f"{base}/partner/notices").json()] == ["no-key-papers"]

    seen = []
    real = chat_service.build_context
    async def spy(*a, **k):
        ctx = await real(*a, **k)
        seen.append((k.get("focus"), ctx.system, [c["paper_id"] for c in ctx.sources]))
        return ctx
    monkeypatch.setattr(chat_service, "build_context", spy)

    themes = owner.get(f"{base}/analysis").json()["analysis"]["themes"]
    events(owner.post(f"{base}/chat/stream", json={"question": "What do they find?", "theme": 0}))
    focus, system, used = seen[-1]
    assert focus["kind"] == "theme" and themes[0]["label"] in system
    assert set(used) & set(themes[0]["paper_ids"])
    assert owner.post(f"{base}/chat/stream", json={"question": "x?", "theme": 99}).status_code == 404

    secs = owner.post(f"{base}/writing/outline").json()
    owner.put(f"{base}/writing/sections/{secs[0]['id']}", json={"user_text": "My draft cites [2] and [3]."})
    events(owner.post(f"{base}/chat/stream", json={"question": "Is this well supported?", "section_id": secs[0]["id"]}))
    focus, system, _ = seen[-1]
    assert focus["kind"] == "section" and "My draft cites [2] and [3]." in system and "Do not write sentences" in system

    # notices react to the session
    papers = owner.get(f"{base}/papers").json()
    owner.patch(f"{base}/papers/{papers[1]['id']}", json={"status": "removed"})
    owner.patch(f"{base}/papers/{papers[0]['id']}", json={"is_key": True})
    ids = [n["id"] for n in owner.get(f"{base}/partner/notices").json()]
    assert any(i.startswith(f"removed-cite-{secs[0]['id']}-2") for i in ids)
    assert any(i.startswith("key-abstract-only") for i in ids) and "no-key-papers" not in ids
    note = next(n for n in owner.get(f"{base}/partner/notices").json() if n["id"].startswith("removed-cite"))
    assert "[2]" in note["text"] and note["actions"][0]["to"].startswith("write?section=")
