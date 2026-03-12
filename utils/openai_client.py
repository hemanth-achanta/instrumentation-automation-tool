"""
OpenAI GPT-4o API client for all vision + text calls.
Replaces the original Claude client with OpenAI equivalents.
"""
import json
import os
import re
from typing import Any

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

MODEL = "gpt-4o"


def _get_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set. Please add it to .env")
    return OpenAI(api_key=api_key)


def _parse_json_response(text: str) -> Any:
    """Safely parse JSON from the model's response, handling markdown fences."""
    # Strip markdown code fences if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (```json or ```)
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        # Remove closing fence
        cleaned = re.sub(r"\n?```$", "", cleaned)
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to extract a JSON array from the text
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


def _build_image_content(images: list[dict]) -> list[dict]:
    """
    Build OpenAI vision content blocks from a list of image dicts.
    Each dict has keys: filename, base64, label, media_type.
    """
    content: list[dict] = []
    for img in images:
        label = img.get("label", img.get("filename", "Screenshot"))
        content.append({"type": "text", "text": f"--- Screenshot: {label} ---"})
        media_type = img.get("media_type", "image/png")
        b64 = img["base64"]
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{media_type};base64,{b64}",
                "detail": "high",
            },
        })
    return content


# ---------- API call 1: Analyze screenshots ----------

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
}"""


def analyze_screenshots(
    images: list[dict],
    flow_description: str,
    changes_description: str,
    page_type: str,
) -> list[dict]:
    """Send screenshots + context to GPT-4o and get detected components."""
    client = _get_client()

    user_content = _build_image_content(images)
    user_content.append({
        "type": "text",
        "text": (
            f"Flow description: {flow_description}\n\n"
            f"New/changed elements: {changes_description}\n\n"
            f"Page type: {page_type}"
        ),
    })

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": ANALYZE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        max_tokens=4096,
        temperature=0.2,
    )

    raw = response.choices[0].message.content
    return _parse_json_response(raw)


# ---------- API call 2: Generate Q&A questions ----------

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
]"""


def generate_questions(detected_components: list[dict]) -> list[dict]:
    """Generate contextual Q&A questions based on detected components."""
    client = _get_client()

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": QUESTIONS_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Here are the detected UI components from the Figma screenshots:\n\n"
                    + json.dumps(detected_components, indent=2)
                    + "\n\nGenerate targeted questions to clarify instrumentation needs."
                ),
            },
        ],
        max_tokens=4096,
        temperature=0.3,
    )

    raw = response.choices[0].message.content
    questions = _parse_json_response(raw)

    # Ensure required questions are present
    component_names = [c["component_name"] for c in detected_components]
    _ensure_required_questions(questions, component_names)

    return questions


def _ensure_required_questions(questions: list[dict], component_names: list[str]):
    """Append mandatory questions if not already generated."""
    existing_ids = {q["question_id"] for q in questions}

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


# ---------- API call 3: Generate instrumentation events ----------

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

Return a JSON array of these event objects. No prose, just JSON."""


def generate_instrumentation(
    images: list[dict],
    detected_components: list[dict],
    qa_answers: dict,
    dynamic_questions: list[dict],
    page_name: str,
) -> list[dict]:
    """Generate the full instrumentation event specification."""
    client = _get_client()

    # Build Q&A summary
    qa_summary_lines = []
    for q in dynamic_questions:
        qid = q["question_id"]
        answer = qa_answers.get(qid, "Not answered")
        qa_summary_lines.append(f"Q: {q['question']}\nA: {answer}")
    qa_summary = "\n\n".join(qa_summary_lines)

    user_content = _build_image_content(images)
    user_content.append({
        "type": "text",
        "text": (
            f"Page name: {page_name}\n\n"
            f"Detected components:\n{json.dumps(detected_components, indent=2)}\n\n"
            f"Q&A Answers:\n{qa_summary}\n\n"
            "Generate the complete instrumentation specification as a JSON array."
        ),
    })

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": INSTRUMENTATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        max_tokens=8192,
        temperature=0.2,
    )

    raw = response.choices[0].message.content
    return _parse_json_response(raw)
