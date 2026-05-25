# Code dictation

Code-grammar mode applies deterministic transformations before LLM cleanup when the active preset is `code`.

## Enablement

```yaml
cleanup:
  code_grammar:
    enabled: true
    presets: [code]
```

The code preset is selected for terminals, VS Code, Xcode, JetBrains IDEs, Cursor, Sublime Text, and other bundle IDs in `config/app_map.yaml`.

## Case conversions

Say a case trigger followed by two to five words:

| Spoken | Output |
|---|---|
| `snake case user id` | `user_id` |
| `camel case user id` | `userId` |
| `pascal case user id` | `UserId` |
| `kebab case user id` | `user-id` |
| `screaming snake user id` | `USER_ID` |

## Symbol substitutions

| Spoken | Output |
|---|---|
| `triple equals` | `===` |
| `double equals` | `==` |
| `not equals` | `!=` |
| `less or equal` / `greater or equal` | `<=` / `>=` |
| `less than` / `greater than` | `<` / `>` |
| `open paren` / `close paren` | `(` / `)` |
| `open bracket` / `close bracket` | `[` / `]` |
| `open brace` / `close brace` | `{` / `}` |
| `open angle` / `close angle` | `<` / `>` |
| `fat arrow` / `arrow` | `=>` / `->` |
| `double pipe` / `pipe` | `||` / `|` |
| `double ampersand` / `ampersand` | `&&` / `&` |
| `at sign`, `hash`, `dollar` | `@`, `#`, `$` |
| `underscore`, `dash`, `hyphen` | `_`, `-`, `-` |
| `plus`, `minus`, `star`, `slash`, `backslash` | `+`, `-`, `*`, `/`, `\` |
| `percent`, `caret`, `tilde`, `bang`, `question` | `%`, `^`, `~`, `!`, `?` |
| `quote`, `string`, `single quote`, `apostrophe`, `backtick` | `"`, `"`, `'`, `'`, `` ` `` |
| `semicolon`, `colon`, `comma`, `dot`, `period` | `;`, `:`, `,`, `.`, `.` |
| `new line`, `tab` | newline, tab |

## Examples

Before cleanup:

```text
const snake case user id equals request dot params dot id semicolon
```

After code grammar:

```text
const user_id = request.params.id;
```

Before cleanup:

```text
if open paren camel case is active double ampersand count greater than zero close paren open brace new line return true semicolon new line close brace
```

After code grammar:

```text
if (isActive && count > zero) {
return true;
}
```
