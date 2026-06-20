# Edit this configuration file to define what should be installed on
# your system.  Help is available in the configuration.nix(5) man page
# and in the NixOS manual (accessible by running ‘nixos-help’).

{ config, lib, pkgs, ... }:

let
  fauxnixWorkspace = "/home/chvk/Fauxnix";
  cowriterWorkspace = "${fauxnixWorkspace}/Cowriter";
  fauxnixKnowledge = "${fauxnixWorkspace}/Knowledge";
  fauxnixThreads = "${fauxnixWorkspace}/Threads";
  workspacePython = pkgs.python3.withPackages (ps: [ ps.pyqt6 ps.pyqt6-webengine ps.faster-whisper ps.xlib ]);
  fauxnixArchivist = import ./archivist-gnome {
    inherit pkgs;
    # Point at the copied archivist-app source for Nix builds.
    # Sync from E:\Archivist\app\ before rebuilding on the remote.
    archivistAppSrc = ./archivist_app;
  };
  workspaceLib = pkgs.stdenvNoCC.mkDerivation {
    pname = "fauxnix-workspace-lib";
    version = "0.1.0";
    src = ./fauxnix_workspace;
    buildPhase = "true";
    installPhase = ''
      mkdir -p $out/lib/fauxnix_workspace
      cp $src/__init__.py $out/lib/fauxnix_workspace/
      cp $src/__main__.py $out/lib/fauxnix_workspace/
      cp $src/canvas.py $out/lib/fauxnix_workspace/
      cp $src/main_window.py $out/lib/fauxnix_workspace/
      cp $src/fauxd_client.py $out/lib/fauxnix_workspace/
      cp $src/theme.py $out/lib/fauxnix_workspace/
      cp $src/otg_server.py $out/lib/fauxnix_workspace/
      cp $src/node_server.py $out/lib/fauxnix_workspace/
      cp $src/node_process.py $out/lib/fauxnix_workspace/
      cp $src/window_manager.py $out/lib/fauxnix_workspace/
      cp $src/window_thumbnail.py $out/lib/fauxnix_workspace/
      mkdir -p $out/lib/fauxnix_workspace/nodes
      cp $src/nodes/__init__.py $out/lib/fauxnix_workspace/nodes/
      cp $src/nodes/node_types.py $out/lib/fauxnix_workspace/nodes/
      mkdir -p $out/lib/fauxnix_workspace/surface_providers
      cp $src/surface_providers/__init__.py $out/lib/fauxnix_workspace/surface_providers/
      cp $src/surface_providers/base.py $out/lib/fauxnix_workspace/surface_providers/
      cp $src/surface_providers/fauxpass_app.py $out/lib/fauxnix_workspace/surface_providers/
      cp $src/surface_providers/registry.py $out/lib/fauxnix_workspace/surface_providers/
      cp $src/surface_providers/xwayland_per_app.py $out/lib/fauxnix_workspace/surface_providers/
      cp $src/surface_providers/test_xwayland.py $out/lib/fauxnix_workspace/surface_providers/
      cp $src/surface_providers/test_app_card.py $out/lib/fauxnix_workspace/surface_providers/
      cp $src/surface_providers/test_app_launcher.py $out/lib/fauxnix_workspace/surface_providers/
      cp $src/surface_providers/test_input.py $out/lib/fauxnix_workspace/surface_providers/
      mkdir -p $out/lib/fauxnix_workspace/examples
      cp $src/examples/*.json $out/lib/fauxnix_workspace/examples/
    '';
  };
  fauxnixSnapshots = "${fauxnixWorkspace}/Snapshots";
  ollamaUpstreamVersion = "0.30.7";
  ollamaUpstream = pkgs.stdenv.mkDerivation {
    pname = "ollama-upstream";
    version = ollamaUpstreamVersion;
    src = pkgs.fetchurl {
      url = "https://ollama.com/download/ollama-linux-amd64.tar.zst?version=${ollamaUpstreamVersion}";
      sha256 = "0k6k0ibn25qmvwfy2d6q72v3q0fvimzg945as1g0w4x9r6k11hc8";
    };
    nativeBuildInputs = [
      pkgs.autoPatchelfHook
      pkgs.zstd
    ];
    buildInputs = [
      pkgs.stdenv.cc.cc.lib
    ];
    dontBuild = true;
    unpackPhase = ''
      tar --use-compress-program=${pkgs.zstd}/bin/unzstd -xf $src
    '';
    installPhase = ''
      runHook preInstall
      mkdir -p $out
      cp -r bin lib $out/
      rm -rf $out/lib/ollama/cuda_v12 $out/lib/ollama/cuda_v13 $out/lib/ollama/vulkan
      runHook postInstall
    '';
    meta = pkgs.ollama.meta // {
      description = "Upstream Ollama binary, patched for NixOS";
      changelog = "https://github.com/ollama/ollama/releases/tag/v${ollamaUpstreamVersion}";
    };
  };
  fauxnixCanvas = pkgs.writeShellApplication {
    name = "fauxnix-workspace";
    runtimeInputs = [
      workspacePython
      pkgs.xwayland
      pkgs.xorg.setxkbmap
      pkgs.xorg.xrdb
      pkgs.xorg.xkbcomp
      pkgs.wlrctl
    ];
    text = ''
      export QT_QPA_PLATFORM=xcb
      export QT_WAYLAND_DISABLE_WINDOWDECORATION=1
      export PYTHONPATH="${workspaceLib}/lib''${PYTHONPATH:+:$PYTHONPATH}"
      exec ${workspacePython}/bin/python3 -m fauxnix_workspace "$@"
    '';
  };
  fauxnixNode = pkgs.writeShellApplication {
    name = "fauxnix-node";
    runtimeInputs = [ workspacePython ];
    text = ''
      export PYTHONPATH="${workspaceLib}/lib''${PYTHONPATH:+:$PYTHONPATH}"
      exec ${workspacePython}/bin/python3 ${workspaceLib}/lib/fauxnix_workspace/node_server.py "$@"
    '';
  };
  fauxnixSddmTheme = pkgs.stdenvNoCC.mkDerivation {
    pname = "fauxnix-sddm-theme";
    version = "0.3.0";
    dontUnpack = true;
    installPhase = ''
      runHook preInstall
      theme_dir="$out/share/sddm/themes/fauxnix-login-v2"
      mkdir -p "$theme_dir"

      cat > "$theme_dir/metadata.desktop" <<'EOF'
[SddmGreeterTheme]
Name=Fauxnix Login
Description=FauxnixOS dark glass login theme
Author=Fauxnix
Copyright=Fauxnix
License=MIT
Type=sddm-theme
Version=0.3.0
MainScript=Main.qml
ConfigFile=theme.conf
Theme-Id=fauxnix-login-v2
Theme-API=2.0
QtVersion=6
EOF

      cat > "$theme_dir/theme.conf" <<'EOF'
[General]
background=#080909
accent=#ff7800
cyan=#00c8ff
EOF

      cat > "$theme_dir/Main.qml" <<'EOF'
import QtQuick 2.0
import SddmComponents 2.0

Rectangle {
    id: root

    property color background: config.background ? config.background : "#080909"
    property color panel: "#b8141619"
    property color panelStrong: "#dd141619"
    property color panelSoft: "#b820242a"
    property color panelSofter: "#88121518"
    property color line: "#38d7dde1"
    property color text: "#f1f2ed"
    property color muted: "#a2a8ad"
    property color accent: config.accent ? config.accent : "#ff7800"
    property color cyan: config.cyan ? config.cyan : "#00c8ff"
    property int unit: Math.max(52, Math.min(width, height) / 14)

    color: background

    TextConstants { id: textConstants }

    signal tryLogin()

    onTryLogin: {
        promptText.text = "Checking credentials..."
        busy.visible = true
        busyAnimation.start()
        sddm.login(userName.text, password.text, session.index)
    }

    Connections {
        target: sddm
        onLoginSucceeded: {
            promptText.text = textConstants.loginSucceeded
            promptBar.color = "#00c8ff"
            busy.visible = false
            busyAnimation.stop()
        }
        onLoginFailed: {
            promptText.text = textConstants.loginFailed
            promptBar.color = "#ff3366"
            password.text = ""
            busy.visible = false
            busyAnimation.stop()
            password.focus = true
        }
        onInformationMessage: {
            promptText.text = message
            promptBar.color = "#ff7800"
            busy.visible = false
            busyAnimation.stop()
        }
    }

    Timer {
        interval: 1000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: {
            var now = new Date()
            timeText.text = Qt.formatTime(now, "h:mm AP")
            dateText.text = Qt.formatDate(now, "dddd, MMMM d")
        }
    }

    Repeater {
        model: screenModel
        Rectangle {
            x: geometry.x
            y: geometry.y
            width: geometry.width
            height: geometry.height
            color: root.background
        }
    }

    Rectangle {
        anchors.fill: parent
        color: "#00000000"

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: Math.max(1, parent.height * 0.28)
            color: "#2200c8ff"
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: Math.max(1, parent.height * 0.32)
            color: "#24ff7800"
        }

        Canvas {
            anchors.fill: parent
            opacity: 0.26
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                ctx.lineWidth = 1
                ctx.strokeStyle = "#00c8ff"
                for (var i = 0; i < 7; i++) {
                    var y = height * (0.18 + i * 0.11)
                    ctx.beginPath()
                    ctx.moveTo(width * 0.08, y)
                    ctx.lineTo(width * 0.92, y + Math.sin(i) * 22)
                    ctx.stroke()
                }
            }
        }
    }

    Rectangle {
        id: glass
        width: Math.min(parent.width - 72, 620)
        height: Math.min(parent.height - 72, 500)
        anchors.centerIn: parent
        radius: 10
        color: panel
        border.color: line
        border.width: 1

        Rectangle {
            anchors.fill: parent
            anchors.margins: 1
            radius: 9
            color: "#00000000"
            border.color: "#18ffffff"
            border.width: 1
        }

        Rectangle {
            width: parent.width
            height: 4
            radius: 2
            color: accent
            opacity: 0.95
        }

        Item {
            id: header
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 34
            height: 126

            Canvas {
                id: foxMark
                width: 72
                height: 72
                anchors.left: parent.left
                anchors.top: parent.top
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    ctx.lineWidth = 6
                    ctx.strokeStyle = root.accent
                    ctx.lineJoin = "miter"
                    ctx.beginPath()
                    ctx.moveTo(36, 17)
                    ctx.lineTo(17, 4)
                    ctx.lineTo(5, 10)
                    ctx.lineTo(16, 39)
                    ctx.lineTo(27, 57)
                    ctx.lineTo(36, 66)
                    ctx.lineTo(45, 57)
                    ctx.lineTo(56, 39)
                    ctx.lineTo(67, 10)
                    ctx.lineTo(55, 4)
                    ctx.closePath()
                    ctx.stroke()
                    ctx.fillStyle = root.accent
                    ctx.beginPath()
                    ctx.moveTo(25, 36)
                    ctx.lineTo(33, 42)
                    ctx.lineTo(21, 44)
                    ctx.closePath()
                    ctx.fill()
                    ctx.beginPath()
                    ctx.moveTo(47, 36)
                    ctx.lineTo(39, 42)
                    ctx.lineTo(51, 44)
                    ctx.closePath()
                    ctx.fill()
                }
            }

            Text {
                anchors.left: foxMark.right
                anchors.leftMargin: 18
                anchors.top: foxMark.top
                text: "FauxnixOS"
                color: accent
                font.pixelSize: 18
                font.bold: true
                font.capitalization: Font.AllUppercase
            }

            Text {
                anchors.left: foxMark.right
                anchors.leftMargin: 18
                anchors.top: foxMark.top
                anchors.topMargin: 30
                text: "Local mind, networked intelligence."
                color: muted
                font.pixelSize: 15
            }

            Text {
                id: timeText
                anchors.right: parent.right
                anchors.top: parent.top
                color: text
                font.pixelSize: 44
                font.bold: true
                horizontalAlignment: Text.AlignRight
            }

            Text {
                id: dateText
                anchors.right: parent.right
                anchors.top: timeText.bottom
                anchors.topMargin: 4
                color: muted
                font.pixelSize: 15
                horizontalAlignment: Text.AlignRight
            }
        }

        Item {
            id: form
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: header.bottom
            anchors.bottom: promptBar.top
            anchors.leftMargin: 42
            anchors.rightMargin: 42
            anchors.bottomMargin: 18

            Text {
                id: userLabel
                anchors.left: parent.left
                anchors.top: parent.top
                color: accent
                text: textConstants.userName
                font.pixelSize: 14
                font.bold: true
            }

            TextBox {
                id: userName
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: userLabel.bottom
                anchors.topMargin: 8
                height: 48
                text: userModel.lastUser ? userModel.lastUser : "chvk"
                color: panelSoft
                borderColor: line
                focusColor: accent
                hoverColor: cyan
                textColor: text
                font.pixelSize: 18
                KeyNavigation.tab: password
            }

            Text {
                id: passwordLabel
                anchors.left: parent.left
                anchors.top: userName.bottom
                anchors.topMargin: 18
                color: accent
                text: textConstants.password
                font.pixelSize: 14
                font.bold: true
            }

            PasswordBox {
                id: password
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: passwordLabel.bottom
                anchors.topMargin: 8
                height: 48
                color: panelSoft
                borderColor: line
                focusColor: accent
                hoverColor: cyan
                textColor: text
                tooltipEnabled: true
                tooltipText: textConstants.capslockWarning
                tooltipFG: text
                tooltipBG: panelStrong
                font.pixelSize: 18
                focus: true
                KeyNavigation.tab: loginButton
                KeyNavigation.backtab: userName
                Keys.onPressed: {
                    if ((event.key === Qt.Key_Return) || (event.key === Qt.Key_Enter)) {
                        root.tryLogin()
                        event.accepted = true
                    }
                }
            }

            Row {
                id: sessionRow
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: password.bottom
                anchors.topMargin: 18
                height: 44
                spacing: 12

                Text {
                    width: 82
                    height: parent.height
                    color: muted
                    text: textConstants.session
                    font.pixelSize: 14
                    verticalAlignment: Text.AlignVCenter
                }

                ComboBox {
                    id: session
                    width: parent.width - 94
                    height: parent.height
                    model: sessionModel
                    index: sessionModel.lastIndex
                    color: panelSoft
                    borderColor: line
                    focusColor: accent
                    hoverColor: cyan
                    textColor: text
                    menuColor: panel
                    font.pixelSize: 16
                    KeyNavigation.tab: loginButton
                    KeyNavigation.backtab: password
                }
            }

            Button {
                id: loginButton
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: sessionRow.bottom
                anchors.topMargin: 18
                height: 50
                text: textConstants.login
                color: panelSoft
                textColor: text
                borderColor: accent
                pressedColor: cyan
                activeColor: accent
                font.pixelSize: 18
                font.bold: true
                KeyNavigation.tab: rebootButton
                KeyNavigation.backtab: session
                onClicked: root.tryLogin()
                Keys.onPressed: {
                    if ((event.key === Qt.Key_Return) || (event.key === Qt.Key_Enter)) {
                        root.tryLogin()
                        event.accepted = true
                    }
                }
            }
        }

        Rectangle {
            id: promptBar
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 34
            anchors.leftMargin: 42
            anchors.rightMargin: 42
            height: 24
            radius: 5
            color: "#00000000"

            Text {
                id: promptText
                anchors.fill: parent
                text: "Sign in to start Sway"
                color: muted
                font.pixelSize: 14
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
        }

        Rectangle {
            id: busy
            anchors.left: promptBar.left
            anchors.right: promptBar.right
            anchors.bottom: promptBar.top
            anchors.bottomMargin: 8
            height: 4
            radius: 2
            color: panelSofter
            visible: false

            Rectangle {
                id: busyIndicator
                width: 80
                height: parent.height
                radius: 2
                color: cyan
            }

            SequentialAnimation {
                id: busyAnimation
                running: false
                loops: Animation.Infinite
                NumberAnimation {
                    target: busyIndicator
                    property: "x"
                    from: 0
                    to: busy.width - busyIndicator.width
                    duration: 900
                }
                NumberAnimation {
                    target: busyIndicator
                    property: "x"
                    to: 0
                    duration: 900
                }
            }
        }

    }

    Row {
        id: powerControls
        z: 50
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 28
        height: 46
        spacing: 12
        layoutDirection: Qt.RightToLeft

        Button {
            id: shutdownButton
            width: 150
            height: parent.height
            text: textConstants.shutdown
            color: panelStrong
            textColor: text
            borderColor: accent
            pressedColor: "#ff3366"
            activeColor: accent
            font.pixelSize: 14
            KeyNavigation.tab: userName
            KeyNavigation.backtab: rebootButton
            onClicked: sddm.powerOff()
        }

        Button {
            id: rebootButton
            width: 150
            height: parent.height
            text: textConstants.reboot
            color: panelStrong
            textColor: text
            borderColor: accent
            pressedColor: cyan
            activeColor: accent
            font.pixelSize: 14
            KeyNavigation.tab: shutdownButton
            KeyNavigation.backtab: loginButton
            onClicked: sddm.reboot()
        }
    }
}
EOF

      runHook postInstall
    '';
  };
  fennixPython = pkgs.python3.withPackages (pythonPackages: [
    pythonPackages.tkinter
  ]);
  fennixChatLauncher = pkgs.writeShellApplication {
    name = "fennix-chat";
    runtimeInputs = with pkgs; [
      systemd
    ];
    text = ''
      set -eu

      if systemctl --user is-active --quiet fennix-chat.service; then
        exit 0
      fi

      exec systemd-run --user --unit=fennix-chat --collect ${fennixPython}/bin/python3 /etc/fennix/gui.py "$@"
    '';
  };
  fennixDesktop = pkgs.makeDesktopItem {
    name = "fennix";
    desktopName = "Fennix";
    genericName = "Local assistant";
    comment = "Fennix local assistant for Fauxnix";
    exec = "fennix-chat";
    startupWMClass = "Fennix";
    terminal = false;
    categories = [ "Utility" ];
  };
  fauxnixRofi = pkgs.rofi;
  fauxnixLock = pkgs.swaylock-effects or pkgs.swaylock;
  fauxnixGit = pkgs.writeShellApplication {
    name = "fauxnix-git";
    runtimeInputs = with pkgs; [
      bash
      coreutils
      findutils
      git
      gnugrep
      gnused
      ollamaUpstream
      rsync
    ];
    text = ''
      exec bash /etc/fauxnix/fauxnix-git.sh "$@"
    '';
  };
  fauxdex = pkgs.writeShellApplication {
    name = "fauxdex";
    runtimeInputs = with pkgs; [
      coreutils
      findutils
      git
      python3
      ripgrep
    ];
    text = ''
      exec python3 /etc/fennix/fauxdex.py "$@"
    '';
  };
  fennixCode = pkgs.writeShellApplication {
    name = "fennix-code";
    runtimeInputs = [
      fauxdex
    ];
    text = ''
      exec fauxdex "$@"
    '';
  };
  fauxfetch = pkgs.writeShellApplication {
    name = "fauxfetch";
    runtimeInputs = with pkgs; [
      bash
      coreutils
      gawk
      gnugrep
      gnused
      iproute2
    ];
    text = ''
      set -eu

      orange="$(printf '\033[38;5;208m')"
      cyan="$(printf '\033[38;5;45m')"
      dim="$(printf '\033[2m')"
      reset="$(printf '\033[0m')"
      bold="$(printf '\033[1m')"

      user="$(id -un 2>/dev/null || printf chvk)"
      host="$(cat /proc/sys/kernel/hostname 2>/dev/null || printf fauxnix)"
      os="$(grep -E '^PRETTY_NAME=' /etc/os-release 2>/dev/null | sed -E 's/^PRETTY_NAME="?([^"]*)"?$/\1/' | head -n 1)"
      os="''${os:-FauxnixOS}"
      kernel="$(uname -r)"
      shell_name="''${SHELL:-unknown}"
      shell_name="''${shell_name##*/}"
      wm="''${XDG_CURRENT_DESKTOP:-Sway}"
      uptime_text="$(awk '{ seconds=int($1); days=int(seconds/86400); hours=int((seconds%86400)/3600); mins=int((seconds%3600)/60); if (days>0) printf "%dd %dh %dm", days, hours, mins; else if (hours>0) printf "%dh %dm", hours, mins; else printf "%dm", mins; }' /proc/uptime)"
      mem_text="$(awk '/MemTotal/ { total=$2 } /MemAvailable/ { avail=$2 } END { used=total-avail; printf "%.1fGiB / %.1fGiB", used/1048576, total/1048576 }' /proc/meminfo)"
      disk_text="$(df -h / | awk 'NR==2 { print $3 " / " $2 " (" $5 ")" }')"
      cpu_text="$(grep -m1 'model name' /proc/cpuinfo | sed 's/model name[[:space:]]*: //; s/(R)//g; s/(TM)//g' | cut -c1-46)"
      model_text="$(cat /sys/devices/virtual/dmi/id/product_version 2>/dev/null || cat /sys/devices/virtual/dmi/id/product_name 2>/dev/null || printf ThinkPad)"
      ip_text="$(ip -brief addr 2>/dev/null | awk '$1 !~ /^lo/ && $3 ~ /^[0-9]/ { print $3; exit }' | cut -d/ -f1)"
      ip_text="''${ip_text:-offline}"
      faux_score=20
      for tool in fauxd fennix-gui fauxdex fennix-code fauxnix-power faux-pass fauxfetch; do
        if command -v "$tool" >/dev/null 2>&1; then
          faux_score=$((faux_score + 6))
        fi
      done
      [ -d "$HOME/Fauxnix/Knowledge" ] && faux_score=$((faux_score + 6))
      [ -d "$HOME/Fauxnix/Threads" ] && faux_score=$((faux_score + 6))
      [ "$faux_score" -gt 82 ] && faux_score=82
      nix_score=$((100 - faux_score))

      logo_lines=(
        ' ##                                                             ##'
        '  ####                                                        ####'
        '  ######                                                   #######'
        '   ########                                              ########'
        '   ##########                                          ##########'
        '   #############                                    #############'
        '    ####  ########                                ########  ####'
        '    #####    ########                          ########    #####'
        '    #####      ########                      ########      #####'
        '     ####        ########                  #######         ####'
        '     #####          ########            ########          #####'
        '     #####            ###########  ###########            #####'
        '      ####               #####        #####               ####'
        '      #####                                              #####'
        '      #####                                              ####'
        '       #####                                            #####'
        '       ######                                          ######'
        '      #######                                          #######'
        '     #######                                            #######'
        '   #######                                                #######'
        ' ########      ##                                  ##      ########'
        '########       ####                              ####       ########'
        ' ########        #####                        #####        ########'
        '   ########        ######                  ######        ########'
        '      #######         ####                ####         #######'
        '        #######          #                #          #######'
        '          ########                                ########'
        '            ########                            ########'
        '              ########                        ########'
        '                ########                    ########'
        '                   ######                  ######'
        '                     #####                #####'
        '                      #####              #####'
        '                       #####            #####'
        '                        #####          #####'
        '                         ####          ####'
        '                          ######    ######'
        '                           ######  ######'
        '                            ###### #####'
        '                              ########'
      )

      info_lines=(
        "''${bold}''${user}@''${host}''${reset}"
        "''${cyan}OS''${reset}       $os"
        "''${cyan}Host''${reset}     $model_text"
        "''${cyan}Kernel''${reset}   $kernel"
        "''${cyan}CPU''${reset}      $cpu_text"
        "''${cyan}WM''${reset}       $wm"
        "''${cyan}Shell''${reset}    $shell_name"
        "''${cyan}Uptime''${reset}   $uptime_text"
        "''${cyan}Memory''${reset}   $mem_text"
        "''${cyan}Disk''${reset}     $disk_text"
        "''${cyan}IP''${reset}       $ip_text"
        "''${orange}faux''${reset}     $faux_score%"
        "''${cyan}nix''${reset}      $nix_score%"
      )

      max="''${#info_lines[@]}"
      if [ "''${#logo_lines[@]}" -gt "$max" ]; then
        max="''${#logo_lines[@]}"
      fi
      for ((i = 0; i < max; i++)); do
        logo="''${logo_lines[$i]:-}"
        info="''${info_lines[$i]:-}"
        printf '%b%-66s%b  %b\n' "$orange" "$logo" "$reset" "$info"
      done
      printf '%b\n' "$dim Orange local mind. Cyan networked compute. $reset"
    '';
  };
  fauxnixFetch = pkgs.writeShellApplication {
    name = "fauxnix-fetch";
    runtimeInputs = [
      fauxfetch
    ];
    text = ''
      exec fauxfetch "$@"
    '';
  };
  fauxnixScreenshot = pkgs.writeShellApplication {
    name = "fauxnix-screenshot";
    runtimeInputs = with pkgs; [
      bash
      coreutils
      glib
      gnugrep
      gnused
      python3
      systemd
    ] ++ lib.optionals (builtins.hasAttr "ffmpeg-headless" pkgs) [
      pkgs.ffmpeg-headless
    ] ++ lib.optionals (builtins.hasAttr "gnome-screenshot" pkgs) [
      pkgs.gnome-screenshot
    ];
    text = ''
      set -eu

      method=auto
      output=""
      json=0
      snapshot_dir="''${FAUXNIX_SNAPSHOTS_DIR:-${fauxnixSnapshots}}/screenshots"

      usage() {
        printf '%s\n' \
          'usage: fauxnix-screenshot [capture] [output.png]' \
          '       fauxnix-screenshot --method auto|screencast|gnome|dbus|fb [output.png]' \
          '       fauxnix-screenshot --json [output.png]' \
          '       fauxnix-screenshot status' \
          >&2
        exit 2
      }

      status() {
        echo "snapshot_dir=$snapshot_dir"
        if [ -e "$snapshot_dir/latest.png" ]; then
          echo "latest=$snapshot_dir/latest.png"
        else
          echo "latest="
        fi
      }

      while [ "$#" -gt 0 ]; do
        case "$1" in
          capture)
            ;;
          status)
            status
            exit 0
            ;;
          --method)
            shift
            [ "$#" -gt 0 ] || usage
            method="$1"
            ;;
          --json)
            json=1
            ;;
          --dir)
            shift
            [ "$#" -gt 0 ] || usage
            snapshot_dir="$1"
            ;;
          -o|--output)
            shift
            [ "$#" -gt 0 ] || usage
            output="$1"
            ;;
          -h|--help)
            usage
            ;;
          *)
            output="$1"
            ;;
        esac
        shift
      done

      case "$method" in
        auto|screencast|gnome|dbus|fb) ;;
        *) usage ;;
      esac

      mkdir -p "$snapshot_dir"
      if [ -z "''${XDG_RUNTIME_DIR:-}" ]; then
        runtime_dir="/run/user/$(id -u)"
        export XDG_RUNTIME_DIR="$runtime_dir"
      fi
      if [ -z "''${DBUS_SESSION_BUS_ADDRESS:-}" ] && [ -S "$XDG_RUNTIME_DIR/bus" ]; then
        export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
      fi
      user_env="$snapshot_dir/.fauxnix-screenshot-env.$$"
      if systemctl --user show-environment > "$user_env" 2>/dev/null; then
        while IFS='=' read -r key value; do
          case "$key" in
            DISPLAY|WAYLAND_DISPLAY|XAUTHORITY|XDG_CURRENT_DESKTOP|XDG_SESSION_TYPE|DBUS_SESSION_BUS_ADDRESS)
              export "$key=$value"
              ;;
          esac
        done < "$user_env"
      fi
      rm -f "$user_env"

      if [ -z "$output" ]; then
        output="$snapshot_dir/$(date +%Y%m%d-%H%M%S)-screen.png"
      else
        case "$output" in
          */*) ;;
          *) output="$snapshot_dir/$output" ;;
        esac
        case "$output" in
          *.png) ;;
          *) output="$output.png" ;;
        esac
      fi
      mkdir -p "$(dirname "$output")"

      base="$(basename "$output")"
      tmp="$(dirname "$output")/.$base.tmp.$$.png"
      err="$tmp.err"
      method_used=""

      try_gnome_cli() {
        command -v gnome-screenshot >/dev/null 2>&1 || return 1
        rm -f "$tmp"
        timeout 4s gnome-screenshot -f "$tmp" >"$err" 2>&1 || return 1
        [ -s "$tmp" ] || return 1
        method_used=gnome-screenshot
      }

      try_gnome_dbus() {
        command -v gdbus >/dev/null 2>&1 || return 1
        rm -f "$tmp"
        timeout 4s gdbus call --session \
          --dest org.gnome.Shell.Screenshot \
          --object-path /org/gnome/Shell/Screenshot \
          --method org.gnome.Shell.Screenshot.Screenshot \
          false true "$tmp" >"$err" 2>&1 || return 1
        [ -s "$tmp" ] || return 1
        method_used=gnome-dbus
      }

      try_screencast() {
        command -v gdbus >/dev/null 2>&1 || return 1
        command -v ffmpeg >/dev/null 2>&1 || return 1
        rm -f "$tmp"
        clip_template="$(dirname "$tmp")/.$base.clip-%d.webm"
        rm -f "$(dirname "$tmp")/.$base.clip-"*.webm 2>/dev/null || true

        saved_banners=""
        restore_banners=0
        if command -v gsettings >/dev/null 2>&1; then
          saved_banners="$(gsettings get org.gnome.desktop.notifications show-banners 2>/dev/null || true)"
          if [ "$saved_banners" = "true" ]; then
            if gsettings set org.gnome.desktop.notifications show-banners false >/dev/null 2>&1; then
              restore_banners=1
            fi
          fi
        fi

        screencast_ok=0
        clip=""
        if timeout 4s gdbus call --session \
          --dest org.gnome.Shell.Screencast \
          --object-path /org/gnome/Shell/Screencast \
          --method org.gnome.Shell.Screencast.Screencast \
          "$clip_template" "{}" >"$err" 2>&1; then
          sleep 1
          gdbus call --session \
            --dest org.gnome.Shell.Screencast \
            --object-path /org/gnome/Shell/Screencast \
            --method org.gnome.Shell.Screencast.StopScreencast >>"$err" 2>&1 || true
          for candidate in "$(dirname "$tmp")/.$base.clip-"*.webm; do
            if [ -s "$candidate" ]; then
              clip="$candidate"
              break
            fi
          done
          if [ -n "$clip" ] && [ -s "$clip" ]; then
            if timeout 8s ffmpeg -y -hide_banner -loglevel error -i "$clip" -frames:v 1 "$tmp" >>"$err" 2>&1 && [ -s "$tmp" ]; then
              screencast_ok=1
            fi
          fi
        fi

        if [ "$restore_banners" -eq 1 ]; then
          gsettings set org.gnome.desktop.notifications show-banners "$saved_banners" >/dev/null 2>&1 || true
        fi

        [ "$screencast_ok" -eq 1 ] || return 1
        rm -f "$clip"
        method_used=gnome-screencast
      }

      try_fb() {
        python3 - "$tmp" >"$err" 2>&1 <<'PY'
import binascii
import os
import struct
import sys
import zlib
from pathlib import Path

out = Path(sys.argv[1])
fb = Path(os.environ.get("FAUXNIX_FRAMEBUFFER", "/dev/fb0"))
root = Path("/sys/class/graphics/fb0")

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()

width, height = [int(part) for part in read_text(root / "virtual_size").split(",", 1)]
bpp = int(read_text(root / "bits_per_pixel"))
stride_path = root / "stride"
stride = int(read_text(stride_path)) if stride_path.exists() else width * (bpp // 8)
if bpp != 32:
    raise SystemExit(f"unsupported framebuffer depth: {bpp}")

with fb.open("rb", buffering=0) as handle:
    raw = handle.read(stride * height)
if len(raw) < stride * height:
    raise SystemExit("short framebuffer read")

scanlines = []
for y in range(height):
    row = raw[y * stride : y * stride + width * 4]
    rgba = bytearray(width * 4)
    for src in range(0, width * 4, 4):
        # i915drmfb exposes little-endian XRGB8888: B, G, R, unused.
        rgba[src] = row[src + 2]
        rgba[src + 1] = row[src + 1]
        rgba[src + 2] = row[src]
        rgba[src + 3] = 255
    scanlines.append(b"\x00" + bytes(rgba))

def chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)
    )

png = [
    b"\x89PNG\r\n\x1a\n",
    chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
    chunk(b"IDAT", zlib.compress(b"".join(scanlines), 6)),
    chunk(b"IEND", b""),
]
out.write_bytes(b"".join(png))
PY
        method_used=framebuffer
      }

      capture_ok=0
      case "$method" in
        auto)
          if try_gnome_dbus || try_screencast || try_gnome_cli || try_fb; then
            capture_ok=1
          fi
          ;;
        screencast)
          if try_screencast; then capture_ok=1; fi
          ;;
        gnome)
          if try_gnome_cli; then capture_ok=1; fi
          ;;
        dbus)
          if try_gnome_dbus; then capture_ok=1; fi
          ;;
        fb)
          if try_fb; then capture_ok=1; fi
          ;;
      esac

      if [ "$capture_ok" -ne 1 ]; then
        echo "screenshot failed" >&2
        if [ -s "$err" ]; then
          sed -n '1,8p' "$err" >&2
        fi
        rm -f "$tmp" "$err"
        exit 1
      fi

      mv "$tmp" "$output"
      chmod 0644 "$output"
      ln -sfn "$output" "$snapshot_dir/latest.png" 2>/dev/null || cp "$output" "$snapshot_dir/latest.png"

      meta="$output.json"
      python3 - "$output" "$meta" "$method_used" <<'PY'
import json
import os
import sys
import time
from pathlib import Path

path = Path(sys.argv[1])
meta = Path(sys.argv[2])
payload = {
    "path": str(path),
    "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "method": sys.argv[3],
    "size_bytes": path.stat().st_size,
}
meta.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
      rm -f "$err"

      if [ "$json" -eq 1 ]; then
        cat "$meta"
      else
        echo "$output"
        echo "method=$method_used"
      fi
    '';
  };
  fauxnixSettings = pkgs.writeShellApplication {
    name = "fauxnix-settings";
    runtimeInputs = with pkgs; [
      bash
      coreutils
      gnugrep
    ];
    text = ''
      set -eu

      config_dir="''${XDG_CONFIG_HOME:-$HOME/.config}/fauxnix"
      settings="$config_dir/settings.env"
      mkdir -p "$config_dir"

      get_key() {
        key="$1"
        if [ ! -r "$settings" ]; then
          return 1
        fi
        grep -E "^$key=" "$settings" | tail -n 1 | cut -d= -f2- || true
      }

      set_key() {
        key="$1"
        value="$2"
        tmp="$settings.tmp.$$"
        if [ -r "$settings" ]; then
          grep -Ev "^$key=" "$settings" > "$tmp" || true
        else
          : > "$tmp"
        fi
        printf '%s=%s\n' "$key" "$value" >> "$tmp"
        mv "$tmp" "$settings"
        chmod 0600 "$settings"
      }

      usage() {
        printf '%s\n' \
          'usage: fauxnix-settings weather-location [location]' \
          '       fauxnix-settings status' \
          >&2
        exit 2
      }

      cmd="''${1:-status}"
      case "$cmd" in
        weather-location|weather)
          shift || true
          if [ "$#" -eq 0 ]; then
            value="$(get_key FAUXNIX_WEATHER_LOCATION || true)"
            if [ -n "$value" ]; then
              echo "$value"
            else
              echo "weather location is not set"
            fi
          else
            location="$*"
            set_key FAUXNIX_WEATHER_LOCATION "$location"
            echo "weather location set to $location"
          fi
            ;;
        status)
          echo "settings=$settings"
          echo "weather_location=$(get_key FAUXNIX_WEATHER_LOCATION || true)"
          ;;
        *)
          usage
          ;;
      esac
    '';
  };
  fauxnixDisplay = pkgs.writeShellApplication {
    name = "fauxnix-display";
    runtimeInputs = with pkgs; [
      bash
      coreutils
      gawk
      gnugrep
      gnused
      jq
      sway
    ];
    text = ''
      set -eu

      usage() {
        printf '%s\n' \
          'usage: fauxnix-display status [output]' \
          '       fauxnix-display modes [output]' \
          '       fauxnix-display set <mode> [output]' \
          '       fauxnix-display set <output> <mode>' \
          "" \
          'mode examples: 1600x900, 1600x900@60Hz, 1600x900@40.003Hz' \
          >&2
        exit 2
      }

      ensure_sway() {
        export XDG_RUNTIME_DIR="''${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
        if [ -z "''${SWAYSOCK:-}" ] || [ ! -S "''${SWAYSOCK:-}" ]; then
          for sock in "$XDG_RUNTIME_DIR"/sway-ipc.*.sock; do
            if [ -S "$sock" ]; then
              export SWAYSOCK="$sock"
              break
            fi
          done
        fi
        if [ -z "''${SWAYSOCK:-}" ] || [ ! -S "''${SWAYSOCK:-}" ]; then
          echo "sway socket not found for this user" >&2
          exit 1
        fi
      }

      outputs_json() {
        ensure_sway
        swaymsg -t get_outputs
      }

      default_output_from_json() {
        jq -r 'map(select(.active)) | .[0].name // empty'
      }

      output_exists() {
        json="$1"
        output="$2"
        [ -n "$(printf '%s' "$json" | jq -r --arg output "$output" '.[] | select(.name==$output) | .name' | head -n 1)" ]
      }

      status_output() {
        json="$(outputs_json)"
        output="''${1:-}"
        if [ -z "$output" ]; then
          output="$(printf '%s' "$json" | default_output_from_json)"
        fi
        if [ -z "$output" ] || ! output_exists "$json" "$output"; then
          echo "display output not found" >&2
          exit 1
        fi

        printf 'output=%s\n' "$output"
        printf '%s' "$json" | jq -r --arg output "$output" '
          .[] | select(.name==$output) |
          "current=\((.current_mode.width // 0))x\((.current_mode.height // 0))@\(((.current_mode.refresh // 0) / 1000)|tostring)Hz",
          "scale=\(.scale)",
          "make=\(.make // "unknown")",
          "model=\(.model // "unknown")",
          "active=\(.active)",
          "supported_modes=\([.modes[] | "\(.width)x\(.height)@\((.refresh / 1000)|tostring)Hz"] | join(", "))"
        '
      }

      list_modes() {
        json="$(outputs_json)"
        output="''${1:-}"
        if [ -z "$output" ]; then
          output="$(printf '%s' "$json" | default_output_from_json)"
        fi
        if [ -z "$output" ] || ! output_exists "$json" "$output"; then
          echo "display output not found" >&2
          exit 1
        fi

        printf '%s' "$json" | jq -r --arg output "$output" '
          .[] | select(.name==$output) |
          .modes[] |
          "\(.width)x\(.height)@\((.refresh / 1000)|tostring)Hz"
        '
      }

      parse_mode() {
        raw="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[[:space:]]+//g; s/hz$//')"
        if ! printf '%s' "$raw" | grep -Eq '^[0-9]{3,5}x[0-9]{3,5}(@[0-9]+(\.[0-9]+)?)?$'; then
          echo "invalid mode: $1" >&2
          usage
        fi
        width="''${raw%x*}"
        rest="''${raw#*x}"
        height="''${rest%@*}"
        refresh=""
        if [ "$rest" != "$height" ]; then
          refresh="''${rest#*@}"
        fi
      }

      refresh_for_mode() {
        json="$1"
        output="$2"
        width="$3"
        height="$4"
        refresh="$5"

        if [ -n "$refresh" ]; then
          requested_mhz="$(awk -v hz="$refresh" 'BEGIN { printf "%d", (hz * 1000) + 0.5 }')"
          printf '%s' "$json" | jq -r \
            --arg output "$output" \
            --argjson width "$width" \
            --argjson height "$height" \
            --argjson requested "$requested_mhz" '
              .[] | select(.name==$output) |
              .modes[] |
              select(.width==$width and .height==$height) |
              ((.refresh - $requested) as $delta | (if $delta < 0 then -$delta else $delta end)) as $diff |
              select($diff <= 1000) |
              "\($diff)\t\(.refresh)"
            ' | sort -n | head -n 1 | awk '{ print $2 }'
        else
          printf '%s' "$json" | jq -r \
            --arg output "$output" \
            --argjson width "$width" \
            --argjson height "$height" '
              .[] | select(.name==$output) |
              .modes[] |
              select(.width==$width and .height==$height) |
              .refresh
            ' | sort -nr | head -n 1
        fi
      }

      set_mode() {
        if [ "$#" -eq 1 ]; then
          mode="$1"
          output=""
        elif [ "$#" -eq 2 ]; then
          if printf '%s' "$1" | grep -Eq '^[0-9]{3,5}[[:space:]]*x'; then
            mode="$1"
            output="$2"
          else
            output="$1"
            mode="$2"
          fi
        else
          usage
        fi

        parse_mode "$mode"
        ensure_sway
        json="$(outputs_json)"
        if [ -z "$output" ]; then
          output="$(printf '%s' "$json" | default_output_from_json)"
        fi
        if [ -z "$output" ] || ! output_exists "$json" "$output"; then
          echo "display output not found" >&2
          exit 1
        fi

        refresh_mhz="$(refresh_for_mode "$json" "$output" "$width" "$height" "$refresh")"
        if [ -z "$refresh_mhz" ]; then
          echo "unsupported display mode for $output: $mode" >&2
          echo "supported modes:" >&2
          list_modes "$output" >&2
          exit 1
        fi

        refresh_hz="$(awk -v mhz="$refresh_mhz" 'BEGIN { printf "%.3f", mhz / 1000 }')"
        mode_spec="$(printf '%sx%s@%sHz' "$width" "$height" "$refresh_hz")"
        swaymsg output "$output" mode "$mode_spec" >/dev/null
        echo "display mode set: $output $mode_spec"
      }

      cmd="''${1:-status}"
      case "$cmd" in
        status)
          shift || true
          [ "$#" -le 1 ] || usage
          status_output "''${1:-}"
          ;;
        modes|resolutions)
          shift || true
          [ "$#" -le 1 ] || usage
          list_modes "''${1:-}"
          ;;
        set)
          shift || true
          set_mode "$@"
          ;;
        *)
          usage
          ;;
      esac
    '';
  };
  fauxPass = pkgs.writeShellApplication {
    name = "faux-pass";
    runtimeInputs = with pkgs; [
      python3
    ];
    text = ''
      export PYTHONPATH=/etc/faux-pass/python''${PYTHONPATH:+:$PYTHONPATH}
      exec python3 -m faux_pass.cli "$@"
    '';
  };
  fauxnixThreadLauncher = pkgs.writeShellApplication {
    name = "fauxnix-thread";
    runtimeInputs = with pkgs; [
      alacritty
      bash
      coreutils
      fauxdex
      fauxnixGit
      firefox
      sudo
      sway
      fauxnixRofi
    ];
    text = ''
      set -eu
      export PATH=/run/wrappers/bin:/run/current-system/sw/bin:$PATH

      workspace_root="''${FAUXNIX_WORKSPACE_ROOT:-${fauxnixWorkspace}}"
      cmd="''${1:-list}"

      wm_msg() {
        if [ -n "''${SWAYSOCK:-}" ] && command -v swaymsg >/dev/null 2>&1; then
          swaymsg "$@"
        fi
      }

      list_threads() {
        printf '%s\n' \
          fennix \
          fauxnix \
          fauxdex \
          cowriter \
          admin \
          root \
          web \
          terminal
      }

      open_terminal() {
        dir="$1"
        shift
        if [ "$#" -gt 0 ]; then
          exec alacritty --working-directory "$dir" -e "$@"
        fi
        exec alacritty --working-directory "$dir"
      }

      open_root_terminal() {
        # shellcheck disable=SC2016
        open_terminal "$workspace_root" bash -lc '
          set +e
          clear
          echo "Fauxnix Root Thread"
          echo
          echo "Enter the root password to open a root login shell."
          echo "If authentication fails, this window will stay open with the error."
          echo
          if [ -x /run/wrappers/bin/su ]; then
            /run/wrappers/bin/su -
          else
            su -
          fi
          status=$?
          echo
          echo "Root thread exited with status $status."
          printf "Press Enter to close..."
          IFS= read -r _
        '
      }

      case "$cmd" in
        list)
          list_threads
          ;;
        menu)
          choice="$(list_threads | rofi -dmenu -p Threads)"
          [ -n "$choice" ] || exit 0
          exec "$0" "$choice"
          ;;
        fennix)
          wm_msg 'workspace 1:Fennix'
          exec fennix-gui
          ;;
        fauxnix)
          wm_msg 'workspace 2:Fauxnix'
          open_terminal "$workspace_root"
          ;;
        fauxdex|code)
          wm_msg 'workspace 2:Fauxnix'
          open_terminal "$workspace_root" bash -lc 'fauxdex status; exec bash'
          ;;
        cowriter)
          wm_msg 'workspace 3:Cowriter'
          open_terminal "$workspace_root/Cowriter" bash -lc 'cowriter status; exec bash'
          ;;
        admin)
          wm_msg 'workspace 6:Ops'
          open_terminal "$workspace_root" bash -lc 'fauxnix-git status; exec bash'
          ;;
        root)
          wm_msg 'workspace 6:Ops'
          open_root_terminal
          ;;
        web)
          wm_msg 'workspace 5:Web'
          exec firefox
          ;;
        terminal)
          wm_msg 'workspace 4:Terminal'
          open_terminal "$HOME"
          ;;
        *)
          echo "unknown thread: $cmd" >&2
          echo "available threads:" >&2
          list_threads >&2
          exit 2
          ;;
      esac
    '';
  };
  fauxd = pkgs.writeShellApplication {
    name = "fauxd";
    runtimeInputs = [
      pkgs.python3
      fauxnixThreadLauncher
      fauxnixRofi
    ];
    text = ''
      export PATH=/run/current-system/sw/bin:$PATH
      exec python3 /etc/fauxshell/fauxd.py "$@"
    '';
  };
  fauxnixPower = pkgs.writeShellApplication {
    name = "fauxnix-power";
    runtimeInputs = with pkgs; [
      bash
      brightnessctl
      coreutils
      gnugrep
      gnused
      python3
      procps
      fauxnixLock
      swayidle
    ];
    text = ''
      set -eu

      config_dir="''${XDG_CONFIG_HOME:-$HOME/.config}/fauxnix"
      state_dir="''${XDG_STATE_HOME:-$HOME/.local/state}/fauxnix"
      runtime_dir="''${XDG_RUNTIME_DIR:-/tmp}/fauxnix"
      config="$config_dir/power.env"
      assistant_config="/etc/fauxnix/assistant.env"
      settings="$config_dir/settings.env"
      pid_file="$runtime_dir/swayidle.pid"
      dim_pid_file="$runtime_dir/dim-loop.pid"
      pause_file="$runtime_dir/dim-paused-until"
      log_file="$state_dir/power.log"

      mkdir -p "$config_dir" "$state_dir" "$runtime_dir"

      write_default_config() {
        if [ ! -e "$config" ]; then
          printf '%s\n' \
            'FAUXNIX_DIM_TIMEOUT_SECONDS=300' \
            'FAUXNIX_DIM_PERCENT=25' \
            'FAUXNIX_DIM_FADE_SECONDS=180' \
            > "$config"
        fi
      }

      load_config() {
        write_default_config
        # shellcheck disable=SC1090
        . "$config"
        timeout_seconds="''${FAUXNIX_DIM_TIMEOUT_SECONDS:-300}"
        dim_percent="''${FAUXNIX_DIM_PERCENT:-25}"
        fade_seconds="''${FAUXNIX_DIM_FADE_SECONDS:-180}"
      }

      duration_to_seconds() {
        raw="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[[:space:]]//g')"
        number="$(printf '%s' "$raw" | sed 's/[^0-9]//g')"
        if [ -z "$number" ]; then
          echo "duration must include a number, for example 5m or 300" >&2
          exit 2
        fi

        case "$raw" in
          *hour|*hours|*hr|*hrs|*h) echo $((number * 3600)) ;;
          *minute|*minutes|*min|*mins|*m) echo $((number * 60)) ;;
          *second|*seconds|*sec|*secs|*s) echo "$number" ;;
          *) echo "$number" ;;
        esac
      }

      format_seconds() {
        seconds="$1"
        if [ "$seconds" -ge 3600 ] && [ $((seconds % 3600)) -eq 0 ]; then
          value=$((seconds / 3600))
          if [ "$value" -eq 1 ]; then
            echo "1 hour"
          else
            echo "$value hours"
          fi
        elif [ "$seconds" -ge 60 ] && [ $((seconds % 60)) -eq 0 ]; then
          value=$((seconds / 60))
          if [ "$value" -eq 1 ]; then
            echo "1 minute"
          else
            echo "$value minutes"
          fi
        else
          echo "$seconds seconds"
        fi
      }

      save_config() {
        seconds="$1"
        percent="$2"
        fade="$3"
        printf '%s\n' \
          "FAUXNIX_DIM_TIMEOUT_SECONDS=$seconds" \
          "FAUXNIX_DIM_PERCENT=$percent" \
          "FAUXNIX_DIM_FADE_SECONDS=$fade" \
          > "$config"
      }

      read_env_value() {
        key="$1"
        file="$2"
        if [ ! -r "$file" ]; then
          return 1
        fi
        grep -E "^$key=" "$file" | tail -n 1 | cut -d= -f2- | sed "s/^['\"]//; s/['\"]$//" || true
      }

      setting_value() {
        key="$1"
        value="$(read_env_value "$key" "$settings" || true)"
        if [ -n "$value" ]; then
          echo "$value"
          return
        fi
        read_env_value "$key" "$assistant_config" || true
      }

      paused_remaining() {
        if [ ! -r "$pause_file" ]; then
          echo 0
          return
        fi
        until="$(cat "$pause_file" 2>/dev/null || echo 0)"
        now="$(date +%s)"
        case "$until" in
          *[!0-9]*|"") echo 0 ;;
          *)
            if [ "$until" -gt "$now" ]; then
              echo $((until - now))
            else
              rm -f "$pause_file"
              echo 0
            fi
            ;;
        esac
      }

      stop_idle() {
        if [ -r "$pid_file" ]; then
          pid="$(cat "$pid_file" 2>/dev/null || true)"
          case "$pid" in
            ""|*[!0-9]*) ;;
            *)
              if kill -0 "$pid" 2>/dev/null; then
                kill "$pid" 2>/dev/null || true
              fi
              ;;
          esac
          rm -f "$pid_file"
        fi
      }

      stop_dim_loop() {
        if [ -r "$dim_pid_file" ]; then
          pid="$(cat "$dim_pid_file" 2>/dev/null || true)"
          case "$pid" in
            ""|*[!0-9]*) ;;
            *)
              if kill -0 "$pid" 2>/dev/null; then
                kill "$pid" 2>/dev/null || true
              fi
              ;;
          esac
          rm -f "$dim_pid_file"
        fi
      }

      weather_label() {
        location="$(setting_value FAUXNIX_WEATHER_LOCATION)"
        if [ -z "$location" ]; then
          echo ""
          return
        fi

        python3 - "$location" <<'PY'
import sys
import urllib.error
import urllib.parse
import urllib.request

location = sys.argv[1].strip()
if not location:
    print("Weather not configured")
    raise SystemExit(0)

url = "https://wttr.in/" + urllib.parse.quote(location) + "?format=%l:+%c+%t,+%C"
request = urllib.request.Request(url, headers={"User-Agent": "fauxnix-lock"})
try:
    with urllib.request.urlopen(request, timeout=4) as response:
        text = response.read(180).decode("utf-8", errors="replace").strip()
except (OSError, urllib.error.URLError, TimeoutError):
    text = location
print(text or location)
PY
      }

      telemetry_label() {
        python3 <<'PY'
import os
from pathlib import Path

cpu_count = max(os.cpu_count() or 1, 1)
try:
    load = os.getloadavg()[0]
except OSError:
    load = 0.0
load_pct = max(0, min(int(round((load / cpu_count) * 100)), 100))

meminfo = {}
for line in Path("/proc/meminfo").read_text(errors="ignore").splitlines():
    parts = line.split()
    if len(parts) >= 2:
        meminfo[parts[0].rstrip(":")] = int(parts[1])
total = meminfo.get("MemTotal", 0)
available = meminfo.get("MemAvailable", 0)
ram_pct = 0
if total:
    ram_pct = max(0, min(int(round(((total - available) / total) * 100)), 100))

battery = "BAT n/a"
for bat in sorted(Path("/sys/class/power_supply").glob("BAT*")):
    capacity = (bat / "capacity").read_text(errors="ignore").strip() if (bat / "capacity").exists() else ""
    status = (bat / "status").read_text(errors="ignore").strip().lower() if (bat / "status").exists() else ""
    if capacity:
        battery = f"BAT {capacity}%" + (f" {status}" if status else "")
        break

net = "NET offline"
for iface in sorted(Path("/sys/class/net").iterdir()):
    name = iface.name
    if name == "lo":
        continue
    state_path = iface / "operstate"
    state = state_path.read_text(errors="ignore").strip() if state_path.exists() else ""
    if state == "up":
        net = f"NET {name}"
        break

print(f"CPU load {load_pct}%   RAM {ram_pct}%   {battery}   {net}")
PY
      }

      lock_status_label() {
        weather="$(weather_label)"
        telemetry="$(telemetry_label)"
        if [ -n "$weather" ]; then
          echo "$weather   |   $telemetry"
        else
          echo "$telemetry"
        fi
      }

      lock_screen() {
        lock_info="$(lock_status_label)"
        if swaylock --help 2>&1 | grep -q -- '--clock'; then
          if swaylock \
            --daemonize \
            --ignore-empty-password \
            --show-failed-attempts \
            --screenshots \
            --effect-blur 18x5 \
            --effect-vignette 0.45:0.85 \
            --clock \
            --timestr '%I:%M %p' \
            --datestr "$lock_info" \
            --indicator \
            --indicator-radius 110 \
            --indicator-thickness 8 \
            --inside-color 090b10dd \
            --inside-clear-color 10202bdd \
            --inside-caps-lock-color 281600dd \
            --inside-ver-color 101a22dd \
            --inside-wrong-color 2a0810dd \
            --ring-color ff7800dd \
            --ring-clear-color 00c8ffdd \
            --ring-caps-lock-color ffb000dd \
            --ring-ver-color 00c8ffdd \
            --ring-wrong-color ff3366dd \
            --line-color 00000000 \
            --separator-color 00000000 \
            --text-color f4f7ffee \
            --text-clear-color f4f7ffee \
            --text-caps-lock-color f4f7ffee \
            --text-ver-color f4f7ffee \
            --text-wrong-color f4f7ffee \
            >/dev/null 2>&1; then
            return
          fi
        fi

        swaylock \
          --daemonize \
          --ignore-empty-password \
          --show-failed-attempts \
          --color 080a0f \
          --indicator \
          --indicator-radius 110 \
          --indicator-thickness 8 \
          --inside-color 090b10dd \
          --ring-color ff7800dd \
          --line-color 00000000 \
          --separator-color 00000000 \
          --text-color f4f7ffee \
          >/dev/null 2>&1 || true
      }

      fade_and_lock() {
        load_config
        remaining="$(paused_remaining)"
        if [ "$remaining" -gt 0 ]; then
          exit 0
        fi

        current="$(brightnessctl get 2>/dev/null || echo 0)"
        max="$(brightnessctl max 2>/dev/null || echo 100)"
        case "$current" in
          *[!0-9]*|"") current=0 ;;
        esac
        case "$max" in
          *[!0-9]*|""|0) max=100 ;;
        esac
        if [ "$current" -le 0 ]; then
          current="$max"
        fi
        brightnessctl -s set "$current" >/dev/null 2>&1 || true

        steps=36
        if [ "$fade_seconds" -lt 30 ]; then
          fade_seconds=30
        fi
        sleep_seconds=$((fade_seconds / steps))
        if [ "$sleep_seconds" -lt 1 ]; then
          sleep_seconds=1
        fi

        index=1
        while [ "$index" -le "$steps" ]; do
          remaining="$(paused_remaining)"
          if [ "$remaining" -gt 0 ]; then
            exit 0
          fi
          level=$((current - (current * index / steps)))
          if [ "$level" -lt 1 ]; then
            level=0
          fi
          brightnessctl set "$level" >/dev/null 2>&1 || true
          sleep "$sleep_seconds"
          index=$((index + 1))
        done

        lock_screen
      }

      start_dim_sequence() {
        stop_dim_loop
        (
          trap 'exit 0' TERM INT
          fade_and_lock
          rm -f "$dim_pid_file"
        ) >> "$log_file" 2>&1 &
        echo "$!" > "$dim_pid_file"
      }

      start_idle() {
        load_config
        stop_idle
        self="$0"
        swayidle -w \
          timeout "$timeout_seconds" "$self idle-lock-sequence" \
          resume "$self wake" \
          before-sleep "$self lock-now" \
          >> "$log_file" 2>&1 &
        echo "$!" > "$pid_file"
        echo "screen fades after $(format_seconds "$timeout_seconds"), locks after another $(format_seconds "$fade_seconds")"
      }

      status() {
        load_config
        remaining="$(paused_remaining)"
        echo "timeout_seconds=$timeout_seconds"
        echo "timeout=$(format_seconds "$timeout_seconds")"
        echo "dim_percent=$dim_percent"
        echo "fade_seconds=$fade_seconds"
        echo "fade=$(format_seconds "$fade_seconds")"
        echo "weather_location=$(setting_value FAUXNIX_WEATHER_LOCATION)"
        if [ "$remaining" -gt 0 ]; then
          echo "paused=yes"
          echo "paused_remaining_seconds=$remaining"
          echo "paused_remaining=$(format_seconds "$remaining")"
        else
          echo "paused=no"
        fi
        if [ -r "$dim_pid_file" ]; then
          dim_pid="$(cat "$dim_pid_file" 2>/dev/null || true)"
          if [ -n "$dim_pid" ] && kill -0 "$dim_pid" 2>/dev/null; then
            echo "dim_loop=running"
            echo "dim_loop_pid=$dim_pid"
          else
            echo "dim_loop=stopped"
          fi
        else
          echo "dim_loop=stopped"
        fi
        if [ -r "$pid_file" ]; then
          pid="$(cat "$pid_file" 2>/dev/null || true)"
          if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "idle_watcher=running"
            echo "idle_watcher_pid=$pid"
            return
          fi
        fi
        echo "idle_watcher=stopped"
      }

      dim_now() {
        start_dim_sequence
      }

      restore_brightness() {
        stop_dim_loop
        brightnessctl -r >/dev/null 2>&1 || true
      }

      wake() {
        stop_dim_loop
        restore_brightness
      }

      lock_now() {
        stop_dim_loop
        restore_brightness
        lock_screen
      }

      usage() {
        printf '%s\n' \
          'usage: fauxnix-power {start|restart|stop|status|set-timeout <duration>|set-dim <percent>|set-fade <duration>|pause <duration>|resume|dim-now|idle-lock-sequence|lock-now|wake|restore-brightness}' \
          'durations accept seconds, 5m, 10min, 1h, etc.' \
          >&2
        exit 2
      }

      cmd="''${1:-status}"
      case "$cmd" in
        start|restart)
          start_idle
          ;;
        stop)
          stop_idle
          stop_dim_loop
          echo "screen dimming stopped"
          ;;
        status)
          status
          ;;
        set-timeout|timeout|dim-timeout)
          [ "$#" -ge 2 ] || usage
          load_config
          seconds="$(duration_to_seconds "$2")"
          if [ "$seconds" -lt 30 ]; then
            echo "screen timeout must be at least 30 seconds" >&2
            exit 2
          fi
          save_config "$seconds" "$dim_percent" "$fade_seconds"
          start_idle
          ;;
        set-dim|dim-percent)
          [ "$#" -ge 2 ] || usage
          load_config
          percent="$2"
          case "$percent" in
            *[!0-9]*|"") echo "dim percent must be a number" >&2; exit 2 ;;
          esac
          if [ "$percent" -lt 1 ] || [ "$percent" -gt 100 ]; then
            echo "dim percent must be between 1 and 100" >&2
            exit 2
          fi
          save_config "$timeout_seconds" "$percent" "$fade_seconds"
          start_idle
          ;;
        set-fade|fade-duration)
          [ "$#" -ge 2 ] || usage
          load_config
          seconds="$(duration_to_seconds "$2")"
          if [ "$seconds" -lt 30 ]; then
            echo "fade duration must be at least 30 seconds" >&2
            exit 2
          fi
          save_config "$timeout_seconds" "$dim_percent" "$seconds"
          start_idle
          ;;
        pause)
          [ "$#" -ge 2 ] || usage
          seconds="$(duration_to_seconds "$2")"
          until=$(( $(date +%s) + seconds ))
          echo "$until" > "$pause_file"
          restore_brightness
          echo "screen dimming paused for $(format_seconds "$seconds")"
          ;;
        resume|unpause)
          rm -f "$pause_file"
          restore_brightness
          echo "screen dimming resumed"
          ;;
        dim-now|idle-lock-sequence)
          dim_now
          ;;
        lock-now|lock)
          lock_now
          ;;
        wake)
          wake
          ;;
        restore-brightness)
          restore_brightness
          ;;
        *)
          usage
          ;;
      esac
    '';
  };
  fauxnixSwayConfig = pkgs.writeText "fauxnix-sway.conf" ''
    # FauxnixOS usable Sway profile.
    # This file is generated by NixOS from /etc/nixos/configuration.nix.

    set $mod Mod4
    set $term ${pkgs.alacritty}/bin/alacritty
    set $menu ${fauxnixRofi}/bin/rofi -show drun
    set $ws1 "1:Fennix"
    set $ws2 "2:Fauxnix"
    set $ws3 "3:Cowriter"
    set $ws4 "4:Terminal"
    set $ws5 "5:Web"
    set $ws6 "6:Ops"
    set $ws7 "7"
    set $ws8 "8"
    set $ws9 "9"
    set $ws10 "10"

    exec ${pkgs.dbus}/bin/dbus-update-activation-environment --systemd WAYLAND_DISPLAY DISPLAY SWAYSOCK XDG_CURRENT_DESKTOP XDG_SESSION_TYPE
    exec ${pkgs.mako}/bin/mako
    exec ${fauxd}/bin/fauxd
    exec ${pkgs.runtimeShell} -c "while true; do ${fauxnixCanvas}/bin/fauxnix-workspace; sleep 1; done"
    exec ${fauxnixPower}/bin/fauxnix-power start

    output * bg #0b0b0b solid_color

    input type:touchpad {
      natural_scroll enabled
      tap enabled
      dwt enabled
      scroll_method two_finger
    }

    input type:pointer {
      natural_scroll enabled
    }

    floating_modifier $mod normal
    focus_follows_mouse yes
    default_border pixel 2
    default_floating_border pixel 2
    hide_edge_borders smart
    gaps inner 6
    gaps outer 3

    assign [title="^Fennix Desktop$"] $ws1
    for_window [title="^Fennix Desktop$"] border none
    for_window [title="^Fennix Launcher$"] floating enable, sticky enable, border none
    for_window [title="^Fennix Panel$"] floating enable, sticky enable, border none
    for_window [app_id="pavucontrol"] floating enable
    for_window [app_id="nm-connection-editor"] floating enable
    for_window [title="^Fauxnix Workspace$"] fullscreen enable, border none
    for_window [title="^Fauxnix Launcher$"] floating enable, sticky enable, border none

    bindsym $mod+Return exec $term
    bindsym $mod+d exec $menu
    bindsym $mod+t exec ${fauxnixThreadLauncher}/bin/fauxnix-thread menu
    bindsym $mod+f exec ${fauxnixThreadLauncher}/bin/fauxnix-thread fennix
    bindsym $mod+Shift+d exec ${fauxnixCanvas}/bin/fauxnix-workspace
    bindsym $mod+Ctrl+Shift+d exec ${fennixPython}/bin/python3 /etc/fennix/gui.py --desktop
    bindsym $mod+Shift+f exec ${fauxnixThreadLauncher}/bin/fauxnix-thread fauxnix
    bindsym $mod+Shift+c exec ${fauxnixThreadLauncher}/bin/fauxnix-thread cowriter

    # Canvas navigation — return from fullscreen apps
    bindsym $mod+Escape workspace 2:Fauxnix
    bindsym $mod+Shift+Escape kill; workspace 2:Fauxnix

    # Trackpad gestures feed Fauxshell navigation and window control.
    bindgesture swipe:3:down kill

    bindsym Print exec ${pkgs.grim}/bin/grim "$HOME/Pictures/screenshot-$(date +%Y%m%d-%H%M%S).png"
    bindsym Shift+Print exec ${pkgs.grim}/bin/grim -g "$(${pkgs.slurp}/bin/slurp)" "$HOME/Pictures/screenshot-$(date +%Y%m%d-%H%M%S).png"
    bindsym XF86AudioRaiseVolume exec ${pkgs.wireplumber}/bin/wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%+
    bindsym XF86AudioLowerVolume exec ${pkgs.wireplumber}/bin/wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-
    bindsym XF86AudioMute exec ${pkgs.wireplumber}/bin/wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle
    bindsym XF86MonBrightnessUp exec ${pkgs.brightnessctl}/bin/brightnessctl set +10%
    bindsym XF86MonBrightnessDown exec ${pkgs.brightnessctl}/bin/brightnessctl set 10%-

    bindsym $mod+Shift+q kill
    bindsym Mod1+F4 kill
    bindsym $mod+Shift+r reload
    bindsym $mod+Shift+e exec "${pkgs.sway}/bin/swaynag -t warning -m 'Exit Sway?' -b 'Exit' '${pkgs.sway}/bin/swaymsg exit'"

    bindsym $mod+h focus left
    bindsym $mod+j focus down
    bindsym $mod+k focus up
    bindsym $mod+l focus right
    bindsym $mod+Left focus left
    bindsym $mod+Down focus down
    bindsym $mod+Up focus up
    bindsym $mod+Right focus right

    bindsym $mod+Shift+h move left
    bindsym $mod+Shift+j move down
    bindsym $mod+Shift+k move up
    bindsym $mod+Shift+l move right
    bindsym $mod+Shift+Left move left
    bindsym $mod+Shift+Down move down
    bindsym $mod+Shift+Up move up
    bindsym $mod+Shift+Right move right

    bindsym $mod+b splith
    bindsym $mod+v splitv
    bindsym $mod+s layout stacking
    bindsym $mod+w layout tabbed
    bindsym $mod+e layout toggle split
    bindsym $mod+Shift+space floating toggle
    bindsym $mod+a focus parent
    bindsym $mod+Shift+minus move scratchpad
    bindsym $mod+minus scratchpad show

    bindsym $mod+1 workspace $ws1
    bindsym $mod+2 workspace $ws2
    bindsym $mod+3 workspace $ws3
    bindsym $mod+4 workspace $ws4
    bindsym $mod+5 workspace $ws5
    bindsym $mod+6 workspace $ws6
    bindsym $mod+7 workspace $ws7
    bindsym $mod+8 workspace $ws8
    bindsym $mod+9 workspace $ws9
    bindsym $mod+0 workspace $ws10

    bindsym $mod+Shift+1 move container to workspace $ws1
    bindsym $mod+Shift+2 move container to workspace $ws2
    bindsym $mod+Shift+3 move container to workspace $ws3
    bindsym $mod+Shift+4 move container to workspace $ws4
    bindsym $mod+Shift+5 move container to workspace $ws5
    bindsym $mod+Shift+6 move container to workspace $ws6
    bindsym $mod+Shift+7 move container to workspace $ws7
    bindsym $mod+Shift+8 move container to workspace $ws8
    bindsym $mod+Shift+9 move container to workspace $ws9
    bindsym $mod+Shift+0 move container to workspace $ws10

    mode "resize" {
      bindsym h resize shrink width 10 px
      bindsym j resize grow height 10 px
      bindsym k resize shrink height 10 px
      bindsym l resize grow width 10 px
      bindsym Left resize shrink width 10 px
      bindsym Down resize grow height 10 px
      bindsym Up resize shrink height 10 px
      bindsym Right resize grow width 10 px
      bindsym Return mode "default"
      bindsym Escape mode "default"
      bindsym $mod+r mode "default"
    }
    bindsym $mod+r mode "resize"

    client.focused #ff7800 #ff7800 #111111 #00c8ff #ff7800
    client.focused_inactive #333333 #333333 #eeeeee #333333 #333333
    client.unfocused #222222 #222222 #aaaaaa #222222 #222222
    client.urgent #cc0055 #cc0055 #ffffff #cc0055 #cc0055
  '';
  fauxnixMakoConfig = pkgs.writeText "fauxnix-mako-config" ''
    background-color=#141414
    text-color=#eeeeee
    border-color=#ff7800
    border-size=2
    border-radius=4
    default-timeout=5000
    font=monospace 10
  '';

in
{
  nixpkgs.config = {
    allowUnfree = true;
  };

  imports =
    [ # Include the results of the hardware scan.
      ./hardware-configuration.nix
    ];

  # Bootloader.
  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;

  hardware.enableRedistributableFirmware = true;
  hardware.graphics.enable = true;

  # The NVIDIA NVS 5400M is Fermi-era hardware. Keep Nouveau for now: the
  # proprietary 390 kernel module is marked broken and hangs during objtool.

  networking.hostName = "nixos"; # Define your hostname.
  # networking.wireless.enable = true;  # Enables wireless support via wpa_supplicant.

  # Configure network proxy if necessary
  # networking.proxy.default = "http://user:password@proxy:port/";
  # networking.proxy.noProxy = "127.0.0.1,localhost,internal.domain";

  # Tailscale config
  services.tailscale.enable = true;

  networking.firewall.trustedInterfaces = [ "tailscale0" ];
  networking.firewall.allowedUDPPorts = [ config.services.tailscale.port ];

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
    Display modes are managed through GNOME Settings or `gsettings`; do not use Sway commands on this profile.
    The current desktop target is a fresh Nix-owned GDM+GNOME profile with macOS-style WhiteSur theming. Propose Nix patches, build before switching, and keep rollback notes.
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
    Display modes are checked and changed through GNOME Settings or `gsettings`; never invent unsupported resolutions.
    Defer complex coding, planning, or long-context reasoning to Fennix, Fauxdex, or Nexus.
    """
  '';
  environment.etc."fauxshell/fauxd.py".source = ./fauxd.py;
  environment.etc."fennix/gui.py".source = ./fennix-gui.py;
  environment.etc."fennix/fauxdex.py".source = ./fauxdex.py;
  environment.etc."fennix/cowriter.py".source = ./cowriter.py;
  environment.etc."fauxnix/fauxnix-git.sh".source = ./fauxnix-git.sh;
  environment.etc."faux-pass/python/faux_pass".source = ./faux-pass/faux_pass;
  environment.etc."faux-pass/docs/ARCHITECTURE.md".source = ./faux-pass/ARCHITECTURE.md;
  environment.etc."faux-pass/docs/DESIGN.md".source = ./faux-pass/DESIGN.md;
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
      ${fauxnixKnowledge}/gnome \
      ${fauxnixKnowledge}/nix \
      ${fauxnixWorkspace}/Repos \
      ${fauxnixThreads} \
      ${fauxnixSnapshots} \
      ${fauxnixSnapshots}/screenshots

    if [ ! -e ${fauxnixKnowledge}/README.md ] || ${pkgs.gnugrep}/bin/grep -q 'sway/' ${fauxnixKnowledge}/README.md; then
      cat > ${fauxnixKnowledge}/README.md <<'EOF'
    # Fauxnix Knowledge

    This directory is Fennix and Nexus working knowledge for local system
    administration. Keep durable notes here before turning them into code.

    Initial areas:

    - `nix/` NixOS modules, rebuild workflow, rollback notes
    - `gnome/` GNOME profile notes, macOS-style theming, display settings
    - `fauxshell/` desktop cards, launcher surfaces, and continuity views
    EOF
      chown chvk:users ${fauxnixKnowledge}/README.md
      chmod 0644 ${fauxnixKnowledge}/README.md
    fi

    install -o chvk -g users -m 0644 \
      ${./docs/archivist-file-manager-card.md} \
      ${fauxnixKnowledge}/fauxshell/archivist-file-manager-card.md
    install -o chvk -g users -m 0644 \
      ${./docs/fauxshell-glass.md} \
      ${fauxnixKnowledge}/fauxshell/fauxshell-glass.md
    if [ ! -e ${fauxnixKnowledge}/gnome/display-settings.md ]; then
      cat > ${fauxnixKnowledge}/gnome/display-settings.md <<'EOF'
    # GNOME Display Settings

    The active desktop profile is GNOME on GDM. Prefer GNOME Settings for
    display layout, scaling, refresh rate, night light, and power behavior.

    Command-line checks should use GNOME-oriented tools such as `gsettings`,
    `gnome-control-center`, or `loginctl`; do not use Sway or Wayfire IPC
    commands on this profile.
    EOF
      chown chvk:users ${fauxnixKnowledge}/gnome/display-settings.md
      chmod 0644 ${fauxnixKnowledge}/gnome/display-settings.md
    fi

    if [ ! -e ${fauxnixKnowledge}/gnome/screenshot-memory.md ]; then
      cat > ${fauxnixKnowledge}/gnome/screenshot-memory.md <<'EOF'
    # Screenshot Memory

    Fauxnix visual memory uses `fauxnix-screenshot`.

    Commands:

    - `fauxnix-screenshot` captures the screen and writes a PNG into
      `~/Fauxnix/Snapshots/screenshots/`.
    - `fauxnix-screenshot --json` returns metadata for Fennix.
    - `fauxnix-screenshot status` reports the screenshot directory and latest
      capture.

    On GNOME Wayland, portal and Shell screenshot APIs can deny unattended
    calls. The tool falls back to `/dev/fb0` on this ThinkPad so local memory
    captures still work without Sway/Wayfire.
    EOF
      chown chvk:users ${fauxnixKnowledge}/gnome/screenshot-memory.md
      chmod 0644 ${fauxnixKnowledge}/gnome/screenshot-memory.md
    fi

    if [ ! -e ${fauxnixKnowledge}/nix/rebuild-workflow.md ]; then
      cat > ${fauxnixKnowledge}/nix/rebuild-workflow.md <<'EOF'
    # NixOS Rebuild Workflow

    Fennix should treat NixOS changes as a gated loop:

    1. Inspect the current config and system state.
    2. Propose a narrow patch.
    3. Run `nixos-rebuild build --show-trace`.
    4. Summarize what changed and what the build proved.
    5. Ask for approval before `nixos-rebuild switch`.
    6. Verify services and keep rollback generation notes.

    Use `/etc/nixos/fauxnix-backups/` for source backups before replacing
    `/etc/nixos` files.
    EOF
      chown chvk:users ${fauxnixKnowledge}/nix/rebuild-workflow.md
      chmod 0644 ${fauxnixKnowledge}/nix/rebuild-workflow.md
    fi

    if [ ! -e ${fauxnixKnowledge}/gnome/fresh-profile.md ]; then
      cat > ${fauxnixKnowledge}/gnome/fresh-profile.md <<'EOF'
    # GNOME Fresh Profile

    Current branch target:

    - Display manager: GDM
    - Desktop: GNOME
    - Session: gnome
    - Theme direction: macOS-style WhiteSur GTK/icons with Bibata cursor
    - Dock: Dash to Dock, bottom aligned
    - Terminal: Alacritty
    - Launcher: GNOME app grid/search

    This profile intentionally removes the active Wayfire/Sway/Fauxnix
    workspace shell path. Keep native GNOME stable first, then rebuild app
    pass-through or card-like experiments as separate user-level features.

    Prefer small Nix patches and `nixos-rebuild build --show-trace` before
    switching generations.
    EOF
      chown chvk:users ${fauxnixKnowledge}/gnome/fresh-profile.md
      chmod 0644 ${fauxnixKnowledge}/gnome/fresh-profile.md
    fi

    if [ ! -e ${fauxnixKnowledge}/fauxdex/workspace-loop.md ]; then
      cat > ${fauxnixKnowledge}/fauxdex/workspace-loop.md <<'EOF'
    # Fauxdex Workspace Loop

    Fauxdex is the bounded workspace engine underneath Fennix.

    Initial loop:

    1. Observe the active project, git status, threads, and current goal.
    2. Read or search only the files needed for the task.
    3. Plan the smallest useful change.
    4. Propose edits before applying risky changes.
    5. Verify with focused commands.
    6. Snapshot state through `fauxnix-git`.

    v0 commands:

    - `fauxdex status`
    - `fauxdex observe`
    - `fauxdex plan <request>`
    - `fauxdex prompt <request>`
    - `fauxdex set-project <project>`
    - `fauxdex set-goal <goal>`
    - `fauxdex read <project> <relative-path>`
    - `fauxdex search <project> <query>`
    EOF
      chown chvk:users ${fauxnixKnowledge}/fauxdex/workspace-loop.md
      chmod 0644 ${fauxnixKnowledge}/fauxdex/workspace-loop.md
    fi

    if [ ! -e ${fauxnixThreads}/README.md ] || ${pkgs.gnugrep}/bin/grep -q 'fauxnix-thread' ${fauxnixThreads}/README.md; then
      cat > ${fauxnixThreads}/README.md <<'EOF'
    # Fauxnix Threads

    Threads are named workspaces plus app launch profiles. The current GNOME
    profile launches ordinary desktop apps directly or through Faux-pass.

    Commands:

    - `faux-pass status`
    - `faux-pass apps`
    - `faux-pass run web`
    - `faux-pass run terminal`
    - `faux-pass run fennix`

    Legacy thread definitions may remain here for reference, but the fresh
    desktop target should not depend on the old Sway/Rofi thread launcher.
    EOF
      chown chvk:users ${fauxnixThreads}/README.md
      chmod 0644 ${fauxnixThreads}/README.md
    fi

    if [ -e ${fauxnixThreads}/README.md ] && ${pkgs.gnugrep}/bin/grep -q 'opencode' ${fauxnixThreads}/README.md; then
      ${pkgs.gnused}/bin/sed -i \
        -e 's/fauxnix-thread opencode/fauxnix-thread fauxdex/g' \
        -e 's/OpenCode/Fauxdex/g' \
        -e 's/opencode/fauxdex/g' \
        ${fauxnixThreads}/README.md
      chown chvk:users ${fauxnixThreads}/README.md
      chmod 0644 ${fauxnixThreads}/README.md
    fi
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

  # Enable networking
  networking.networkmanager.enable = true;
  networking.networkmanager.wifi.powersave = false;

  # Stabilize the TP-Link 2357:0115 / Realtek RTL8822BU USB Wi-Fi adapter.
  boot.extraModprobeConfig = ''
    options rtw88_core disable_lps_deep=Y
  '';
  services.udev.extraRules = ''
    ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="2357", ATTR{idProduct}=="0115", TEST=="power/control", ATTR{power/control}="on"
  '';

  # Set your time zone.
  time.timeZone = "America/New_York";

  # Select internationalisation properties.
  i18n.defaultLocale = "en_US.UTF-8";

  i18n.extraLocaleSettings = {
    LC_ADDRESS = "en_US.UTF-8";
    LC_IDENTIFICATION = "en_US.UTF-8";
    LC_MEASUREMENT = "en_US.UTF-8";
    LC_MONETARY = "en_US.UTF-8";
    LC_NAME = "en_US.UTF-8";
    LC_NUMERIC = "en_US.UTF-8";
    LC_PAPER = "en_US.UTF-8";
    LC_TELEPHONE = "en_US.UTF-8";
    LC_TIME = "en_US.UTF-8";
  };

  # Fresh desktop base: GNOME on GDM, with a macOS-style WhiteSur look.
  services.xserver.enable = true;
  services.displayManager.gdm = {
    enable = true;
  };
  services.desktopManager.gnome.enable = true;
  services.displayManager.defaultSession = "gnome";
  services.displayManager.autoLogin = {
    enable = true;
    user = "chvk";
  };

  programs.dconf.enable = true;
  programs.dconf.profiles.user.databases = [
    {
      settings = {
        "org/gnome/desktop/interface" = {
          gtk-theme = "WhiteSur-Dark";
          icon-theme = "WhiteSur";
          cursor-theme = "Bibata-Modern-Ice";
          color-scheme = "prefer-dark";
          clock-show-weekday = true;
          show-battery-percentage = true;
          enable-hot-corners = false;
        };
        "org/gnome/desktop/wm/preferences" = {
          button-layout = "close,minimize,maximize:";
          focus-mode = "click";
        };
        "org/gnome/shell" = {
          enabled-extensions = [
            "appindicatorsupport@rgcjonas.gmail.com"
            "blur-my-shell@aunetx"
            "dash-to-dock@micxgx.gmail.com"
            "just-perfection-desktop@just-perfection"
            "user-theme@gnome-shell-extensions.gcampax.github.com"
          ];
          favorite-apps = [
            "firefox.desktop"
            "fennix.desktop"
            "fauxnix-archivist.desktop"
            "org.gnome.Nautilus.desktop"
            "Alacritty.desktop"
            "codium.desktop"
            "org.gnome.Settings.desktop"
          ];
        };
        "org/gnome/shell/extensions/user-theme" = {
          name = "WhiteSur-Dark";
        };
        "org/gnome/shell/extensions/dash-to-dock" = {
          dock-position = "BOTTOM";
          extend-height = false;
          dock-fixed = true;
          dash-max-icon-size = lib.gvariant.mkInt32 48;
          transparency-mode = "DYNAMIC";
          click-action = "minimize-or-previews";
          show-trash = false;
          show-mounts = false;
        };
        "org/gnome/shell/extensions/just-perfection" = {
          panel = true;
          activities-button = false;
          search = true;
          startup-status = lib.gvariant.mkInt32 0;
          workspace-popup = false;
        };
      };
    }
  ];

  xdg.portal = {
    enable = true;
    extraPortals = with pkgs; [
      xdg-desktop-portal-gnome
      xdg-desktop-portal-gtk
    ];
  };

  # Configure keymap in X11
  services.xserver.xkb = {
    layout = "us";
    variant = "";
  };

  # Enable CUPS to print documents.
  services.printing.enable = true;

  # Enable sound with pipewire.
  services.pulseaudio.enable = false;
  security.rtkit.enable = true;
  security.sudo = {
    enable = true;
    extraRules = [
      {
        users = [ "chvk" ];
        commands = [
          {
            command = "ALL";
            options = [ "NOPASSWD" "SETENV" ];
          }
        ];
      }
    ];
  };
  services.pipewire = {
    enable = true;
    alsa.enable = true;
    alsa.support32Bit = true;
    pulse.enable = true;
    # If you want to use JACK applications, uncomment this
    #jack.enable = true;

    # use the example session manager (no others are packaged yet so this is enabled by default,
    # no need to redefine it in your config for now)
    #media-session.enable = true;
  };

  # Enable touchpad support for graphical sessions.
  services.libinput.enable = true;

  # Define a user account. Don't forget to set a password with ‘passwd’.
  users.users."chvk" = {
    isNormalUser = true;
    description = "Chvk";
    extraGroups = [ "networkmanager" "wheel" "video" ];
    packages = with pkgs; [
    #  thunderbird
    ];
  };

  # Install firefox.
  programs.firefox.enable = true;

  environment.sessionVariables = {
    NIXOS_OZONE_WL = "1";
    MOZ_ENABLE_WAYLAND = "1";
    QT_QPA_PLATFORM = "wayland;xcb";
    SDL_VIDEODRIVER = "wayland";
    CLUTTER_BACKEND = "wayland";
  };

  # List packages installed in system profile. To search, run:
  # $ nix search wget
  environment.systemPackages = with pkgs; [
    alacritty
    brightnessctl
    curl
    ethtool
    fennixChatLauncher
    fennixDesktop
    fennixPython
    fauxd
    fauxdex
    fennixCode
    fauxfetch
    fauxnixFetch
    fauxnixGit
    fauxPass
    fauxnixScreenshot
    fauxnixSettings
    git
    iw
    jq
    mesa-demos
    pciutils
    pavucontrol
    ripgrep
    rsync
    usbutils
    # ── application suite ──
    gimp
    krita
    vscodium
    chromium
    amberol
    libreoffice
  ]
  ++ lib.optionals (builtins.hasAttr "gnome-tweaks" pkgs) [
    pkgs.gnome-tweaks
  ]
  ++ lib.optionals (builtins.hasAttr "gnome-extension-manager" pkgs) [
    pkgs.gnome-extension-manager
  ]
  ++ lib.optionals (builtins.hasAttr "whitesur-gtk-theme" pkgs) [
    pkgs.whitesur-gtk-theme
  ]
  ++ lib.optionals (builtins.hasAttr "whitesur-icon-theme" pkgs) [
    pkgs.whitesur-icon-theme
  ]
  ++ lib.optionals (builtins.hasAttr "bibata-cursors" pkgs) [
    pkgs.bibata-cursors
  ]
  ++ lib.optionals (builtins.hasAttr "appindicator" pkgs.gnomeExtensions) [
    pkgs.gnomeExtensions.appindicator
  ]
  ++ lib.optionals (builtins.hasAttr "blur-my-shell" pkgs.gnomeExtensions) [
    pkgs.gnomeExtensions.blur-my-shell
  ]
  ++ lib.optionals (builtins.hasAttr "dash-to-dock" pkgs.gnomeExtensions) [
    pkgs.gnomeExtensions.dash-to-dock
  ]
  ++ lib.optionals (builtins.hasAttr "just-perfection" pkgs.gnomeExtensions) [
    pkgs.gnomeExtensions.just-perfection
  ]
  ++ lib.optionals (builtins.hasAttr "user-themes" pkgs.gnomeExtensions) [
    pkgs.gnomeExtensions.user-themes
  ]
  ++ [
    (writeShellApplication {
      name = "fennix";
      runtimeInputs = [ fennixPython ];
      text = ''
        set -eu

        mode=local
        if [ "$#" -gt 0 ] && { [ "$1" = "--parent" ] || [ "$1" = "-p" ]; }; then
          mode=parent
          shift
        fi

        exec ${fennixPython}/bin/python3 /etc/fennix/gui.py --route "$mode" --ask "$@"
      '';
    })
    (writeShellApplication {
      name = "fauxnix-assistant";
      runtimeInputs = [ ];
      text = ''
        exec fennix "$@"
      '';
    })
    (writeShellApplication {
      name = "fennix-gui";
      runtimeInputs = [ fennixPython ];
      text = ''
        exec python3 /etc/fennix/gui.py "$@"
      '';
    })
    (writeShellApplication {
      name = "cowriter";
      runtimeInputs = [ fennixPython ];
      text = ''
        export FAUXNIX_COWRITER_WORKSPACE=''${FAUXNIX_COWRITER_WORKSPACE:-${cowriterWorkspace}}
        exec python3 /etc/fennix/cowriter.py "$@"
      '';
    })
    fauxnixArchivist
  # vim # Do not forget to add an editor to edit configuration.nix! The Nano editor is also installed by default.
  # wget
  ];

  # Some programs need SUID wrappers, can be configured further or are
  # started in user sessions.
  # programs.mtr.enable = true;
  # programs.gnupg.agent = {
  #   enable = true;
  #   enableSSHSupport = true;
  # };

  # List services that you want to enable:

  # Enable the OpenSSH daemon.
  services.openssh.enable = true;

  # Open ports in the firewall.
  # networking.firewall.allowedTCPPorts = [ ... ];
  # networking.firewall.allowedUDPPorts = [ ... ];
  # Or disable the firewall altogether.
  # networking.firewall.enable = false;

  # This value determines the NixOS release from which the default
  # settings for stateful data, like file locations and database versions
  # on your system were taken. It‘s perfectly fine and recommended to leave
  # this value at the release version of the first install of this system.
  # Before changing this value read the documentation for this option
  # (e.g. man configuration.nix or on https://nixos.org/nixos/options.html).
  system.stateVersion = "26.05"; # Did you read the comment?

}
