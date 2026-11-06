"""Gaps workspace and writing guide (offline mode)."""
import asyncio
import io

import pytest
from docx import Document

from app.models.research import Gap, SessionMessage, WritingSection
from app.services import gaps_service as gs
from app.services import writing_service as ws
from app.services.analysis_service import generate_gaps, generate_themes, list_session_papers
from app.services.chat_service import answer_question
from app.services.discovery_service import discover_papers, save_artifact
from app.services.export_service import render


def run(c):
    return asyncio.run(c)


@pytest.fixture()
def analysed(db, make_user, make_session):
    u = make_user()
    s = make_session(u)
    run(discover_papers(db, s.id, u.id, s.topic, max_papers=15))
    run(generate_themes(db, s.id, s.topic))
    run(generate_gaps(db, s.id, s.topic))
    return u, s


def test_ai_gaps_saved_and_regeneration_keeps_pinned_and_user_gaps(db, analysed):
    u, s = analysed
    gaps = gs.list_gaps(db, s.id)
    assert len(gaps) == 3 and all(g.source == "ai" for g in gaps)
    pinned = gaps[0]
    gs.update_gap(db, pinned, pinned=True, status="promising", notes="looks good")
    mine = gs.add_user_gap(db, s.id, u.id, "My own gap about rural hospitals", "Nobody studies rural EDs")
    run(answer_question(db, s.id, u.id, "Is this gap real?", gap=gaps[1]))  # thread on an unpinned gap
    assert db.query(SessionMessage).filter_by(gap_id=gaps[1].id).count() == 2

    run(generate_gaps(db, s.id, s.topic))
    after = gs.list_gaps(db, s.id)
    ids = {g.id for g in after}
    assert pinned.id in ids and mine.id in ids
    assert gaps[1].id not in ids
    assert db.query(SessionMessage).filter_by(gap_id=gaps[1].id).count() == 0  # orphan thread removed
    assert db.get(Gap, pinned.id).status == "promising"
    with pytest.raises(gs.GapError):
        gs.update_gap(db, pinned, status="bogus")
    with pytest.raises(gs.GapError):
        gs.add_user_gap(db, s.id, u.id, "abc")


def test_legacy_gaps_are_imported(db, make_user, make_session):
    u = make_user()
    s = make_session(u)
    save_artifact(db, s.id, "analysis", {"gaps": [{"title": "Old gap", "description": "from v1",
                                                     "evidence_paper_ids": []}]})
    [g] = gs.list_gaps(db, s.id)
    assert g.title == "Old gap" and g.source == "ai"


def test_gap_chat_is_separate_thread(db, analysed):
    u, s = analysed
    g = gs.list_gaps(db, s.id)[0]
    run(answer_question(db, s.id, u.id, "Main chat question"))
    res = run(answer_question(db, s.id, u.id, "Gap question", gap=g))
    assert "[99]" not in res["answer"]
    assert db.query(SessionMessage).filter(SessionMessage.session_id == s.id,
                                           SessionMessage.gap_id.is_(None)).count() == 2
    assert [m.content for m in gs.gap_messages(db, g.id)][0] == "Gap question"


def test_assess_user_gap(db, analysed):
    u, s = analysed
    g = gs.add_user_gap(db, s.id, u.id, "LLM triage in rural emergency departments", "Not studied")
    run(gs.assess_gap(db, g))
    a = db.get(Gap, g.id).assessment
    valid = {p.id for p in list_session_papers(db, s.id)}
    assert a["evidence"]["supporting"] and all(e["paper_id"] in valid for e in a["evidence"]["supporting"])
    assert a["novelty"]["verdict"] == "partially_addressed"
    assert len(a["novelty"]["closest"]) == 1  # invalid index dropped
    assert g.evidence_paper_ids and g.research_question == "Fake research question?"


def test_writing_guide_flow(db, analysed):
    u, s = analysed
    gs.update_gap(db, gs.list_gaps(db, s.id)[0], pinned=True)
    sections = run(ws.generate_outline(db, s.id, s.topic))
    assert [x.kind for x in sections] == ["intro", "theme", "gaps", "conclusion"]
    allowed = {n for n in range(1, 16)}
    for x in sections:
        assert all(set(p["refs"]) <= allowed for p in x.guidance["points"]), "invented refs dropped"
    assert ws.get_title(db, s.id, "x") == "Fake Review Title"

    intro = sections[0]
    with pytest.raises(ws.WritingError):
        run(ws.check_section(db, intro))  # nothing written yet
    ws.save_text(db, intro, "Large language models are increasingly used in clinics [1]. "
                 "They help clinicians decide faster [2][77]. Some studies report errors and "
                 "hallucinations that worry regulators and patients alike in many settings.\n\n"
                 "A second paragraph with more detail about adoption [3].", u.id)
    fb = run(ws.check_section(db, intro))
    assert fb["unknown_refs"] == [77] and fb["words"] > 20
    assert all(999 not in c["suggested_refs"] for c in fb["uncited_claims"])

    # regenerate keeps user text and custom sections
    custom = ws.add_section(db, s.id, "Methods of this review")
    ws.save_text(db, custom, "We searched four databases [1].", u.id)
    sections2 = run(ws.generate_outline(db, s.id, s.topic))
    assert db.get(WritingSection, intro.id).user_text.startswith("Large language models")
    assert custom.id in {x.id for x in sections2}
    ws.move_section(db, db.get(WritingSection, custom.id), -1)

    review = ws.compile_review(db, s.id, "Default")
    assert [x["heading"] for x in review["sections"]] == ["Introduction", "Methods of this review"]
    assert len(review["sections"][0]["paragraphs"]) == 2
    data = render(db, s.id, review, "APA", "docx", user_written=True)
    text = "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
    assert "Prepared with ResearchMind AI" in text and "AI-generated draft" not in text
    assert "[77]" not in text and "References" in text
    assert render(db, s.id, review, "IEEE", "pdf", user_written=True)[:4] == b"%PDF"
