"""
📊 Instrumentation Generator — Main Streamlit App
A multi-step wizard that takes Figma screenshots and generates
analytics instrumentation Excel files using Anthropic Claude vision.
"""
import os
import sys

import streamlit as st

# Ensure the app directory is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from steps import step1_upload, step2_analysis, step3_review, step4_download
from utils.claude_client import get_api_status

# ──────────────────────────────────────────────
# Page config
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="Instrumentation Generator",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────
# Session state defaults
# ──────────────────────────────────────────────
if "step" not in st.session_state:
    st.session_state.step = 1

DEFAULTS = {
    "uploaded_images": [],
    "flow_description": "",
    "changes_description": "",
    "page_name": "",
    "page_type": "New page / feature",
    "figma_url": "",
    "detected_components": [],
    "dynamic_questions": [],
    "qa_answers": {},
    "final_rows": [],
    "analysis_done": False,
    "questions_generated": False,
    "instrumentation_generated": False,
    "no_question_mode": False,
}

for key, default in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ──────────────────────────────────────────────
# Sidebar
# ──────────────────────────────────────────────
def render_sidebar():
    with st.sidebar:
        st.markdown("## 📊 Instrumentation Generator")
        st.caption("Figma → Analytics Events → Excel")
        st.divider()

        # API status
        ok, msg = get_api_status()
        if ok:
            st.markdown("🟢 **Anthropic Claude API**: Connected")
            st.caption(msg)
        else:
            st.markdown("🔴 **Anthropic Claude API**: Key not found / invalid")
            st.caption(msg)

        st.divider()

        # Step indicator
        steps = {
            1: "① Upload & Context",
            2: "② AI Analysis & Q&A",
            3: "③ Review & Edit",
            4: "④ Download",
        }
        current = st.session_state.step
        for num, label in steps.items():
            if num < current:
                st.markdown(f"✅ ~~{label}~~")
            elif num == current:
                st.markdown(f"🔵 **{label}**")
            else:
                st.markdown(f"⬜ {label}")

        st.divider()

        # Detected components (after Step 2)
        if st.session_state.detected_components:
            with st.expander("🔍 Detected Components", expanded=False):
                for comp in st.session_state.detected_components:
                    name = comp.get("component_name", "Unknown")
                    ctype = comp.get("component_type", "")
                    new_badge = " 🆕" if comp.get("likely_new") else ""
                    st.markdown(f"- **{name}** ({ctype}){new_badge}")

        # Q&A answers (after Step 2)
        if st.session_state.qa_answers:
            with st.expander("📝 Your Answers", expanded=False):
                for qid, answer in st.session_state.qa_answers.items():
                    display_answer = answer if not isinstance(answer, list) else ", ".join(answer)
                    st.markdown(f"**{qid}**: {display_answer}")


# ──────────────────────────────────────────────
# Step indicator (top of page)
# ──────────────────────────────────────────────
def render_step_indicator():
    current = st.session_state.step
    labels = [
        "① Upload & Context",
        "② AI Analysis & Q&A",
        "③ Review & Edit",
        "④ Download",
    ]

    cols = st.columns(len(labels))
    for i, (col, label) in enumerate(zip(cols, labels), start=1):
        with col:
            if i < current:
                st.markdown(
                    f'<div style="text-align:center;padding:8px;background:#c6efce;'
                    f'border-radius:8px;font-weight:600;color:#256029;">✅ {label}</div>',
                    unsafe_allow_html=True,
                )
            elif i == current:
                st.markdown(
                    f'<div style="text-align:center;padding:8px;background:#bdd7ee;'
                    f'border-radius:8px;font-weight:700;color:#1f4e79;">▶ {label}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div style="text-align:center;padding:8px;background:#e0e0e0;'
                    f'border-radius:8px;color:#888;">{label}</div>',
                    unsafe_allow_html=True,
                )

    st.markdown("")  # Spacer


# ──────────────────────────────────────────────
# Main routing
# ──────────────────────────────────────────────
def main():
    render_sidebar()
    render_step_indicator()

    step = st.session_state.step

    if step == 1:
        step1_upload.render()
    elif step == 2:
        step2_analysis.render()
    elif step == 3:
        step3_review.render()
    elif step == 4:
        step4_download.render()
    else:
        st.session_state.step = 1
        st.rerun()


if __name__ == "__main__":
    main()
