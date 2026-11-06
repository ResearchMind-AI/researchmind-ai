"""
ResearchMind AI — POC user interface (Streamlit).

Run from the backend folder:  streamlit run ui/app.py
Uses the same services and database as the FastAPI backend.
"""
import asyncio
import os
import secrets
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st  # noqa: E402

from app.config import settings  # noqa: E402
from app.core.database import SessionLocal, init_db  # noqa: E402
from app.core.security import get_password_hash, verify_password  # noqa: E402
from app.models.research import SessionMessage  # noqa: E402
from app.models.session import Session, SessionMember  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import access  # noqa: E402
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


def current_user():
    uid = st.session_state.get("user_id")
    return db.get(User, uid) if uid else None


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
                    st.session_state.user_id = u.id
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
                    st.session_state.user_id = u.id
                    st.rerun()


# ── Sidebar ──────────────────────────────────────────────────────────────────

def sidebar(user: User):
    with st.sidebar:
        st.markdown(f"**{user.full_name or user.email}**")
        if st.button("Log out", use_container_width=True):
            st.session_state.clear()
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
            st.caption("Add free API keys in the server's .env to switch 🟡 sources to full mode.")


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


def gaps_tab(s, editable, papers, refs):
    if editable and papers and st.button("🔄 Find gaps again"):
        with st.spinner("Analysing gaps…"):
            run(generate_gaps(db, s.id, s.topic or s.title))
    analysis = get_artifact(db, s.id, "analysis") or {}
    gaps = analysis.get("gaps") or []
    if not gaps:
        st.info("Research gaps appear here after analysis.")
        return
    st.caption("Based on abstracts only — treat these as leads to verify, not conclusions.")
    by_id = {p.id: p for p in papers}
    for g in gaps:
        conf = {"high": "🟢", "medium": "🟡", "low": "🟠"}.get(g.get("confidence"), "⚪")
        with st.container(border=True):
            st.markdown(f"#### {g['title']}")
            st.caption(f"{g.get('gap_type', 'gap').title()} gap · confidence {conf} {g.get('confidence', 'n/a')}")
            st.write(g.get("description", ""))
            if g.get("research_question"):
                st.markdown(f"**Possible research question:** _{g['research_question']}_")
            ev = [link(by_id[i], refs) for i in g.get("evidence_paper_ids", []) if i in by_id]
            if ev:
                st.markdown("**Evidence:**\n" + "\n".join(f"- {e}" for e in ev))


def chat_tab(s, user, editable, papers):
    msgs = db.query(SessionMessage).filter(SessionMessage.session_id == s.id).order_by(SessionMessage.id).all()
    if not msgs:
        st.caption("Ask anything about the papers in this session. Answers cite papers by their # number.")
    for m in msgs:
        with st.chat_message(m.role):
            st.markdown(m.content)
            if m.citations:
                with st.expander(f"Sources ({len(m.citations)})"):
                    for c in m.citations:
                        st.markdown(f"[{c['n']}] " + (f"[{c['title']}]({c['url']})" if c.get("url") else c["title"]))
    if not editable:
        st.info("You have read-only access, so you can read the chat but not ask new questions.")
        return
    if not papers:
        return
    q = st.chat_input("Ask a question about these papers…")
    if q:
        with st.chat_message("user"):
            st.markdown(q)
        with st.chat_message("assistant"):
            ctx = run(build_context(db, s.id, q))
            placeholder = st.empty()
            with placeholder.container():
                raw = st.write_stream(iter_sync(stream_answer(ctx)))
            result = save_exchange(db, s.id, user.id, ctx, raw if isinstance(raw, str) else "".join(raw))
            placeholder.markdown(result["answer"])  # replace with the citation-checked version
            if result["citations"]:
                with st.expander(f"Sources ({len(result['citations'])})"):
                    for c in result["citations"]:
                        st.markdown(f"[{c['n']}] " + (f"[{c['title']}]({c['url']})" if c.get("url") else c["title"]))


def export_tab(s, editable, papers):
    if not papers:
        st.info("Add papers first.")
        return
    review = get_artifact(db, s.id, "lit_review")
    c1, c2 = st.columns([1, 2])
    style = c1.selectbox("Citation style", STYLES)
    if editable:
        label = "🔄 Write a new draft" if review else "✍️ Write literature review"
        if c2.button(label, type="primary"):
            with st.spinner("Writing the literature review (about 30–60 seconds)…"):
                review = run(draft_review(db, s.id, s.topic or s.title))
    if not review:
        st.info("No draft yet." + (" Click **Write literature review**." if editable else ""))
        return
    st.caption(f"Draft generated {review.get('generated', '')}. Re-run themes/gaps first if you added papers.")
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ Download DOCX", render(db, s.id, review, style, "docx"),
                       file_name=f"literature-review-{s.id}.docx", use_container_width=True,
                       mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    d2.download_button("⬇️ Download PDF", render(db, s.id, review, style, "pdf"),
                       file_name=f"literature-review-{s.id}.pdf", mime="application/pdf",
                       use_container_width=True)
    formatted = format_review(review, papers, style)
    with st.container(border=True):
        st.markdown(f"## {formatted['title']}")
        st.caption(DISCLAIMER)
        for sec in formatted["sections"]:
            st.markdown(f"### {sec['heading']}")
            for para in sec["paragraphs"]:
                st.write(para)
        st.markdown("### References")
        for ref in formatted["references"]:
            st.markdown(f"<div style='padding-left:1.5em;text-indent:-1.5em;margin-bottom:.4em'>{ref}</div>",
                        unsafe_allow_html=True)


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
    s = db.get(Session, sid) if sid else None
    if not s or not access.can_view(db, s, user):
        st.title("🔬 ResearchMind AI")
        st.markdown("Create a research session in the sidebar to get started. ResearchMind will:\n"
                    "1. find relevant papers in OpenAlex, Semantic Scholar, PubMed and arXiv\n"
                    "2. group them into themes\n3. point out research gaps\n"
                    "4. answer your questions with citations\n5. draft a literature review (DOCX/PDF)")
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
    views = ["📚 Papers", "🧭 Themes", "🔍 Gaps", "💬 Chat", "📄 Literature review", "👥 Share"]
    view = st.radio("View", views, horizontal=True, key=f"view_{s.id}", label_visibility="collapsed")
    st.divider()
    if view == views[0]:
        papers_tab(s, user, editable, papers, refs)
    elif view == views[1]:
        themes_tab(s, editable, papers, refs)
    elif view == views[2]:
        gaps_tab(s, editable, papers, refs)
    elif view == views[3]:
        chat_tab(s, user, editable, papers)
    elif view == views[4]:
        export_tab(s, editable, papers)
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
