# IIT Visitor Kiosk

Visitor kiosk for IIT: an animated assistant that greets people and answers questions
from an on-device knowledge base. Requirements: `docs/baseline-spec.md`.
Build design: `docs/superpowers/specs/2026-10-14-mvp-build-design.md`.

## Run on a laptop

```bash
uv sync
uv run python -m core --dev
```

Open http://localhost:8765/ in Chromium with the window at 1080 x 1920
(DevTools device toolbar works). Press `D` to toggle the dev panel.

First time only:

```bash
uv run python -m models.download          # Piper voice
echo "LLM_API_KEY=your-key" > .data/.env   # never commit this file
uv run python -m core.rag.ingest add-file path/to/content.pdf --title "Programmes"
```

Without a key or voice, `--dev` falls back to canned answers and placeholder audio.

## Test

```bash
uv run pytest
uv run ruff check .
```

## Kiosk operations

Setup, deploy, rollback, spare SD card, venue checklist: `docs/runbook.md`.
