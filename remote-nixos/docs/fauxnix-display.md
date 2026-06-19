# Fauxnix Display Settings

Fennix should manage display modes through `fauxnix-display`, not through model-written Sway commands.

## Commands

- `fauxnix-display status [output]` prints the active output, current mode, scale, make, model, and supported modes.
- `fauxnix-display modes [output]` lists modes reported by Sway for the active output or named output.
- `fauxnix-display set <mode> [output]` applies a mode only after validating that Sway reports it as supported.
- `fauxnix-display set <output> <mode>` is accepted when the output should be explicit.

Mode examples:

- `1600x900`
- `1600x900@60Hz`
- `1600x900@40.003Hz`

If the refresh rate is omitted, the helper chooses the highest reported refresh for that resolution.
If the user asks for `60Hz` and Sway reports `60.007Hz`, the helper treats that as the same supported mode.

## Current ThinkPad Panel

As of the first display-settings pass, the internal panel reports:

- Output: `LVDS-2`
- Current mode: `1600x900 @ 60.007Hz`
- Scale: `1.0`
- Supported modes: `1600x900 @ 60.007Hz`, `1600x900 @ 40.003Hz`

Do not promise lower internal-panel resolutions unless a later `fauxnix-display modes` run shows them.
External monitors may expose additional outputs and modes.

## Fennix Behavior

Fennix should answer questions like:

- "What resolution is this display using?"
- "What resolutions are supported?"
- "Set the screen resolution to 1600x900 at 60Hz."

For changes, Fennix should call `fauxnix-display set ...` and let the helper reject unsupported modes.
