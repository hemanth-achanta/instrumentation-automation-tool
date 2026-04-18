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

from utils.prompts import (
    ANALYZE_SYSTEM_PROMPT,
    QUESTIONS_SYSTEM_PROMPT,
    INSTRUMENTATION_SYSTEM_PROMPT,
)

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
