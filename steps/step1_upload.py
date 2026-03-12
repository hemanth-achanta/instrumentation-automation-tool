"""
Step 1 — Upload & Context
Upload Figma screenshots and provide flow context.
"""
import streamlit as st
from utils.image_utils import encode_image_to_base64, get_media_type


def render():
    st.header("📱 Upload & Context")
    st.markdown(
        "Upload Figma screenshots and describe the user flow to auto-generate analytics instrumentation."
    )

    # --- Multi-file uploader ---
    uploaded_files = st.file_uploader(
        "Upload Figma Screenshots (one per screen/state)",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="file_uploader",
    )

    # Process uploaded files
    if uploaded_files:
        # Only re-process if files changed
        current_filenames = sorted([f.name for f in uploaded_files])
        prev_filenames = sorted(
            [img["filename"] for img in st.session_state.get("uploaded_images", [])]
        )

        if current_filenames != prev_filenames:
            images = []
            for f in uploaded_files:
                try:
                    b64 = encode_image_to_base64(f)
                    images.append({
                        "filename": f.name,
                        "base64": b64,
                        "media_type": get_media_type(f.name),
                        "label": "",
                    })
                except Exception as e:
                    st.warning(f"⚠️ Could not process {f.name}: {e}")
            st.session_state.uploaded_images = images

        # Display thumbnails with label inputs
        if st.session_state.get("uploaded_images"):
            st.subheader("Label your screenshots")
            images = st.session_state.uploaded_images
            cols_per_row = 3

            for i in range(0, len(images), cols_per_row):
                cols = st.columns(cols_per_row)
                for j, col in enumerate(cols):
                    idx = i + j
                    if idx < len(images):
                        img = images[idx]
                        with col:
                            st.image(
                                f"data:{img['media_type']};base64,{img['base64']}",
                                caption=img["filename"],
                                use_column_width=True,
                            )
                            label = st.text_input(
                                "Screen label",
                                value=img.get("label", ""),
                                key=f"label_{idx}",
                                placeholder="e.g. Homepage, Checkout Step 2",
                            )
                            images[idx]["label"] = label

            st.session_state.uploaded_images = images

    # --- Flow description ---
    flow_desc = st.text_area(
        "Describe the user flow",
        value=st.session_state.get("flow_description", ""),
        placeholder=(
            "Walk us through what the user sees and does across these screens. "
            "E.g. 'User lands on homepage → taps Doctor Consult banner → "
            "sees booking flow → confirms booking'"
        ),
        height=120,
        key="flow_desc_input",
    )
    st.session_state.flow_description = flow_desc

    # --- Changes description ---
    changes_desc = st.text_area(
        "What is new or changed in this design?",
        value=st.session_state.get("changes_description", ""),
        placeholder=(
            "E.g. 'The Doctor Consult banner is a new launch. "
            "The Home Cards section is unchanged. "
            "The search bar has a new design but same behavior.'"
        ),
        height=100,
        key="changes_desc_input",
    )
    st.session_state.changes_description = changes_desc

    # --- Page type ---
    page_type_options = [
        "New page / feature",
        "Modification to existing page",
        "Mix of both",
    ]
    page_type = st.radio(
        "Is this a new page/feature or a modification to an existing one?",
        page_type_options,
        index=page_type_options.index(
            st.session_state.get("page_type", "New page / feature")
        ),
        key="page_type_input",
    )
    st.session_state.page_type = page_type

    # --- Page name ---
    page_name = st.text_input(
        "Page name (snake_case)",
        value=st.session_state.get("page_name", ""),
        placeholder="e.g. p_home, p_doctor_consult, p_wlm_home",
        key="page_name_input",
    )
    st.session_state.page_name = page_name

    # --- Figma URL (optional) ---
    figma_url = st.text_input(
        "Figma URL (optional)",
        value=st.session_state.get("figma_url", ""),
        placeholder="https://www.figma.com/file/...",
        key="figma_url_input",
    )
    st.session_state.figma_url = figma_url

    # --- PRD upload (optional) ---
    prd_file = st.file_uploader(
        "Upload PRD (optional, txt/md/pdf/docx)",
        type=["txt", "md", "pdf", "docx"],
        key="prd_uploader",
    )
    if prd_file is not None:
        try:
            # Simple text extraction; for binary formats this may be partial but still useful.
            raw_bytes = prd_file.read()
            text = raw_bytes.decode("utf-8", errors="ignore")
            # Truncate to avoid overwhelming the model context.
            st.session_state.prd_text = text[:20000]
            st.caption(f"Loaded PRD '{prd_file.name}' ({len(text)} chars, truncated for context).")
        except Exception as e:
            st.warning(f"Could not read PRD file: {e}")

    # --- Next button ---
    has_images = bool(st.session_state.get("uploaded_images"))
    has_flow = bool(flow_desc.strip())
    can_proceed = has_images and has_flow

    st.divider()
    if st.button("Next → AI Analysis", disabled=not can_proceed, type="primary", use_container_width=True):
        st.session_state.step = 2
        st.rerun()

    if not can_proceed:
        st.caption("Upload at least one image and describe the user flow to proceed.")
