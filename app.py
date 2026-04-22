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
# CUSTOM CSS
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap');

html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }

.stApp { background-color: #0e0e10; color: #e8e6e3; }

[data-testid="stChatMessage"] {
    background: #1a1a1f !important;
    border: 1px solid #2a2a35 !important;
    border-radius: 8px !important;
    margin-bottom: 8px !important;
}
[data-testid="stChatInput"] textarea {
    background: #1a1a1f !important;
    border: 1px solid #3a3a50 !important;
    color: #e8e6e3 !important;
}
[data-testid="stSidebar"] {
    background: #12121a !important;
    border-right: 1px solid #2a2a35 !important;
}
[data-testid="metric-container"] {
    background: #1a1a1f;
    border: 1px solid #2a2a35;
    border-radius: 8px;
    padding: 12px;
}
.stButton > button {
    font-family: 'IBM Plex Mono', monospace !important;
    border-radius: 4px !important;
}
hr { border-color: #2a2a35 !important; }
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
# SECRETS
# ══════════════════════════════════════════════════════════════════════════════
try:
    GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
    GITHUB_REPO  = st.secrets["GITHUB_REPO"]
    POE_API_KEY  = st.secrets["POE_API_KEY"]
    PASSWORD     = st.secrets["PASSWORD"] # ADD THIS TO YOUR STREAMLIT SECRETS
except KeyError as missing:
    st.error(f"⚠️ Missing secret: `{missing}`. Check Streamlit Cloud → App Settings → Secrets.")
    st.stop()

MAIN_BOT    = st.secrets.get("MAIN_BOT",  "gemini-3.1-pro")
FLASH_BOT   = st.secrets.get("FLASH_BOT", "gemini-3-flash")
MAX_HISTORY = 20


# ══════════════════════════════════════════════════════════════════════════════
# ACCESS CONTROL (Password Gate)
# ══════════════════════════════════════════════════════════════════════════════

def check_password():
    """Returns True if the user had the correct password."""
    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password"] == st.secrets["PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.markdown("### 🧠 AI Manager Login")
        st.text_input(
            "Enter password to access the workspace", 
            type="password", 
            on_change=password_entered, 
            key="password"
        )
        return False
    elif not st.session_state["password_correct"]:
        st.text_input(
            "Password", type="password", on_change=password_entered, key="password"
        )
        st.error("😕 Password incorrect")
        return False
    return True


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
                message: str = "AI Manager update") -> tuple[bool, str]:
    """
    Create or update a file on GitHub.
    Returns (success: bool, error_detail: str).
    sha is required when UPDATING an existing file; omit when CREATING.
    """
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
    }
    if sha:
        payload["sha"] = sha
    try:
        r = requests.put(url, headers=_gh_headers(), json=payload, timeout=15)
        if r.status_code in [200, 201]:
            return True, ""
        err = r.json().get("message", r.text)[:400]
        return False, f"GitHub {r.status_code}: {err}"
    except Exception as e:
        return False, str(e)[:300]


def gh_list_dir(path: str) -> list[tuple[str, str]]:
    """List files in a GitHub directory. Returns [(name, full_path)]."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    try:
        r = requests.get(url, headers=_gh_headers(), timeout=15)
        if r.status_code == 200:
            return [(f["name"], f["path"]) for f in r.json() if f["type"] == "file"]
    except Exception:
        pass
    return []


# ══════════════════════════════════════════════════════════════════════════════
# WIKI
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=60, show_spinner=False)
def load_wiki() -> str:
    """Load all wiki/*.md files from GitHub into one context string. Cached 60s."""
    files = gh_list_dir("wiki")
    if not files:
        return ""
    parts = []
    for name, path in sorted(files):
        if not name.endswith(".md"):
            continue
        content, _ = gh_get_file(path)
        if content and content.strip():
            title = name.replace(".md", "").replace("_", " ").title()
            parts.append(f"### {title}\n\n{content.strip()}")
    return "\n\n---\n\n".join(parts)


def refresh_wiki_cache():
    load_wiki.clear()


# ══════════════════════════════════════════════════════════════════════════════
# CHAT HISTORY
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
    path = f"chat_history_{username}.json"
    ok, _ = gh_put_file(
        path,
        json.dumps(messages, ensure_ascii=False, indent=2),
        sha,
        f"Chat update — {username} — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
    )
    if ok:
        _, new_sha = gh_get_file(path)
        return new_sha
    return sha


def load_last_summary(username: str) -> str:
    files = gh_list_dir("summaries")
    user_files = sorted([(n, p) for n, p in files if username in n], reverse=True)
    if user_files:
        content, _ = gh_get_file(user_files[0][1])
        return content or ""
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# POE API
# ══════════════════════════════════════════════════════════════════════════════

def call_poe(bot_name: str, messages: list[dict]) -> tuple[str, str]:
    """
    Call a Poe bot synchronously.
    Returns (response_text, error_message). One of them will be empty.
    Runs async in a background thread to avoid Streamlit event loop conflicts.
    """
    import fastapi_poe as fp

    result:     list[str] = []
    error_info: list[str] = []

    async def _run():
        protocol_messages = []
        for m in messages:
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
        return "", f"Poe API error ({bot_name}): {error_info[0][:400]}"
    if not result:
        return "", f"No response from {bot_name} — timeout or empty reply"
    return result[0], ""


# ══════════════════════════════════════════════════════════════════════════════
# PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

def build_system_prompt(wiki: str, last_summary: str, username: str) -> str:
    today = datetime.date.today().strftime("%A, %B %d, %Y")
    wiki_block    = wiki         if wiki         else "No entries yet. The wiki will grow from conversations."
    summary_block = last_summary if last_summary else "No previous session summaries yet."
    return f"""You are an AI Manager — a strategic, knowledgeable, and proactive assistant built to help this team run and grow their company.

You have a growing company knowledge base (LLM Wiki) below. Reference it naturally when relevant. Speak like a senior advisor who knows this company deeply — not a generic assistant.

You have web search capabilities. Use them when current information or recent data is needed.

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


def build_wiki_update_prompt(wiki: str, last_user_msg: str, last_ai_msg: str, username: str) -> str:
    today = datetime.date.today().isoformat()
    return f"""TASK: Extract only NEW permanent company knowledge from the latest exchange.

You MUST respond with **exactly one valid JSON object** and nothing else.

JSON SCHEMA:
{{
  "updates": [
    {{
      "filename": "wiki/some_name.md",
      "content": "Full markdown content here"
    }}
  ],
  "skip_reason": "string only if no updates"
}}

RULES:
- Output ONLY the JSON. No explanations, no markdown, no code blocks, no extra text.
- Use proper "filename" (e.g. "wiki/retail_channels.md"), not "path".
- If nothing new to add, return "updates": [] and a short skip_reason.
- Existing wiki: {wiki if wiki else "No entries yet."}

LATEST EXCHANGE:
User ({username}): {last_user_msg}
AI: {last_ai_msg}

JSON:
"""


# ══════════════════════════════════════════════════════════════════════════════
# WIKI UPDATER — runs after every single message
# ══════════════════════════════════════════════════════════════════════════════

def extract_json(text: str) -> str:
    """Robust JSON extractor that handles multiple JSON blocks, markdown, and extra text."""
    if not text or not text.strip():
        return "{}"

    # Clean common LLM wrappers
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<JSON>(.*?)</JSON>", r"\1", text, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove markdown code blocks
    text = re.sub(r"```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```", "", text, flags=re.IGNORECASE)

    # Find ALL JSON-like objects and take only the FIRST complete one
    # This regex is more precise for nested structures
    matches = re.findall(r'(\{[\s\S]*?\})', text, re.DOTALL)
    
    if matches:
        # Try each candidate until one parses successfully
        for candidate in matches:
            cleaned = candidate.strip()
            try:
                # Test parse
                json.loads(cleaned)
                return cleaned
            except json.JSONDecodeError:
                continue  # try next match if this one is broken

    # Ultimate fallback: return the whole cleaned text
    return text.strip()


# Then update the parsing section in run_wiki_update_after_message:
    clean_json_str = extract_json(raw)
    # Safety: if there are multiple JSON objects, take only the first one
    if '}{' in clean_json_str:
        clean_json_str = clean_json_str.split('}{')[0] + '}'

    try:
        data = json.loads(clean_json_str)
    except json.JSONDecodeError as e:
        return {
            "updated": False,
            "files": [],
            "skip_reason": "",
            "error": f"JSON Parse Failed: {str(e)}",
            "raw": raw[:1500],   # Show more context for debugging
        }


def run_wiki_update_after_message(username: str, last_user_msg: str, last_ai_msg: str) -> dict:
    """
    Analyzes the latest exchange and updates the GitHub wiki if necessary.
    """
    wiki = load_wiki()
    prompt = build_wiki_update_prompt(wiki, last_user_msg, last_ai_msg, username)

    raw, poe_err = call_poe(FLASH_BOT, [{"role": "user", "content": prompt}])

    if poe_err:
        return {
            "updated": False, 
            "files": [], 
            "skip_reason": "", 
            "error": f"Poe API Error: {poe_err}", 
            "raw": ""
        }

    # ── Hardened Extraction Logic ───────────────────────────────────────────
    clean_json_str = extract_json(raw)

    try:
        data = json.loads(clean_json_str)
    except json.JSONDecodeError as e:
        return {
            "updated": False, 
            "files": [], 
            "skip_reason": "",
            "error": f"JSON Parse Failed: {str(e)}",
            "raw": raw[:1000],  # Include more raw data for debugging
        }

    # ── Process Updates ─────────────────────────────────────────────────────
    updates = data.get("updates", [])
    skip_reason = data.get("skip_reason", "")
    
    files_saved = []
    file_errors = []

    for item in updates:
        fname = item.get("filename", "").strip()
        content = item.get("content", "").strip()

        if not fname or not content:
            continue

        # Get current SHA to allow updating existing files
        _, sha = gh_get_file(fname)

        ok, err = gh_put_file(
            fname, 
            content, 
            sha,
            f"Wiki Update — {username} — {datetime.date.today()}",
        )
        
        if ok:
            files_saved.append(fname)
        else:
            file_errors.append(f"{fname}: {err}")

    # Clear the local Streamlit cache so the UI shows the new data immediately
    if files_saved:
        refresh_wiki_cache()

    return {
        "updated": bool(files_saved),
        "files": files_saved,
        "skip_reason": skip_reason,
        "error": "; ".join(file_errors) if file_errors else "",
        "raw": raw[:800],
    }

    updates = data.get("updates", []) if isinstance(data, dict) else []
    skip_reason = data.get("skip_reason", "") if isinstance(data, dict) else ""
    
    files_saved = []
    file_errors = []

    for item in updates:
        fname   = item.get("filename", "").strip()
        content = item.get("content",  "").strip()

        if not fname or not content:
            continue

        # Get SHA if file already exists (needed for updates, None for creates)
        _, sha = gh_get_file(fname)

        ok, err = gh_put_file(
            fname, content, sha,
            f"Wiki — {username} — {datetime.date.today()}",
        )
        if ok:
            files_saved.append(fname)
        else:
            file_errors.append(f"`{fname}`: {err}")

    if files_saved:
        refresh_wiki_cache()

    return {
        "updated":     bool(files_saved),
        "files":       files_saved,
        "skip_reason": skip_reason,
        "error":       "; ".join(file_errors) if file_errors else "",
        "raw":         raw[:600],
    }


# ══════════════════════════════════════════════════════════════════════════════
# STREAMLIT UI
# ══════════════════════════════════════════════════════════════════════════════

def render_sidebar(username: str):
    """Sidebar after username is confirmed."""
    with st.sidebar:
        # Username is shown at top already — skip repeating it
        st.divider()

        # Wiki file list
        st.markdown("**📚 Knowledge Base**")
        wiki_files = gh_list_dir("wiki")
        md_files   = [(n, p) for n, p in wiki_files if n.endswith(".md")]
        if md_files:
            for name, _ in md_files:
                label = name.replace(".md", "").replace("_", " ").title()
                st.caption(f"  📄 {label}")
        else:
            st.caption("  *(empty — grows automatically)*")

        st.divider()

        # Session progress
        msg_count = len(st.session_state.get("messages", []))
        st.markdown("**Session**")
        st.caption(f"Messages: {msg_count} / {MAX_HISTORY}")
        st.progress(min(msg_count / MAX_HISTORY, 1.0))

        # Last wiki check result
        s = st.session_state.get("last_wiki_status")
        if s:
            st.divider()
            st.markdown("**Last wiki check**")
            if s.get("error"):
                st.caption(f"⚠️ {s['error'][:150]}")
                if s.get("raw"):
                    with st.expander("🔍 Raw Flash response (debug)"):
                        st.code(s["raw"], language="text")
            elif s.get("updated"):
                for f in s["files"]:
                    short = f.replace("wiki/", "")
                    st.caption(f"✅ Updated `{short}`")
            else:
                st.caption(f"⏭ {s.get('skip_reason', 'nothing to add')}")

        st.divider()
        if st.button("🗑️ Clear chat", use_container_width=True,
                     help="Clears chat without touching the wiki."):
            st.session_state["messages"]         = []
            st.session_state["history_sha"]      = None
            st.session_state["last_wiki_status"] = None
            st.rerun()

        st.divider()
        st.caption("Wiki checked automatically after every message.")


def main():
    # ── Username input lives at the very top of the sidebar ─────────────────
    with st.sidebar:
        st.markdown("### 🧠 AI Manager")
        st.caption("Powered by Gemini via Poe API")
        st.divider()
        username_raw = st.selectbox(
            "Who are you?",
            options=["— select —", "Jason", "Francis", "Esther"],
        )

    username = username_raw.strip().lower().replace(" ", "_") if username_raw != "— select —" else ""

    if not username:
        with st.sidebar:
            st.info("👆 Enter your name to begin.")
        st.markdown("## 🧠 AI Manager")
        st.markdown("Enter your name in the sidebar to start.")
        st.stop()

    with st.sidebar:
        st.success(f"👤 {username}")

    # ── Load history (once per user) ─────────────────────────────────────────
    if ("messages" not in st.session_state or
            st.session_state.get("current_user") != username):
        with st.spinner("Loading chat history…"):
            history, sha = load_chat_history(username)
        st.session_state["messages"]         = history
        st.session_state["history_sha"]      = sha
        st.session_state["current_user"]     = username
        st.session_state["last_wiki_status"] = None

    render_sidebar(username)

    # ── Header ───────────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns([3, 1, 1])
    with c1:
        st.markdown("## 🧠 AI Manager")
    with c2:
        st.metric("Wiki files", len([n for n, _ in gh_list_dir("wiki") if n.endswith(".md")]))
    with c3:
        st.metric("Messages", f"{len(st.session_state['messages'])}/{MAX_HISTORY}")

    st.divider()

    # ── Chat display ─────────────────────────────────────────────────────────
    for msg in st.session_state["messages"]:
        avatar = "👤" if msg["role"] == "user" else "🧠"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

    # ── Input ────────────────────────────────────────────────────────────────
    if user_input := st.chat_input("Ask the AI Manager anything…"):

        # 1 — show user message
        st.session_state["messages"].append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_input)

        # 2 — build context
        wiki         = load_wiki()
        last_summary = load_last_summary(username)
        system_msg   = build_system_prompt(wiki, last_summary, username)

        poe_messages = [
            {"role": "user",      "content": system_msg},
            {"role": "assistant", "content": "Understood. I'm your AI Manager. How can I help?"},
        ] + st.session_state["messages"]

        # 3 — get main AI response
        with st.chat_message("assistant", avatar="🧠"):
            with st.spinner("Thinking…"):
                response, poe_err = call_poe(MAIN_BOT, poe_messages)
            if poe_err:
                st.error(f"⚠️ Main model error: {poe_err}")
                st.stop()
            st.markdown(response)

        st.session_state["messages"].append({"role": "assistant", "content": response})

        # 4 — AUTO WIKI UPDATE after every single message
        with st.spinner("📚 Checking wiki for updates…"):
            wiki_status = run_wiki_update_after_message(username, user_input, response)

        st.session_state["last_wiki_status"] = wiki_status

        # Show result briefly
        if wiki_status["error"]:
            st.warning(f"⚠️ Wiki check issue: {wiki_status['error'][:200]}")
            with st.expander("🔍 Debug info"):
                st.code(wiki_status.get("raw", "no raw response"), language="text")
        elif wiki_status["updated"]:
            for f in wiki_status["files"]:
                st.toast(f"📄 Wiki updated: {f.replace('wiki/', '')}", icon="✅")
        # (if skipped, sidebar shows the skip reason — no need to show inline)

        # 5 — trim history if full
        if len(st.session_state["messages"]) >= MAX_HISTORY:
            st.session_state["messages"] = st.session_state["messages"][-4:]
            st.toast("History trimmed. Wiki is up to date.", icon="🔄")

        # 6 — persist chat to GitHub
        new_sha = save_chat_history(
            username,
            st.session_state["messages"],
            st.session_state.get("history_sha"),
        )
        st.session_state["history_sha"] = new_sha


if __name__ == "__main__":
    if check_password():
        main()
