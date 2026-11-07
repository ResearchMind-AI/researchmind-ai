"""Working together: proposals, ownership + suggested edits, versions, comments, what's new, presence."""
from tests.test_web import client_for, events


def _session_with_papers(owner, n=8):
    s = owner.post("/api/v1/research/sessions", json={"topic": "LLMs for clinical decision support"}).json()
    base = f"/api/v1/research/sessions/{s['id']}"
    events(owner.post(f"{base}/analyse/stream", json={"max_papers": n}))
    return base


def test_solo_changes_apply_immediately_and_are_logged(db):
    a = client_for("solo@x.com", name="Vicky Solo")
    base = _session_with_papers(a)
    p = a.get(f"{base}/papers").json()[2]
    r = a.patch(f"{base}/papers/{p['id']}", json={"status": "removed", "removed_reason": "off_topic"})
    assert r.status_code == 200 and r.json()["status"] == "removed"
    assert a.get(f"{base}/collab").json()["collaborative"] is False
    h = a.get(f"{base}/history", params={"target_type": "paper", "target_id": p["id"]}).json()
    assert h[0]["kind"] == "paper_removed" and "paper 3 (off-topic)" in h[0]["summary"]


def test_proposals_need_someone_else(db):
    a = client_for("va@x.com", name="Vicky")
    b = client_for("pr@x.com", name="Priya Raman")
    base = _session_with_papers(a)
    a.post(f"{base}/share", json={"email": "pr@x.com", "role": "contributor"})
    st = a.get(f"{base}/collab").json()
    assert st["collaborative"] and [m["role"] for m in st["members"]] == ["owner", "contributor"]

    papers = a.get(f"{base}/papers").json()
    p = papers[0]
    r = b.patch(f"{base}/papers/{p['id']}", json={"status": "removed", "removed_reason": "off_topic"})
    assert r.status_code == 202
    prop = r.json()["proposal"]
    assert prop["kind"] == "remove_paper" and prop["proposed_by_name"] == "Priya Raman"
    assert r.json()["paper"]["status"] == "kept"                      # nothing changes yet
    assert b.patch(f"{base}/papers/{p['id']}", json={"status": "removed"}).status_code == 409   # duplicate
    d = f"{base}/proposals/{prop['id']}/decide"
    assert b.post(d, json={"decision": "approve"}).status_code == 403   # not your own
    # what's new for Vicky: the proposal needs her
    wn = a.get(f"{base}/whats-new").json()
    assert any(x["type"] == "proposal" and "removing paper 1" in x["text"] for x in wn["needs_you"])
    assert a.post(d, json={"decision": "approve"}).json()["status"] == "approved"
    assert next(x for x in a.get(f"{base}/papers").json() if x["id"] == p["id"])["status"] == "removed"
    assert a.post(d, json={"decision": "reject"}).status_code == 409    # already decided
    h = a.get(f"{base}/history", params={"target_type": "paper", "target_id": p["id"]}).json()
    assert h[0]["summary"] == "removed paper 1 (off-topic) (approved by Vicky)" and h[0]["user_name"] == "Priya Raman"

    # restore is a proposal too; the proposer can withdraw it
    r = a.patch(f"{base}/papers/{p['id']}", json={"status": "kept"}).json()["proposal"]
    assert a.post(f"{base}/proposals/{r['id']}/decide", json={"decision": "withdraw"}).json()["status"] == "withdrawn"
    # someone else rejects a removal: the paper stays
    r = a.patch(f"{base}/papers/{papers[1]['id']}", json={"status": "removed"}).json()["proposal"]
    assert b.post(f"{base}/proposals/{r['id']}/decide", json={"decision": "reject"}).json()["status"] == "rejected"
    assert next(x for x in a.get(f"{base}/papers").json() if x["id"] == papers[1]["id"])["status"] == "kept"
    # key papers and notes don't need approval
    assert b.patch(f"{base}/papers/{papers[2]['id']}", json={"is_key": True}).json()["is_key"] is True

    # gaps: tracking is direct, untracking and deleting are proposals
    g = a.get(f"{base}/gaps").json()[0]
    assert a.patch(f"{base}/gaps/{g['id']}", json={"pinned": True}).json()["pinned"] is True
    r = a.patch(f"{base}/gaps/{g['id']}", json={"pinned": False})
    assert r.status_code == 202 and r.json()["gap"]["pinned"] is True
    b.post(f"{base}/proposals/{r.json()['proposal']['id']}/decide", json={"decision": "approve"})
    assert next(x for x in a.get(f"{base}/gaps").json() if x["id"] == g["id"])["pinned"] is False
    r = b.delete(f"{base}/gaps/{g['id']}")
    assert r.status_code == 202
    a.post(f"{base}/proposals/{r.json()['proposal']['id']}/decide", json={"decision": "approve"})
    assert all(x["id"] != g["id"] for x in a.get(f"{base}/gaps").json())

    # viewers can't propose or decide
    v = client_for("sup@x.com", name="Supervisor")
    a.post(f"{base}/share", json={"email": "sup@x.com", "role": "viewer"})
    assert v.patch(f"{base}/papers/{papers[3]['id']}", json={"status": "removed"}).status_code == 403


def test_sections_owners_suggestions_and_versions(db):
    a = client_for("wa@x.com", name="Vicky")
    b = client_for("wb@x.com", name="Priya")
    base = _session_with_papers(a, n=6)
    a.post(f"{base}/share", json={"email": "wb@x.com", "role": "contributor"})
    secs = a.post(f"{base}/writing/outline").json()
    intro = secs[0]
    r = a.put(f"{base}/writing/sections/{intro['id']}", json={"user_text": "Early evaluations report high accuracy [1].", "base_version": 0}).json()
    assert r["owner_id"] and r["version"] == 1

    # Priya can't overwrite Vicky's section; she suggests an edit instead
    assert b.put(f"{base}/writing/sections/{intro['id']}", json={"user_text": "mine now"}).status_code == 403
    sug = b.post(f"{base}/writing/sections/{intro['id']}/suggestions",
                 json={"text": "Early evaluations report accuracy between 74% and 86% [1].", "note": "Give the numbers"}).json()
    assert sug["status"] == "pending" and sug["base_text"].startswith("Early evaluations report high")
    assert a.post(f"{base}/writing/sections/{intro['id']}/suggestions", json={"text": "x"}).status_code == 400
    wn = a.get(f"{base}/whats-new").json()
    assert any(x["type"] == "suggestion" and x["section_id"] == intro["id"] for x in wn["needs_you"])
    assert b.post(f"{base}/suggestions/{sug['id']}/decide", json={"decision": "accept"}).status_code == 403
    assert a.post(f"{base}/suggestions/{sug['id']}/decide", json={"decision": "accept"}).json()["status"] == "accepted"
    w = a.get(f"{base}/writing").json()["sections"][0]
    assert "74% and 86%" in w["user_text"] and w["version"] == 2

    # a suggestion made against an older text can't be accepted blindly
    s2 = b.post(f"{base}/writing/sections/{intro['id']}/suggestions", json={"text": "Different wording [1]."}).json()
    a.put(f"{base}/writing/sections/{intro['id']}", json={"user_text": "Vicky changed it again [1].", "base_version": 2})
    r = a.post(f"{base}/suggestions/{s2['id']}/decide", json={"decision": "accept"})
    assert r.status_code == 409 and r.json()["detail"]["current_text"] == "Vicky changed it again [1]."
    assert b.post(f"{base}/suggestions/{s2['id']}/decide", json={"decision": "withdraw"}).json()["status"] == "withdrawn"

    # stale saves are refused with the current text, so nothing is silently overwritten
    r = a.put(f"{base}/writing/sections/{intro['id']}", json={"user_text": "from an old tab", "base_version": 1})
    assert r.status_code == 409 and r.json()["detail"]["current_text"] == "Vicky changed it again [1]."

    # Priya owns the section she starts; deleting a section is a proposal
    other = secs[1]
    assert b.put(f"{base}/writing/sections/{other['id']}", json={"user_text": "Priya's words."}).json()["owner_id"]
    r = a.delete(f"{base}/writing/sections/{other['id']}")
    assert r.status_code == 202
    b.post(f"{base}/proposals/{r.json()['proposal']['id']}/decide", json={"decision": "approve"})
    assert all(x["id"] != other["id"] for x in a.get(f"{base}/writing").json()["sections"])

    # writing in one go is one history entry, not one per autosave
    h = a.get(f"{base}/history", params={"target_type": "section", "target_id": intro["id"]}).json()
    kinds = [x["kind"] for x in h]
    assert kinds.count("suggestion_accepted") == 1 and kinds.count("suggestion_created") == 2


def test_comments_mentions_whats_new_and_presence(db):
    a = client_for("ca@x.com", name="Vicky Srinivasan")
    b = client_for("cb@x.com", name="Priya")
    v = client_for("cv@x.com", name="Supervisor")
    base = _session_with_papers(a, n=6)
    a.post(f"{base}/share", json={"email": "cb@x.com", "role": "contributor"})
    a.post(f"{base}/share", json={"email": "cv@x.com", "role": "viewer"})
    a.post(f"{base}/seen")
    p = a.get(f"{base}/papers").json()[0]

    c = v.post(f"{base}/comments", json={"target_type": "paper", "target_id": p["id"],
                                         "body": "@Vicky the panel was only 3 psychiatrists. Limitation?"}).json()
    b.post(f"{base}/comments", json={"parent_id": c["id"], "body": "Agree, worth flagging."})
    assert v.post(f"{base}/comments", json={"target_type": "nope", "target_id": 1, "body": "x"}).status_code == 400
    t = a.get(f"{base}/comments", params={"target_type": "paper", "target_id": p["id"]}).json()
    assert len(t) == 1 and t[0]["user_name"] == "Supervisor" and len(t[0]["replies"]) == 1
    assert t[0]["mentions"] == [a.get("/api/v1/web/me").json()["id"]]

    wn = a.get(f"{base}/whats-new").json()
    assert any(x["type"] == "mention" for x in wn["needs_you"]) and wn["unseen"] >= 2 and wn["count"] >= 3
    a.post(f"{base}/comments/{c['id']}/resolve", json={"resolved": True})
    wn = a.get(f"{base}/whats-new").json()
    assert not any(x["type"] == "mention" for x in wn["needs_you"])
    a.post(f"{base}/seen")
    assert a.get(f"{base}/whats-new").json()["unseen"] == 0

    # section comments can quote a sentence
    secs = a.post(f"{base}/writing/outline").json()
    q = b.post(f"{base}/comments", json={"target_type": "section", "target_id": secs[0]["id"],
                                         "quote": "most studies use retrospective cases", "body": "How many exactly?"})
    assert q.status_code == 201
    assert a.get(f"{base}/comments", params={"target_type": "section"}).json()[0]["quote"].startswith("most studies")

    # presence
    b.post(f"{base}/presence", json={"where": "Write · Benchmarking"})
    here = a.post(f"{base}/presence", json={"where": "Papers"}).json()
    assert [x["name"] for x in here] == ["Priya"] and here[0]["where"] == "Write · Benchmarking"
    assert a.get(f"{base}/collab").json()["present"][0]["name"] == "Priya"
