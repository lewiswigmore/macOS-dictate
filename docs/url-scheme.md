# URL scheme

The `dictate://` URL scheme lets automation tools control recording and open local views.

!!! note "Registration"
    macOS registers custom URL schemes from a packaged `.app` bundle. In v0.1 development, invoke the handler directly with `python3 -m dictate "dictate://toggle"`.

## Supported URLs

```bash
open "dictate://record"
open "dictate://stop"
open "dictate://toggle"
open "dictate://history"
open "dictate://settings"
```

## Hammerspoon

```lua
hs.hotkey.bind({"cmd", "alt"}, "D", function()
  hs.execute('open "dictate://toggle"')
end)
```

During development:

```lua
hs.execute('cd ~/dictate && python3 -m dictate "dictate://toggle"')
```

## Keyboard Maestro

Create a macro with an **Execute Shell Script** action:

```bash
open "dictate://record"
```

Add a second macro for stop:

```bash
open "dictate://stop"
```

## Shortcuts.app

1. Create a new shortcut.
2. Add **Open URLs**.
3. Use `dictate://toggle` or `dictate://history` as the URL.
4. Assign a keyboard shortcut or Siri phrase.

For development, use **Run Shell Script** instead:

```bash
cd ~/dictate
python3 -m dictate "dictate://toggle"
```
