"""
Step 2 — AI Analysis & Q&A
Two sub-phases: automatic visual analysis, then guided Q&A.
"""
import streamlit as st
from utils.claude_client import analyze_screenshots, generate_questions
import pandas as pd


def _run_analysis():
    """Sub-phase A: Analyze screenshots with Claude vision."""
    images = st.session_state.uploaded_images
    flow_desc = st.session_state.flow_description
    changes_desc = st.session_state.get("changes_description", "")
    page_type = st.session_state.get("page_type", "New page / feature")

    with st.spinner("🔍 Analyzing your screenshots with Claude..."):
        try:
            components = analyze_screenshots(
                images,
                flow_desc,
                changes_desc,
                page_type,
                prd_text=st.session_state.get("prd_text"),
            )
            st.session_state.detected_components = components
            st.session_state.analysis_done = True
        except Exception as e:
            st.error(f"❌ Analysis failed: {e}")
            raw = st.session_state.get("last_model_raw")
            if raw:
                with st.expander("🔎 Raw model output (for debugging)", expanded=False):
                    st.code(raw)
            if st.button("🔄 Retry Analysis"):
                st.rerun()
            return False
    return True


def _run_question_generation():
    """Sub-phase A (cont): Generate Q&A questions."""
    components = st.session_state.detected_components

    with st.spinner("🤔 Generating questions based on your design..."):
        try:
            questions = generate_questions(components)
            st.session_state.dynamic_questions = questions
            st.session_state.questions_generated = True
        except Exception as e:
            st.error(f"❌ Question generation failed: {e}")
            if st.button("🔄 Retry Questions"):
                st.rerun()
            return False
    return True


def _render_analysis_results():
    """Display detected component results."""
    components = st.session_state.detected_components
    screen_labels = set(c.get("screen_label", "Unknown") for c in components)

    st.success(f"✅ Detected **{len(components)}** components across **{len(screen_labels)}** screens")

    with st.expander("📋 View detected components", expanded=False):
        df = pd.DataFrame(components)
        display_cols = [
            "screen_label",
            "suggested_story_key",
            "component_name",
            "component_type",
            "suggested_element_unique_name",
            "likely_new",
            "notes",
        ]
        available_cols = [c for c in display_cols if c in df.columns]
        st.dataframe(df[available_cols], use_container_width=True, hide_index=True)


CORE_REQUIRED_IDS = {
    "req_new_components",
    "req_existing_unchanged",
    "req_skip_components",
    "req_business_metric",
    "req_common_payload",
}


def _render_qa_form():
    """Sub-phase B: Render dynamic Q&A form."""
    questions = st.session_state.dynamic_questions

    st.subheader("📝 Answer these questions to refine instrumentation")
    st.caption("Your answers help generate more accurate event specifications.")

    # Initialize qa_answers if not present
    if "qa_answers" not in st.session_state:
        st.session_state.qa_answers = {}

    all_answered = True

    for q in questions:
        qid = q["question_id"]
        qtype = q.get("type", "text")
        options = q.get("options") or []
        component_ref = q.get("component_ref", "general")
        why = q.get("why", "")

        # Component reference badge
        st.markdown(f"**{q['question']}** &nbsp; `{component_ref}`")
        if why:
            st.caption(f"_{why}_")

        current = st.session_state.qa_answers.get(qid)

        if qtype == "yes_no":
            answer = st.radio(
                q["question"],
                ["Yes", "No"],
                index=["Yes", "No"].index(current) if current in ["Yes", "No"] else 0,
                key=f"qa_{qid}",
                label_visibility="collapsed",
            )
            st.session_state.qa_answers[qid] = answer

        elif qtype == "single_select":
            idx = options.index(current) if current in options else 0
            answer = st.selectbox(
                q["question"],
                options,
                index=idx,
                key=f"qa_{qid}",
                label_visibility="collapsed",
            )
            st.session_state.qa_answers[qid] = answer

        elif qtype == "multiselect":
            # Let Streamlit manage state via the widget key; avoid resetting defaults every rerun.
            answer = st.multiselect(
                q["question"],
                options,
                key=f"qa_{qid}",
                label_visibility="collapsed",
            )
            st.session_state.qa_answers[qid] = answer
            if qid in CORE_REQUIRED_IDS and not answer:
                all_answered = False

        else:  # text
            answer = st.text_area(
                q["question"],
                value=current if current else "",
                key=f"qa_{qid}",
                label_visibility="collapsed",
                height=80,
            )
            st.session_state.qa_answers[qid] = answer
            if qid in CORE_REQUIRED_IDS and not answer.strip():
                all_answered = False

        st.markdown("---")

    return all_answered


def render():
    st.header("🔬 AI Analysis & Q&A")

    # Sub-phase A: Run analysis if not done
    if not st.session_state.get("analysis_done"):
        if not _run_analysis():
            return

    # Generate questions if not done (skipped entirely in no question mode)
    if not st.session_state.get("no_question_mode"):
        if not st.session_state.get("questions_generated"):
            if not _run_question_generation():
                return

    # Show results
    _render_analysis_results()

    st.divider()

    # Sub-phase B: Q&A (skipped in no question mode)
    if st.session_state.get("no_question_mode"):
        st.info(
            "**No question mode** — Q&A is skipped. Instrumentation is inferred directly from "
            "your screenshots and the detected components on the next step."
        )
        all_answered = True
    else:
        all_answered = _render_qa_form()

    # Navigation
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Back to Upload", use_container_width=True):
            st.session_state.step = 1
            st.rerun()
    with col2:
        if st.button(
            "Next → Review & Edit",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.step = 3
            st.rerun()

    if not all_answered:
        st.caption(
            "Some recommended questions are unanswered. You can still proceed, "
            "but consider filling them for better instrumentation."
        )
