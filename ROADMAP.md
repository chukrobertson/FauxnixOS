# FauxnixOS Roadmap

## Done

| Feature | Status |
|---------|--------|
| Thread infrastructure (btrfs + nspawn + template) | ✅ |
| wsctl CLI (20 commands) | ✅ |
| Git per-thread + auto-commit | ✅ |
| 3-layer snapshot safety net | ✅ |
| Nexus host daemon (5 services) | ✅ |
| Fennix in-thread assistant (11 services) | ✅ |
| Archivist auto-indexing + face/object detection | ✅ |
| Real embeddings (Ollama nomic-embed-text, 768-dim) | ✅ |
| Cross-thread context streaming (Fennix → Nexus) | ✅ |
| Suggestion engine with dedup + notifications | ✅ |
| Thread health monitoring | ✅ |
| 11 thread templates | ✅ |
| Desktop feel profiles (win11/macos QSS + labwc) | ✅ |
| Shared clipboard | ✅ |
| Cross-thread search | ✅ |
| LLM-powered wsctl ask (Ollama HTTP) | ✅ |
| wsctl dashboard (TUI) | ✅ |
| Browser watcher (9 browsers) | ✅ |
| Immutable NixOS base module | ✅ |
| GNOME base + Fennix shell extension | ✅ |
| VNC access per thread (wayvnc, ports 5901-5920) | ✅ |

## Next — Short Term

| Feature | What |
|---------|------|
| **Deploy immutable base** | Install on a spare machine. Test full boot flow: GNOME login → Nexus running → create thread → VNC in. |
| **Waypipe auto-connect** | `wsctl attach` should detect if a display is available and auto-launch waypipe for graphical threads. |
| **Template closure rebuild** | Rebuild the container closure with templates included so packages actually install (currently advisory). |
| **VNC auto-start** | Start wayvnc inside graphical threads automatically on boot. |

## Next — Medium Term

| Feature | What |
|---------|------|
| **Nexus search provider** | GNOME Shell search integration. Type "create ml thread" in the GNOME Activities search → Nexus creates it. Register as a DBus `SearchProvider`. |
| **Thread dock integration** | Running threads appear in the GNOME dash like apps. Click dock icon → VNC or waypipe into thread. |
| **Multi-user threads** | `wsctl create --user bob`. Per-user thread ownership, quotas. |
| **Thread resource limits** | CPU/mem quotas per thread via nspawn resource controls. |
| **Web dashboard** | Remote thread management from browser. Shows thread tree, health, suggestions. |

## Next — Long Term

| Feature | What |
|---------|------|
| **Threads as VMs** | Option to boot threads as full QEMU/KVM VMs instead of nspawn containers. Full OS isolation. |
| **PXE-booted threads** | Boot threads on other machines over the network. Cluster computing. |
| **OTG mobile web** | Port the original Membrie mobile web interface for thread management on the go. |
| **GPU passthrough** | Pass GPU to gaming threads. Vulkan, CUDA. |
| **Intrusion detection** | Nexus monitors thread activity for anomalies. Security audit logging. |
| **Cross-machine threads** | Threads that span multiple physical machines. Distributed workspaces. |

## Design Principles

1. **Base is sacred** — never modified. All change happens in threads.
2. **Threads are disposable** — snapshotted before every operation. Undo always possible.
3. **Fennix → Nexus → Fennix** — context flows from threads to host, intelligence flows back.
4. **One command** — `wsctl ask` goes from idea to running thread with full AI stack.
5. **Files survive everything** — git auto-commit + btrfs snapshots + shared /shared directory.
