# NixOS Rebuild Workflow

Agents should treat NixOS changes as a gated loop:

1. Inspect the current config and live system state.
2. Patch the narrowest owning module.
3. Run `sudo nixos-rebuild build --show-trace`.
4. Summarize what changed and what the build proved.
5. Switch only after the build succeeds.
6. Verify the services or binaries touched by the change.
7. Record rollback generation details when the change affects login, network,
   display, storage, or agent runtime.

Use `/etc/nixos/fauxnix-backups/` for source backups before replacing remote
files by hand.
