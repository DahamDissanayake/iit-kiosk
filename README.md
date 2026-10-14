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

## Test

```bash
uv run pytest
uv run ruff check .
```
