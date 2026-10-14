# IIT Visitor Kiosk: MVP Build Design

- **Date:** 14 Oct 2026
- **Requirements:** [`docs/baseline-spec.md`](../../baseline-spec.md) (the single source of truth for behaviour, interfaces, data model, config, BOM and acceptance tests)
- **UI reference:** [`docs/kiosk-bot.html`](../../kiosk-bot.html) (prototype; its engine is kept, its visuals are replaced)
- **Target:** MVP running on site on 21 Oct 2026, code freeze evening of 20 Oct

This document records how the MVP is built: what the baseline spec leaves open, the decisions made during design, and the changes to the baseline spec. Where this document and the baseline spec disagree, this document wins for the items listed in section 2; raise anything else.

---

## 1. Intent

Deliver an English-only kiosk that greets approaching visitors, answers spoken questions about IIT and LeapGen from an on-Pi knowledge base, and lets staff manage content and settings through a PIN-protected dashboard. Success is all MVP acceptance tests in baseline section 16 passing at the venue on 21 Oct.

Constraints carried from the baseline: Raspberry Pi 5 8 GB, no PyTorch on the Pi, nothing recorded or stored, offline touch-menu fallback, no Docker, 6 build days, Sinhala and Tamil deferred to later phases.

---

## 2. Changes to the baseline spec

| Baseline section | Change |
| --- | --- |
| 10. Repository layout | Spec lives at `docs/baseline-spec.md`, not `SPEC.md`. UI is `ui/index.html` + `ui/styles.css` + `ui/js/*.js` (ES modules, no build step) instead of one file. |
| 12. Git flow | `task/<KEY>-<slug>` or `issue/<KEY>-<slug>` branches off `dev`, merged to `dev` by pull request; `dev` merged to `main` at release points (see `CLAUDE.md`). Release tags are cut from `main`. |
| 8. Data model | `sources.kind` gains `menu`: the pre-written touch-menu answers, editable in the dashboard. |
| 4.3 Voice | Conversation memory: last 3 Q&A pairs of the current session go to the LLM (section 5). |
| 7.1 WebSocket | Adds `stt` (Core → UI, `{text, final}`) for live transcript in the bubble, `menu` (Core → UI, `{show, items:[{id,label}]}`) for the touch menu, and `dev` (Core → UI) to enable the dev panel. |

---

## 3. Build approach

**Thin end-to-end slice first, then deepen.** Day one produces the controller, the redesigned UI and the WebSocket link working together on a laptop with faked presence and typed questions. Each later milestone replaces a fake with the real component. If time runs out, polish is dropped, never a whole subsystem.

Voice sits behind an interface so it can run inside kiosk-core or as its own kiosk-voice service. The choice is made on day 3 from CPU measurements on the Pi. kiosk-vision is always a separate process.

---

## 4. Module boundaries

Hardware and cloud services sit behind small interfaces so the same code runs on a laptop and on the Pi.

| Interface | Laptop | Pi |
| --- | --- | --- |
| `PresenceSource` | Fake (dev panel events) or webcam + YOLO | picamera2 + YOLO11n (NCNN, OpenVINO fallback) |
| `SpeechInput` | Typed text (dev panel) or laptop mic + Silero VAD + Moonshine | Speakerphone + Silero VAD + Moonshine |
| `SpeechOutput` | Piper | Piper |
| `LLMProvider` | Gemini / Anthropic / OpenAI adapters; scripted fake for tests | Same |
| `Embedder` | FastEmbed bge-small-en-v1.5 | Same |

The **controller** is pure Python: it receives events (presence, VAD, STT final, UI touch, speech ended, LLM sentence, timer) and returns commands (UI messages, TTS requests, mic mute, vision rate, stats events). Time is injected, so every timing rule is unit-testable with a fake clock.

```
core/
  controller/   state machine and encounter/session rules (pure, no I/O)
  rag/          extract, chunk, embed, retrieve, threshold
  llm/          provider adapters, prompt builder, sentence splitter
  api/          FastAPI app: UI WebSocket, dashboard HTTP API, auth
  store/        SQLite access, migrations, settings, events and stats
  bus.py        ZeroMQ wrapper with an in-process fallback
vision/         camera, detector, tracker -> presence events
voice/          VAD, STT, TTS; runnable in-process or as a service
ui/             character page (vanilla JS, inline SVG, Web Audio)
dashboard/      Vite + React + TypeScript + Tailwind + Recharts, built in CI
models/         download script + checksums
deploy/         systemd units, labwc autostart, setup.sh, deploy.sh
tests/          unit tests, RAG eval, replay assets
config.toml
```

Each unit must be understandable from its interface alone. Files that grow past one clear responsibility get split.

---

## 5. Conversation flow

1. **Presence.** Vision publishes `presence`. The controller applies the approach and dwell rules (baseline 4.2) to move Idle → Attentive → Greeting, or back to Idle for a walk-past, and sends `state` and `lookAt` to the UI.
2. **Greeting.** Controller sends `tts.say` with the greeting (group variant for 2+ people). Piper PCM chunks are forwarded to the UI as `audio` with `afterSpeech: listening`. The mic stays muted until the UI sends `speech.ended`.
3. **Listening.** Mic opens; VAD detects speech start and end; Moonshine streams partials, shown live in the bubble via `stt`, then a final transcript.
4. **Thinking.** Core embeds the question and retrieves the top 4 enabled chunks. Below `rag.min_score`: say "I don't have that information", show the touch menu, record `unmatched`. Otherwise stream from the LLM.
5. **Speaking.** A sentence splitter sends each complete sentence to Piper immediately; the bubble shows reply text as it arrives.
6. **Next.** Back to Listening; to Farewell on bye / no thanks, or zone empty for `depart_empty_s`. After Farewell: full session reset (history, UI, counters) and `greet_cooldown_s` cooldown.

**Conversation memory.** The LLM receives the last 3 Q&A pairs of the current session so follow-ups resolve. Retrieval embeds the current question; when it is under 5 words it is concatenated with the previous question before embedding. History lives in memory only and is cleared on every reset.

**Intent shortcuts.** "bye", "no thanks", "that's all" and similar phrases go to Farewell without an LLM call. Matching is a small keyword list in config.

**Latency target.** First reply audio within about 2 s of end of speech. Every turn records `reply_latency_ms`.

**Dev harness.** With `--dev`, the UI shows a dev panel: fake approach / walk past / leave, type a question, force camera / mic / internet failure, jump to any state. Every acceptance test can be shown on a laptop.

---

## 6. Character UI design

**Stage.** All-white studio backdrop: a soft white floor curving into a back wall with no visible seam (cyclorama), a faint horizon gradient and a soft contact shadow under the bot, so the scene reads as 3D space. Pure CSS and SVG gradients; no WebGL.

**Character.** Inspired by EVE from WALL-E, with its own proportions and details so it is not a copy of the film character:
- Glossy white egg-shaped body and separate floating head, no legs. Gloss from SVG gradients and a specular highlight.
- Gentle float bob replaces "breathing"; the floor shadow scales with height.
- Black glass face visor with soft white-blue glowing eyes. Eyes blink, follow `lookAt`, and change shape for happy (greeting, farewell), thinking (looking up and aside) and listening (slightly wider).
- Mouth: a thin light bar under the eyes that pulses with speech loudness, driven by the existing `AnalyserNode` path. Music never reaches the analyser.
- Floating arms with no visible joint; one waves on greeting and farewell.
- Red accents only: chest badge (logo placeholder), listening ring, active controls and status lights. Black for the visor and text.

**Layout (portrait 1080 x 1920).**
1. Header: IIT and LeapGen logo placeholder slots (`ui/assets/logo-*.svg`, swapped by replacing the files) and the privacy notice.
2. Bot in the upper two thirds; speech bubble beside or above the head.
3. Bottom bar: "Tap to talk" button, Kids toggle, rotating idle ticker (messages and the "Idea → Validate → Build → Launch" journey).
4. Settings gear in a bottom corner; opens the PIN pad after a 3 s press and hold, with a visible fill ring during the hold.
5. Touch menu: a full-width sheet that slides up over the bottom third with large buttons for pre-written answers and a Close button.

**Language.** English only. Sinhala and Tamil chips and fonts are removed. All visible strings live in one `ui/js/strings.js` table keyed by language so Phase 2 adds languages without layout changes.

**Kept from the prototype.** State-driven CSS via `data-state`, the Web Audio graph and PCM streaming, mouth smoothing (fast attack, slow release), blink and gaze easing, music ducking on its own gain path, WebSocket reconnect, `window.kiosk`.

**Motion.** All animation respects `prefers-reduced-motion`. Animations use `transform` and `opacity` only to keep the Pi GPU load low.

---

## 7. Failure handling

| Failure | Behaviour |
| --- | --- |
| LLM error, no internet, or no first sentence within `llm.timeout_s` | Abort the turn, say "I can't reach my answers right now", show the touch menu (answers read by Piper). Connectivity probe every 30 s; voice Q&A resumes automatically. |
| Camera missing or failing | UI shows "Tap to talk"; touch starts an encounter; voice works. Core retries the camera every 10 s. |
| Mic missing or failing | Touch menu becomes the main path. |
| Vision process hung | No `presence` heartbeat for 5 s is treated as a camera failure; systemd watchdog restarts kiosk-vision. |
| UI disconnected | Page reconnects every 2 s; reloads when `version` changes. |
| Any crash | systemd `Restart=always`; restart count shown on the Health page. |

Every failure is recorded in `events` and shown on the Health page.

---

## 8. Testing

- **Controller:** pytest with a fake clock covering every rule in baseline 4.1: one greeting per encounter, no greeting for passers-by, at most one silence follow-up, no interruption by a second visitor, clean reset, cooldown, music ducking commands, half-duplex mic muting.
- **RAG:** chunker tests (size, overlap, headings kept with text, Q&A as one chunk); an eval script over the 20 test questions reporting hit rate and scores, used to tune `rag.min_score`; a check that the embedding model name is stored and that mixing models is refused.
- **LLM:** prompt-builder snapshot tests; sentence-splitter tests on streamed fragments; timeout behaviour with the fake provider.
- **API:** PIN lockout after 5 wrong tries, session idle expiry, source create / disable / delete reflected in retrieval on the next query.
- **UI:** manual checklist through the dev panel in a portrait 1080 x 1920 window.
- **Replay on the bench Pi:** recorded hall noise plus the 20 spoken questions through the full pipeline; reports time to first reply and correct-content match.
- **Soak:** 8 hours of simulated encounters on the Pi in the closed cabinet; CPU temperature stays below 80 °C.
- **CI (GitHub Actions):** pytest, ruff, dashboard build on every push and pull request.

---

## 9. Milestones

Each milestone ends with something that runs.

| # | Milestone | Done when | Target |
| --- | --- | --- | --- |
| M1 | Repo skeleton, redesigned UI, controller | Fake presence drives the bot through every state in a portrait window; controller tests pass | 15 Oct |
| M2 | RAG, LLM adapter, Piper | A typed question gets a spoken answer from the knowledge base; honest refusal when nothing matches | 16 Oct |
| M3 | Real voice | A spoken question works on the laptop; Pi benchmarks done (YOLO NCNN vs OpenVINO, embeddings, CPU) and voice placement decided | 17 Oct |
| M4 | Real vision | Approach, walk-past and departure work with the camera on the Pi | 17 to 18 Oct |
| M5 | Dashboard | PIN, overview stats, knowledge base CRUD, test a question, settings with calibration, health | 18 to 19 Oct |
| M6 | Deploy and hardening | systemd units, boot into kiosk, `deploy.sh` with rollback, 8-hour soak, SD card cloned | 19 to 20 Oct |

**Cut order if time runs short** (none are acceptance tests): unmatched-questions page; busiest-hours chart; live box preview in calibration (number fields instead); keeping voice as a separate service (merge into core).

---

## 10. Open items

These come from IIT / LeapGen and do not block the build; placeholders are used until they arrive (baseline 15.1 and 19).

- LLM provider and model (config only; all three adapters exist).
- Logos and brand colours (placeholder SVGs and colour tokens).
- Approved content and top 20 FAQs (seed knowledge base and RAG eval).
- Music file (config URL).
- Display model and touch support.
- Open or closed source decision (affects YOLO and Piper licences).
- Written confirmation that acceptance test 7 moves to Phase 2.
