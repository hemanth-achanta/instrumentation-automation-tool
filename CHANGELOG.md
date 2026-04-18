# Changelog

## 2026-04-18 - Changes from `641d081` to `746a4f2`

This log captures the major updates introduced in the latest workflow revision.

### Added
- Prompt template files under `config/prompts/` for analysis, instrumentation, and question handling.
- `no_question_mode.py` for no-question execution flow.
- `utils/prompts.py` for centralized prompt loading and management.

### Updated
- `app.py` to integrate new prompt and execution flow wiring.
- `steps/step1_upload.py`, `steps/step2_analysis.py`, and `steps/step3_review.py` for revised staged processing behavior.
- `utils/claude_client.py`, `utils/openai_client.py`, and `utils/image_utils.py` to align model calls and helper behavior with new prompting paths.

### Notes
- Several generated `__pycache__` files also changed during local execution.
- Functional impact is centered on introducing configurable prompts and a no-question operating mode.
