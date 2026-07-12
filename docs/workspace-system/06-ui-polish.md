# Phase 6: UI Layer + Desktop Feel Profiles + Polish

## Objective

Make the workspace system pleasant to use. Integrate workspace management into Fennix's Qt6 UI, implement Windows 11 and macOS desktop feel profiles, add a TUI dashboard, and polish the onboarding experience.

## Deliverables

- Desktop feel profiles (win11, macos) as compositor + Fennix panel templates
- Workspace management integrated into Fennix Qt6 UI (quickbar, tray)
- TUI dashboard (`wsctl dashboard`)
- Waybar/taskbar workspace widget
- Workspace templates library
- Documentation and onboarding

## Tasks

### 6.1 Desktop Feel Profiles

Workspaces get their visual identity from two layers:

```
┌──────────────────────────────────┐
│  Fennix Qt6 Panel (overlay)      │  ← Fennix owns the UI chrome
│  ┌──────────┐ ┌──┐ ┌──┐ ┌──┐   │
│  │ Quickbar │ │  │ │  │ │  │   │     Layout controlled by profile
│  └──────────┘ └──┘ └──┘ └──┘   │
├──────────────────────────────────┤
│  Workspace Compositor             │  ← Renders windows
│  (labwc / wayfire / sway)        │
│                                    │     WM config controlled by profile
└──────────────────────────────────┘
```

#### Profile Definitions

Profiles are Nix module templates under `modules/workspace-profiles.nix`:

```nix
{ config, lib, pkgs, ... }:

let
  win11Profile = {
    # Compositor
    services.labwc.enable = true;
    services.labwc.config = {
      window.cornerRadius = 8;
      theme = "win11-qss";
    };

    # Fennix panel layout: bottom bar, centered launcher
    fauxnix.fennix.panel = {
      position = "bottom";
      height = 48;
      quickbar.centered = true;
      tray.alignment = "right";
      blur.enabled = true;          # acrylic effect
    };

    environment.systemPackages = with pkgs; [ labwc waybar ];
  };

  macosProfile = {
    services.labwc.enable = true;
    services.labwc.config = {
      window.cornerRadius = 10;
      theme = "macos-qss";
    };

    # Fennix panel layout: top bar, bottom dock
    fauxnix.fennix.panel = {
      position = "top";             # global menu bar
      height = 28;
      topBar.menus = [ "File" "Edit" "View" "Window" "Help" ];
      dock.enabled = true;
      dock.position = "bottom";
      dock.height = 56;
      dock.magnification = true;
    };

    environment.systemPackages = with pkgs; [ labwc ];
  };

  headlessProfile = {
    # No compositor, no panel
    fauxnix.fennix.panel.enabled = false;
    services.openssh.enable = true;
  };
in
{
  options.fauxnix.workspace-profile = {
    win11 = lib.mkOption { type = lib.types.attrs; default = win11Profile; };
    macos = lib.mkOption { type = lib.types.attrs; default = macosProfile; };
    headless = lib.mkOption { type = lib.types.attrs; default = headlessProfile; };
  };
}
```

#### QSS Themes

Fennix's Qt6 panel applies QSS (Qt Style Sheets) per profile:

**win11.qss** — Acrylic blur, Segoe-like font (Inter), rounded elements:
```css
FennixPanel {
    background: rgba(32, 32, 32, 0.85);
    backdrop-filter: blur(20px);
    border: 1px solid rgba(255, 255, 255, 0.08);
}
FennixQuickBar {
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.05);
}
FennixQuickBar::item:selected {
    background: rgba(255, 255, 255, 0.15);
    border-radius: 4px;
}
```

**macos.qss** — Frosted glass, SF-like font, thin separators:
```css
FennixTopBar {
    background: rgba(245, 245, 245, 0.85);
    backdrop-filter: blur(20px);
    border-bottom: 0.5px solid rgba(0, 0, 0, 0.1);
}
FennixDock {
    background: rgba(255, 255, 255, 0.70);
    backdrop-filter: blur(20px);
    border-radius: 16px;
    border: 0.5px solid rgba(0, 0, 0, 0.08);
}
```

### 6.2 Workspace Management in Fennix UI

Extend existing Fennix Qt6 components:

#### Quickbar (`fennix.ui.quickbar`)

Add workspace management entries:

```
┌──────────────────────────────────────┐
│  🔍  Search workspaces...            │
│  ─────────────────────────────────── │
│  📝  ml-paper       running  · win11 │
│  🦀  rust-dev        stopped  · macos│
│  🎨  design          running  · win11│
│  ─────────────────────────────────── │
│  ＋  New workspace...                │
│  ⎇   Fork current workspace...      │
│  ⇄   Merge workspaces...            │
│  📊  Dashboard                        │
└──────────────────────────────────────┘
```

#### System Tray (`fennix.ui.tray`)

Show workspace indicator with context menu:

```
┌─────┐
│ 🖥️  │ → ml-paper (click to switch)
├─────┤
│  𝍇  │ → 2 suggestions (Phase 5 notification count)
└─────┘
```

Right-click → workspace switcher + suggestion inbox.

#### Workspace Window (`fennix.ui.window`)

Full management window with:
- List of workspaces (running/stopped status, resource usage)
- Suggestion inbox (accept/dismiss cards)
- Snapshot timeline browser
- Activity heatmap per workspace

### 6.3 TUI Dashboard

`wsctl dashboard` — Rich terminal UI for headless environments:

```
┌─────────────────────────────────────────────────────────┐
│  FAUXNIX WORKSPACES                    [q] quit  [tab]   │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  📊 Overview                                             │
│  ┌──────────┬─────────┬──────────┬─────────────────────┐│
│  │ Workspace│ Status  │ Profile  │ Last Active         ││
│  ├──────────┼─────────┼──────────┼─────────────────────┤│
│  │ ml-paper │ running │ win11    │ 2 min ago           ││
│  │ rust-dev │ stopped │ macos    │ 3 hours ago         ││
│  │ design   │ running │ win11    │ 5 min ago           ││
│  └──────────┴─────────┴──────────┴─────────────────────┘│
│                                                          │
│  🔗 Workspace Tree                                       │
│  (root)                                                   │
│    ├── ml-paper [running]                                 │
│    │   ├── rust-dev [stopped]  ← forked 2025-07-10       │
│    │   └── vit-training [running]                        │
│    └── design [running]                                   │
│                                                          │
│  💡 Suggestions                                          │
│  [!] Merge 'ml-paper' and 'vit-training'? (87% similar) │
│      [A]ccept  [D]ismiss                                 │
│                                                          │
│  📈 Activity (last 24h)                                  │
│  ml-paper    ████████████████████████████  6.2h          │
│  design      ████████████                  3.1h          │
│  rust-dev    ██                            0.4h          │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

Use `textual` (Python) or `rich` library for rendering.

### 6.4 Waybar/Taskbar Widget

A custom Waybar module that displays current workspace info:

```json
// waybar config
"custom/workspace": {
    "exec": "wsctl current --format waybar",
    "interval": 30,
    "format": "{icon} {}",
    "on-click": "wsctl dashboard",
    "on-click-right": "wsctl suggestions",
}
```

Output format:
```
{"text": "📝 ml-paper", "tooltip": "Profile: win11\nActive: 2h 15m\nSnapshots: 12", "class": "running"}
{"text": "📝 ml-paper · 2", "tooltip": "...", "class": "has-suggestions"}
```

### 6.5 Workspace Templates

Pre-built Nix closures for common tasks, stored as Nix modules:

```
modules/workspace-templates/
├── default.nix          # Aggregator
├── ml-python.nix        # Python, PyTorch, Jupyter, CUDA
├── rust-dev.nix         # Rust toolchain, cargo, rust-analyzer
├── writing.nix          # Pandoc, Zathura, LaTeX, Obsidian
├── browsing.nix         # Firefox isolated profile
├── gaming.nix           # Steam, GPU passthrough, lutris
├── design.nix           # Inkscape, GIMP, Blender, Figma (web)
└── media.nix            # ffmpeg, audacity, kdenlive
```

Each template is a partial NixOS module that extends the workspace container config:

```nix
# ml-python.nix
{ pkgs, ... }: {
  environment.systemPackages = with pkgs; [
    python3
    python3.pkgs.torch
    python3.pkgs.torchvision
    python3.pkgs.jupyter
    python3.pkgs.matplotlib
    python3.pkgs.numpy
    python3.pkgs.pandas
    cudaPackages.cudatoolkit
  ];

  services.fennix-context-agent.enable = true;
}
```

User-definable templates: any workspace can be exported as a template:
```
$ wsctl export ml-paper --as-template ml-research
Template saved: ~/.config/fauxnix/templates/ml-research.nix
```

### 6.6 Documentation

- `man wsctl` — full CLI reference
- `wsctl tutorial` — interactive walkthrough of create/fork/merge/snapshot
- `docs/workspace-system/README.md` — architecture overview (already written)
- Phase documents for contributors

### 6.7 Onboarding Flow

First boot after installing workspace components:

```
$ wsctl setup

Welcome to FauxnixOS Workspace System!

Choose your default desktop feel:
[1] Windows 11 style (bottom taskbar, centered launcher)
[2] macOS style (top menu bar, bottom dock)
[3] Headless (SSH only, no desktop)

> 1

Creating default workspace 'main' with win11 profile...
Starting workspace...

Connect to your workspace:
  ssh main.local         (from base system)
  wsctl attach main      (from base system)
  Or use Fennix quickbar to switch workspaces
```

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Compositor | labwc (wlroots) | Lightweight, configurable, Wayland-native, good for nesting |
| Panel framework | Fennix Qt6 (existing) | Already has tray, quickbar, window components |
| QSS themes | Per-profile Qt Style Sheets | No additional deps, Qt6 supports them natively |
| TUI framework | textual or rich | Python-native, consistent with project stack |
| Templates | Nix modules (partial containers) | Declarative, reproducible, version-controlled |
| Display forwarding | waypipe | Wayland-native, efficient, already packaged in nixpkgs |

## Success Criteria

- [ ] `wsctl create --profile win11` launches workspace with bottom bar, centered quickbar
- [ ] `wsctl create --profile macos` launches workspace with top bar, bottom dock
- [ ] Fennix quickbar shows workspace list and switcher
- [ ] Fennix tray shows current workspace indicator
- [ ] `wsctl dashboard` renders TUI with workspace tree, suggestions, activity
- [ ] Waybar widget shows current workspace name and suggestion count
- [ ] Template creation: `wsctl create --template ml-python` installs Python/PyTorch/Jupyter
- [ ] Template export: `wsctl export <ws> --as-template <name>` works
- [ ] `wsctl tutorial` guides user through create/fork/merge/snapshot in < 5 minutes
- [ ] Onboarding flow runs on first `wsctl setup` invocation
