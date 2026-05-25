<!-- Mirror of ../THREAT_MODEL.md - update both when changing -->

# Threat Model

This is an honest summary of what dictate is designed to protect, and what it is not designed to protect.

## What dictate protects against

- **Opportunistic network observers.** dictate has no telemetry by default. Local dictation, local cleanup, local history, and the local WebUI do not send usage data to a remote service.
- **Accidental cloud upload.** The default path is local-first: Whisper runs locally for speech-to-text, cleanup defaults to Ollama, and cloud cleanup is only used when OpenRouter is explicitly enabled in config.
- **Curious people who pick up your laptop briefly.** dictate inserts text through clipboard paste for reliable Unicode input, then restores the previous clipboard after paste so dictated text is not left as a plaintext clipboard surprise.

## What dictate does NOT protect against

- **Malware already running as your user.** It can read `history.jsonl`, inspect `NSPasteboard`, capture the microphone feed, observe synthetic input, or read dictate's config and logs.
- **A compromised Ollama or OpenRouter endpoint.** If you opt into a backend and that endpoint is compromised, transcripts sent to it may be exposed or modified.
- **A compromised macOS installation.** dictate relies on macOS permissions and process isolation. If the OS is compromised, dictate cannot provide meaningful protection.
- **A person with persistent physical access.** Someone who can repeatedly access an unlocked or poorly secured Mac can read files, change config, or install monitoring tools.
- **Supply-chain attacks on PyPI dependencies.** dictate depends on third-party Python packages. Pinning, reviewing, and auditing dependencies remains a user and maintainer responsibility.

## Data at rest

`history.jsonl` is plaintext JSON stored in the user's home directory. It may contain raw transcripts, cleaned text, app context, backend names, timestamps, and correction-learning examples depending on configuration. Treat it like sensitive local data.

## Data in transit

By default, no transcript data leaves the Mac. The only supported remote cleanup path is OpenRouter, which sends HTTPS requests to `openrouter.ai` when explicitly enabled. Secret redaction runs before OpenRouter requests, but redaction is best-effort and should not be treated as a cryptographic boundary.

## Recommendations for higher-risk users

- Enable FileVault.
- Store the OpenRouter API key in Keychain rather than shell history or plaintext config.
- Set history retention low, or purge history regularly.
- Run Ollama exclusively and keep OpenRouter out of the fallback chain.
