"""
Step 3 — Review & Edit Instrumentation Table
Generates the full event spec with GPT-4o, then shows an editable table.
"""
import streamlit as st
import pandas as pd
from utils.claude_client import generate_instrumentation
from utils.instrumentation_post import ensure_page_load_ids


EVENT_NAME_OPTIONS = [
    "property_load",
    "element_clicked",
    "i_element_viewed",
    "page_load",
    "session_start",
    "l_event",
]
COMMON_PAYLOAD_OPTIONS = ["Change", "No Change"]
EVENT_STATUS_OPTIONS = ["New", "existing", "Exists", "Exists - Update"]
PRIORITY_OPTIONS = ["P1", "P2", "P3"]


def _generate_draft():
    """Call Claude to produce the instrumentation specification."""
    with st.spinner("✍️ Drafting instrumentation events with Claude..."):
        try:
            rows = generate_instrumentation(
                images=st.session_state.uploaded_images,
                detected_components=st.session_state.detected_components,
                qa_answers=st.session_state.qa_answers,
                dynamic_questions=st.session_state.dynamic_questions,
                page_name=st.session_state.page_name,
                prd_text=st.session_state.get("prd_text"),
                no_question_mode=st.session_state.get("no_question_mode", False),
            )
            st.session_state.final_rows = rows
            st.session_state.instrumentation_generated = True
        except Exception as e:
            st.error(f"❌ Instrumentation generation failed: {e}")
            if st.button("🔄 Retry Generation"):
                st.rerun()
            return False
    return True


def _render_summary(rows: list[dict]):
    """Show summary bar above the table."""
    total = len(rows)
    def _is_exists(status: str) -> bool:
        return status in ("Exists", "existing")

    new_count = sum(1 for r in rows if r.get("event_status") == "New")
    exists_count = sum(1 for r in rows if _is_exists(r.get("event_status")))
    update_count = sum(1 for r in rows if r.get("event_status") == "Exists - Update")
    p1 = sum(1 for r in rows if r.get("aat_priority") == "P1")
    p2 = sum(1 for r in rows if r.get("aat_priority") == "P2")
    p3 = sum(1 for r in rows if r.get("aat_priority") == "P3")

    st.markdown(
        f"📊 **{total} events** | "
        f"🆕 {new_count} New · 📦 {exists_count} Exists · 🔄 {update_count} Updates | "
        f"🔴 {p1} P1 · 🟠 {p2} P2 · 🟢 {p3} P3"
    )


def render():
    st.header("📝 Review & Edit Instrumentation")

    # Generate if not done
    if not st.session_state.get("instrumentation_generated"):
        if not _generate_draft():
            return

    rows = st.session_state.final_rows

    # Summary bar
    _render_summary(rows)

    st.divider()

    # Action buttons
    col_add, col_del = st.columns(2)
    with col_add:
        if st.button("➕ Add Row", use_container_width=True):
            rows.append({
                "story": "",
                "name": "element_clicked",
                "trigger": "",
                "event_specific_payload": "",
                "common_payload": "No Change",
                "event_status": "New",
                "aat_priority": "P2",
                "notes": "",
                "metrics": "",
            })
            st.session_state.final_rows = rows
            st.rerun()

    with col_del:
        if st.button("🗑️ Delete Last Row", use_container_width=True):
            if rows:
                rows.pop()
                st.session_state.final_rows = rows
                st.rerun()

    # Editable table
    df = pd.DataFrame(rows)

    # Ensure all expected columns exist
    expected_cols = [
        "story", "name", "trigger", "event_specific_payload",
        "common_payload", "event_status", "aat_priority", "notes", "metrics",
    ]
    for col in expected_cols:
        if col not in df.columns:
            df[col] = ""

    df = df[expected_cols]

    column_config = {
        "story": st.column_config.TextColumn("Story", width="medium"),
        "name": st.column_config.SelectboxColumn(
            "Name", options=EVENT_NAME_OPTIONS, width="medium"
        ),
        "trigger": st.column_config.TextColumn("Trigger", width="medium"),
        "event_specific_payload": st.column_config.TextColumn(
            "Event Specific Payload", width="large"
        ),
        "common_payload": st.column_config.SelectboxColumn(
            "Common Payload", options=COMMON_PAYLOAD_OPTIONS, width="small"
        ),
        "event_status": st.column_config.SelectboxColumn(
            "Event Status", options=EVENT_STATUS_OPTIONS, width="small"
        ),
        "aat_priority": st.column_config.SelectboxColumn(
            "AAT + Priority", options=PRIORITY_OPTIONS, width="small"
        ),
        "notes": st.column_config.TextColumn("Notes", width="medium"),
        "metrics": st.column_config.TextColumn("Metrics", width="medium"),
    }

    edited_df = st.data_editor(
        df,
        column_config=column_config,
        use_container_width=True,
        num_rows="dynamic",
        hide_index=True,
        key="instrumentation_editor",
    )

    # Sync edits back to session state (page_load rows must include page_load_id)
    records = edited_df.to_dict("records")
    st.session_state.final_rows = ensure_page_load_ids(records)

    # Feedback + regenerate section (below table, above navigation)
    st.divider()
    regen_comment = st.text_area(
        "Feedback for regenerating instrumentation (optional)",
        value=st.session_state.get("regen_comment", ""),
        help="Explain what you want changed; this comment will be sent back to Claude if you regenerate.",
    )
    st.session_state.regen_comment = regen_comment

    if st.button("🔁 Regenerate Instrumentation", use_container_width=True):
        with st.spinner("♻️ Regenerating instrumentation with your feedback..."):
            try:
                rows = generate_instrumentation(
                    images=st.session_state.uploaded_images,
                    detected_components=st.session_state.detected_components,
                    qa_answers=st.session_state.qa_answers,
                    dynamic_questions=st.session_state.dynamic_questions,
                    page_name=st.session_state.page_name,
                    prd_text=st.session_state.get("prd_text"),
                    regen_comment=st.session_state.get("regen_comment"),
                    no_question_mode=st.session_state.get("no_question_mode", False),
                )
                st.session_state.final_rows = rows
                st.session_state.instrumentation_generated = True
                st.success("Instrumentation regenerated using your feedback.")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Regeneration failed: {e}")

    # Navigation
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        back_label = (
            "← Back to Analysis"
            if st.session_state.get("no_question_mode")
            else "← Back to Q&A"
        )
        if st.button(back_label, use_container_width=True):
            st.session_state.step = 2
            st.rerun()
    with col2:
        if st.button("Next → Download", type="primary", use_container_width=True):
            st.session_state.step = 4
            st.rerun()
