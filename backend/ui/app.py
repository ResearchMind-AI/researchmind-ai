"""
ResearchMind AI — POC user interface (Streamlit).

Run from the backend folder:  streamlit run ui/app.py
Uses the same services and database as the FastAPI backend.
"""
import asyncio
import json
import os
import secrets
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

from app.config import settings  # noqa: E402
from app.core.database import SessionLocal, init_db  # noqa: E402
from app.core.security import (  # noqa: E402
    create_access_token, decode_access_token, get_password_hash, verify_password,
)
from app.models.research import SessionMessage  # noqa: E402
from app.models.session import Session, SessionMember  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import access  # noqa: E402
from app.services import gaps_service as gs  # noqa: E402
from app.services import writing_service as ws  # noqa: E402
from app.services.analysis_service import (  # noqa: E402
    generate_gaps, generate_themes, list_session_papers, reference_numbers,
)
from app.services.chat_service import build_context, iter_sync, save_exchange, stream_answer  # noqa: E402
from app.services.discovery_service import discover_papers, get_artifact, source_status  # noqa: E402
from app.services.export_service import DISCLAIMER, STYLES, draft_review, format_review, render  # noqa: E402
from app.services.upload_service import UploadError, add_uploaded_paper  # noqa: E402

st.set_page_config(page_title="ResearchMind AI", page_icon="🔬", layout="wide")


@st.cache_resource
def _init():
    init_db()
    return True


_init()
db = SessionLocal()


def run(coro):
    return asyncio.run(coro)


COOKIE = "rm_session"
COOKIE_DAYS = 7


def _write_cookie(value: str, max_age: int) -> None:
    """Set or clear the login cookie on the app's own page (Streamlit has no cookie API)."""
    components.html(f"""<script>
      const secure = window.parent.location.protocol === "https:" ? "; Secure" : "";
      window.parent.document.cookie = "{COOKIE}=" + {json.dumps(value)} +
        "; Path=/; Max-Age={max_age}; SameSite=Lax" + secure;
    </script>""", height=0)


def log_in(user: User) -> None:
    st.session_state.user_id = user.id
    st.session_state.cookie_to_set = create_access_token(
        {"sub": user.email, "scope": "ui"}, expires_delta=timedelta(days=COOKIE_DAYS))


def log_out() -> None:
    st.session_state.clear()
    st.session_state.logged_out = True  # don't auto-login from the old cookie in this tab
    st.session_state.cookie_to_clear = True


def current_user():
    # Cookie writes are deferred to the run after login/logout so the page has rendered.
    if st.session_state.pop("cookie_to_set", None) is not None and st.session_state.get("user_id"):
        u = db.get(User, st.session_state.user_id)
        _write_cookie(create_access_token({"sub": u.email, "scope": "ui"},
                                          expires_delta=timedelta(days=COOKIE_DAYS)), COOKIE_DAYS * 86400)
    if st.session_state.pop("cookie_to_clear", None):
        _write_cookie("", 0)

    uid = st.session_state.get("user_id")
    if uid:
        return db.get(User, uid)
    if st.session_state.get("logged_out"):
        return None
    token = st.context.cookies.get(COOKIE)  # survives refreshes, redeploys and wake-ups
    email = decode_access_token(token) if token else None
    u = db.query(User).filter(User.email == email).first() if email else None
    if u and u.is_active:
        st.session_state.user_id = u.id
        return u
    return None


# ── Auth ─────────────────────────────────────────────────────────────────────

def auth_screen():
    st.title("🔬 ResearchMind AI")
    st.caption("From a research topic to papers, themes, gaps and a cited literature review.")
    login_tab, signup_tab = st.tabs(["Log in", "Create account"])
    with login_tab:
        with st.form("login"):
            email = st.text_input("Email").strip().lower()
            pw = st.text_input("Password", type="password")
            if st.form_submit_button("Log in", type="primary"):
                u = db.query(User).filter(User.email == email).first()
                if u and u.is_active and verify_password(pw, u.hashed_password):
                    log_in(u)
                    st.rerun()
                st.error("Incorrect email or password.")
    with signup_tab:
        with st.form("signup"):
            name = st.text_input("Full name")
            email = st.text_input("Your email").strip().lower()
            pw = st.text_input("Password (8+ characters)", type="password")
            code = st.text_input("Invite code", type="password") if settings.INVITE_CODE else ""
            if st.form_submit_button("Create account", type="primary"):
                if settings.INVITE_CODE and not secrets.compare_digest(code.strip(), settings.INVITE_CODE):
                    st.error("That invite code is not valid. Ask the person who sent you the link.")
                elif "@" not in email or len(pw) < 8:
                    st.error("Enter a valid email and a password of at least 8 characters.")
                elif db.query(User).filter(User.email == email).first():
                    st.error("An account with that email already exists.")
                else:
                    u = User(email=email, full_name=name or None, hashed_password=get_password_hash(pw))
                    db.add(u)
                    db.commit()
                    log_in(u)
                    st.rerun()


# ── Sidebar ──────────────────────────────────────────────────────────────────

def sidebar(user: User):
    with st.sidebar:
        st.markdown(f"**{user.full_name or user.email}**")
        if st.button("Log out", use_container_width=True):
            log_out()
            st.rerun()
        st.divider()

        with st.expander("➕ New research session", expanded=not access.list_user_sessions(db, user)):
            with st.form("new_session", clear_on_submit=True):
                topic = st.text_area("Research topic", placeholder="e.g. Large language models for clinical "
                                                                     "decision support in emergency medicine")
                title = st.text_input("Short title (optional)")
                if st.form_submit_button("Create session", type="primary") and topic.strip():
                    s = Session(title=(title or topic)[:120], topic=topic.strip(), creator_id=user.id)
                    db.add(s)
                    db.commit()
                    st.session_state.session_id = s.id
                    st.session_state.autorun = True
                    st.rerun()

        sessions = access.list_user_sessions(db, user)
        if sessions:
            st.markdown("**Your sessions**")
            for s in sessions:
                role = access.role_of(db, s, user)
                tag = "" if role == "owner" else f" · _{role}_"
                active = st.session_state.get("session_id") == s.id
                short = s.title if len(s.title) <= 42 else s.title[:40].rsplit(" ", 1)[0] + "…"
                if st.button(f"{'▶ ' if active else ''}{short}", key=f"s{s.id}",
                             use_container_width=True, help=s.topic):
                    st.session_state.session_id = s.id
                    st.rerun()
                if tag:
                    st.caption(f"↳ shared with you{tag}")

        st.divider()
        with st.expander("⚙️ Paper sources & AI"):
            for src in source_status():
                icon = "🟢" if src["mode"] == "full" else "🟡"
                st.markdown(f"{icon} **{src['label']}**: {src['mode']}  \n<small>{src['detail']}</small>",
                            unsafe_allow_html=True)
            provider = "offline (fake)" if settings.OFFLINE_DEMO else (
                f"Claude ({settings.CLAUDE_MODEL})" if settings.llm_provider == "anthropic"
                else f"OpenAI ({settings.CHAT_MODEL})")
            st.markdown(f"🧠 **AI model**: {provider}")
            st.caption("Add the free API keys to the server settings (.env, or Variables on Railway) to switch 🟡 sources to full mode.")


# ── Session view ─────────────────────────────────────────────────────────────

def ids_to_refs(text: str, refs) -> str:
    """Turn '(id=12, id=40)' from the LLM into the session's reference numbers '[3][7]'."""
    import re

    def repl(m):
        nums = [refs[int(i)] for i in re.findall(r"id=(\d+)", m.group(0)) if int(i) in refs]
        return "".join(f"[{n}]" for n in nums)
    out = re.sub(r"\(\s*id=\d+(?:\s*,\s*id=\d+)*\s*\)|\bid=\d+(?:\s*,\s*id=\d+)*", repl, text)
    return re.sub(r"  +", " ", out).replace(" .", ".")


def paper_label(p, refs):
    year = p.publication_date.year if p.publication_date else "n.d."
    return f"[{refs[p.id]}] {p.title} ({year})"


def link(p, refs):
    text = paper_label(p, refs)
    return f"[{text}]({p.url})" if p.url else text


def full_analysis(s: Session, user: User, start_year=None, end_year=None):
    with st.status("Researching…", expanded=True) as status:
        stats = run(discover_papers(db, s.id, user.id, s.topic or s.title, start_year, end_year,
                                    progress=lambda m: st.write(m)))
        if stats.get("error"):
            status.update(label="No papers found", state="error")
            st.error(stats["error"])
            return
        st.write("Finding themes…")
        run(generate_themes(db, s.id, s.topic or s.title))
        st.write("Looking for research gaps…")
        run(generate_gaps(db, s.id, s.topic or s.title))
        status.update(label=f"Done: {stats['added']} new papers analysed", state="complete", expanded=False)


def papers_tab(s, user, editable, papers, refs):
    stats = get_artifact(db, s.id, "discovery")
    if stats:
        cols = st.columns(4)
        cols[0].metric("Papers in session", len(papers))
        cols[1].metric("Unique candidates", stats.get("candidates", 0))
        cols[2].metric("Research field", (stats.get("domain") or "").title())
        cols[3].metric("Search queries", len(stats.get("queries") or []))
        with st.expander("How these papers were found"):
            st.markdown("**Queries:** " + " · ".join(f"`{q}`" for q in stats.get("queries", [])))
            for name, info in (stats.get("sources") or {}).items():
                icon = "🟢" if info["mode"] == "full" else "🟡"
                err = f" — {info['errors']} failed request(s)" if info.get("errors") else ""
                st.markdown(f"{icon} {info['label']} ({info['mode']} mode): {info['found']} results{err}")

    if editable:
        with st.expander("📎 Upload your own papers (PDF or DOCX)"):
            files = st.file_uploader("Files", type=["pdf", "docx"], accept_multiple_files=True,
                                     label_visibility="collapsed")
            if files and st.button("Add to session", type="primary"):
                added, failed = [], False
                for f in files:
                    with st.spinner(f"Reading {f.name}…"):
                        try:
                            added.append(run(add_uploaded_paper(db, s.id, user.id, f.name, f.getvalue())).title)
                        except UploadError as e:
                            failed = True
                            st.error(f"{f.name}: {e}")
                for title in added:
                    st.toast(f"Added: {title}")
                if added:
                    st.toast("Click 'Find papers & analyse' or regenerate themes/gaps to include them.")
                if added and not failed:
                    st.rerun()

    if not papers:
        st.info("No papers yet. Click **Find papers & analyse** above.")
        return
    rows = []
    for p in papers:
        found = (p.extra_metadata or {}).get("found_in") or [p.source.value]
        rows.append({
            "#": refs[p.id],
            "Title": p.title,
            "Year": p.publication_date.year if p.publication_date else None,
            "Authors": ", ".join((p.authors or [])[:3]) + (" et al." if len(p.authors or []) > 3 else ""),
            "Found in": ", ".join(found).replace("_", " "),
            "Citations": p.citations_count or 0,
            "Link": p.url or (f"https://doi.org/{p.doi}" if p.doi else None),
        })
    st.dataframe(rows, hide_index=True, use_container_width=True,
                 column_config={"Link": st.column_config.LinkColumn("Link", display_text="open"),
                                "#": st.column_config.NumberColumn(width="small"),
                                "Year": st.column_config.NumberColumn(format="%d")})


def themes_tab(s, editable, papers, refs):
    if editable and papers and st.button("🔄 Regenerate themes"):
        with st.spinner("Clustering papers and naming themes…"):
            run(generate_themes(db, s.id, s.topic or s.title))
    analysis = get_artifact(db, s.id, "analysis") or {}
    if not analysis.get("themes"):
        st.info("Themes appear here after analysis.")
        return
    if analysis.get("overview"):
        st.markdown(f"> {analysis['overview']}")
    by_id = {p.id: p for p in papers}
    for t in analysis["themes"]:
        years = f" · {t['year_range'][0]}–{t['year_range'][1]}" if t.get("year_range") else ""
        with st.expander(f"**{t['label']}** · {t['size']} papers{years}", expanded=True):
            st.write(t.get("summary", ""))
            if t.get("key_findings"):
                st.markdown("**Key findings**\n" + "\n".join(f"- {ids_to_refs(f, refs)}" for f in t["key_findings"]))
            st.markdown("**Representative papers**\n" + "\n".join(
                f"- {link(by_id[i], refs)}" for i in t.get("key_paper_ids", []) if i in by_id))
            if t.get("top_authors"):
                st.caption("Frequent authors: " + ", ".join(t["top_authors"]))


def _source_line(c):
    return f"[{c['n']}] " + (f"[{c['title']}]({c['url']})" if c.get("url") else c["title"])


def render_chat(s, user, editable, papers, gap=None):
    """Main session chat, or the thread for one gap."""
    thread = SessionMessage.gap_id.is_(None) if gap is None else SessionMessage.gap_id == gap.id
    msgs = (db.query(SessionMessage).filter(SessionMessage.session_id == s.id, thread)
            .order_by(SessionMessage.id).all())
    if not msgs:
        st.caption("Ask anything about the papers in this session. Answers cite papers by their # number."
                   if gap is None else
                   "Discuss this gap: is it real, how would you scope it, what methods or data could work?")
    for m in msgs:
        with st.chat_message(m.role):
            st.markdown(m.content)
            if m.citations:
                with st.expander(f"Sources ({len(m.citations)})"):
                    for c in m.citations:
                        st.markdown(_source_line(c))
    if not editable:
        st.info("You have read-only access, so you can read the chat but not ask new questions.")
        return
    if not papers:
        return
    q = st.chat_input("Ask a question about these papers…" if gap is None else "Ask about this gap…")
    if q:
        with st.chat_message("user"):
            st.markdown(q)
        with st.chat_message("assistant"):
            ctx = run(build_context(db, s.id, q, gap=gap))
            placeholder = st.empty()
            with placeholder.container():
                raw = st.write_stream(iter_sync(stream_answer(ctx)))
            result = save_exchange(db, s.id, user.id, ctx, raw if isinstance(raw, str) else "".join(raw))
            placeholder.markdown(result["answer"])  # replace with the citation-checked version
            if result["citations"]:
                with st.expander(f"Sources ({len(result['citations'])})"):
                    for c in result["citations"]:
                        st.markdown(_source_line(c))


def chat_tab(s, user, editable, papers):
    render_chat(s, user, editable, papers)


# ── Gaps workspace ───────────────────────────────────────────────────────────

STATUS_ICON = {"open": "⚪", "exploring": "🔵", "promising": "🟢", "dropped": "⚫"}
VERDICT = {"open": ("🟢", "Looks open: no paper found that directly addresses it"),
           "partially_addressed": ("🟡", "Partly addressed by existing work"),
           "addressed": ("🔴", "Probably already addressed"),
           "unknown": ("⚪", "Could not check")}


def _gap_card_meta(g):
    conf = {"high": "🟢", "medium": "🟡", "low": "🟠"}.get(g.confidence, "")
    bits = ["Your gap" if g.source == "user" else f"{(g.gap_type or 'gap').title()} gap"]
    if g.confidence:
        bits.append(f"confidence {conf} {g.confidence}")
    if g.pinned:
        bits.append(f"status {STATUS_ICON.get(g.status, '')} {g.status}")
    if g.assessment:
        bits.append(VERDICT.get(g.assessment.get("novelty", {}).get("verdict", "unknown"))[0] + " checked")
    return " · ".join(bits)


def _open_gap(session_id, gap_id):
    st.session_state[f"gap_open_{session_id}"] = gap_id


def gap_detail(s, user, editable, papers, refs, g):
    if st.button("← All gaps"):
        st.session_state.pop(f"gap_open_{s.id}", None)
        st.rerun()
    st.markdown(f"### {g.title}")
    st.caption(_gap_card_meta(g))
    if g.description:
        st.write(g.description)
    by_id = {p.id: p for p in papers}

    c1, c2 = st.columns([1, 1])
    with c1:
        if g.research_question:
            st.markdown(f"**Research question:** _{g.research_question}_")
        ev = [link(by_id[i], refs) for i in (g.evidence_paper_ids or []) if i in by_id]
        if ev:
            st.markdown("**Evidence in this session:**\n" + "\n".join(f"- {e}" for e in ev))
    with c2:
        if editable:
            pin = st.toggle("📌 Pinned to my gaps", value=g.pinned, key=f"pin_{g.id}")
            status = st.selectbox("Status", gs.STATUSES, index=gs.STATUSES.index(g.status),
                                  key=f"status_{g.id}", format_func=lambda x: f"{STATUS_ICON[x]} {x}")
            notes = st.text_area("My notes", value=g.notes or "", key=f"notes_{g.id}", height=110)
            if (pin, status, notes) != (g.pinned, g.status, g.notes or ""):
                gs.update_gap(db, g, pinned=pin, status=status, notes=notes)
                st.toast("Saved")
        elif g.notes:
            st.markdown(f"**Notes:** {g.notes}")

    with st.container(border=True):
        st.markdown("**Is this gap real?**")
        a = g.assessment
        if editable and st.button("🔎 Check evidence and novelty" if not a else "🔄 Check again", key=f"assess_{g.id}"):
            with st.spinner("Checking the session's papers and searching for recent work (about 20–40 s)…"):
                run(gs.assess_gap(db, g))
            a = g.assessment
        if not a:
            st.caption("Checks which papers in this session support or contradict the gap, and searches "
                       "OpenAlex and Semantic Scholar for papers that may already have addressed it.")
        else:
            icon, label = VERDICT.get(a["novelty"].get("verdict", "unknown"))
            st.markdown(f"{icon} **{label}.** {a['novelty'].get('explanation', '')}")
            for c in a["novelty"].get("closest") or []:
                title = f"[{c['title']}]({c['url']})" if c.get("url") else c["title"]
                st.markdown(f"- {title} ({c.get('year') or 'n.d.'}): {c.get('why', '')}")
            evid = a.get("evidence") or {}
            if evid.get("summary"):
                st.markdown(f"**Session evidence:** {evid['summary']}")
            for label2, key in (("Supports the gap", "supporting"), ("Already addresses it", "contradicting")):
                if evid.get(key):
                    st.markdown(f"_{label2}:_\n" + "\n".join(
                        f"- [{e['n']}] {e['title']}: {e['why']}" for e in evid[key]))
            st.caption("Based on abstracts only. Verify with the full papers.")

    st.markdown("#### Discussion")
    render_chat(s, user, editable, papers, gap=g)


def gaps_tab(s, user, editable, papers, refs):
    gaps = gs.list_gaps(db, s.id)
    open_id = st.session_state.get(f"gap_open_{s.id}")
    if open_id:
        g = next((x for x in gaps if x.id == open_id), None)
        if g:
            return gap_detail(s, user, editable, papers, refs, g)
        st.session_state.pop(f"gap_open_{s.id}", None)

    mine = [g for g in gaps if g.pinned or g.source == "user"]
    suggested = [g for g in gaps if not (g.pinned or g.source == "user")]

    if editable:
        with st.expander("➕ Add your own gap"):
            with st.form(f"add_gap_{s.id}", clear_on_submit=True):
                t = st.text_input("Gap (short title)", placeholder="e.g. LLM triage support in rural emergency departments")
                d = st.text_area("What is missing, and why does it matter? (optional)")
                check = st.checkbox("Check evidence and novelty now", value=True)
                if st.form_submit_button("Add gap", type="primary"):
                    try:
                        g = gs.add_user_gap(db, s.id, user.id, t, d)
                        if check and papers:
                            with st.spinner("Checking evidence and searching recent work…"):
                                run(gs.assess_gap(db, g))
                        _open_gap(s.id, g.id)
                        st.rerun()
                    except gs.GapError as e:
                        st.error(str(e))

    st.markdown(f"#### 📌 My gaps ({len(mine)})")
    if not mine:
        st.caption("Pin suggested gaps or add your own to track them, take notes and discuss each one.")
    for g in mine:
        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"**{g.title}**")
            c1.caption(_gap_card_meta(g))
            c2.button("Open", key=f"open_{g.id}", on_click=_open_gap, args=(s.id, g.id), use_container_width=True)

    st.markdown(f"#### 💡 Suggested by AI ({len(suggested)})")
    if editable and papers and st.button("🔄 Suggest new gaps", help="Replaces unpinned suggestions; "
                                                                   "your pinned and own gaps are kept"):
        with st.spinner("Analysing gaps…"):
            run(generate_gaps(db, s.id, s.topic or s.title))
        st.rerun()
    if not suggested:
        st.caption("Suggestions appear here after analysis.")
    else:
        st.caption("Based on abstracts only — leads to verify, not conclusions.")
    by_id = {p.id: p for p in papers}
    for g in suggested:
        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"**{g.title}**")
            c1.caption(_gap_card_meta(g))
            c1.write(g.description or "")
            ev = [link(by_id[i], refs) for i in (g.evidence_paper_ids or []) if i in by_id]
            if ev:
                c1.markdown("Evidence: " + " · ".join(ev))
            if editable:
                if c2.button("📌 Pin", key=f"pinbtn_{g.id}", use_container_width=True):
                    gs.update_gap(db, g, pinned=True, status="exploring")
                    st.rerun()
            c2.button("Discuss", key=f"disc_{g.id}", on_click=_open_gap, args=(s.id, g.id), use_container_width=True)


# ── Writing guide ────────────────────────────────────────────────────────────

def _refs_md(nums, by_n):
    return " ".join(f"[{n}]" for n in nums if n in by_n)


def write_tab(s, user, editable, papers, refs):
    if not papers:
        st.info("Add papers first.")
        return
    by_n = {refs[p.id]: p for p in papers}
    sections = ws.list_sections(db, s.id)
    st.caption("You write the review. ResearchMind suggests what each section should cover, which papers "
               "support each point, and gives feedback on your draft. Cite papers by their # number, e.g. [4] or [4][9].")

    if not sections:
        if editable:
            if st.button("🧭 Create my writing guide", type="primary"):
                with st.spinner("Planning sections from your themes and gaps (about 20–40 s)…"):
                    try:
                        run(ws.generate_outline(db, s.id, s.topic or s.title))
                    except ws.WritingError as e:
                        st.error(str(e))
                st.rerun()
        else:
            st.info("The owner hasn't created a writing guide yet.")
        _example_draft(s, editable, papers)
        return

    title_default = ws.get_title(db, s.id, f"Literature review: {s.topic or s.title}")
    c1, c2, c3 = st.columns([3, 1, 1])
    if editable:
        new_title = c1.text_input("Review title", value=title_default, key=f"wt_{s.id}")
        if new_title != title_default:
            ws.set_title(db, s.id, new_title)
    else:
        c1.markdown(f"### {title_default}")
    style = c2.selectbox("Citation style", STYLES, key=f"style_{s.id}")
    if editable and c3.button("🔄 Refresh guide", help="Updates the guidance from the latest themes and pinned gaps. "
                                                       "Your writing is kept."):
        with st.spinner("Refreshing the guide…"):
            run(ws.generate_outline(db, s.id, s.topic or s.title))
        st.rerun()

    total = sum(ws.word_count(x.user_text) for x in sections)
    target = sum((x.guidance or {}).get("target_words") or 0 for x in sections)
    st.progress(min(1.0, total / target) if target else 0.0,
                text=f"{total} words written" + (f" of about {target} suggested" if target else ""))

    with st.expander("📚 Paper numbers for citing"):
        for p in papers:
            st.markdown(f"[{refs[p.id]}] {p.title} ({p.publication_date.year if p.publication_date else 'n.d.'})")

    for i, sec in enumerate(sections):
        g = sec.guidance or {}
        words = ws.word_count(sec.user_text)
        tgt = g.get("target_words")
        done = "✅ " if tgt and words >= 0.8 * tgt else ("✏️ " if words else "")
        open_id = st.session_state.get(f"open_sec_{s.id}")
        with st.expander(f"{done}{sec.heading} · {words}" + (f"/{tgt}" if tgt else "") + " words",
                         expanded=(sec.id == open_id) if open_id else (i == 0 and total == 0)):
            left, right = st.columns([2, 3])
            with left:
                if g.get("points"):
                    st.markdown("**Points to cover**\n" + "\n".join(
                        f"- {pt['text']} {_refs_md(pt.get('refs', []), by_n)}" for pt in g["points"]))
                if g.get("agreements"):
                    st.markdown("**Where studies agree**\n" + "\n".join(f"- {x}" for x in g["agreements"]))
                if g.get("disagreements"):
                    st.markdown("**Where they disagree**\n" + "\n".join(f"- {x}" for x in g["disagreements"]))
                if g.get("questions"):
                    st.markdown("**Questions to answer**\n" + "\n".join(f"- {x}" for x in g["questions"]))
                if not any(g.get(k) for k in ("points", "agreements", "disagreements", "questions")):
                    st.caption("Your own section: no guidance.")
            with right:
                if editable:
                    # A form submits the text and the button click together (no lost clicks).
                    with st.form(f"secform_{sec.id}", border=False):
                        heading = st.text_input("Heading", value=sec.heading)
                        text = st.text_area("Your text (blank line between paragraphs)", value=sec.user_text or "",
                                            height=280, placeholder="Write this section in your own words. "
                                                                    "Cite papers like [4] or [4][9].")
                        f1, f2, _ = st.columns([1, 2, 2])
                        save = f1.form_submit_button("💾 Save")
                        check = f2.form_submit_button("🧑‍🏫 Save & check")
                    if save or check:
                        ws.save_text(db, sec, text, user.id, heading)
                        st.session_state[f"open_sec_{s.id}"] = sec.id
                        if check:
                            with st.spinner("Reviewing your draft…"):
                                try:
                                    run(ws.check_section(db, sec))
                                except ws.WritingError as e:
                                    st.warning(str(e))
                        else:
                            st.toast("Saved")
                    st.caption("Save before switching views; unsaved text is lost.")
                    b3, b4, b5, _ = st.columns([1, 1, 1, 4])
                    if b3.button("↑", key=f"up_{sec.id}", help="Move up"):
                        ws.move_section(db, sec, -1)
                        st.rerun()
                    if b4.button("↓", key=f"dn_{sec.id}", help="Move down"):
                        ws.move_section(db, sec, 1)
                        st.rerun()
                    if b5.button("🗑", key=f"del_{sec.id}", help="Delete section"):
                        ws.delete_section(db, sec)
                        st.rerun()
                else:
                    st.markdown(sec.user_text or "_Not written yet._")
                fb = sec.feedback
                if fb:
                    with st.container(border=True):
                        st.markdown(f"**Feedback** · {fb.get('words', 0)} words"
                                    + (f" (suggested ~{fb['target_words']})" if fb.get("target_words") else ""))
                        if fb.get("summary"):
                            st.write(fb["summary"])
                        if fb.get("unknown_refs"):
                            st.warning("These citation numbers don't match any paper in the session: "
                                       + ", ".join(f"[{n}]" for n in fb["unknown_refs"]))
                        if fb.get("uncited_claims"):
                            st.markdown("**Claims that need a citation**\n" + "\n".join(
                                f"- “{c['sentence']}” → consider {_refs_md(c['suggested_refs'], by_n) or 'a source'}"
                                f" ({c['why']})" for c in fb["uncited_claims"]))
                        if fb.get("citation_issues"):
                            st.markdown("**Citations to double-check**\n" + "\n".join(
                                f"- [{c['ref']}] “{c['sentence']}”: {c['issue']}" for c in fb["citation_issues"]))
                        if fb.get("missing_points"):
                            st.markdown("**Not covered yet**\n" + "\n".join(f"- {m}" for m in fb["missing_points"]))
                        if fb.get("strengths"):
                            st.markdown("**Working well**\n" + "\n".join(f"- {m}" for m in fb["strengths"]))

    if editable:
        with st.form(f"addsec_{s.id}", clear_on_submit=True):
            c1, c2 = st.columns([4, 1])
            h = c1.text_input("Add a section", placeholder="e.g. Methods of this review", label_visibility="collapsed")
            if c2.form_submit_button("➕ Add section") and h.strip():
                ws.add_section(db, s.id, h)
                st.rerun()

    review = ws.compile_review(db, s.id, title_default)
    st.markdown("#### Export your review")
    if not review["sections"]:
        st.caption("Write at least one section to export it with formatted references.")
    else:
        d1, d2 = st.columns(2)
        d1.download_button("⬇️ Download DOCX", render(db, s.id, review, style, "docx", user_written=True),
                           file_name=f"literature-review-{s.id}.docx", use_container_width=True,
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        d2.download_button("⬇️ Download PDF", render(db, s.id, review, style, "pdf", user_written=True),
                           file_name=f"literature-review-{s.id}.pdf", mime="application/pdf",
                           use_container_width=True)
        with st.expander("Preview with formatted citations"):
            formatted = format_review(review, papers, style)
            st.markdown(f"## {formatted['title']}")
            for sec in formatted["sections"]:
                st.markdown(f"### {sec['heading']}")
                for para in sec["paragraphs"]:
                    st.write(para)
            st.markdown("### References")
            for ref in formatted["references"]:
                st.markdown(f"<div style='padding-left:1.5em;text-indent:-1.5em;margin-bottom:.4em'>{ref}</div>",
                            unsafe_allow_html=True)
    _example_draft(s, editable, papers)


def _example_draft(s, editable, papers):
    with st.expander("Example draft (AI-written, for reference only)"):
        st.caption("A fully AI-written draft, to see how a review could be structured. "
                   "It is not your writing and shouldn't be submitted as such.")
        review = get_artifact(db, s.id, "lit_review")
        if editable and st.button("Generate example draft" if not review else "Regenerate example",
                                  key=f"ex_{s.id}"):
            with st.spinner("Writing an example (about 30–60 seconds)…"):
                review = run(draft_review(db, s.id, s.topic or s.title))
        if review:
            formatted = format_review(review, papers, "APA")
            st.markdown(f"**{formatted['title']}**")
            for sec in formatted["sections"]:
                st.markdown(f"**{sec['heading']}**")
                for para in sec["paragraphs"]:
                    st.write(para)


def share_tab(s, user):
    owner = db.get(User, s.creator_id)
    members = db.query(SessionMember).filter(SessionMember.session_id == s.id).all()
    st.markdown(f"**Owner:** {owner.full_name or owner.email} ({owner.email})")
    if not access.can_manage(db, s, user):
        st.info("Only the owner can change sharing.")
    else:
        with st.form("share", clear_on_submit=True):
            c1, c2 = st.columns([3, 1])
            email = c1.text_input("Share with (their account email)")
            role = c2.selectbox("Access", ["viewer", "contributor"],
                                help="Viewers can read everything and download exports. "
                                     "Contributors can also add papers, re-run analysis and chat.")
            if st.form_submit_button("Share", type="primary") and email:
                try:
                    access.share_session(db, s, user, email, role)
                    st.success(f"Shared with {email} as {role}.")
                except access.AccessError as e:
                    st.error(str(e))
        st.caption("The other person needs an account first: send them this app's link and ask them to sign up.")
    if members:
        st.markdown("**People with access**")
        for m in members:
            u = db.get(User, m.user_id)
            c1, c2 = st.columns([4, 1])
            c1.write(f"{u.full_name or u.email} ({u.email}) — {m.role.value}")
            if access.can_manage(db, s, user) and c2.button("Remove", key=f"rm{m.id}"):
                access.unshare_session(db, s, user, m.user_id)
                st.rerun()


def session_view(user: User):
    sid = st.session_state.get("session_id")
    qp = st.query_params.get("s", "")
    if sid is None and qp.isdigit():  # remember the open session across page refreshes
        sid = st.session_state.session_id = int(qp)
    if sid and qp != str(sid):
        st.query_params["s"] = str(sid)
    s = db.get(Session, sid) if sid else None
    if not s or not access.can_view(db, s, user):
        st.title("🔬 ResearchMind AI")
        st.markdown("Create a research session in the sidebar to get started. ResearchMind will:\n"
                    "1. find relevant papers in OpenAlex, Semantic Scholar, PubMed and arXiv\n"
                    "2. group them into themes\n3. point out research gaps\n"
                    "4. answer your questions with citations\n5. guide you while you write your literature review (DOCX/PDF export)")
        return
    editable = access.can_edit(db, s, user)
    role = access.role_of(db, s, user)

    st.title(s.title)
    if s.topic and s.topic != s.title:
        st.caption(s.topic)
    if not editable:
        st.info(f"You have **{role}** access to this session (read-only).")

    if editable:
        c1, c2 = st.columns([1, 3])
        go = c1.button("🔎 Find papers & analyse", type="primary", use_container_width=True)
        with c2.expander("Options"):
            y1, y2 = st.columns(2)
            start = y1.number_input("From year", 1900, 2100, value=None, step=1)
            end = y2.number_input("To year", 1900, 2100, value=None, step=1)
        if go or st.session_state.pop("autorun", False):
            full_analysis(s, user, int(start) if start else None, int(end) if end else None)

    papers = list_session_papers(db, s.id)
    refs = reference_numbers(papers)
    views = ["📚 Papers", "🧭 Themes", "🔍 Gaps", "💬 Chat", "✍️ Write", "👥 Share"]
    view = st.radio("View", views, horizontal=True, key=f"view_{s.id}", label_visibility="collapsed")
    st.divider()
    if view == views[0]:
        papers_tab(s, user, editable, papers, refs)
    elif view == views[1]:
        themes_tab(s, editable, papers, refs)
    elif view == views[2]:
        gaps_tab(s, user, editable, papers, refs)
    elif view == views[3]:
        chat_tab(s, user, editable, papers)
    elif view == views[4]:
        write_tab(s, user, editable, papers, refs)
    else:
        share_tab(s, user)


# ── Main ─────────────────────────────────────────────────────────────────────

if settings.OFFLINE_DEMO:
    st.warning("OFFLINE TEST MODE: all papers, answers and analysis are fake. Do not use for research.")
try:
    user = current_user()
    if not user:
        auth_screen()
    else:
        sidebar(user)
        session_view(user)
finally:
    db.close()
