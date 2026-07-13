#!/usr/bin/env bash
# Nexus Welcome — first-boot assistant dialog
# Runs on GNOME login, shows thread status and next actions

export PATH="$HOME/.local/bin:$PATH"
WSCTL="$HOME/.local/bin/wsctl"

threads=$($WSCTL list 2>/dev/null | tail -n +3)
running_count=$(echo "$threads" | grep -c "running")
total_count=$(echo "$threads" | wc -l)

if [ "$total_count" -eq 0 ]; then
    choice=$(zenity --list \
        --title="Welcome to FauxnixOS" \
        --text="<big><b>What do you need to do today?</b></big>\n\nNo threads yet. Let's create your first one." \
        --column="Action" --column="Description" \
        --width=550 --height=350 \
        "🚀 Create a coding thread" "Python, Rust, Go, Node.js — all ready" \
        "🧠 Create an ML thread" "PyTorch, Jupyter, NumPy — for data work" \
        "🔬 Create a research thread" "Browser, notes, Zotero — dive deep" \
        "✍️  Create a writing thread" "Pandoc, LaTeX, Zathura — get writing" \
        "🎮 Create a gaming thread" "Steam, Lutris, GameMode — let's play" \
        "📊 Open Dashboard" "Full thread management view" \
        "❌ Close" "I'll explore on my own" 2>/dev/null)
else
    thread_list=""
    while IFS= read -r line; do
        name=$(echo "$line" | awk '{print $1}')
        status=$(echo "$line" | awk '{print $2}')
        icon="○"
        [ "$status" = "running" ] && icon="●"
        thread_list+="$icon $name $status\\n"
    done <<< "$threads"

    choice=$(zenity --list \
        --title="Welcome to FauxnixOS" \
        --text="<big><b>What do you need to do today?</b></big>\n\n$running_count running · $total_count total threads\n\n<i>Would you like to pick up where you left off?</i>" \
        --column="Action" --column="Description" \
        --width=550 --height=450 \
        "🔄 Resume most recent" "Pick up where you left off" \
        "🚀 New thread..." "Create a new workspace" \
        "📊 Open Dashboard" "Full thread management view" \
        "❌ Close" "Maybe later" 2>/dev/null)
fi

case "$choice" in
    "🚀 Create a coding thread")
        $WSCTL ask "coding development work" --profile win11 &
        ;;
    "🧠 Create an ML thread")
        $WSCTL ask "machine learning and data science" --profile win11 &
        ;;
    "🔬 Create a research thread")
        $WSCTL ask "research and web browsing" --profile win11 &
        ;;
    "✍️  Create a writing thread")
        $WSCTL ask "writing and document editing" --profile win11 &
        ;;
    "🎮 Create a gaming thread")
        $WSCTL ask "gaming with steam" --profile win11 &
        ;;
    "🔄 Resume most recent")
        recent=$($WSCTL list 2>/dev/null | tail -n +3 | head -1 | awk '{print $1}')
        if [ -n "$recent" ]; then
            $WSCTL start "$recent" &
            sleep 5
            $WSCTL attach "$recent"
        fi
        ;;
    "🚀 New thread...")
        template=$(zenity --list \
            --title="Choose a template" \
            --text="What kind of work?" \
            --column="Template" --column="Description" \
            --width=500 --height=500 \
            "coding" "Python, Rust, Go, Node.js, C, git, neovim, tmux" \
            "ml-python" "PyTorch, Jupyter, NumPy, Pandas" \
            "research" "Chrome, Firefox, Obsidian, Zotero" \
            "writing" "Pandoc, Zathura, LaTeX" \
            "documents" "LibreOffice, Pandoc, LaTeX, Calibre" \
            "audio" "Ardour, Audacity, LMMS, FFmpeg" \
            "image-video" "GIMP, Inkscape, Blender, Kdenlive" \
            "gaming" "Steam, Lutris, Wine, GameMode" \
            "emulation" "RetroArch, Dolphin, PCSX2, DuckStation" \
            "dvd-ripping" "Handbrake, MakeMKV, FFmpeg, libdvdcss" \
            "web-dev" "Node.js, TypeScript, VS Code" \
            "rust-dev" "cargo, rustc, rust-analyzer" 2>/dev/null)
        if [ -n "$template" ]; then
            profile=$(zenity --list \
                --title="Desktop feel" \
                --text="Which desktop experience?" \
                --column="Profile" --column="Description" \
                --width=450 --height=200 \
                "win11" "Windows 11 — bottom taskbar, acrylic blur" \
                "macos" "macOS — top bar, dock, frosted glass" \
                "headless" "SSH only, no desktop" 2>/dev/null)
            profile=${profile:-win11}
            $WSCTL ask "$template development work" --profile "$profile" &
        fi
        ;;
    "📊 Open Dashboard")
        gnome-terminal -- $WSCTL dashboard &
        ;;
    *)
        ;;
esac
