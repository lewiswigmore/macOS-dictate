# Troubleshooting

## Hotkey not firing

**Causes**

- Accessibility or Input Monitoring is missing.
- Another app owns the same shortcut.
- The event tap was disabled by macOS after a timeout.

**Fixes**

- Grant permissions in System Settings → Privacy & Security → Accessibility and Input Monitoring.
- Restart dictate after granting permissions.
- Change `hotkey.mods` or `hotkey.key` in `config/settings.yaml`.
- Run `dictate doctor` to check conflicts.

## Mic permission issues

**Causes**

- Microphone permission is denied for Terminal, Python, or the packaged app.
- The active input device changed or disappeared.

**Fixes**

- Enable the app in System Settings → Privacy & Security → Microphone.
- Reopen dictate after changing permission.
- Select a working input device in macOS Sound settings.
- Run the first-run mic test or `dictate doctor`.

## ASR confidence low

**Causes**

- Noisy room or low input gain.
- Whisper model too small for your accent or vocabulary.
- Missing project-specific vocabulary.

**Fixes**

- Move closer to the mic or reduce background noise.
- Try a larger Whisper model.
- Add terms to `config/vocab/code.txt`, `work.txt`, `personal.txt`, or `projects/<repo>.txt`.
- Raise VAD sensitivity only if silence is being captured as speech.

## Ollama unreachable

**Causes**

- Ollama is not installed or not running.
- The configured model has not been pulled.
- The backend URL in config is wrong.

**Fixes**

```bash
brew services start ollama
ollama pull qwen2.5:3b-instruct
```

Then run:

```bash
dictate doctor
```

If Ollama remains unhealthy, keep `raw` in `cleanup.fallback_chain` so dictation still inserts text.

## Secure-input refusal

**Causes**

- The focused field is a password or secure text input.
- macOS secure input is active in another app.

**Fixes**

- Move focus to a normal text field.
- Quit or unlock the app holding secure input.
- Paste manually only if you are sure the destination is safe.

## WebUI port in use

**Causes**

- Another `dictate-web` process is already running.
- Another local service is bound to port `47843`.

**Fixes**

- Open <http://127.0.0.1:47843> to see if the WebUI is already running.
- Stop the duplicate process from your terminal or Activity Monitor.
- Launch the WebUI from code with a different loopback port if needed.
