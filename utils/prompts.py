"""Load LLM system prompts from ``config/prompts/*.txt``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "config" / "prompts"


def _load_file(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.txt"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _all_prompts() -> dict[str, str]:
    analyze = _load_file("analyze")
    questions = _load_file("questions")
    instrumentation = _load_file("instrumentation")
    instrumentation_nq = _load_file("instrumentation_no_question")
    return {
        "ANALYZE_SYSTEM_PROMPT": analyze,
        "ANALYZE_SYSTEM_PROMPT_COMPACT": analyze
        + "\n\n"
        + _load_file("analyze_compact_suffix"),
        "QUESTIONS_SYSTEM_PROMPT": questions,
        "INSTRUMENTATION_SYSTEM_PROMPT": instrumentation,
        "INSTRUMENTATION_SYSTEM_PROMPT_COMPACT": instrumentation
        + "\n\n"
        + _load_file("instrumentation_compact_suffix"),
        "INSTRUMENTATION_SYSTEM_PROMPT_NO_QUESTION": instrumentation_nq,
        "INSTRUMENTATION_SYSTEM_PROMPT_NO_QUESTION_COMPACT": instrumentation_nq
        + "\n\n"
        + _load_file("instrumentation_no_question_compact_suffix"),
    }


def reload_prompts() -> None:
    """Clear the prompt cache (e.g. after editing files at runtime)."""
    _all_prompts.cache_clear()


_p = _all_prompts()
ANALYZE_SYSTEM_PROMPT = _p["ANALYZE_SYSTEM_PROMPT"]
ANALYZE_SYSTEM_PROMPT_COMPACT = _p["ANALYZE_SYSTEM_PROMPT_COMPACT"]
QUESTIONS_SYSTEM_PROMPT = _p["QUESTIONS_SYSTEM_PROMPT"]
INSTRUMENTATION_SYSTEM_PROMPT = _p["INSTRUMENTATION_SYSTEM_PROMPT"]
INSTRUMENTATION_SYSTEM_PROMPT_COMPACT = _p["INSTRUMENTATION_SYSTEM_PROMPT_COMPACT"]
INSTRUMENTATION_SYSTEM_PROMPT_NO_QUESTION = _p["INSTRUMENTATION_SYSTEM_PROMPT_NO_QUESTION"]
INSTRUMENTATION_SYSTEM_PROMPT_NO_QUESTION_COMPACT = _p[
    "INSTRUMENTATION_SYSTEM_PROMPT_NO_QUESTION_COMPACT"
]
