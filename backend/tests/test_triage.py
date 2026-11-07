"""Paper triage: fixed numbers, keep/remove, key papers, notes, add by DOI, upload matching."""
from tests.test_web import client_for, events


def _pdf(title: str, body: str) -> bytes:
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 560, 800), f"{title}\n\n{body}", fontsize=9)
    doc.set_metadata({"title": title})
    return doc.tobytes()


def _setup(owner, n=10):
    s = owner.post("/api/v1/research/sessions", json={"topic": "LLMs for clinical decision support"}).json()
    base = f"/api/v1/research/sessions/{s['id']}"
    events(owner.post(f"{base}/analyse/stream", json={"max_papers": n}))
    return base


def test_triage_flow(db):
    owner = client_for("t@x.com")
    base = _setup(owner)
    papers = owner.get(f"{base}/papers").json()
    assert [p["n"] for p in papers] == list(range(1, 11))
    assert all(p["status"] == "kept" and not p["is_key"] for p in papers)
    p2, p3 = papers[1], papers[2]

    # remove with a reason; key + note on another
    r = owner.patch(f"{base}/papers/{p2['id']}", json={"status": "removed", "removed_reason": "off_topic"}).json()
    assert r["status"] == "removed" and r["removed_reason"] == "off_topic" and r["n"] == 2
    r = owner.patch(f"{base}/papers/{p3['id']}", json={"is_key": True, "notes": "  Use in intro  "}).json()
    assert r["is_key"] and r["notes"] == "Use in intro"
    assert owner.patch(f"{base}/papers/{p2['id']}", json={"is_key": True}).status_code == 400
    assert owner.patch(f"{base}/papers/{p2['id']}", json={"removed_reason": "nonsense"}).status_code == 400
    assert owner.patch(f"{base}/papers/999999", json={"status": "removed"}).status_code == 400

    d = owner.get(base).json()
    assert d["paper_count"] == 9
    sc = d["screening"]
    assert (sc["found"], sc["kept"], sc["removed"], sc["key"]) == (10, 9, 1, 1)
    assert sc["removed_reasons"] == {"off_topic": 1} and sc["screened"] >= 10

    # removed papers are not used by chat or themes
    ev = events(owner.post(f"{base}/chat/stream", json={"question": "What do the studies find?"}))
    assert all(c["n"] != 2 for c in ev[-1]["citations"])
    analysis = owner.post(f"{base}/themes").json()
    in_themes = {i for t in analysis["themes"] for i in t["paper_ids"]}
    assert p2["id"] not in in_themes and p3["id"] in in_themes

    # finding more papers never brings the removed one back; numbers continue
    events(owner.post(f"{base}/analyse/stream", json={"max_papers": 14}))
    after = owner.get(f"{base}/papers").json()
    assert sum(p["id"] == p2["id"] for p in after) == 1
    assert next(p for p in after if p["id"] == p2["id"])["status"] == "removed"
    ns = [p["n"] for p in after]
    assert ns == sorted(ns) and len(set(ns)) == len(ns) and ns[:10] == list(range(1, 11))

    # restoring clears the reason; numbers never change
    r = owner.patch(f"{base}/papers/{p2['id']}", json={"status": "kept"}).json()
    assert r["status"] == "kept" and r["removed_reason"] is None and r["n"] == 2


def test_removed_citations_flagged_in_writing_and_viewers_read_only(db):
    owner = client_for("w@x.com")
    viewer = client_for("wv@x.com")
    base = _setup(owner, n=8)
    papers = owner.get(f"{base}/papers").json()
    owner.patch(f"{base}/papers/{papers[3]['id']}", json={"status": "removed"})
    secs = owner.post(f"{base}/writing/outline").json()
    text = ("Large language models are being tested for clinical decision support in many settings [1]. "
            "Accuracy varies widely between studies and settings [4]. Few studies measure patient outcomes [2][99].")
    owner.put(f"{base}/writing/sections/{secs[0]['id']}", json={"user_text": text})
    fb = owner.post(f"{base}/writing/sections/{secs[0]['id']}/check").json()
    assert [r["n"] for r in fb["removed_refs"]] == [4] and fb["unknown_refs"] == [99]
    # export still resolves the removed paper's citation
    r = owner.get(f"{base}/writing/export", params={"style": "APA", "format": "docx"})
    assert r.status_code == 200, r.text

    owner.post(f"{base}/share", json={"email": "wv@x.com", "role": "viewer"})
    assert viewer.patch(f"{base}/papers/{papers[0]['id']}", json={"status": "removed"}).status_code == 403
    assert viewer.get(f"{base}/papers").status_code == 200


def test_add_by_doi_and_upload_matching(db):
    owner = client_for("d@x.com")
    base = _setup(owner, n=6)
    assert owner.post(f"{base}/papers/doi", json={"doi": "not a doi"}).status_code == 400
    assert owner.post(f"{base}/papers/doi", json={"doi": "10.1234/unknown.1"}).status_code == 400
    p = owner.post(f"{base}/papers/doi", json={"doi": "https://doi.org/10.1234/abc.5"})
    assert p.status_code == 201, p.text
    p = p.json()
    assert p["n"] == 7 and p["doi"] == "10.1234/abc.5" and p["status"] == "kept"
    dup = owner.post(f"{base}/papers/doi", json={"doi": "10.1234/abc.5"})
    assert dup.status_code == 400 and "[7]" in dup.json()["detail"]

    # a PDF of a paper already here is attached as its full text, not added twice
    target = owner.get(f"{base}/papers").json()[1]
    body = "Background. " + "This study evaluates decision support in clinical settings. " * 40
    r = owner.post(f"{base}/upload", files={"file": ("copy.pdf", _pdf(target["title"], body), "application/pdf")}).json()
    assert r["attached"] and r["paper_id"] == target["id"]
    papers = owner.get(f"{base}/papers").json()
    assert len(papers) == 7
    t = next(x for x in papers if x["id"] == target["id"])
    assert t["full_text"] and t["full_text_source"] == "upload"

    # explicit attach_to; and a new paper gets the next number
    other = papers[2]
    r = owner.post(f"{base}/upload", params={"attach_to": other["id"]},
                   files={"file": ("x.pdf", _pdf("Something else entirely", body), "application/pdf")}).json()
    assert r["attached"] and r["paper_id"] == other["id"]
    r = owner.post(f"{base}/upload",
                   files={"file": ("new.pdf", _pdf("A completely new study of triage tools in rural hospitals", body),
                                   "application/pdf")}).json()
    assert not r["attached"]
    new = next(x for x in owner.get(f"{base}/papers").json() if x["id"] == r["paper_id"])
    assert new["n"] == 8 and new["uploaded"]


def test_backfill_numbers_for_existing_rows(db, make_user, make_session):
    from app.core.database import backfill_ref_numbers, engine
    from app.models.paper import Paper, PaperSource, SessionPaper
    u = make_user()
    s = make_session(u)
    ps = [Paper(title=f"P{i}", source=PaperSource.OPENALEX, source_id=f"bf{i}") for i in range(4)]
    db.add_all(ps)
    db.flush()
    # older rows: no numbers; relevance decides the order, NULL relevance last
    for p, rel in zip(ps, [3, 5, None, 5]):
        db.add(SessionPaper(session_id=s.id, paper_id=p.id, added_by_user_id=u.id, relevance_score=rel))
    db.commit()
    with engine.begin() as conn:
        backfill_ref_numbers(conn)
    db.expire_all()
    got = {sp.paper_id: sp.ref_no for sp in db.query(SessionPaper).filter(SessionPaper.session_id == s.id)}
    assert got == {ps[1].id: 1, ps[3].id: 2, ps[0].id: 3, ps[2].id: 4}
