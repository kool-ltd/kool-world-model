"""
╔══════════════════════════════════════════════════════╗
║           AI MANAGER — app.py                        ║
║  Stack: Streamlit + GitHub backend + Poe API         ║
╚══════════════════════════════════════════════════════╝
"""

import streamlit as st
import requests
import base64
import json
import asyncio
import datetime
import re
import threading
from typing import Optional

# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="AI Manager",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════════════════════════
# CUSTOM CSS — clean minimalist dark theme
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap');

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
}

/* Dark background */
.stApp {
    background-color: #0e0e10;
    color: #e8e6e3;
}

/* Chat messages */
[data-testid="stChatMessage"] {
    background: #1a1a1f !important;
    border: 1px solid #2a2a35 !important;
    border-radius: 8px !important;
    margin-bottom: 8px !important;
}

/* Input box */
[data-testid="stChatInput"] textarea {
    background: #1a1a1f !important;
    border: 1px solid #3a3a50 !important;
    color: #e8e6e3 !important;
    font-family: 'IBM Plex Sans', sans-serif !important;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: #12121a !important;
    border-right: 1px solid #2a2a35 !important;
}

/* Metrics */
[data-testid="metric-container"] {
    background: #1a1a1f;
    border: 1px solid #2a2a35;
    border-radius: 8px;
    padding: 12px;
}

/* Buttons */
.stButton > button {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.8rem !important;
    border-radius: 4px !important;
}

/* Divider */
hr { border-color: #2a2a35 !important; }

/* Monospace tag */
code {
    font-family: 'IBM Plex Mono', monospace !important;
    background: #1f1f2e !important;
    color: #7c9fff !important;
    padding: 2px 6px !important;
    border-radius: 3px !important;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# SECRETS — set in Streamlit Cloud > App Settings > Secrets
# ══════════════════════════════════════════════════════════════════════════════
try:
    GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
    GITHUB_REPO  = st.secrets["GITHUB_REPO"]   # e.g. "yourname/ai-manager-data"
    POE_API_KEY  = st.secrets["POE_API_KEY"]
except KeyError as missing:
    st.error(f"⚠️ Missing secret: `{missing}`. See the README for setup instructions.")
    st.stop()

MAIN_BOT    = st.secrets.get("MAIN_BOT",  "gemini-3.1-pro")   # main conversation model
FLASH_BOT   = st.secrets.get("FLASH_BOT", "gemini-3-flash")   # fast model for wiki & summaries
MAX_HISTORY = 20   # messages before auto-offload


# ══════════════════════════════════════════════════════════════════════════════
# GITHUB HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _gh_headers() -> dict:
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def gh_get_file(path: str) -> tuple[Optional[str], Optional[str]]:
    """Read a file from GitHub. Returns (content, sha) or (None, None)."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    try:
        r = requests.get(url, headers=_gh_headers(), timeout=15)
        if r.status_code == 200:
            data = r.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            return content, data["sha"]
    except Exception:
        pass
    return None, None


def gh_put_file(path: str, content: str, sha: Optional[str] = None,
                message: str = "AI Manager update") -> bool:
    """Create or update a file on GitHub. Returns True on success."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
    }
    if sha:
        payload["sha"] = sha
    try:
        r = requests.put(url, headers=_gh_headers(), json=payload, timeout=15)
        return r.status_code in [200, 201]
    except Exception:
        return False


def gh_list_dir(path: str) -> list[tuple[str, str]]:
    """List files in a GitHub directory. Returns [(name, full_path), ...]."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    try:
        r = requests.get(url, headers=_gh_headers(), timeout=15)
        if r.status_code == 200:
            return [(f["name"], f["path"]) for f in r.json() if f["type"] == "file"]
    except Exception:
        pass
    return []


# ══════════════════════════════════════════════════════════════════════════════
# WIKI — living knowledge base
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=90, show_spinner=False)
def load_wiki() -> str:
    """
    Fetch all wiki/*.md files from GitHub and merge into one context block.
    Cached for 90 seconds to avoid hammering the GitHub API on every message.
    """
    files = gh_list_dir("wiki")
    if not files:
        return ""
    parts = []
    for name, path in sorted(files):
        if not name.endswith(".md"):
            continue
        content, _ = gh_get_file(path)
        if content:
            title = name.replace(".md", "").replace("_", " ").title()
            parts.append(f"### {title}\n\n{content.strip()}")
    return "\n\n---\n\n".join(parts)


def refresh_wiki_cache():
    """Bust the wiki cache so the next load_wiki() call fetches fresh data."""
    load_wiki.clear()


# ══════════════════════════════════════════════════════════════════════════════
# CHAT HISTORY — per-user JSON stored on GitHub
# ══════════════════════════════════════════════════════════════════════════════

def load_chat_history(username: str) -> tuple[list, Optional[str]]:
    content, sha = gh_get_file(f"chat_history_{username}.json")
    if content:
        try:
            return json.loads(content), sha
        except json.JSONDecodeError:
            return [], None
    return [], None


def save_chat_history(username: str, messages: list, sha: Optional[str]) -> Optional[str]:
    """Persist messages to GitHub and return the new file SHA."""
    path = f"chat_history_{username}.json"
    ok = gh_put_file(
        path,
        json.dumps(messages, ensure_ascii=False, indent=2),
        sha,
        f"Chat update — {username} — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    if ok:
        _, new_sha = gh_get_file(path)
        return new_sha
    return sha


def load_last_summary(username: str) -> str:
    """Return the most recent session summary for this user."""
    files = gh_list_dir("summaries")
    user_files = sorted(
        [(n, p) for n, p in files if username in n],
        reverse=True   # most recent first (filenames start with timestamp)
    )
    if user_files:
        content, _ = gh_get_file(user_files[0][1])
        return content or ""
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# POE API — async wrapped to run safely in Streamlit
# ══════════════════════════════════════════════════════════════════════════════

def call_poe(bot_name: str, messages: list[dict]) -> str:
    """
    Call a Poe bot synchronously.
    Runs the async Poe client in a fresh background thread to avoid
    conflicting with Streamlit's own event loop.
    """
    import fastapi_poe as fp

    result: list[str] = []
    error_info: list[str] = []

    async def _run():
        protocol_messages = []
        for m in messages:
            # Poe uses "bot" where OpenAI uses "assistant"
            role = "bot" if m["role"] == "assistant" else m["role"]
            protocol_messages.append(fp.ProtocolMessage(role=role, content=m["content"]))
        full = ""
        async for partial in fp.get_bot_response(
            messages=protocol_messages,
            bot_name=bot_name,
            api_key=POE_API_KEY,
        ):
            if hasattr(partial, "text"):
                full += partial.text
        result.append(full)

    def run_in_thread():
        try:
            asyncio.run(_run())
        except Exception as e:
            error_info.append(str(e))

    t = threading.Thread(target=run_in_thread, daemon=True)
    t.start()
    t.join(timeout=120)

    if error_info:
        return f"⚠️ Poe API error: {error_info[0][:300]}"
    return result[0] if result else "⚠️ No response received. Please try again."


# ══════════════════════════════════════════════════════════════════════════════
# PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

def build_system_prompt(wiki: str, last_summary: str, username: str) -> str:
    today = datetime.date.today().strftime("%A, %B %d, %Y")

    wiki_block = (
        wiki if wiki
        else "No entries yet. The knowledge base will grow as you have more conversations."
    )
    summary_block = (
        last_summary if last_summary
        else "No previous session summaries yet."
    )

    return f"""You are an AI Manager — a strategic, knowledgeable, and proactive assistant built to help this team run and grow their company.

You have a growing company knowledge base (LLM Wiki) below. Reference it naturally when relevant. Speak like a senior advisor who knows this company deeply — not a generic assistant.

You have web search capabilities. Use them when current information, recent news, or market data is needed.

When the conversation reveals new company information (decisions, strategies, product details, team changes, etc.), acknowledge it — it will be added to the wiki automatically.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMPANY KNOWLEDGE BASE (LLM Wiki)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{wiki_block}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LAST SESSION SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{summary_block}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Current user: {username}
Today: {today}

Be direct, concise, and strategic."""


def build_wiki_update_prompt(wiki: str, transcript: str, username: str) -> str:
    today = datetime.date.today().isoformat()
    return f"""You are a knowledge manager for a growing company. Your job is to keep the company's LLM Wiki up to date — a living, growing knowledge base inspired by how an LLM builds a world model.

Analyze the conversation transcript below. Extract any new facts, decisions, strategies, products, team information, processes, goals, clients, or company context worth preserving.

CURRENT WIKI:
{wiki if wiki else "Empty — no entries yet. Create wiki files from scratch if there is useful information."}

CONVERSATION (user: {username}, date: {today}):
{transcript}

Respond ONLY in raw valid JSON. No markdown code fences, no explanation, nothing before or after the JSON:
{{
  "updates": [
    {{
      "filename": "wiki/topic_name.md",
      "action": "create_or_update",
      "content": "# Topic Title\\n\\nFull markdown content. Use headers and bullet points for clarity."
    }}
  ],
  "summary": "2-3 sentences summarising the key points of this conversation."
}}

Filename rules:
- Lowercase snake_case only: wiki/company_overview.md, wiki/products.md, wiki/team.md, wiki/strategy.md, wiki/clients.md, wiki/processes.md, wiki/goals.md
- If UPDATING an existing file, rewrite the FULL file content (not just the new part)
- Group related information into the same file; avoid fragmentation
- Always write the summary even if there are no wiki updates
- If nothing new: {{"updates": [], "summary": "..."}}"""


# ══════════════════════════════════════════════════════════════════════════════
# WIKI UPDATER — called at end of session or when history is full
# ══════════════════════════════════════════════════════════════════════════════

def run_wiki_update(username: str, messages: list) -> list[str]:
    """
    Ask the Flash model to:
      1. Identify new company information from the conversation
      2. Create or update wiki .md files on GitHub
      3. Write a session summary and save it

    Returns a list of human-readable status lines.
    """
    wiki = load_wiki()
    transcript = "\n".join(
        f"{'USER' if m['role'] == 'user' else 'AI MANAGER'} ({username if m['role'] == 'user' else 'bot'}): {m['content']}"
        for m in messages
    )
    prompt = build_wiki_update_prompt(wiki, transcript, username)

    status = []
    try:
        raw = call_poe(FLASH_BOT, [{"role": "user", "content": prompt}])

        # Strip markdown fences if the model wraps response anyway
        clean = re.sub(r"```json\s*|```\s*", "", raw).strip()

        # Find the outermost JSON object
        start = clean.find("{")
        end   = clean.rfind("}") + 1
        if start >= 0 and end > start:
            clean = clean[start:end]

        data = json.loads(clean)

        # ── Update wiki files ──────────────────────────────────────────────
        for update in data.get("updates", []):
            fname   = update.get("filename", "").strip()
            content = update.get("content", "").strip()
            if not fname or not content:
                continue
            _, sha = gh_get_file(fname)
            ok = gh_put_file(
                fname, content, sha,
                f"Wiki update — {username} — {datetime.date.today()}"
            )
            action = "✅ Updated" if ok else "❌ Failed"
            status.append(f"{action} `{fname}`")

        # ── Save session summary ───────────────────────────────────────────
        summary_text = data.get("summary", "").strip()
        if summary_text:
            ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
            summary_path = f"summaries/{ts}_{username}.md"
            summary_md = (
                f"# Session Summary\n"
                f"**User:** {username}  \n"
                f"**Date:** {ts.replace('_', ' ')}\n\n"
                f"{summary_text}\n"
            )
            ok = gh_put_file(summary_path, summary_md, None,
                             f"Session summary — {username} — {ts}")
            status.append(f"{'✅' if ok else '❌'} Summary → `{summary_path}`")

        if not status:
            status.append("ℹ️ No new information to add to wiki this session.")

        refresh_wiki_cache()
        return status

    except json.JSONDecodeError as e:
        return [f"❌ JSON parse error: {str(e)[:200]}", f"Raw response: {raw[:300]}"]
    except Exception as e:
        return [f"❌ Wiki update error: {str(e)[:300]}"]


# ══════════════════════════════════════════════════════════════════════════════
# STREAMLIT UI
# ══════════════════════════════════════════════════════════════════════════════

def render_sidebar() -> Optional[str]:
    """Render sidebar, return username or None if not set."""
    with st.sidebar:
        st.markdown("### 🧠 AI Manager")
        st.caption("Powered by Gemini via Poe API")
        st.divider()

        username = st.text_input(
            "Your name",
            placeholder="e.g. alice",
            help="Each team member uses their own name. Your chat history is stored separately.",
        ).strip().lower().replace(" ", "_")

        if not username:
            st.info("👆 Enter your name to begin.")
            return None

        st.success(f"👤 {username}")
        st.divider()

        # ── Wiki status ────────────────────────────────────────────────────
        st.markdown("**📚 Knowledge Base**")
        wiki_files = gh_list_dir("wiki")
        if wiki_files:
            for name, _ in wiki_files:
                clean_name = name.replace(".md", "").replace("_", " ").title()
                st.caption(f"  📄 {clean_name}")
        else:
            st.caption("  *(empty — grows from conversations)*")

        st.divider()

        # ── Session controls ───────────────────────────────────────────────
        st.markdown("**Session**")

        msgs = st.session_state.get("messages", [])
        msg_count = len(msgs)
        st.caption(f"Messages: {msg_count} / {MAX_HISTORY}")
        st.progress(min(msg_count / MAX_HISTORY, 1.0))

        if st.button("💾 End Session & Update Wiki", type="primary",
                     use_container_width=True,
                     help="Analyses the conversation, updates the wiki, saves a summary."):
            if msgs:
                with st.spinner("Analysing conversation…"):
                    results = run_wiki_update(username, msgs)
                for r in results:
                    st.write(r)
                st.session_state["messages"] = []
                st.session_state["history_sha"] = None
                st.success("Done! Wiki updated.")
                st.rerun()
            else:
                st.info("No messages in this session.")

        if st.button("🗑️ Clear chat (no save)", use_container_width=True,
                     help="Clears the chat without updating the wiki."):
            st.session_state["messages"] = []
            st.session_state["history_sha"] = None
            st.rerun()

        st.divider()
        st.caption("Data stored on GitHub.  \nWiki updates via Gemini Flash.")

    return username


def main():
    username = render_sidebar()
    if not username:
        # Landing state — no user entered yet
        st.markdown("## 🧠 AI Manager")
        st.markdown("Enter your name in the sidebar to begin.")
        st.stop()

    # ── Load history for this user (once per session / user switch) ─────────
    if ("messages" not in st.session_state or
            st.session_state.get("current_user") != username):
        with st.spinner("Loading your chat history…"):
            history, sha = load_chat_history(username)
        st.session_state["messages"]    = history
        st.session_state["history_sha"] = sha
        st.session_state["current_user"] = username

    # ── Header ──────────────────────────────────────────────────────────────
    col_title, col_meta1, col_meta2 = st.columns([3, 1, 1])
    with col_title:
        st.markdown("## 🧠 AI Manager")
    with col_meta1:
        wiki_count = len(gh_list_dir("wiki"))
        st.metric("Wiki files", wiki_count, help="Pages in the company knowledge base")
    with col_meta2:
        session_count = len(st.session_state["messages"])
        st.metric("Session messages", f"{session_count}/{MAX_HISTORY}")

    st.divider()

    # ── Chat history display ─────────────────────────────────────────────────
    for msg in st.session_state["messages"]:
        avatar = "👤" if msg["role"] == "user" else "🧠"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

    # ── Chat input ───────────────────────────────────────────────────────────
    if user_input := st.chat_input("Ask the AI Manager anything…"):

        # 1. Show user message immediately
        st.session_state["messages"].append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_input)

        # 2. Build full prompt context
        wiki         = load_wiki()
        last_summary = load_last_summary(username)
        system_msg   = build_system_prompt(wiki, last_summary, username)

        # Inject system context as a user→bot pair at the start of the thread.
        # (Poe's API does support a "system" role, but injecting as a
        # conversation opener is more universally compatible across bots.)
        poe_messages = [
            {"role": "user",      "content": system_msg},
            {"role": "assistant", "content": (
                "Understood. I'm your AI Manager — familiar with the company, "
                "ready to help strategically. What do you need?"
            )},
        ] + st.session_state["messages"]

        # 3. Call main model and display response
        with st.chat_message("assistant", avatar="🧠"):
            with st.spinner("Thinking…"):
                response = call_poe(MAIN_BOT, poe_messages)
            st.markdown(response)

        # 4. Append response to session state
        st.session_state["messages"].append({"role": "assistant", "content": response})

        # 5. Auto-offload when history is full
        if len(st.session_state["messages"]) >= MAX_HISTORY:
            with st.spinner("📚 History full — archiving and updating wiki…"):
                results = run_wiki_update(username, st.session_state["messages"])
            # Keep the most recent 4 messages for conversational continuity
            st.session_state["messages"] = st.session_state["messages"][-4:]
            for r in results:
                st.toast(r, icon="📚")

        # 6. Persist to GitHub
        new_sha = save_chat_history(
            username,
            st.session_state["messages"],
            st.session_state.get("history_sha"),
        )
        st.session_state["history_sha"] = new_sha


if __name__ == "__main__":
    main()
