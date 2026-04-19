"""
Step 4 — Generate & Download
Produces the final .xlsx and offers it for download.
"""
import streamlit as st
from utils.excel_generator import generate_excel
from utils.instrumentation_post import ensure_page_load_ids


def render():
    st.header("🎉 Download Instrumentation")

    rows = st.session_state.get("final_rows", [])
    ensure_page_load_ids(rows)
    st.session_state.final_rows = rows
    page_name = st.session_state.get("page_name", "instrumentation")
    figma_url = st.session_state.get("figma_url", "")

    if not rows:
        st.warning("No instrumentation rows found. Please go back and generate events first.")
        if st.button("← Back to Review"):
            st.session_state.step = 3
            st.rerun()
        return

    # Generate Excel
    excel_buffer = generate_excel(rows, page_name, figma_url)

    # Success banner
    st.success(f"✅ Instrumentation ready! **{len(rows)} events** generated.")

    # Summary cards
    st.subheader("📊 Summary")

    col1, col2, col3 = st.columns(3)

    # Event type breakdown
    with col1:
        st.markdown("**By Event Type**")
        event_types = {}
        for r in rows:
            name = r.get("name", "unknown")
            event_types[name] = event_types.get(name, 0) + 1
        for etype, count in sorted(event_types.items()):
            st.markdown(f"- `{etype}`: **{count}**")

    # Status breakdown
    with col2:
        st.markdown("**By Status**")
        statuses = {}
        for r in rows:
            s = r.get("event_status", "Unknown")
            statuses[s] = statuses.get(s, 0) + 1
        for status, count in sorted(statuses.items()):
            emoji = "🆕" if status == "New" else "🔄" if "Update" in status else "📦"
            st.markdown(f"- {emoji} {status}: **{count}**")

    # Priority breakdown
    with col3:
        st.markdown("**By Priority**")
        priorities = {}
        for r in rows:
            p = r.get("aat_priority", "P2")
            priorities[p] = priorities.get(p, 0) + 1
        for prio in ["P1", "P2", "P3"]:
            count = priorities.get(prio, 0)
            emoji = "🔴" if prio == "P1" else "🟠" if prio == "P2" else "🟢"
            st.markdown(f"- {emoji} {prio}: **{count}**")

    st.divider()

    # Download button
    file_name = f"{page_name}_instrumentation.xlsx" if page_name else "instrumentation.xlsx"
    excel_bytes = excel_buffer.getvalue()
    st.download_button(
        label="⬇️ Download Instrumentation Excel",
        data=excel_bytes,
        file_name=file_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )

    st.divider()

    # Start over
    if st.button("🔄 Start Over", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    # Back button
    if st.button("← Back to Review & Edit", use_container_width=True):
        st.session_state.step = 3
        st.rerun()
