"""
Load allowed events from a small JSON config and derive allowed attributes
for those events directly from `resources/events_schema.csv`.

Only attributes whose property-level Status is Active are included (the CSV has
two Status columns: event-level and property-level; we use the one aligned with
Property name).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set

# Attributes always allowed for specific events (even if missing from CSV schema rows).
_EXTRA_ALLOWED_ATTRS: Dict[str, Set[str]] = {
    "page_load": {"page_load_id"},
}


BASE_DIR = Path(__file__).resolve().parents[1]
RESOURCES_DIR = BASE_DIR / "resources"
CONFIG_PATH = RESOURCES_DIR / "events_config.json"
SCHEMA_CSV_PATH = RESOURCES_DIR / "events_schema.csv"


@dataclass(frozen=True)
class EventSchema:
    name: str
    attributes: Set[str]


_allowed_events: List[str] = []
_event_schemas: Dict[str, EventSchema] = {}


def _load_config() -> List[str]:
    if not CONFIG_PATH.exists():
        # Default: allow a small standard set
        return ["property_load", "element_clicked", "i_element_viewed", "page_load"]
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    events = data.get("allowed_events", [])
    return [e for e in events if isinstance(e, str)]


def _property_status_column_index(header: List[str]) -> int | None:
    """
    CSV has two columns named 'Status' (event vs property). Return the index of
    the property Status column (the one after 'Property name').
    """
    try:
        prop_name_idx = header.index("Property name")
    except ValueError:
        return None
    for i in range(prop_name_idx + 1, len(header)):
        if header[i].strip() == "Status":
            return i
    return None


def _load_schema_for_allowed_events() -> Dict[str, EventSchema]:
    """
    Read the large CSV once and derive allowed attributes for each allowed event.

    We assume:
    - Column 0: Event name (or header 'Event name')
    - Column 'Property name' contains the attribute name
    - Property-level 'Status' must be Active for the attribute to be allowed
    """
    schemas: Dict[str, Set[str]] = {e: set() for e in _allowed_events}

    if not SCHEMA_CSV_PATH.exists():
        return {name: EventSchema(name=name, attributes=set()) for name in _allowed_events}

    def _iter_rows_without_nul():
        with SCHEMA_CSV_PATH.open("r", encoding="utf-8", newline="") as f:
            for line in f:
                yield line.replace("\x00", "")

    reader = csv.reader(_iter_rows_without_nul())
    header = next(reader, None)
    if not header:
        return {name: EventSchema(name=name, attributes=set()) for name in _allowed_events}

    # Find indices we care about
    try:
        event_idx = header.index("Event name")
    except ValueError:
        event_idx = 0

    try:
        prop_idx = header.index("Property name")
    except ValueError:
        prop_idx = None

    prop_status_idx = _property_status_column_index(header)

    for row in reader:
        if len(row) <= event_idx:
            continue
        event_name = row[event_idx].strip()
        if event_name not in schemas:
            continue
        if prop_idx is None or len(row) <= prop_idx:
            continue
        prop_name = row[prop_idx].strip()
        if not prop_name:
            continue
        if prop_status_idx is not None:
            if len(row) <= prop_status_idx:
                continue
            status = row[prop_status_idx].strip().casefold()
            if status != "active":
                continue
        schemas[event_name].add(prop_name)

    return {name: EventSchema(name=name, attributes=attrs) for name, attrs in schemas.items()}


def _init():
    global _allowed_events, _event_schemas
    if _allowed_events:
        return
    _allowed_events = _load_config()
    _event_schemas = _load_schema_for_allowed_events()


def get_allowed_event_names() -> List[str]:
    """Return the list of allowed event names from config."""
    _init()
    return list(_allowed_events)


def get_allowed_attributes(event_name: str) -> Set[str]:
    """Return the set of allowed attribute names for a given event name."""
    _init()
    schema = _event_schemas.get(event_name)
    base = set(schema.attributes) if schema else set()
    return base | _EXTRA_ALLOWED_ATTRS.get(event_name, set())


def get_compact_schema_summary() -> str:
    """
    Return a compact, low-token summary of allowed events and their attributes,
    suitable for feeding into Claude prompts.
    """
    _init()
    lines: List[str] = []
    for name in _allowed_events:
        attrs = sorted(_event_schemas.get(name, EventSchema(name, set())).attributes)
        if not attrs:
            lines.append(f"{name}: (no predefined attributes; use event_props_json if needed)")
        else:
            joined = ", ".join(attrs)
            lines.append(f"{name}: {joined}")
    return "\n".join(lines)

