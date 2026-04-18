# Instrumentation Automation Tool

Automation utility for multi-step instrumentation analysis and review workflows.

## What is included
- Main app entrypoint in `app.py`.
- Step-wise processing under `steps/`.
- Prompt and configuration templates under `config/prompts/`.
- Shared helpers and model clients under `utils/`.
- No-question execution path in `no_question_mode.py`.

## Change tracking
- Version-to-version change notes are maintained in `CHANGELOG.md`.
- Latest recorded update: `641d081` -> `746a4f2`.

## Requirements
- Python 3.12+
- Dependencies listed in `requirements.txt`

## Quick start
1. Create and activate a virtual environment.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Set required environment variables in `.env`.
4. Run the application entrypoint as needed for your workflow.
