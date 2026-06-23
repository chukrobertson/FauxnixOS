# Screenshot Memory

Fauxnix visual memory uses `fauxnix-screenshot`.

Commands:

- `fauxnix-screenshot` captures the screen and writes a PNG into
  `~/Fauxnix/Snapshots/screenshots/`.
- `fauxnix-screenshot --json` returns metadata for Fennix.
- `fauxnix-screenshot status` reports the screenshot directory and latest
  capture.

The active desktop profile is Wayfire. Prefer wlroots/portal evidence first;
fallback capture paths exist for the ThinkPad when interactive screenshot APIs
are unavailable.
