# Fish Audio cloud integration audit

This integration calls the hosted REST API, like the existing MiniMax backend.
It does not load Fish Speech weights or install the model library locally.
The skill's local-model CPU, CUDA, HuggingFace cache, and model-source cloning
steps do not apply to this HTTP adapter.

- Reuses `httpx`, `numpy`, and `soundfile`, already direct dependencies.
- No SDK, git-only dependency, new native library, model data, or monkey patch.
- HTTP imports are lazy; add `backend.backends.fish_backend` to PyInstaller.
- `httpx` TLS roots and SoundFile's libsndfile are already part of the app stack.
- Output is PCM16 mono at 44,100 Hz, decoded to numpy float32.
- Private voice models are uploaded once and their IDs retained in SQLite;
  the registry key includes an account fingerprint and the reference content.
- Explicit meditation pauses are inserted locally as silence, never sent as
  spoken words. Direction uses S2 square-bracket cues; MiniMax uses its own
  emotion field and speech-2.8 interjections.
- Keys stay server-side. Settings responses expose only configured state.

Official references consulted on 2026-10-11:

- https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech
- https://docs.fish.audio/api-reference/endpoint/model/create-model
- https://docs.fish.audio/developer-guide/core-features/emotions
- https://platform.minimax.io/docs/api-reference/speech-t2a-http

Live account check: Fish authentication works; no account-owned voices exist.
Accent and naturalness require listening to a real generated sample. Source
verification is not a claim that a native desktop distribution was built.

Verification performed:

- 37 focused backend contract/regression tests passed, including PCM decoding, durable
  private voice registration, account isolation, secret redaction, settings,
  invalid pauses before paid requests, exact silence and existing MCP behavior.
- TypeScript checking and production web build passed.
- Browser inspection: profile and completed library audio visible; loading the
  podcast script sets Spanish, fluent (MiniMax) and 1.06 speed; switching Fish/MiniMax converts
  an unedited template to the appropriate provider syntax.
- PyInstaller standalone adapter smoke passed with a mock HTTP transport:
  frozen imports, PCM decoding, model header and exact pause/chunk pipeline.
  This is not a packaged Tauri application or full native distribution test.
- Real MiniMax Voice Design and persisted full generation completed (193.427s,
  mono 32 kHz). ASR and waveform checks passed; subjective accent review pending.
- Real Fish authentication succeeded, but voice design returned HTTP 402 for
  insufficient API credit. A real Fish synthesis/clone remains unverified until
  the API account is funded; mocked tests do not establish acoustic quality.

One existing unrelated test module, `test_profile_duplicate_names.py`, could
not be collected because of its `from database` relative-import failure.

Editorial correction: the user classified this piece as professional podcast /
promotional narration. The current template preserves the text with an opening
hook and an action-oriented ending, removes audible breathing cues and uses
3.9s of short editorial silences. The replacement MiniMax take completed at
99.527s, 32 kHz, with ASR content and waveform checks; listening review pending.
