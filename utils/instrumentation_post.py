"""
Post-process instrumentation rows from the model: filter allowed event names,
enforce attribute allowlists, and guarantee required payload fields.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from utils.events_config import get_allowed_attributes, get_allowed_event_names


BASE_DIR = Path(__file__).resolve().parents[1]
SCHEMA_CSV_PATH = BASE_DIR / "resources" / "events_schema.csv"


def _has_schema_constraints() -> bool:
    """True when a real schema CSV exists and should constrain payload keys."""
    return SCHEMA_CSV_PATH.exists()


def _payload_declares_page_load_id(payload: str) -> bool:
    """True if page_load_id is set as a top-level key: line or inside event_props_json."""
    payload = (payload or "").strip()
    if not payload:
        return False
    for ln in payload.splitlines():
        s = ln.strip()
        if not s or ":" not in s:
            continue
        key, rest = s.split(":", 1)
        k = key.strip().lower()
        if k == "page_load_id" and rest.strip():
            return True
        if k == "event_props_json":
            try:
                parsed: Any = json.loads(rest.strip())
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and parsed.get("page_load_id") not in (None, ""):
                return True
    return False


def _insert_page_load_id_line(payload: str, example_uuid: str) -> str:
    """Insert a page_load_id template line; prefer after page_name if present."""
    new_line = (
        f"page_load_id: <unique id per qualified page load> (Eg: {example_uuid})"
    )
    if not (payload or "").strip():
        return new_line
    lines = payload.splitlines()
    insert_at = 0
    for i, ln in enumerate(lines):
        if ln.strip().lower().startswith("page_name"):
            insert_at = i + 1
            break
    lines.insert(insert_at, new_line)
    return "\n".join(lines)


def _strip_page_load_id_from_non_page_load_payload(payload: str) -> str:
    """Remove page_load_id from payloads for non-page_load events (model/user mistakes)."""
    if not (payload or "").strip():
        return payload
    new_lines: list[str] = []
    for ln in payload.splitlines():
        s = ln.strip()
        if ":" in s:
            k, rest = s.split(":", 1)
            kl = k.strip().lower()
            if kl == "page_load_id":
                continue
            if kl == "event_props_json":
                try:
                    parsed: Any = json.loads(rest.strip())
                    if isinstance(parsed, dict) and "page_load_id" in parsed:
                        parsed = {a: b for a, b in parsed.items() if a != "page_load_id"}
                    new_lines.append(f"event_props_json: {json.dumps(parsed)}")
                    continue
                except json.JSONDecodeError:
                    pass
            if kl == "additional_cols":
                # additional_cols is an escape hatch; if page_load_id leaked in there, strip it.
                try:
                    parsed: Any = json.loads(rest.strip())
                    if isinstance(parsed, dict) and "page_load_id" in parsed:
                        parsed = {
                            a: b
                            for a, b in parsed.items()
                            if a != "page_load_id"
                        }
                    new_lines.append(f"additional_cols: {json.dumps(parsed)}")
                    continue
                except json.JSONDecodeError:
                    # If it's not parseable, keep it as-is (no destructive changes).
                    pass
        new_lines.append(ln)
    return "\n".join(new_lines)


def _ensure_page_load_id_in_row(row: dict) -> None:
    """Every page_load row must include page_load_id in event_specific_payload."""
    if row.get("name") != "page_load":
        return
    payload = row.get("event_specific_payload") or ""
    if _payload_declares_page_load_id(payload):
        return
    row["event_specific_payload"] = _insert_page_load_id_line(payload, str(uuid.uuid4()))


def ensure_page_load_ids(rows: list[dict]) -> list[dict]:
    """
    Enforce page_load_id scope: required only on page_load rows; strip it elsewhere.
    Use after generation or manual edits.
    """
    for row in rows:
        if row.get("name") == "page_load":
            _ensure_page_load_id_in_row(row)
        else:
            p = row.get("event_specific_payload") or ""
            row["event_specific_payload"] = _strip_page_load_id_from_non_page_load_payload(p)
    return rows


def post_process_instrumentation_rows(rows: list[dict]) -> list[dict]:
    """
    Filter events to allowed names and enforce attribute constraints.
    When a CSV-derived schema exists, unknown attributes are dropped rather than
    rewritten into event_props_json, because the accepted convention is to keep
    payloads flat and avoid event_props_json.
    Ensures every page_load row includes page_load_id; removes it from other event types.
    """
    allowed_events = set(get_allowed_event_names())
    has_schema = _has_schema_constraints()
    processed: list[dict] = []

    for row in rows:
        name = row.get("name")
        if allowed_events and name not in allowed_events:
            continue

        payload = (row.get("event_specific_payload") or "").strip()

        if not payload:
            processed.append(row)
            continue

        if not has_schema:
            row["event_specific_payload"] = _strip_page_load_id_from_non_page_load_payload(
                payload
            )
            processed.append(row)
            continue

        event_name = name or ""
        allowed_attrs = get_allowed_attributes(event_name)

        lines = [ln for ln in payload.splitlines() if ln.strip()]
        allowed_lines: list[str] = []

        for ln in lines:
            if ":" not in ln:
                allowed_lines.append(ln)
                continue
            key, val = ln.split(":", 1)
            k = key.strip()
            v = val.strip()
            if k in allowed_attrs:
                allowed_lines.append(f"{k}: {v}")

        final_lines: list[str] = []
        if allowed_lines:
            final_lines.extend(allowed_lines)

        row["event_specific_payload"] = "\n".join(final_lines)

        processed.append(row)

    ensure_page_load_ids(processed)

    return processed
