# Faux-pass Architecture

## Goal
Lightweight VM environments that pipe native apps (Windows/Linux) directly into the Fauxnix desktop (Sway + Fauxshell).

## Core Components

### 1. VM Runtime: Firecracker MicroVMs
- **Why**: Fast boot (~100ms), minimal overhead, KVM-based, used by AWS Lambda/Fargate
- **Alternative**: QEMU with `-accel kvm` for broader guest support (Windows needs QEMU)
- **Decision**: Firecracker for Linux guests, QEMU for Windows guests

### 2. App Forwarding
| Guest OS | Protocol | Client | Notes |
|----------|----------|--------|-------|
| Windows | RDP (FreeRDP) | `xfreerdp` / `wlfreerdp` | RemoteApp mode for seamless apps |
| Linux | Wayland + virtio-wayland | `waypipe` / `weston` | Native Wayland forwarding |
| Linux (legacy) | SPICE | `spicy` / `remote-viewer` | Fallback |

### 3. Integration Points
- **Sway**: Each forwarded app gets its own window, assigned to workspace
- **Fauxshell**: Dashboard cards showing running VMs, quick-launch apps
- **Fennix**: Natural language VM/app management ("launch Windows Notepad")
- **fauxd API**: `/api/vms`, `/api/vms/{id}/apps`, `/api/vms/{id}/launch`

## VM Lifecycle

```
User Request → faux-pass CLI → VM Manager (systemd service)
    → Firecracker/QEMU starts VM (if not running)
    → Guest agent (systemd service inside VM) reports available apps
    → App launched via RDP/Wayland → Sway window appears
```

## Guest Agent
Runs inside each VM:
- Linux: `faux-pass-guest` (systemd service) - exposes app list via vsock/9p
- Windows: `faux-pass-guest.exe` - WinRM/SSH + RDP RemoteApp registration

## Storage
- **Base images**: `/var/lib/faux-pass/images/` (read-only, shared)
- **Overlay disks**: `/var/lib/faux-pass/overlays/{vm-id}.qcow2` (copy-on-write)
- **Config**: `/etc/faux-pass/vms/{vm-id}.json`

## Networking
- **Host ↔ VM**: vsock (Firecracker) or virtio-serial (QEMU) for control plane
- **VM ↔ Internet**: bridged or NAT via `faux-pass-br0`
- **No direct VM ↔ VM** (isolated by default)

## Security
- Each VM runs as dedicated user (`faux-pass-{vm-id}`)
- Seccomp filters on Firecracker/QEMU
- No host filesystem access unless explicitly mounted via 9p
- RDP/Wayland only exposes requested app window

## CLI UX
```bash
faux-pass list                    # List VMs
faux-pass start win11             # Start VM
faux-pass apps win11              # List available apps
faux-pass run win11 notepad       # Launch app (seamless)
faux-pass stop win11              # Stop VM
faux-pass create --windows        # Create new Windows VM (downloads base)
```

## Fauxshell Dashboard Card
```
┌─ Windows 11 (running) ────────┐
│ 🟢 Running  ·  2.1GB RAM      │
│ Apps: Notepad, Calculator,    │
│       VS Code, Terminal       │
│ [Notepad] [Calc] [VS Code]    │
│ [Stop VM] [Snapshot]          │
└───────────────────────────────┘
```

## Fennix Integration
```
User: "Open Windows Calculator"
Fennix: → faux-pass run win11 calc
        → Returns when window mapped
        → "Calculator opened on workspace 6"
```

## Implementation Phases

### Phase 1: Linux Guests (Firecracker + Wayland)
- [ ] NixOS module with Firecracker service
- [ ] Guest agent (vsock + app registry)
- [ ] `waypipe` forwarding to Sway
- [ ] Fauxshell VM card

### Phase 2: Windows Guests (QEMU + RDP RemoteApp)
- [ ] QEMU VM service with Windows image
- [ ] FreeRDP RemoteApp integration
- [ ] Windows guest agent (WinRM + RDP config)
- [ ] Seamless window mapping in Sway

### Phase 3: Polish
- [ ] Snapshot/restore
- [ ] GPU passthrough (virgl/virtio-gpu)
- [ ] Clipboard/file sharing
- [ ] Fennix natural language commands