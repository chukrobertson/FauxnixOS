# Fauxnix Knowledge

This directory is the on-box working knowledgebase for Fennix, Nexus, and
smaller maintenance agents.

The source of truth lives in the Fauxnix repo under
`remote-nixos/docs/knowledge/`. Nix activation installs these notes into
`/home/chvk/Fauxnix/Knowledge` on every rebuild, so update the source file first
when changing system guidance.

Current areas:

- `desktop/` active SDDM and Wayfire workspace profile notes.
- `nix/` module ownership, rebuild workflow, and rollback notes.
- `fauxshell/` desktop cards, launcher surfaces, screenshots, and continuity
  views.
- `fauxdex/` bounded workspace loop for local agents.
