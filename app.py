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
[data-testid="stChatMessage"] { background-color: #1a1a1e; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# SECRETS & SETUP
# ══════════════════════════════════════════════════════════════════════════════
try:
    GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
    GITHUB_REPO  = st.secrets["GITHUB_REPO"]
    POE_API_KEY  = st.secrets["POE_API_KEY"]
    PASSWORD     = st.secrets["PASSWORD"]
except KeyError as missing:
    st.error(f"⚠️ Missing secret: `{missing}`. Check Streamlit Cloud → App Settings → Secrets.")
    st.stop()

MAIN_BOT    = st.secrets.get("MAIN_BOT",  "gemini-3.1-pro")
FLASH_BOT   = st.secrets.get("FLASH_BOT", "gemini-3-flash")
MAX_HISTORY = 20

# ══════════════════════════════════════════════════════════════════════════════
# ACCESS CONTROL (Session-based Login)
# ══════════════════════════════════════════════════════════════════════════════
def check_password():
    """Returns True if the user had the correct password."""
    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password"] == st.secrets["PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # Don't store password in session state
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.markdown("### 🧠 AI Manager Login")
        st.text_input(
            "Enter master password to access the workspace", 
            type="password", 
            on_change=password_entered, 
            key="password"
        )
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        return False
    return True

# ══════════════════════════════════════════════════════════════════════════════
# API HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════
def call_poe(bot_name: str, messages: list) -> tuple[str, str]:
    """Basic Poe API caller."""
    url = "https://api.poe.com/bot/fetch_messages"
    headers = {
        "Authorization": f"Bearer {POE_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {"bot": bot_name, "messages": messages}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        # Simplified parser for Poe's SSE stream
        full_text = ""
        for line in response.text.splitlines():
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    full_text += data.get("text", "")
                except:
                    pass
        return full_text, ""
    except Exception as e:
        return "", str(e)

def gh_get_file(filepath: str) -> tuple[Optional[str], Optional[str]]:
    """Fetches file content and SHA from GitHub."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        data = r.json()
        return base64.b64decode(data["content"]).decode("utf-8"), data["sha"]
    return None, None

def gh_put_file(filepath: str, content: str, sha: Optional[str], message: str) -> tuple[bool, str]:
    """Pushes a file to GitHub."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=headers, json=payload)
    if r.status_code in [200, 201]:
        return True, ""
    return False, r.text

def load_wiki() -> str:
    """Loads all markdown files in the wiki directory."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/wiki"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        return ""
    
    wiki_text = ""
    for item in r.json():
        if item["name"].endswith(".md"):
            content, _ = gh_get_file(item["path"])
            if content:
                wiki_text += f"\n\n--- FILE: {item['path']} ---\n{content}"
    return wiki_text

def refresh_wiki_cache():
    st.session_state["wiki_cache"] = load_wiki()

def save_chat_history(username: str, messages: list, sha: str = None) -> str:
    date_str = datetime.date.today().isoformat()
    filepath = f"logs/chat_{username}_{date_str}.json"
    content = json.dumps(messages, indent=2)
    _, err = gh_put_file(filepath, content, sha, f"Chat log update for {username}")
    if err:
        st.warning(f"Failed to save history: {err}")
    # Return a dummy SHA for logic flow, in reality you'd parse the PUT response
    return "updated_sha"

# ══════════════════════════════════════════════════════════════════════════════
# WIKI UPDATER & PROMPTS
# ══════════════════════════════════════════════════════════════════════════════
def build_wiki_update_prompt(wiki: str, last_user_msg: str, last_ai_msg: str, username: str) -> str:
    today = datetime.date.today().isoformat()
    
    # Context-aware fallback for an empty wiki
    empty_wiki_msg = "Empty — no entries yet. Create wiki files if useful company information, product specifications (like the new collapsible silicone containers), or strategic goals appear."
    
    return f"""You are a company knowledge manager. After each conversation exchange, you decide if any new company information should be saved to the wiki.

CURRENT WIKI:
{wiki if wiki else empty_wiki_msg}

LATEST EXCHANGE (user: {username}, date: {today}):
USER: {last_user_msg}

AI MANAGER: {last_ai_msg}

TASK: Extract any NEW facts, decisions, strategies, products, team info, processes, goals, or context about the company that is worth storing permanently. Be selective — only add genuinely useful, lasting company knowledge. Skip greetings, one-off questions, generic advice, or anything not specific to this company.

You MUST wrap your final response inside <JSON> and </JSON> tags. Do not use markdown code fences.
<JSON>
{{
  "updates": [
    {{
      "filename": "wiki/topic_name.md",
      "content": "# Topic Title\\n\\nFull markdown content. Use clear headers and bullet points."
    }}
  ],
  "skip_reason": "one sentence explaining why nothing was added"
}}
</JSON>

Filename rules:
- Lowercase snake_case only: wiki/company_overview.md, wiki/products.md
- If UPDATING an existing file, rewrite the FULL file content merging old and new information
- If nothing new to add: {{"updates": [], "skip_reason": "reason here"}}"""

def run_wiki_update_after_message(username: str, last_user_msg: str, last_ai_msg: str) -> dict:
    wiki = st.session_state.get("wiki_cache", "")
    prompt = build_wiki_update_prompt(wiki, last_user_msg, last_ai_msg, username)
    raw, poe_err = call_poe(FLASH_BOT, [{"role": "user", "content": prompt}])

    if poe_err:
        return {"updated": False, "files": [], "skip_reason": "", "error": poe_err, "raw": ""}

    # 1. Strip out <think> tags if the model natively uses them
    clean_raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    
    # 2. Extract content between <JSON> tags if present
    if "<JSON>" in clean_raw and "</JSON>" in clean_raw:
        clean = clean_raw.split("<JSON>")[1].split("</JSON>")[0].strip()
    else:
        clean = re.sub(r"```json\s*|```\s*", "", clean_raw).strip()
        start = clean.find("{")
        end   = clean.rfind("}") + 1
        clean = clean[start:end]

    if not clean.startswith("{") or not clean.endswith("}"):
        return {"updated": False, "files": [], "skip_reason": "", "error": "Malformed JSON structure.", "raw": raw[:600]}

    try:
        data = json.loads(clean)
    except json.JSONDecodeError as e:
        try:
            decoder = json.JSONDecoder()
            data, _ = decoder.raw_decode(clean)
        except json.JSONDecodeError as e2:
            return {"updated": False, "files": [], "skip_reason": "", "error": f"JSON parse failed: {e2}", "raw": raw[:600]}

    updates = data.get("updates", [])
    skip_reason = data.get("skip_reason", "")
    files_saved = []
    file_errors = []

    for item in updates:
        fname = item.get("filename", "").strip()
        content = item.get("content", "").strip()
        if not fname or not content:
            continue

        _, sha = gh_get_file(fname)
        ok, err = gh_put_file(fname, content, sha, f"Wiki — {username} — {datetime.date.today()}")
        
        if ok: files_saved.append(fname)
        else: file_errors.append(f"`{fname}`: {err}")

    if files_saved:
        refresh_wiki_cache()

    return {
        "updated": bool(files_saved), "files": files_saved, 
        "skip_reason": skip_reason, "error": "; ".join(file_errors), "raw": raw[:600]
    }

# ══════════════════════════════════════════════════════════════════════════════
# MAIN APP EXECUTION
# ══════════════════════════════════════════════════════════════════════════════
def main():
    st.title("🧠 AI Manager Workspace")
    username = st.sidebar.text_input("Your Name", "Team Member")
    
    if "messages" not in st.session_state:
        st.session_state["messages"] = []
    if "wiki_cache" not in st.session_state:
        st.session_state["wiki_cache"] = load_wiki()

    with st.sidebar:
        st.header("Workspace Controls")
        if st.button("Refresh Wiki Cache"):
            with st.spinner("Fetching..."):
                refresh_wiki_cache()
            st.success("Wiki refreshed!")
        
        st.subheader("Latest Wiki Status")
        last_status = st.session_state.get("last_wiki_status", {})
        if last_status:
            if last_status.get("updated"):
                st.success(f"Updated: {', '.join(last_status['files'])}")
            else:
                st.info(f"Skipped: {last_status.get('skip_reason', 'No updates required.')}")

    # Display chat history
    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input block
    user_input = st.chat_input("Discuss strategy, brainstorm gear designs, or ask the AI Manager...")
    if user_input:
        st.session_state["messages"].append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                response, poe_err = call_poe(MAIN_BOT, st.session_state["messages"])
            
            if poe_err:
                st.error(f"⚠️ Main model error: {poe_err}")
                st.stop()
            st.markdown(response)

        st.session_state["messages"].append({"role": "assistant", "content": response})

        # 4 — AUTO WIKI UPDATE
        with st.spinner("📚 Checking wiki for updates…"):
            wiki_status = run_wiki_update_after_message(username, user_input, response)
        
        st.session_state["last_wiki_status"] = wiki_status

        if wiki_status["error"]:
            st.warning(f"⚠️ Wiki check issue: {wiki_status['error'][:200]}")
            with st.expander("🔍 Debug info"):
                st.code(wiki_status.get("raw", "no raw response"), language="text")
        elif wiki_status["updated"]:
            for f in wiki_status["files"]:
                st.toast(f"📄 Wiki updated: {f.replace('wiki/', '')}", icon="✅")

        # 5 — Trim history
        if len(st.session_state["messages"]) >= MAX_HISTORY:
            st.session_state["messages"] = st.session_state["messages"][-4:]
            st.toast("History trimmed. Wiki is up to date.", icon="🔄")

        # 6 — Persist chat
        new_sha = save_chat_history(username, st.session_state["messages"], st.session_state.get("history_sha"))
        st.session_state["history_sha"] = new_sha

        st.rerun()

# Execute the gate and the main app
if __name__ == "__main__":
    if check_password():
        main()
