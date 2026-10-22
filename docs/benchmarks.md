# Benchmarks and decisions

Measured results and the decisions they drive. Sections:

- [Voice and embeddings on the bench Pi (IIT-24)](#voice-and-embeddings-on-the-bench-pi-iit-24)
- [Speech to text model (IIT-21)](#speech-to-text-model-iit-21)
- [Detector and live presence checks on the bench Pi (IIT-33)](#detector-and-live-presence-checks-on-the-bench-pi-iit-33)
- The 8-hour soak (IIT-51) is added by that task.

## Voice and embeddings on the bench Pi (IIT-24)

**Status: the tool is built and verified; the Pi numbers and the two decisions are still to be
measured on the bench Pi 5.** The "Laptop" column is a real run on a development machine
(AMD Ryzen 7 7435HS, 8 cores, 16 GB, Windows) so there is a baseline to compare against; it says
nothing about the Pi's speed. Do not copy laptop numbers into the Pi column.

### How to run it (on the Pi, in `/opt/kiosk/current` as the `kiosk` user)

```bash
export KIOSK_MODELS_DIR=/opt/kiosk/models HF_HOME=/opt/kiosk/models/hf
for i in 1 2 3; do uv run python -m tools.bench embed; done
for i in 1 2 3; do uv run python -m tools.bench vad; done
for i in 1 2 3; do uv run python -m tools.bench stt tests/audio/what-courses.wav; done
# system load while a full conversation loop runs (start the kiosk with --dev and the replay tool):
uv run python -m tools.bench system --seconds 600 --every 5 > system.jsonl
```

Each command prints one JSON line per result. Record the **median of the three runs**. To test
Moonshine Voice Small Streaming on the Pi as well, set `[voice] stt_model` accordingly and
repeat the `stt` line (see the model comparison below).

### Results

| Test | Command | Target | Laptop (measured) | Bench Pi 5 |
| --- | --- | --- | --- | --- |
| Embedding model load | `tools.bench embed` | under 10 s | 1.7 s | _to measure_ |
| Embed 50 passages | `tools.bench embed` | under 15 s | 1.4 s | _to measure_ |
| Embed one query | `tools.bench embed` | under 60 ms | 7 ms | _to measure_ |
| VAD per 32 ms frame | `tools.bench vad` | under 3 ms | 0.33 ms (97x real time) | _to measure_ |
| STT, 2.5 s question, `moonshine/base` | `tools.bench stt tests/audio/what-courses.wav` | under 700 ms | 161 ms | _to measure_ |
| STT, same clip, Small Streaming (if tried) | same, other model | under 600 ms | see IIT-21 table | _to measure_ |
| Peak CPU temperature, 10 min conversation loop | `tools.bench system` | under 80 C | n/a | _to measure_ |
| RAM used with all services running | `tools.bench system` | under 3 GB | n/a | _to measure_ |

### Decisions (to be made from the Pi numbers)

Both default to the safe, already-configured choice until measured:

1. **STT model.** Keep `moonshine/base` unless Small Streaming is faster on the Pi and also passes
   `tests/test_stt.py` with the same transcripts. Current setting: `moonshine/base`.
2. **Where voice runs.** Keep `[voice] mode = "inprocess"` unless, with the whole kiosk running,
   either (a) the UI visibly drops animation frames while speech is transcribed, or (b) the
   kiosk-core process uses more than one full CPU core during a conversation. If so set
   `mode = "service"` and enable the `kiosk-voice` unit (see `docs/runbook.md`).
   Current setting: `inprocess`.

Record the outcome here as **Decision: ...** with the numbers that justify it, and change
`config.toml` in the same pull request.

## Detector and live presence checks on the bench Pi (IIT-33)

**Status: the tool is built and verified; the Pi measurements, the live checks and the backend
decision are still to be done on the bench Pi 5 with the camera.** The laptop line below is a
real run (AMD Ryzen 7 7435HS, NCNN, blank synthetic frames, 20 s) kept only as a comparison point.
The OpenVINO export could not be made on that laptop (Windows ran out of paging file loading
OpenVINO), so OpenVINO has no baseline here and must be exported by the `models` workflow first.

### 1. Detector stability (30 minutes each)

```bash
export KIOSK_MODELS_DIR=/opt/kiosk/models
uv run python -m tools.bench_vision --backend ncnn --minutes 30
uv run python -m tools.bench_vision --backend openvino --minutes 30
```

One JSON line each: `median_ms`, `p99_ms`, `max_ms`, `max_fps`, `freezes_over_2s`, `max_temp_c`.
`freezes_over_2s` counts gaps of more than 2 s between frames (the reported NCNN freeze on the
Pi 5); `max_ms` shows a single long stall that `p99_ms` would hide. `--camera synthetic --seconds N`
measures the detector without a camera.

| Backend | Median | p99 | Max | Max fps | Freezes over 2 s | Peak temp |
| --- | --- | --- | --- | --- | --- | --- |
| Laptop, NCNN, synthetic frames (measured) | 41.9 ms | 57.3 ms | 94.2 ms | 23.8 | 0 | n/a |
| Pi 5, NCNN | _to measure_ | _to measure_ | _to measure_ | _to measure_ | _to measure_ | _to measure_ |
| Pi 5, OpenVINO | _to measure_ | _to measure_ | _to measure_ | _to measure_ | _to measure_ | _to measure_ |

**Decision rule:** keep the backend with **zero freezes** and at least **8 fps** at 320 px (that is
a median of 125 ms or better). If both qualify, keep the faster. Set `[vision] backend` in
`config.toml` in the same pull request that records the result.

### 2. Live presence checks (start `python -m vision` and `python -m core --dev`)

| # | Check | Expected | Result |
| --- | --- | --- | --- |
| 1 | Walk straight towards the camera from 3 m | Attentive, then a greeting within about 1.5 s; the eyes follow you (flip `[vision] mirror` if they move the wrong way) | _to check_ |
| 2 | Walk across the frame at 2 m without stopping | No greeting | _to check_ |
| 3 | Stand still about 1 m away for 2 s | A greeting (dwell) | _to check_ |
| 4 | Walk away during the conversation | A silent wave about 3 s after you leave the zone, then Idle | _to check_ |
| 5 | Power off, unplug the camera ribbon, boot | "Tap to talk" within 5 s; touch still works | _to check_ |
| 6 | After the run: `find / -xdev \( -name "*.jpg" -o -name "*.png" -o -name "*.mp4" -o -name "*.h264" \) -newer /tmp/start 2>/dev/null` (run `touch /tmp/start` first) | No output: no image or video files exist | _to check_ |

Then tune `min_box_height_frac`, `approach_growth` and `centre_band` for the bench room (dashboard
Settings shows the live boxes) and record the values here.

## Speech to text model (IIT-21)

**Decision: use `moonshine/base` (Moonshine ONNX) for the MVP. Do not adopt Moonshine Voice
Small Streaming yet.** Re-check on the Pi in IIT-24 before the code freeze.

Both models were run on the same four synthetic English clips (made with Piper, 16 kHz mono)
on a Windows laptop CPU, five runs each after a warm-up. Median time to transcribe a whole
utterance:

| Clip | Audio | `moonshine/base` | Small Streaming (`SMALL_STREAMING`) |
| --- | --- | --- | --- |
| "What courses does IIT offer?" | 1.9 s | 202 ms | 1,172 ms |
| "Hello" | 0.6 s | 70 ms | 471 ms |
| "Where is the campus and how do I apply?" | 2.4 s | 220 ms | 1,606 ms |
| "Tell me about research and startups at LeapGen" | 2.8 s | 254 ms | 1,836 ms |

Accuracy: `moonshine/base` transcribed all four exactly; Small Streaming got three exactly and
heard "LeapGen" as "LeapKit".

Why base for now:
- The kiosk transcribes a whole utterance after the visitor stops speaking, and base is about
  five to six times faster in that mode, which is what the 2 s time-to-first-reply target needs.
- Small Streaming's advantage is incremental output while the person is still speaking. Using
  it that way needs a streaming integration (feeding frames as they arrive), which the
  current pipeline does not do; live partials are produced instead by re-transcribing the
  growing buffer with base every 1.5 s.
- Base has the smaller dependency footprint on the Pi: `useful-moonshine-onnx` needs only
  onnxruntime, tokenizers and librosa.

Caveats:
- The clips are clean synthetic speech, not people in a noisy hall, and the machine is a laptop
  rather than the Pi 5, so only the ratio between the two models is meaningful. Accuracy on
  real voices and in noise is checked with the replay tool (IIT-25).
- Small Streaming was timed through `transcribe_without_streaming`; a true streaming
  integration could shorten the delay after speech ends. Revisit if base proves too slow or
  inaccurate on the Pi.

Packages evaluated: `useful-moonshine-onnx` 20251121 (project dependency) and
`moonshine-voice` 0.1.5 (evaluated in a throwaway environment, not added to the project).
