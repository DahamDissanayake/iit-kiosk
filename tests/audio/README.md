Test clips for the speech-to-text test and the replay benchmark. 16 kHz, mono, 16-bit WAV.

The clips here are **synthetic**: generated with the local Piper voice by
`uv run python -m tools.make_test_clips` (needs `python -m models.download` first), so no
microphone or recording is needed. Add more with `NAME "text"` pairs, for example
`uv run python -m tools.make_test_clips q01 "Where is the campus?"`.

Never add recordings of visitors. Real human voices recorded by the team are welcome for the
replay test, but keep them out of the repo if they identify a person.
