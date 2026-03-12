"""
Anthropic Claude client for all vision + text calls.

This implementation prefers reading the Anthropic API key from environment:
- `ANTHROPIC_API_KEY` (typically loaded from `instrumentation_tool/.env`)

If not present, it falls back to the repo-level `api_key` file:
- `.../Instrumentation/api_key`
"""

from __future__ import annotations

import json
import os
import re
import ast
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv
from json_repair import repair_json
from utils.events_config import (
    get_allowed_event_names,
    get_allowed_attributes,
    get_compact_schema_summary,
)


MODEL = "claude-opus-4-5"

load_dotenv()


def _api_key_file_path() -> Path:
    # utils/claude_client.py -> utils -> instrumentation_tool -> Instrumentation
    return Path(__file__).resolve().parents[2] / "api_key"


def _read_api_key() -> str:
    env_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if env_key:
        return env_key

    path = _api_key_file_path()
    if not path.exists():
        raise ValueError(
            "ANTHROPIC_API_KEY is not set and fallback `api_key` file was not found at: "
            f"{path}"
        )
    key = path.read_text(encoding="utf-8").strip()
    if not key:
        raise ValueError(
            "ANTHROPIC_API_KEY is not set and fallback `api_key` file is empty at: "
            f"{path}"
        )
    return key


def get_api_status() -> tuple[bool, str]:
    """Return (ok, message) for sidebar status."""
    try:
        key = _read_api_key()
        if os.getenv("ANTHROPIC_API_KEY", "").strip():
            return True, "Connected (key from `ANTHROPIC_API_KEY`)"
        return True, f"Connected (fallback key from `{_api_key_file_path().name}`)"
    except Exception as e:
        return False, str(e)


def _get_client() -> Anthropic:
    return Anthropic(api_key=_read_api_key())


def _parse_json_response(text: str) -> Any:
    """Safely parse JSON from the model's response, handling markdown fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to extract the first balanced JSON array/object from the text.
        extracted = _extract_first_json(cleaned)
        if extracted is not None:
            # 1) Try strict JSON first
            try:
                return json.loads(extracted)
            except json.JSONDecodeError:
                # 2) Fallback: handle Python-literal-ish structures (single quotes, True/False, None)
                try:
                    value = ast.literal_eval(extracted)
                    if not isinstance(value, (list, dict)):
                        raise ValueError("Parsed value is not a JSON array/object.")
                    return value
                except Exception:
                    pass

                # 3) Repair malformed JSON (handles unterminated strings, trailing commas, etc.)
                try:
                    repaired = repair_json(extracted)
                    return json.loads(repaired)
                except Exception:
                    # 4) As a last attempt, normalize a couple common issues and retry JSON
                    normalized = _normalize_json_like(extracted)
                    return json.loads(normalized)
        raise


def _normalize_json_like(text: str) -> str:
    """
    Minimal normalization for common near-JSON mistakes:
    - Convert Python booleans/None to JSON (True/False/None -> true/false/null)
    Note: We intentionally do NOT attempt aggressive quote-fixing here.
    """
    out = text
    out = re.sub(r"\bTrue\b", "true", out)
    out = re.sub(r"\bFalse\b", "false", out)
    out = re.sub(r"\bNone\b", "null", out)
    return out


def _extract_first_json(text: str) -> str | None:
    """
    Extract the first balanced JSON array/object substring from text.
    Handles nested braces/brackets and quoted strings.
    """
    # Find first opening token
    start = None
    opening = None
    for i, ch in enumerate(text):
        if ch in "[{":
            start = i
            opening = ch
            break
    if start is None:
        return None

    closing = "]" if opening == "[" else "}"
    stack = [opening]
    in_string = False
    escape = False

    for j in range(start + 1, len(text)):
        ch = text[j]

        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch in "[{":
            stack.append(ch)
            continue
        if ch in "]}":
            if not stack:
                return None
            top = stack.pop()
            expected = "]" if top == "[" else "}"
            if ch != expected:
                # Mismatched closing token; abort extraction.
                return None
            if not stack:
                return text[start : j + 1]

    return None


def _build_image_content(images: list[dict]) -> list[dict]:
    """
    Build Claude vision content blocks from a list of image dicts.
    Each dict has keys: filename, base64, label, media_type.
    """
    content: list[dict] = []
    for img in images:
        label = img.get("label", img.get("filename", "Screenshot"))
        content.append({"type": "text", "text": f"--- Screenshot: {label} ---"})
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.get("media_type", "image/png"),
                    "data": img["base64"],
                },
            }
        )
    return content


ANALYZE_SYSTEM_PROMPT = """You are an expert mobile analytics engineer specializing in event instrumentation for health-tech apps.
Your job is to analyze Figma design screenshots and identify every UI component that requires analytics tracking.

For each screenshot, identify:
1. All interactive UI components (buttons, cards, banners, carousels, navigation items, tabs, toggles, search bars, bottom sheets, CTAs)
2. All content-rendering components (widgets that load data, banners that display offers, lists/carousels of items)
3. Page-level events (page loads, page views)
4. Any components that clearly appear NEW (tagged "NEW LAUNCH", "BETA", visually distinct) vs likely existing

For each component you identify, output structured JSON only (no prose).
Return a JSON array where each object has:
{
  "screen_label": "<which screenshot this is from>",
  "component_name": "<human readable name>",
  "component_type": "page_load | banner | card_list | carousel | cta_button | search | navigation | sticky_element | bottomsheet | widget",
  "suggested_element_unique_name": "<snake_case identifier e.g. hp_doctor_consult_banner>",
  "likely_new": true/false,
  "suggested_events": ["property_load", "i_element_viewed", "element_clicked"],
  "notes": "<any important observations about this component>"
}

Output requirements (critical):
- Output MUST be valid JSON (RFC 8259). Use double quotes for all keys/strings.
- Do NOT include trailing commas, comments, or any other text outside the JSON array.
- Do NOT use single quotes, True/False/None. Use true/false/null.
- Keep strings simple; if you need newlines in \"notes\", use \\n.
- If you cannot comply, return an empty JSON array: []"""

ANALYZE_SYSTEM_PROMPT_COMPACT = ANALYZE_SYSTEM_PROMPT + """

Compact mode (very important to avoid truncation):
- Return AT MOST 35 components total across all screenshots.
- Prioritize: page_load, primary CTAs, navigation, banners, forms/inputs, key list/carousel widgets.
- If multiple similar inputs exist, group them into one component (e.g., \"Patient Details Form\" instead of each field).
- Keep \"notes\" under 120 characters."""


def analyze_screenshots(
    images: list[dict],
    flow_description: str,
    changes_description: str,
    page_type: str,
    prd_text: str | None = None,
) -> list[dict]:
    client = _get_client()

    user_content = _build_image_content(images)
    meta_text = (
        f"Flow description: {flow_description}\n\n"
        f"New/changed elements: {changes_description}\n\n"
        f"Page type: {page_type}"
    )
    if prd_text:
        snippet = prd_text[:8000]
        meta_text += (
            "\n\nPRD context (may be truncated, use only as reference):\n" + snippet
        )
    user_content.append({"type": "text", "text": meta_text})

    def _call(system_prompt: str, max_tokens: int) -> str:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            temperature=0.2,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        return msg.content[0].text if msg.content else ""

    # First attempt: higher output budget
    raw = _call(ANALYZE_SYSTEM_PROMPT, max_tokens=8192)
    _maybe_store_last_raw(raw)
    try:
        return _parse_json_response(raw)
    except Exception:
        # If we likely got truncated / unbalanced output, retry with compact prompt.
        if _looks_truncated(raw):
            raw2 = _call(ANALYZE_SYSTEM_PROMPT_COMPACT, max_tokens=4096)
            _maybe_store_last_raw(raw2)
            return _parse_json_response(raw2)
        raise


def _looks_truncated(text: str) -> bool:
    """
    Heuristics to detect partial/truncated JSON outputs.
    """
    t = text.strip()
    if not t:
        return False
    # If we can't even extract a balanced JSON blob, likely truncated.
    if _extract_first_json(t) is None:
        # Common: starts a JSON array but never closes it.
        if t.count("[") > t.count("]") or t.count("{") > t.count("}"):
            return True
        # Ends in a clearly incomplete token.
        if t[-1] in [":", ",", '"', "\\\\"]:
            return True
    return False


QUESTIONS_SYSTEM_PROMPT = """You are helping a product analyst define analytics instrumentation. Based on the UI components detected from Figma screenshots, generate a targeted Q&A to clarify what needs to be instrumented and how.

Generate between 5-10 questions. Each question should be specific to the components detected — not generic.
Focus on:
- Confirming which components are truly new vs existing (to avoid redundant instrumentation)
- Understanding business-critical actions that MUST be tracked
- Clarifying payload details that can't be inferred from visuals alone (e.g. is a price dynamic? is a banner configurable via CMS?)
- Identifying edge cases (empty states, error states, loading states that need events)
- Understanding the page hierarchy (is this a sub-page, a bottom sheet, or a full page?)

Return JSON array only:
[
  {
    "question_id": "q1",
    "question": "<the question text>",
    "type": "multiselect | single_select | text | yes_no",
    "options": ["option1", "option2"] or null if type is text,
    "component_ref": "<which component_name this question relates to, or 'general'>",
    "why": "<one sentence on why this matters for instrumentation>"
  }
]

Output requirements (critical):
- Output MUST be valid JSON (RFC 8259). Use double quotes for all keys/strings.
- Do NOT include trailing commas, comments, markdown, or any other text outside the JSON array.
- Do NOT use single quotes, True/False/None. Use true/false/null.
- If you cannot comply, return []"""


def generate_questions(detected_components: list[dict]) -> list[dict]:
    client = _get_client()

    message = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        temperature=0.3,
        system=QUESTIONS_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": json.dumps(detected_components, indent=2),
            }
        ],
    )

    raw = message.content[0].text if message.content else ""
    _maybe_store_last_raw(raw)
    questions = _parse_json_response(raw)

    component_names = [c.get("component_name", "Unknown") for c in detected_components]
    _ensure_required_questions(questions, component_names)
    return questions


def _ensure_required_questions(questions: list[dict], component_names: list[str]):
    existing_ids = {q.get("question_id") for q in questions}

    required = [
        {
            "question_id": "req_new_components",
            "question": "Which of the detected components are completely new and have never been instrumented before?",
            "type": "multiselect",
            "options": component_names,
            "component_ref": "general",
            "why": "Determines which components need brand-new event definitions.",
        },
        {
            "question_id": "req_existing_unchanged",
            "question": "Which components already have instrumentation that should remain unchanged?",
            "type": "multiselect",
            "options": component_names,
            "component_ref": "general",
            "why": "Prevents duplicate instrumentation work on unchanged components.",
        },
        {
            "question_id": "req_skip_components",
            "question": "Are there any components that should NOT be instrumented at all?",
            "type": "multiselect",
            "options": component_names,
            "component_ref": "general",
            "why": "Avoids unnecessary events that add noise without analytical value.",
        },
        {
            "question_id": "req_business_metric",
            "question": "What is the primary business metric this feature is designed to impact?",
            "type": "text",
            "options": None,
            "component_ref": "general",
            "why": "Ensures instrumentation is aligned with business goals.",
        },
        {
            "question_id": "req_common_payload",
            "question": "Should all events use the same Common Payload, or are there components needing changes to the common payload?",
            "type": "single_select",
            "options": ["All same", "Some need changes", "All need new common payload"],
            "component_ref": "general",
            "why": "Determines if the common payload structure needs any modifications.",
        },
    ]

    for rq in required:
        if rq["question_id"] not in existing_ids:
            questions.append(rq)


INSTRUMENTATION_SYSTEM_PROMPT = """You are an expert analytics engineer. Generate a complete event instrumentation specification based on the detected UI components and the user's Q&A answers.

For each event row, return JSON in this exact format:
{
  "story": "<UI section name, e.g. 'Doctor Consult Banner'>",
  "name": "<event name, e.g. 'property_load', 'element_clicked', 'i_element_viewed', 'page_load'>",
  "trigger": "<plain English description of when this fires>",
  "event_specific_payload": "<multi-line string of key: value pairs with inline examples and angle-bracket descriptions>",
  "common_payload": "<'Change' if common payload needs updating, 'No Change' if not>",
  "event_status": "<'New' if new event, 'Exists' if existing, 'Exists - Update' if existing but needs changes>",
  "aat_priority": "<P1 / P2 / P3>",
  "notes": "<any important notes for the engineer>",
  "metrics": "<what metric this event enables>"
}

Rules:
- Use snake_case for all payload keys
- event_specific_payload should follow this style:
  element_unique_name: hp_doctor_consult_banner
  item_type: services
  source: <page containing the widget> (Eg: p_home)
  destination: <destination page on click> (Eg: p_doctor_consult)
  price: <discounted price shown> (Eg: 199)
  element_cta: book_now/banner
- For carousels/lists: always include item_rank, num_of_items, element_scroll_type, widget_vertical_rank
- For banners: always include property_name or element_unique_name, item_name, item_type, widget_vertical_rank
- For page loads: always include page_name, source_page_name, and boolean flags for all major widgets (has_X: 0/1)
- Only include events for components NOT in the "should not be instrumented" list from Q&A
- For components marked as "already instrumented, no change" — include a row with event_status = "Exists" and note "No changes needed"
- Mark P1 for anything on the critical user journey (search, primary CTAs, page loads, new feature banners)
- Mark P2 for supporting elements (secondary cards, navigation)
- Mark P3 for edge cases and passive views

Return a JSON array of these event objects. No prose, just JSON.

Output requirements (critical):
- Output MUST be valid JSON (RFC 8259). Use double quotes for all keys/strings.
- Do NOT include trailing commas, comments, markdown, or any other text outside the JSON array.
- Do NOT use single quotes, True/False/None. Use true/false/null.
- If you cannot comply, return an empty array: []."""


INSTRUMENTATION_SYSTEM_PROMPT_COMPACT = INSTRUMENTATION_SYSTEM_PROMPT + """

Compact mode (to avoid truncation):
- Generate AT MOST 40 events total.
- Prioritize: page_load, primary CTAs, navigation, critical widgets (forms, carousels/lists, banners).
- For secondary or repetitive elements, group them into a single event row with generic names.
- Keep `trigger`, `event_specific_payload`, and `notes` as concise as possible while remaining clear."""


def generate_instrumentation(
    images: list[dict],
    detected_components: list[dict],
    qa_answers: dict,
    dynamic_questions: list[dict],
    page_name: str,
    prd_text: str | None = None,
    regen_comment: str | None = None,
) -> list[dict]:
    client = _get_client()

    qa_summary_lines: list[str] = []
    for q in dynamic_questions:
        qid = q.get("question_id")
        answer = qa_answers.get(qid, "Not answered")
        qa_summary_lines.append(f"Q: {q.get('question','')}\nA: {answer}")
    qa_summary = "\n\n".join(qa_summary_lines)

    allowed_events = get_allowed_event_names()
    schema_summary = get_compact_schema_summary()

    user_content = _build_image_content(images)
    meta_text = (
        f"Page name: {page_name}\n\n"
        f"Detected components:\n{json.dumps(detected_components, indent=2)}\n\n"
        f"Q&A Answers:\n{qa_summary}\n\n"
        "You must only generate events with `name` in this list: "
        + ", ".join(allowed_events)
        + "\n\nHere is the allowed attribute schema per event "
        "(do not invent new top-level attributes):\n"
        + schema_summary
        + "\n\nGenerate the complete instrumentation specification as a JSON array "
        "following all rules."
    )
    if prd_text:
        snippet = prd_text[:8000]
        meta_text += (
            "\n\nPRD context (may be truncated, use only as reference):\n" + snippet
        )
    if regen_comment:
        meta_text += (
            "\n\nUser feedback on the previous instrumentation draft "
            "(use this to revise the events accordingly):\n"
            + regen_comment
        )
    user_content.append({"type": "text", "text": meta_text})

    def _call(system_prompt: str, max_tokens: int) -> str:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            temperature=0.2,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        return msg.content[0].text if msg.content else ""

    # First attempt: generous token budget
    raw = _call(INSTRUMENTATION_SYSTEM_PROMPT, max_tokens=8192)
    _maybe_store_last_raw(raw)
    try:
        rows = _parse_json_response(raw)
        return _post_process_events(rows)
    except Exception:
        # Auto-retry with compact mode if output looks truncated/imbalanced
        if _looks_truncated(raw):
            raw2 = _call(INSTRUMENTATION_SYSTEM_PROMPT_COMPACT, max_tokens=4096)
            _maybe_store_last_raw(raw2)
            rows2 = _parse_json_response(raw2)
            return _post_process_events(rows2)
        raise


def _post_process_events(rows: list[dict]) -> list[dict]:
    """
    Filter events to allowed names and enforce attribute constraints.
    Any attribute not present in the CSV-derived schema is moved into
    event_props_json so that no new top-level attributes are introduced.
    """
    allowed_events = set(get_allowed_event_names())
    processed: list[dict] = []

    for row in rows:
        name = row.get("name")
        if allowed_events and name not in allowed_events:
            # Drop events not in config
            continue

        event_name = name or ""
        allowed_attrs = get_allowed_attributes(event_name)
        payload = (row.get("event_specific_payload") or "").strip()

        if not payload:
            processed.append(row)
            continue

        lines = [ln for ln in payload.splitlines() if ln.strip()]
        allowed_lines: list[str] = []
        extra_pairs: list[tuple[str, str]] = []

        for ln in lines:
            if ":" not in ln:
                allowed_lines.append(ln)
                continue
            key, val = ln.split(":", 1)
            k = key.strip()
            v = val.strip()
            if k in allowed_attrs:
                allowed_lines.append(f"{k}: {v}")
            else:
                extra_pairs.append((k, v))

        # Build final payload:
        # - Only allowed attributes stay as top-level lines.
        # - All non-schema attributes are moved into event_props_json.
        final_lines: list[str] = []
        if allowed_lines:
            final_lines.extend(allowed_lines)

        if extra_pairs:
            extra_dict = {k: v for k, v in extra_pairs}
            final_lines.append(f"event_props_json: {json.dumps(extra_dict)}")

        row["event_specific_payload"] = "\n".join(final_lines)

        processed.append(row)

    return processed


def _maybe_store_last_raw(raw: str) -> None:
    """
    Best-effort: store the last model output in Streamlit session_state if available.
    This avoids importing streamlit at module import time.
    """
    try:
        import streamlit as st  # local import

        st.session_state["last_model_raw"] = raw
    except Exception:
        # Not running in Streamlit context (e.g. unit tests / CLI)
        pass

