#!/usr/bin/env python3
"""
No question mode — screenshot(s) → instrumentation JSON without Q&A.

Run from the instrumentation-automation-tool directory:

  python no_question_mode.py screen1.png --page-name p_home -o events.json

Import from another tool or training script:

  from no_question_mode import run_no_question_mode
  rows = run_no_question_mode(["screen1.png"], page_name="p_home")
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.claude_client import analyze_screenshots, generate_instrumentation
from utils.image_utils import load_image_dict_from_path


def run_no_question_mode(
    image_paths: list[str | Path],
    *,
    flow_description: str = "",
    changes_description: str = "",
    page_type: str = "New page / feature",
    page_name: str = "",
    prd_text: str | None = None,
    skip_component_analysis: bool = False,
) -> list[dict]:
    """
    Load images from disk, optionally run screenshot analysis, then generate
    instrumentation without Q&A (same model path as the Streamlit checkbox).
    """
    images = []
    for p in image_paths:
        path = Path(p)
        images.append(load_image_dict_from_path(path, label=path.stem))

    if skip_component_analysis:
        components: list[dict] = []
    else:
        components = analyze_screenshots(
            images,
            flow_description or "(No flow description provided)",
            changes_description,
            page_type,
            prd_text=prd_text,
        )

    return generate_instrumentation(
        images=images,
        detected_components=components,
        qa_answers={},
        dynamic_questions=[],
        page_name=page_name,
        prd_text=prd_text,
        no_question_mode=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "No question mode: generate instrumentation JSON from screenshot files without Q&A."
        )
    )
    parser.add_argument(
        "images",
        nargs="+",
        help="One or more screenshot image paths (png, jpg, webp)",
    )
    parser.add_argument("--page-name", default="", help="Page name (snake_case)")
    parser.add_argument(
        "--flow",
        default="",
        help="User flow description (recommended unless --skip-component-analysis)",
    )
    parser.add_argument(
        "--changes",
        default="",
        help="Description of what is new or changed in the design",
    )
    parser.add_argument(
        "--page-type",
        default="New page / feature",
        help="New page / feature | Modification to existing page | Mix of both",
    )
    parser.add_argument(
        "--prd",
        type=Path,
        help="Optional path to a PRD text file (truncated for model context)",
    )
    parser.add_argument(
        "--skip-component-analysis",
        action="store_true",
        help=(
            "Skip the component-detection API call; infer events purely from images "
            "(one fewer model call; use when you only care about image→events)."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write JSON array to this file (default: print to stdout)",
    )
    args = parser.parse_args()

    prd_text = None
    if args.prd:
        raw = args.prd.read_text(encoding="utf-8", errors="ignore")
        prd_text = raw[:20000]

    for img_path in args.images:
        if not Path(img_path).is_file():
            print(f"Error: file not found: {img_path}", file=sys.stderr)
            sys.exit(1)

    rows = run_no_question_mode(
        args.images,
        flow_description=args.flow,
        changes_description=args.changes,
        page_type=args.page_type,
        page_name=args.page_name,
        prd_text=prd_text,
        skip_component_analysis=args.skip_component_analysis,
    )

    out = json.dumps(rows, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(out, encoding="utf-8")
        print(f"Wrote {len(rows)} rows to {args.output}", file=sys.stderr)
    else:
        print(out)


if __name__ == "__main__":
    main()
