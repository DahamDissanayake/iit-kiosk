# Benchmarks and decisions

Measured results and the decisions they drive. Sections:

- [Voice and embeddings on the bench Pi (IIT-24)](#voice-and-embeddings-on-the-bench-pi-iit-24)
- [Speech to text model (IIT-21)](#speech-to-text-model-iit-21)
- Detector on the Pi (IIT-33) and the 8-hour soak (IIT-51) are added by those tasks.

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
