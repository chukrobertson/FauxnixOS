# Fauxshell Glass System

Fauxshell uses dark translucent glass as a core visual language.

## Intent

- Keep the desktop spatial and layered instead of flat.
- Let cards feel like persistent system surfaces, not regular app panels.
- Preserve high contrast for text, telemetry, and evidence rows.
- Use orange for Fauxnix identity and cyan for live/system/evidence signal.

## Current Rules

- Dashboard cards, Fennix launcher, Archivist Files, notes, clipboard,
  continuity bubbles, login, and lock surfaces should share the same dark glass
  treatment.
- Use translucent black surfaces with subtle light borders.
- Keep cards at 8px radius unless a full-window shell needs a slightly larger
  outer radius.
- Avoid decorative blobs, heavy gradients, and opaque slabs that break the
  workspace map feel.
- Plain Sway does not provide true background blur. Under Sway, glass is a
  translucent GTK treatment. True blur should be tested later with `swayfx`.
- SDDM login should use the same dark glass sheet, orange identity signal, and
  cyan system signal without decorative blob backgrounds.

## Implementation Notes

- Native surfaces are styled in `fauxshell-host.c`.
- Use RGBA-capable windows for launcher, desktop, and expanded Fauxshell tools.
- Keep whole-window opacity close to full opacity; use CSS alpha on surfaces for
  most of the glass effect so text remains readable.
- Treat file/evidence rows as glass strips with a cyan left rail.
- Keep lock/login legible first: prefer one central glass sheet, subtle system
  lines, and minimal power controls.
