"""
Anthropic Claude client for all vision + text calls.

This implementation prefers reading the Anthropic API key from environment:
- `ANTHROPIC_API_KEY` (typically loaded from `instrumentation_tool/.env`)

If not present, it falls back to the repo-level `api_key` file:
- `.../Instrumentation/api_key`
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from anthropic import Anthropic
from dotenv import load_dotenv
from json_repair import repair_json
from utils.events_config import (
    get_allowed_event_names,
    get_compact_schema_summary,
)
from utils.instrumentation_post import post_process_instrumentation_rows
from utils.prompts import (
    ANALYZE_SYSTEM_PROMPT,
    ANALYZE_SYSTEM_PROMPT_COMPACT,
    QUESTIONS_SYSTEM_PROMPT,
    INSTRUMENTATION_SYSTEM_PROMPT,
    INSTRUMENTATION_SYSTEM_PROMPT_COMPACT,
    INSTRUMENTATION_SYSTEM_PROMPT_NO_QUESTION,
    INSTRUMENTATION_SYSTEM_PROMPT_NO_QUESTION_COMPACT,
)


MODEL = "claude-sonnet-4-6"
# Optional: set to a smaller/faster model for JSON repair-only calls (same key).
REPAIR_MODEL = os.getenv("ANTHROPIC_REPAIR_MODEL", MODEL)
_MAX_JSON_REPAIR_CHARS = 200_000

_JSON_REPAIR_SYSTEM = """You fix malformed model outputs so they become valid JSON (RFC 8259).
Rules:
- Output ONLY a single JSON value (usually a JSON array). No markdown fences, no commentary, no keys outside the data.
- Use double quotes for all keys and string values. Use true/false/null, not Python tokens.
- Remove trailing commas; do not include comments.
- If the input is too corrupted to recover meaningfully, output [] (empty array)."""

_INSTRUMENTATION_REPAIR_HINT = (
    "a JSON array of event specification objects. Each object uses string keys: "
    "story, name, trigger, event_specific_payload, common_payload, event_status, "
    "aat_priority, notes, metrics."
)
_ANALYZE_REPAIR_HINT = (
    "a JSON array of component objects with string keys including: screen_label, "
    "component_name, suggested_story_key, component_type, suggested_element_unique_name, "
    "likely_new, suggested_events, notes."
)
_QUESTIONS_REPAIR_HINT = (
    "a JSON array of question objects with string keys: question_id, question, type, "
    "options, component_ref, why."
)

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


def _llm_repair_json_text(
    client: Anthropic,
    broken_text: str,
    parse_error: str,
    expected_shape: str,
) -> str:
    """
    Second-stage recovery when heuristics + json_repair cannot parse model output.
    Uses a cheap follow-up call that only fixes syntax (no vision).
    """
    snippet = broken_text
    if len(snippet) > _MAX_JSON_REPAIR_CHARS:
        snippet = (
            snippet[: _MAX_JSON_REPAIR_CHARS]
            + "\n\n[... truncated for repair request; output must still be complete valid JSON ...]"
        )
    user_msg = (
        f"The text below was supposed to be {expected_shape}\n\n"
        f"Python json.loads error:\n{parse_error}\n\n"
        "Fix the text into strictly valid JSON. Output nothing else.\n\n"
        "---\n"
        f"{snippet}\n"
        "---"
    )
    msg = client.messages.create(
        model=REPAIR_MODEL,
        max_tokens=8192,
        temperature=0,
        system=_JSON_REPAIR_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    return msg.content[0].text if msg.content else "[]"


def _parse_json_with_llm_repair(
    client: Anthropic,
    broken_text: str,
    parse_error: Exception,
    expected_shape: str,
) -> Any:
    logger.warning("JSON parse failed; attempting LLM repair: %s", parse_error)
    repaired = _llm_repair_json_text(client, broken_text, str(parse_error), expected_shape)
    _maybe_store_last_raw(repaired)
    try:
        return _parse_json_response(repaired)
    except Exception as second_err:
        raise RuntimeError(
            "Could not parse model output as JSON, even after an automatic repair pass. "
            "Check logs and `last_model_raw` for the last response. "
            f"Repair-stage error: {second_err}"
        ) from second_err


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
    except Exception as e:
        # If we likely got truncated / unbalanced output, retry with compact prompt.
        if _looks_truncated(raw):
            raw2 = _call(ANALYZE_SYSTEM_PROMPT_COMPACT, max_tokens=4096)
            _maybe_store_last_raw(raw2)
            try:
                return _parse_json_response(raw2)
            except Exception as e2:
                return _parse_json_with_llm_repair(
                    client, raw2, e2, _ANALYZE_REPAIR_HINT
                )
        return _parse_json_with_llm_repair(client, raw, e, _ANALYZE_REPAIR_HINT)


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
    try:
        questions = _parse_json_response(raw)
    except Exception as e:
        questions = _parse_json_with_llm_repair(
            client, raw, e, _QUESTIONS_REPAIR_HINT
        )

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


def generate_instrumentation(
    images: list[dict],
    detected_components: list[dict],
    qa_answers: dict,
    dynamic_questions: list[dict],
    page_name: str,
    prd_text: str | None = None,
    regen_comment: str | None = None,
    no_question_mode: bool = False,
) -> list[dict]:
    client = _get_client()

    if no_question_mode:
        qa_summary = (
            "(No interactive Q&A. Infer all instrumentation decisions from screenshots "
            "and the detected-components list.)"
        )
    else:
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
    if no_question_mode and not detected_components:
        meta_text += (
            "\n\nNote: No separate component-detection step was run; the list above may be empty. "
            "Derive all events directly from the screenshots."
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

    primary_prompt = (
        INSTRUMENTATION_SYSTEM_PROMPT_NO_QUESTION
        if no_question_mode
        else INSTRUMENTATION_SYSTEM_PROMPT
    )
    compact_prompt = (
        INSTRUMENTATION_SYSTEM_PROMPT_NO_QUESTION_COMPACT
        if no_question_mode
        else INSTRUMENTATION_SYSTEM_PROMPT_COMPACT
    )

    # First attempt: generous token budget
    raw = _call(primary_prompt, max_tokens=8192)
    _maybe_store_last_raw(raw)
    try:
        rows = _parse_json_response(raw)
    except Exception as e:
        # Auto-retry with compact mode if output looks truncated/imbalanced
        if _looks_truncated(raw):
            raw2 = _call(compact_prompt, max_tokens=4096)
            _maybe_store_last_raw(raw2)
            try:
                rows = _parse_json_response(raw2)
            except Exception as e2:
                rows = _parse_json_with_llm_repair(
                    client, raw2, e2, _INSTRUMENTATION_REPAIR_HINT
                )
        else:
            rows = _parse_json_with_llm_repair(
                client, raw, e, _INSTRUMENTATION_REPAIR_HINT
            )
    return post_process_instrumentation_rows(rows)


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

