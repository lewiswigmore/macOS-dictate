# Homebrew tap

`Formula/dictate.rb` lives in this repository as the source of truth for the Homebrew formula. It is not installable as a tap until a separate tap repository exists at `lewiswigmore/homebrew-dictate` with a `Formula/` directory containing the same file.

## Maintainer setup

1. Create `lewiswigmore/homebrew-dictate`.
2. Copy `Formula/dictate.rb` from this repository into `lewiswigmore/homebrew-dictate/Formula/dictate.rb`.
3. Users can then install with:

   ```bash
   brew tap lewiswigmore/dictate
   brew install dictate
   ```

   (`brew tap lewiswigmore/dictate` resolves to the
   `lewiswigmore/homebrew-dictate` repository per Homebrew naming
   convention.)

After each release, update the formula SHA256 in the tap repository and push the tap change.

## Future

If dictate gets enough traction, propose it for `homebrew-core` so users can run `brew install dictate` without a tap.
