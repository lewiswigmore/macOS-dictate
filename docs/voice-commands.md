# Voice commands

Voice commands are matched against the full final transcript after trimming whitespace and punctuation. Add or edit commands in `config/commands.yaml`.

## New line

Say `new line` as the whole utterance to insert a single newline.

Examples:

- `new line`
- `new line.`

## New paragraph

Say `new paragraph` as the whole utterance to insert a blank line between paragraphs.

Examples:

- `new paragraph`
- `new paragraph.`

## Spell that

Say `spell that` followed by letters to insert a literal spelling. This bypasses cleanup.

Examples:

- `spell that D I C T A T E`
- `spell that A P I`

## Tab

Say `tab` as the whole utterance to insert a tab character.

Example:

- `tab`

## Scratch that

Say `scratch that` to remove the last inserted dictate output.

Examples:

- `scratch that`
- `scratch that.`

## Stop or cancel

Say one of these to stop or cancel the current recording command path:

- `stop`
- `stop recording`
- `cancel`

## Fix last / redo

Ask dictate to re-clean the previous transcript.

Examples:

- `fix last`
- `fix that`
- `redo`
- `try again`

## Paste raw

Bypass LLM cleanup and paste the raw ASR output.

Examples:

- `paste raw`
- `raw paste`
- `no cleanup`
