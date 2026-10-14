# Benchmarks and decisions

Results from the bench Pi 5 are added here as they are measured (voice and embeddings in
IIT-24, detector in IIT-33, soak in IIT-51). This file starts with the speech-to-text model
decision, which was measured on a development laptop.

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
