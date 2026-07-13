# Security Notes

## Audit Results (2026-07-12)

### Clean
- No API keys, tokens, or SSH private keys in source
- No `shell=True` or `os.system()` subprocess calls
- No hardcoded production IPs or hostnames
- All DB access uses parameterized queries (no SQL injection)

### Addressed
| Issue | Fix |
|-------|-----|
| `chmod 777 /run/nexus` | Changed to `755` — world-readable, root-writable only |
| Hardcoded `/home/chxk/Projects` paths | Now use `FAUXNIX_ROOT` env var with sensible default |
| Default thread password `"workspace"` | Changed to `"fauxnix-thread"` — still a dev default |
| Nexus uses passwordless sudo | Required for `machinectl list`, `wsctl snapshot`. Run Nexus as root or with limited sudoers. |

### Known — Acceptable for Dev
| Issue | Context |
|-------|---------|
| Threads share host network (no `--private-network`) | Needed for Ollama access. Isolate threads behind firewall in production. |
| Container user password in Nix config | Used only inside isolated nspawn threads, not exposed to network. |
| `/var/lib/workspaces/` owned by root | Requires sudo for wsctl operations. Run wsctl with limited sudoers. |
| fennix.nix Nix module has absolute build paths | Used for local development. Production builds use flake inputs. |

### Production Hardening
1. Run Nexus as a non-root user with passwordless sudo limited to: `machinectl list`, `wsctl snapshot`
2. Use `--private-network` + forward Ollama port specifically
3. Set `services.openssh.settings.PasswordAuthentication = false`
4. Add `boot.kernel.sysctl."kernel.kptr_restrict" = 2`
5. Use `security.auditd.enable = true` for audit logging
6. Rotate thread snapshots with retention policy

### Port Exposure
| Port | Service | Scope |
|------|---------|-------|
| 22 | SSH | Base system |
| 5901-5920 | VNC (threads) | Localhost or firewall-restricted |
| 11434 | Ollama | Localhost only (bound to 127.0.0.1) |
