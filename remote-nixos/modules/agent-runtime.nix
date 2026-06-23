{ fauxnix, ... }:

let
  inherit (fauxnix.paths)
    fauxnixWorkspace
    cowriterWorkspace
    fauxnixKnowledge
    fauxnixThreads
    fauxnixSnapshots
    ;
  inherit (fauxnix.packages) ollamaUpstream;
in
{
  # Local Fauxnix assistant. Ollama listens on all interfaces, but the firewall
  # only trusts Tailscale, so the API is local + tailnet reachable.
  services.ollama = {
    enable = true;
    package = ollamaUpstream;
    host = "0.0.0.0";
    port = 11434;
    openFirewall = false;
    loadModels = [ "qwen3:1.7b" "qwen3:0.6b" ];
    environmentVariables = {
      OLLAMA_LLM_LIBRARY = "cpu";
      OLLAMA_MAX_LOADED_MODELS = "1";
      OLLAMA_NUM_PARALLEL = "1";
    };
  };

  environment.etc."fennix/Modelfile".text = ''
    FROM qwen3:1.7b

    PARAMETER temperature 0.15
    PARAMETER repeat_penalty 1.12
    PARAMETER num_ctx 4096

    SYSTEM """
    You are Fennix, a small CPU-only assistant running on a NixOS ThinkPad node for the Fauxnix project.
    Be concise, practical, and honest about your limits.
    Prefer local diagnostics and simple NixOS commands.
    You can help write inside the Cowriter workspace at ${cowriterWorkspace}.
    You can inspect a bounded workspace rooted at ${fauxnixWorkspace}; the v0 GUI workspace tools are read-only.
    You can consult Fauxnix knowledge notes at ${fauxnixKnowledge} and thread definitions at ${fauxnixThreads}.
    Fauxdex is your bounded workspace loop: observe, plan, inspect, propose, verify, and summarize.
    Faux-pass is the pass-through app provider registry, not a password manager. Use `faux-pass status`, `faux-pass apps`, and `faux-pass run <app>` for local/remote app provider state.
    Visual memory snapshots are captured with `fauxnix-screenshot`; screenshots are stored under ${fauxnixSnapshots}/screenshots.
    Display modes are managed through Wayfire and wlroots-compatible tools; use local evidence before changing compositor state.
    The current desktop target is a Nix-owned SDDM+Wayfire profile that autostarts the Fauxnix workspace. Propose Nix patches, build before switching, and keep rollback notes.
    For heavy reasoning, long code work, or large-context tasks, suggest escalating to the parent node.
    """
  '';
  environment.etc."fennix/FauxnixModelfile".text = ''
    FROM qwen3:0.6b

    PARAMETER temperature 0.1
    PARAMETER repeat_penalty 1.12
    PARAMETER num_ctx 4096

    SYSTEM """
    You are Fauxnix Local, a very small CPU-only helper model for quick local status, settings, and shell-facing answers on FauxnixOS.
    Be brief and practical.
    Prefer deterministic Fauxnix commands and local evidence over speculation.
    Faux-pass is the local/remote app provider registry; it is checked with `faux-pass status` and `faux-pass apps`.
    Visual memory snapshots are captured with `fauxnix-screenshot`.
    Display modes are checked with Wayfire, wlroots-compatible tools, `loginctl`, and local evidence; never invent unsupported resolutions.
    Defer complex coding, planning, or long-context reasoning to Fennix, Fauxdex, or Nexus.
    """
  '';
  environment.etc."fauxshell/fauxd.py".source = ../fauxd.py;
  environment.etc."fennix/gui.py".source = ../fennix-gui.py;
  environment.etc."fennix/fauxdex.py".source = ../fauxdex.py;
  environment.etc."fennix/cowriter.py".source = ../cowriter.py;
  environment.etc."fauxnix/fauxnix-git.sh".source = ../fauxnix-git.sh;
  environment.etc."faux-pass/python/faux_pass".source = ../faux-pass/faux_pass;
  environment.etc."faux-pass/docs/ARCHITECTURE.md".source = ../faux-pass/ARCHITECTURE.md;
  environment.etc."faux-pass/docs/DESIGN.md".source = ../faux-pass/DESIGN.md;
  environment.etc."faux-pass/registry.json".text = ''
    {
      "version": 1,
      "providers": [
        {
          "id": "local",
          "name": "FauxnixOS",
          "type": "local",
          "status": "available",
          "apps": [
            { "id": "web", "name": "Firefox", "action": ["firefox"] },
            { "id": "terminal", "name": "Terminal", "action": ["alacritty"] },
            { "id": "fennix", "name": "Fennix", "action": ["fennix-gui"] },
            { "id": "fauxdex", "name": "Fauxdex", "action": ["alacritty", "-e", "fauxdex", "status"] },
            { "id": "cowriter", "name": "Cowriter", "action": ["alacritty", "--working-directory", "/home/chvk/Fauxnix/Cowriter", "-e", "cowriter", "status"] }
          ]
        },
        {
          "id": "nexus",
          "name": "Nexus Windows Provider",
          "type": "remote-provider",
          "status": "available",
          "transport": "tailscale-http",
          "endpoint": "http://100.126.117.60:4433/faux-pass",
          "token_file": "/etc/faux-pass/nexus.token",
          "apps": [
            { "id": "notepad", "name": "Notepad", "remote": true },
            { "id": "calc", "name": "Calculator", "remote": true },
            { "id": "powershell", "name": "PowerShell", "remote": true },
            { "id": "vscode", "name": "VS Code", "remote": true }
          ]
        }
      ]
    }
  '';

  systemd.services.fauxnix-ollama-local-model = {
    description = "Create the local Fennix and Fauxnix Ollama assistant models";
    after = [ "ollama.service" "ollama-model-loader.service" ];
    requires = [ "ollama.service" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      Environment = [
        "HOME=/var/lib/ollama"
        "OLLAMA_HOST=http://127.0.0.1:11434"
      ];
    };
    path = [ ollamaUpstream ];
    script = ''
      ensure_model() {
        base_model="$1"

        for i in $(seq 1 30); do
          if ollama list | grep -Fq "$base_model"; then
            return 0
          fi
          sleep 2
        done

        if ! ollama list | grep -Fq "$base_model"; then
          ollama pull "$base_model"
        fi
      }

      ensure_model qwen3:1.7b
      ensure_model qwen3:0.6b

      ollama create fennix-local -f /etc/fennix/Modelfile
      ollama create fauxnix-local -f /etc/fennix/FauxnixModelfile
    '';
  };

  system.activationScripts.fennixCowriterWorkspace.text = ''
    install -d -o chvk -g users -m 0755 \
      ${fauxnixWorkspace} \
      ${cowriterWorkspace} \
      ${cowriterWorkspace}/drafts \
      ${cowriterWorkspace}/notes \
      ${cowriterWorkspace}/sessions \
      ${cowriterWorkspace}/outlines \
      ${cowriterWorkspace}/inbox

    if [ ! -e ${cowriterWorkspace}/README.md ]; then
      cat > ${cowriterWorkspace}/README.md <<'EOF'
    # Cowriter Workspace

    This workspace is shared by Fennix and the Fauxnix project.

    ## Folders

    - `drafts/` prose, responses, articles, letters, plans
    - `notes/` durable observations and research notes
    - `sessions/` working logs from conversations
    - `outlines/` structured plans before drafting
    - `inbox/` unsorted fragments to process later

    Use `cowriter new`, `cowriter capture`, `cowriter list`, `cowriter read`, and
    `cowriter search` to work here from the terminal.
    EOF
      chown chvk:users ${cowriterWorkspace}/README.md
      chmod 0644 ${cowriterWorkspace}/README.md
    fi
  '';

  system.activationScripts.fauxnixKnowledgeBase.text = ''
    install -d -o chvk -g users -m 0755 \
      ${fauxnixKnowledge} \
      ${fauxnixKnowledge}/fauxdex \
      ${fauxnixKnowledge}/fauxshell \
      ${fauxnixKnowledge}/desktop \
      ${fauxnixKnowledge}/gnome \
      ${fauxnixKnowledge}/nix \
      ${fauxnixWorkspace}/Repos \
      ${fauxnixThreads} \
      ${fauxnixSnapshots} \
      ${fauxnixSnapshots}/screenshots

    install -o chvk -g users -m 0644 \
      ${../docs/knowledge/README.md} \
      ${fauxnixKnowledge}/README.md
    install -o chvk -g users -m 0644 \
      ${../docs/knowledge/desktop-wayfire-profile.md} \
      ${fauxnixKnowledge}/desktop/wayfire-profile.md
    install -o chvk -g users -m 0644 \
      ${../docs/knowledge/nix-module-map.md} \
      ${fauxnixKnowledge}/nix/module-map.md
    install -o chvk -g users -m 0644 \
      ${../docs/knowledge/rebuild-workflow.md} \
      ${fauxnixKnowledge}/nix/rebuild-workflow.md
    install -o chvk -g users -m 0644 \
      ${../docs/knowledge/screenshot-memory.md} \
      ${fauxnixKnowledge}/fauxshell/screenshot-memory.md
    install -o chvk -g users -m 0644 \
      ${../docs/knowledge/fauxdex-workspace-loop.md} \
      ${fauxnixKnowledge}/fauxdex/workspace-loop.md
    install -o chvk -g users -m 0644 \
      ${../docs/knowledge/threads.md} \
      ${fauxnixThreads}/README.md
    install -o chvk -g users -m 0644 \
      ${../docs/knowledge/gnome-deprecated.md} \
      ${fauxnixKnowledge}/gnome/display-settings.md
    install -o chvk -g users -m 0644 \
      ${../docs/knowledge/gnome-deprecated.md} \
      ${fauxnixKnowledge}/gnome/fresh-profile.md
    install -o chvk -g users -m 0644 \
      ${../docs/knowledge/screenshot-memory.md} \
      ${fauxnixKnowledge}/gnome/screenshot-memory.md

    install -o chvk -g users -m 0644 \
      ${../docs/archivist-file-manager-card.md} \
      ${fauxnixKnowledge}/fauxshell/archivist-file-manager-card.md
    install -o chvk -g users -m 0644 \
      ${../docs/fauxshell-glass.md} \
      ${fauxnixKnowledge}/fauxshell/fauxshell-glass.md
  '';

  environment.etc."fauxnix/assistant.env".text = ''
    FAUXNIX_LOCAL_OLLAMA_URL=http://127.0.0.1:11434
    FAUXNIX_LOCAL_MODEL=fennix-local
    FAUXNIX_FAST_LOCAL_MODEL=fauxnix-local
    FAUXNIX_LOCAL_CODE_MODEL=qwen2.5-coder:14b
    FAUXNIX_PARENT_OLLAMA_URL=http://100.126.117.60:11434
    FAUXNIX_PARENT_MODEL=devstral-small-2:24b
    FAUXNIX_PARENT_ALT_MODEL=granite-code:20b
    FAUXNIX_PARENT_OPENAI_BASE_URL=http://100.126.117.60:8000/v1
    FAUXNIX_WORKSPACE_ROOT=${fauxnixWorkspace}
    FAUXNIX_COWRITER_WORKSPACE=${cowriterWorkspace}
    FAUXNIX_KNOWLEDGE_ROOT=${fauxnixKnowledge}
    FAUXNIX_THREADS_DIR=${fauxnixThreads}
    FAUXNIX_SNAPSHOTS_DIR=${fauxnixSnapshots}
    FAUXNIX_REPOS_ROOT=${fauxnixWorkspace}/Repos
    FAUXNIX_WEATHER_LOCATION=
  '';
}
