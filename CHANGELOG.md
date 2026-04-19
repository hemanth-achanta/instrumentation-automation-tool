# Changelog

## 2026-04-19 — 0-indexed ranks in prompts and page-based export filename

### Updated
- **Prompts** (`config/prompts/instrumentation*.txt`, `analyze*.txt`, `questions.txt`): Document that **`item_rank`**, **`widget_vertical_rank`**, and similar rank fields are **0-indexed** (first visible item = 0, not 1).
- **`utils/excel_generator.py`**: Add **`sanitize_page_basename()`** for safe workbook/sheet metadata and filenames (strip invalid path/sheet characters; if the page name is empty/whitespace, use a timestamped `instrumentation_YYYYMMDD_HHMMSS` base so consecutive exports do not overwrite).
- **`steps/step4_download.py`**: Download file is **`{page_name}.xlsx`** (sanitized routing/page label from Step 1), not `{page_name}_instrumentation.xlsx`.

---

## 2026-04-19 — Active-only attributes from `events_schema.csv`

### Updated
- `utils/events_config.py`: Allowed attributes for events listed in `resources/events_config.json` are now taken only from CSV rows where the **property-level** `Status` column is `Active` (the export has separate event-level and property-level `Status` columns; filtering uses the one after `Property name`). Discarded or inactive properties are excluded. NUL bytes embedded in some lines of `events_schema.csv` are stripped during read so the file parses reliably.

---

## 2026-04-19 — `page_load_id` enforcement and shared instrumentation post-processing

### Added
- `utils/instrumentation_post.py`: central `post_process_instrumentation_rows` (moved from `claude_client`), plus `ensure_page_load_ids` so `page_load_id` appears only on `page_load` rows and is injected or stripped as needed.

### Updated
- `config/prompts/instrumentation.txt` and `config/prompts/instrumentation_no_question.txt`: clarify that `page_load_id` is required only on `page_load` events, never on `element_clicked`, `i_element_viewed`, etc.
- `utils/events_config.py`: always allow `page_load_id` as an attribute for `page_load` (even if absent from CSV-derived schema).
- `utils/claude_client.py` and `utils/openai_client.py`: route instrumentation output through `post_process_instrumentation_rows`; OpenAI path also guards against non-list JSON.
- `steps/step3_review.py` and `steps/step4_download.py`: run `ensure_page_load_ids` when syncing the editor and before download so manual edits stay valid.

---

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
