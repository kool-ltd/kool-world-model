import streamlit as st
import requests
from openai import OpenAI

st.set_page_config(page_title="Company World Model", layout="wide")

# Hide sidebar completely
st.markdown("""
<style>
    [data-testid="stSidebar"] {display: none !important;}
    [data-testid="collapsedControl"] {display: none !important;}
</style>
""", unsafe_allow_html=True)

st.title("🧠 Company World Model Assistant")
st.caption("Pure GitHub wiki context • Web search optional")

POE_API_KEY = st.secrets["POE_API_KEY"]

# Model picker (still fully flexible)
MODEL = st.selectbox(
    "Model",
    ["Gemini-3.1-Pro", "Claude-Opus-4.7", "Claude-Sonnet-4.6", "Gemini-3.1-Flash"],
    index=0
)

# Toggle for web search
USE_WEB_SEARCH = st.toggle("🔍 Allow web search (Responses API)", value=False)

client = OpenAI(api_key=POE_API_KEY, base_url="https://api.poe.com/v1")

@st.cache_data(ttl=300)
def load_world_model():
    base = "https://raw.githubusercontent.com/YOUR-USERNAME/your-company-world-model/main/wiki/"
    context = ""
    for f in ["schema.md", "index.md"]:
        try:
            r = requests.get(base + f, timeout=10)
            if r.ok:
                context += f"\n\n--- {f.upper()} ---\n{r.text}"
        except:
            pass
    return context

world_context = load_world_model()

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Ask anything about the company..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        full_prompt = f"""
{world_context}

You are the company AI. Use ONLY the world model above unless web search is explicitly enabled.
Always cite wiki pages when possible.
User: {prompt}
"""

        if USE_WEB_SEARCH:
            # === Use Responses API with web search ===
            response = client.responses.create(
                model=MODEL,
                input=full_prompt,
                tools=[{"type": "web_search_preview"}],
                temperature=0.7,
                max_output_tokens=16000,
                stream=True
            )
            result = st.write_stream(chunk.output_text or "" for chunk in response)
        else:
            # === Original Chat Completions (no web search) ===
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": full_prompt}],
                temperature=0.7,
                max_tokens=16000,
                stream=True
            )
            result = st.write_stream(chunk.choices[0].delta.content or "" for chunk in response)

    st.session_state.messages.append({"role": "assistant", "content": result})

# Trigger update button stays the same
if st.button("🔄 Trigger world model update"):
    requests.post(
        "https://api.github.com/repos/YOUR-USERNAME/your-company-world-model/actions/workflows/maintain-wiki.yml/dispatches",
        headers={"Authorization": f"token {st.secrets['GITHUB_TOKEN']}"},
        json={"ref": "main"}
    )
    st.success("Update triggered on GitHub!")