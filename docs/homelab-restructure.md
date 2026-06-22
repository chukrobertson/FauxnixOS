# Fauxnix Homelab Restructure

## Branch Map

- `Fauxnix-Archivist`: ThinkPad file-server appliance.
- `Fauxnix-Desktop`: desktop/workspace test platform for the old MacBook.
- `main`: stable baseline until the branch split settles.

## System Roles

### Fauxnix Archivist

Target hardware: ThinkPad.

Primary role:
- Always-on file server.
- Workspace node UI exposed over the local network.
- File management powered by selected Archivist tooling.
- Admin assistant surface for storage, indexing, file operations, and health checks.

Near-term direction:
- Pull reusable file-management, indexing, preview, metadata, and operational-control patterns from `E:\Archivist`.
- Keep file operations bounded, auditable, and visible.
- Treat GPU-heavy file work as offloadable to the Windows Nexus Node.

### Fauxnix Desktop

Target hardware: old MacBook.

Primary role:
- Desktop/workspace experiment branch.
- Display-card and VM-streaming test platform.
- Receives piped-in virtual machines and remote display sources from Nexus.

Near-term direction:
- Keep compositor/session work here instead of mixing it into the file-server branch.
- Preserve Display card/source concepts for apps, VMs, and remote streams.

### Nexus Node

Target hardware: Windows machine.

Primary role:
- Coordinator that connects to both Fauxnix Archivist and Fauxnix Desktop.
- Provides admin assistance and GPU offload for file work from the ThinkPad.
- Provides VM/display streams to Fauxnix Desktop machines.

Near-term direction:
- Standardize node discovery, status, and control APIs.
- Keep high-power compute and GPU work on Windows when it is cheaper than running it on the ThinkPad.
- Treat VM streaming as a Display source that can be routed to desktop clients.

## Design Principles

- The ThinkPad should become appliance-like: reliable, reachable, and quiet.
- The Desktop branch should stay experimental and visual.
- Nexus should be the powerful coordinator, not just another client.
- Archivist imports should be deliberate: reuse proven file/index/admin tooling without dragging unrelated product surfaces into Fauxnix.
- File operations, offload jobs, and VM streams should have visible state, logs, and recoverable control paths.

## First Pass Checklist

1. Rename the current branch to `Fauxnix-Archivist`.
2. Create `Fauxnix-Desktop` from the current checkpoint so the VM/display work is not lost.
3. Inventory Archivist modules that can be reused for file management.
4. Define the local-network workspace node UI entrypoint for the ThinkPad.
5. Define the Nexus Node contract for admin assistance, GPU offload, and VM/display streams.
6. Move or gate desktop-specific VM/compositor work away from the Archivist appliance profile.
