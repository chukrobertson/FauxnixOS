# Faux-pass: Client + Provider Architecture

## Overview

**Faux-pass Client** — Runs on FauxnixOS (laptop). Launches local VMs AND connects to remote Providers.
**Faux-pass Provider** — Runs on Windows Nexus (desktop). Serves Windows apps via RDP RemoteApp over Tailscale.

Both sides speak the same protocol. The Client presents a unified "app launcher" whether the app runs locally (Firecracker/QEMU) or remotely (Windows Nexus).

---

## Faux-pass Client (FauxnixOS)

### Responsibilities
1. **Local VM Management** — Firecracker (Linux) + QEMU (Windows) microVMs
2. **Remote Provider Discovery** — Find Providers on Tailscale tailnet
3. **Unified App Registry** — Merge local VM apps + remote Provider apps
4. **App Launch** — Route to local VM or remote Provider transparently
5. **Desktop Integration** — Sway windows, Fauxshell dashboard, Fennix commands

### Components

| Component | Technology | Purpose |
|-----------|------------|---------|
| `faux-pass-manager` | Python systemd service | Local VM lifecycle, API server |
| `faux-pass-provider-client` | Python module | Connect to Providers over Tailscale |
| `faux-pass-cli` | Python CLI | User-facing commands |
| `faux-pass-api` | HTTP + Unix socket | Fauxshell/Fennix integration |
| `faux-pass-guest` | Shell/Python (in VM) | App registry inside local VMs |

### Local VM Stack
```
┌─────────────────────────────────────────────────────┐
│  faux-pass-manager (systemd service)                │
│  ├─ Firecracker → Linux microVMs (waypipe → Sway)  │
│  └─ QEMU/KVM → Windows VMs (FreeRDP RemoteApp)     │
└─────────────────────────────────────────────────────┘
```

### Remote Provider Connection
```
Tailscale Mesh
┌──────────────┐     WebSocket/JSON-RPC     ┌──────────────────┐
│ FauxnixOS    │ ◄─────────────────────────► │ Windows Nexus    │
│ (Client)     │     tailscale IP:4433       │ (Provider)       │
└──────────────┘                             └──────────────────┘
```

---

## Faux-pass Provider (Windows Nexus)

### Responsibilities
1. **App Enumeration** — Scan Start Menu, registry, configured paths for `.exe`/`.lnk`
2. **RDP RemoteApp Host** — Configure Windows Server RemoteApp (or standalone RDP wrapper)
3. **Tailscale Integration** — Accept connections only from tailnet
4. **Session Management** — One RDP session per concurrent app, auto-cleanup
5. **Health/Status** — Report capacity, active sessions to Client

### Components

| Component | Technology | Purpose |
|-----------|------------|---------|
| `faux-pass-provider.exe` | Go/Win32 service | Main service, WebSocket server |
| `RemoteApp Config` | PowerShell/Registry | Publish apps as RemoteApps |
| `Tailscale` | System service | Mesh VPN, ACL tags |
| `RDP Listener` | Windows RDP stack | Port 3389 (tailscale-only) |

### Windows RemoteApp Setup
```powershell
# Enable RemoteApp (Windows 10/11 Pro/Enterprise)
# Requires: RDS role OR third-party RemoteApp wrapper
# Faux-pass uses: FreeRDP's RemoteApp mode (no RDS CAL needed)
```

---

## Protocol: Faux-pass Wire Protocol (FPWP)

### Transport
- **Local**: Unix socket (`/var/run/faux-pass/api.sock`)
- **Remote**: WebSocket over Tailscale (`wss://<provider-tailscale-ip>:4433/faux-pass`)

### Message Format (JSON-RPC 2.0)
```json
{ "jsonrpc": "2.0", "id": 1, "method": "apps.list", "params": {} }
{ "jsonrpc": "2.0", "id": 1, "result": { "apps": [...] } }
```

### Methods

#### Provider Discovery (Client → Provider)
| Method | Params | Result |
|--------|--------|--------|
| `provider.info` | `{}` | `{ name, os, version, caps: ["rdp", "clipboard", "file-transfer"] }` |
| `apps.list` | `{ filter?: string }` | `{ apps: [{ id, name, exec, icon, category, remote: true }] }` |
| `apps.launch` | `{ app_id, display_id?, geometry? }` | `{ session_id, rdp_file_base64, websocket_url }` |
| `sessions.list` | `{}` | `{ sessions: [{ id, app_id, state, created }] }` |
| `sessions.close` | `{ session_id }` | `{ ok: true }` |

#### Local VM (Client internal)
| Method | Params | Result |
|--------|--------|--------|
| `vm.list` | `{}` | `{ vms: [{ id, name, type, state, memory, apps: [...] }] }` |
| `vm.start` | `{ vm_id }` | `{ ok: true }` |
| `vm.stop` | `{ vm_id, force?: bool }` | `{ ok: true }` |
| `vm.create` | `{ name, type: "linux"|"windows", base_image? }` | `{ vm_id }` |

#### Unified (Client exposes to Fauxshell/Fennix)
| Method | Params | Result |
|--------|--------|--------|
| `apps.all` | `{}` | `{ apps: [{ ...source: "local-vm"|"remote-provider", vm_id?, provider_id? }] }` |
| `apps.launch` | `{ app_id, source }` | `{ window_id, pid }` |

---

## Data Flow: Launch Remote Windows App

```
1. User clicks "Notepad" in Fauxshell (tagged source=remote, provider=nexus)
        │
        ▼
2. Fauxshell POST /api/apps/launch { app_id: "notepad", source: "remote", provider_id: "nexus" }
        │
        ▼
3. faux-pass-manager → Provider Client → WebSocket to nexus:4433
        │
        ▼
4. Provider: apps.launch({ app_id: "notepad" })
        │
        ▼
5. Provider generates .rdp file + starts RDP session
        │
        ▼
6. Returns: { session_id, rdp_file_base64, websocket_url: "wss://nexus:4433/rdp/<session>" }
        │
        ▼
7. Client: launches `wlfreerdp /v:nexus /app:notepad /rdp-file:<decoded> +clipboard`
        │
        ▼
8. FreeRDP connects via Tailscale → Windows RDP → RemoteApp → seamless window on Sway
```

---

## Fauxshell Dashboard Integration

### VM Card (Local)
```
┌─ Ubuntu Dev (running) ──────────────────┐
│ 🟢 Firecracker  ·  2GB/4GB  ·  2 vCPU   │
│ Apps: [Terminal] [VS Code] [Firefox]    │
│ [Snapshot] [Stop] [Console]             │
└─────────────────────────────────────────┘
```

### Provider Card (Remote)
```
┌─ Nexus (Windows 11) ────────────────────┐
│ 🟢 Connected via Tailscale  ·  100.64.x │
│ Apps: [Notepad] [Calc] [VS Code] [PS]   │
│ [Disconnect] [Refresh Apps]             │
└─────────────────────────────────────────┘
```

### Unified App Grid (Fauxshell Home View)
```
Quick Launch:
[Terminal] [VS Code] [Firefox] [Notepad♥] [Calc♥] [PowerShell♥]
                    ▲local          ▲remote (♥)
```

---

## Fennix Integration

```python
# In fennix-gui.py: build_prompt() adds faux-pass context
if wants_apps_context(user_text):
    apps = faux_pass_client.apps_all()
    blocks.append("AVAILABLE APPS:\n" + format_apps(apps))

# Local actions
def local_action_for_text(text):
    if "launch" in text and "notepad" in text:
        return LocalAction("Launching Notepad...", commands=(("faux-pass", "run", "notepad"),))
```

---

## Security Model

| Layer | Mechanism |
|-------|-----------|
| Network | Tailscale ACL: `tag:faux-pass-client` → `tag:faux-pass-provider` port 4433 |
| Auth | Pre-shared key (PSK) in `/etc/faux-pass/psk` + Tailscale identity |
| Transport | TLS 1.3 (WebSocket) / Unix socket permissions (local) |
| RDP | NLA (Network Level Auth) + TLS, restricted to Tailscale subnet |
| Isolation | Each VM: dedicated user, seccomp, no host fs access |
| Provider | Runs as standard user, no admin (RemoteApp via FreeRDP user-mode) |

---

## Implementation Priority

### Phase 1: Provider (Windows Nexus)
- [ ] `faux-pass-provider.exe` — Go service, WebSocket + JSON-RPC
- [ ] App enumeration (Start Menu, registry, custom paths)
- [ ] FreeRDP RemoteApp launch (`wlfreerdp` on client side)
- [ ] Tailscale integration (auto-discover, ACL tags)
- [ ] Config: `C:\ProgramData\FauxPass\config.json`

### Phase 2: Client (FauxnixOS)
- [ ] NixOS module: `services.faux-pass`
- [ ] `faux-pass-manager` — local VMs + provider client
- [ ] Provider discovery via Tailscale API (`tailscale status --json`)
- [ ] Unified API (`/api/apps/all`, `/api/apps/launch`)
- [ ] Fauxshell dashboard cards

### Phase 3: Polish
- [ ] Clipboard sync (local ↔ remote)
- [ ] File transfer (9p for local, RDP drive redirect for remote)
- [ ] GPU passthrough (virtio-gpu / virgl for local, RemoteFX for remote)
- [ ] Fennix natural language ("open Windows calculator on nexus")
- [ ] Snapshot/restore for local VMs