# AppleScript

The AppleScript dictionary lives at `assets/dictate.sdef`. It becomes active when dictate ships as a packaged `.app` with `NSScriptingDefinitionFile` in `Info.plist`.

## Start recording

```applescript
tell application "dictate"
    start recording
end tell
```

## Stop recording

```applescript
tell application "dictate"
    stop recording
end tell
```

## Toggle recording

```applescript
tell application "dictate"
    toggle recording
end tell
```

## Open history

```applescript
tell application "dictate"
    open history
end tell
```

## Development fallback

Before the packaged app is registered, use shell commands from AppleScript:

```applescript
do shell script "cd ~/dictate && python3 -m dictate 'dictate://toggle'"
```
