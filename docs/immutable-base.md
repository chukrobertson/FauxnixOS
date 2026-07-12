# Immutable Base Deployment

The immutable base is a NixOS module that makes the host system read-only with a tmpfs root overlay. Only essential services run — Nexus, Ollama, SSH, systemd-nspawn. All user work happens inside threads.

## Testing in a VM (safe — no changes to your system)

```bash
# Build and boot the immutable base VM
nix-build '<nixpkgs/nixos>' -A config.system.build.vm \
  -I nixos-config=configurations/vm-immutable.nix
./result/bin/run-nixos-vm
```

## Deploying on real hardware

Add to your `/etc/nixos/configuration.nix`:

```nix
{
  imports = [
    /path/to/fauxnix-core/modules/immutable-base.nix
    # ... your hardware config ...
  ];

  fauxnix.immutable-base.enable = true;
  fauxnix.immutable-base.persistentPaths = [
    "/home"
    "/var/lib/workspaces"
    "/var/lib/workspaces-shared"
    "/var/lib/ollama"
    "/var/log"
  ];
}
```

Then rebuild:
```bash
sudo nixos-rebuild switch
```

## What changes

| Before (Normal NixOS) | After (Immutable) |
|----------------------|-------------------|
| `/` on btrfs, writable | `/` on tmpfs, resets every boot |
| All services run | Only: ssh, ollama, nexus, systemd-nspawn |
| Desktop environment on host | No desktop — threads are graphical |
| `/etc` persistent | `/etc` recreated from closure each boot |
| Can `nix-shell -p` anything | Must use threads for packages |

## Boot safety

`nixos-rebuild switch` creates a new generation. If the immutable base doesn't boot properly:
1. Reboot
2. At the systemd-boot menu, select the previous generation
3. You're back to your normal system

## Persistent paths

Only paths listed in `persistentPaths` survive reboots. These must be on btrfs subvolumes:
- `/home` — user data
- `/var/lib/workspaces` — thread roots
- `/var/lib/workspaces-shared` — cross-thread files
- `/var/lib/ollama` — downloaded models
- `/var/log` — system logs

Everything else in `/var` and `/etc` resets on boot.
