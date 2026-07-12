# Phase 1: Immutable NixOS Base + btrfs + nspawn Workspaces

## Objective

Boot into a minimal, locked NixOS base system with btrfs as the root filesystem and the ability to launch isolated container workspaces via systemd-nspawn.

## Deliverables

- Bootable NixOS flake configuration (extending existing `fauxnix-core/flake.nix`)
- btrfs layout with dedicated subvolumes
- Immutable root via tmpfs overlay
- At least one declarative workspace container
- Verification script

## Tasks

### 1.1 btrfs Subvolume Layout

Mount the root btrfs filesystem with this structure:

```
/
├── @base/              ← NixOS root (mounted ro at boot)
├── @workspaces/        ← parent for workspace subvolumes
│   ├── default/        ← default workspace btrfs subvolume
│   └── ...
├── @snapshots/         ← snapper snapshot storage
├── @shared/            ← shared files across all workspaces
├── @home/              ← persistent user home
├── @nix/               ← /nix/store (btrfs subvolume)
└── @swap/              ← swap subvolume
```

### 1.2 NixOS Flake — Base System Module

Create `modules/workspace-base.nix` with:

```nix
{ config, lib, pkgs, ... }:

{
  options.fauxnix.workspace-base = {
    enable = lib.mkEnableOption "FauxnixOS immutable workspace base system";
    containerBackend = lib.mkOption {
      type = lib.types.enum [ "nspawn" "podman" ];
      default = "nspawn";
    };
  };

  config = lib.mkIf config.fauxnix.workspace-base.enable {
    # Immutable root: tmpfs overlay on top of ro-mounted @base
    boot.initrd.systemd.enable = true;
    boot.initrd.systemd.mounts = [
      {
        where = "/mnt/@base";
        what = "/dev/disk/by-label/NIXROOT";
        type = "btrfs";
        options = "subvol=@base,ro";
      }
      # ... more mounts
    ];

    fileSystems."/" = {
      device = "tmpfs";
      fsType = "tmpfs";
      options = [ "defaults" "size=2G" "mode=755" ];
    };

    # Bind-mount persistent subvolumes
    fileSystems."/nix" = { /* @nix subvol, ro */ };
    fileSystems."/shared" = { /* @shared subvol, rw */ };
    fileSystems."/workspaces" = { /* @workspaces subvol, rw */ };
    fileSystems."/home" = { /* @home subvol, rw */ };

    # Snapper for automatic snapshots
    services.snapper = {
      enable = true;
      snapshotRoot = "/workspaces";
      snapshotInterval = "hourly";
      cleanupInterval = "1d";
    };

    # Container runtime
    boot.enableContainers = true;  # nspawn support

    # Base system packages (minimal)
    environment.systemPackages = with pkgs; [
      git
      btrfs-progs
      snapper
      podman  # optional
    ];

    # SSH for remote management (optional)
    services.openssh.enable = true;
  };
}
```

### 1.3 Workspace Container Definition

Define a declarative nixos-container at `/workspaces/default`:

```nix
containers.default = {
  autoStart = false;
  privateNetwork = true;
  hostAddress = "10.250.0.1";
  localAddress = "10.250.0.2";

  bindMounts = {
    "/shared" = {
      hostPath = "/shared";
      isReadOnly = false;
    };
  };

  config = { pkgs, ... }: {
    # Workspace NixOS config
    environment.systemPackages = with pkgs; [
      git
    ];

    services.fennix-context-agent = {
      enable = true;  # Phase 3
    };
  };
};
```

### 1.4 Integration with Existing flake.nix

Add to the root `flake.nix`:

```nix
nixosModules = {
  # existing modules...
  workspace-base = import ./modules/workspace-base.nix;
  workspace-profiles = import ./modules/workspace-profiles.nix;  # Phase 6
};
```

### 1.5 Verification Script

Create `scripts/verify-phase1.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
FAIL=0

echo "=== Phase 1 Verification ==="

# 1. Confirm root is tmpfs
if mount | grep 'on / type tmpfs' > /dev/null; then
  echo "[PASS] Root is tmpfs overlay"
else
  echo "[FAIL] Root is not tmpfs"
  FAIL=1
fi

# 2. Confirm btrfs subvolumes exist
for subvol in @base @workspaces @shared @snapshots @home @nix; do
  if btrfs subvolume list / | grep -q "$subvol"; then
    echo "[PASS] Subvolume $subvol exists"
  else
    echo "[FAIL] Subvolume $subvol missing"
    FAIL=1
  fi
done

# 3. Shared file test: write from base, read in container
echo "test-$(date +%s)" > /shared/test-phase1.txt
if sudo systemd-run --machine=default \
    --quiet --wait --pipe \
    cat /shared/test-phase1.txt 2>/dev/null; then
  echo "[PASS] Shared file accessible from container"
else
  echo "[FAIL] Shared file not accessible from container"
  FAIL=1
fi

# 4. Create btrfs snapshot of workspace
sudo btrfs subvolume snapshot \
  /workspaces/default \
  /snapshots/default-test-$(date +%Y%m%d-%H%M%S)
if [ $? -eq 0 ]; then
  echo "[PASS] Workspace snapshot created"
else
  echo "[FAIL] Workspace snapshot failed"
  FAIL=1
fi

# 5. Container networking isolation
if sudo systemd-run --machine=default --quiet --wait --pipe \
    ip addr show 2>/dev/null | grep -q "10.250"; then
  echo "[PASS] Container has isolated network"
else
  echo "[FAIL] Container network isolation check failed"
  FAIL=1
fi

echo ""
if [ $FAIL -eq 0 ]; then
  echo "=== ALL PASSED ==="
else
  echo "=== $FAIL FAILURES ==="
fi
exit $FAIL
```

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Container runtime | systemd-nspawn | Nix-native via `nixos-containers`, no daemon, lightweight |
| Filesystem | btrfs | Native snapshot support, subvolumes, send/receive for forking |
| Snapshot tool | snapper | Battle-tested, automatic cleanup policies, NixOS module exists |
| Base system desktop | Headless | No compositor on base — workspaces are the interactive layer |
| User namespace | Same UID across workspaces | Personal use, no multi-tenant isolation needed |

## Success Criteria

- [ ] System boots to immutable base
- [ ] `systemctl start container@default` launches workspace
- [ ] File written in `/shared` on base is readable inside container
- [ ] `btrfs subvolume snapshot` on workspace subvolume succeeds
- [ ] Container has isolated networking (private network, NAT)
- [ ] Root filesystem is cleared on reboot (tmpfs)
- [ ] All 5 verification script checks pass
