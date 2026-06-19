#!/usr/bin/env bash
set -euo pipefail

workspace_root="${FAUXNIX_WORKSPACE_ROOT:-/home/chvk/Fauxnix}"
repos_root="${FAUXNIX_REPOS_ROOT:-$workspace_root/Repos}"
admin_repo="$repos_root/admin"
home_repo="$repos_root/home"
threads_repo="${FAUXNIX_THREADS_DIR:-$workspace_root/Threads}"
git_user_name="${FAUXNIX_GIT_USER_NAME:-Fauxnix}"
git_user_email="${FAUXNIX_GIT_USER_EMAIL:-fauxnix@local}"

timestamp() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

require_under_workspace() {
  local path="$1"
  local root
  local resolved
  root="$(realpath -m "$workspace_root")"
  resolved="$(realpath -m "$path")"
  case "$resolved" in
    "$root"|"$root"/*) ;;
    *)
      echo "refusing to write outside $root: $resolved" >&2
      exit 2
      ;;
  esac
}

ensure_repo() {
  local repo="$1"
  require_under_workspace "$repo"
  mkdir -p "$repo"
  if [ ! -d "$repo/.git" ]; then
    git -C "$repo" init -q
  fi
  git -C "$repo" config user.name "$git_user_name"
  git -C "$repo" config user.email "$git_user_email"
}

commit_if_changed() {
  local repo="$1"
  local message="$2"
  ensure_repo "$repo"
  git -C "$repo" add -A
  if git -C "$repo" diff --cached --quiet; then
    echo "$(basename "$repo"): no staged changes"
    return 0
  fi
  git -C "$repo" commit -m "$message"
}

write_admin_scaffold() {
  ensure_repo "$admin_repo"
  cat > "$admin_repo/README.md" <<'EOF'
# Fauxnix Admin Git

This repository tracks curated machine administration state.

Tracked by default:

- `/etc/nixos`
- `/etc/fauxnix`
- generated Sway config snapshot
- current generation and system status notes

Do not store private keys, tokens, Tailscale state, model blobs, browser data,
or large mutable caches here.
EOF
  cat > "$admin_repo/.gitignore" <<'EOF'
result
*.drv
*.log
*.tmp
EOF
}

write_home_scaffold() {
  ensure_repo "$home_repo"
  cat > "$home_repo/README.md" <<'EOF'
# Fauxnix Home Git

This repository tracks curated user continuity state from `/home/chvk`.

Tracked by default:

- `Fauxnix/Knowledge`
- `Fauxnix/Cowriter`
- `Fauxnix/Threads` without its nested `.git`
- selected desktop/app config directories
- Fennix local data

This is not a whole-home backup. Caches, downloads, browser profiles, models,
secrets, and large binary churn belong outside this Git repo.
EOF
  cat > "$home_repo/.gitignore" <<'EOF'
*.log
*.tmp
*.swp
*.sqlite3-shm
*.sqlite3-wal
__pycache__/
.cache/
Cache/
cache/
node_modules/
.npm/
.cargo/
.ollama/
Downloads/
Trash/
*.gguf
*.safetensors
*.bin
EOF
}

write_threads_scaffold() {
  ensure_repo "$threads_repo"
  if [ ! -e "$threads_repo/README.md" ]; then
    cat > "$threads_repo/README.md" <<'EOF'
# Fauxnix Threads

Threads are named workspaces with resumable state.

Suggested layout per thread:

- `thread.toml` stable thread metadata
- `README.md` human summary
- `state.md` current working state
- `workspace/` active files
- `history/` append-only notes and logs
- `snapshots/` exported milestones
EOF
  fi
  cat > "$threads_repo/.gitignore" <<'EOF'
*.log
*.tmp
*.swp
__pycache__/
node_modules/
.env
.env.*
secrets/
EOF
}

copy_dir_if_exists() {
  local source="$1"
  local dest="$2"
  shift 2
  if [ ! -d "$source" ]; then
    return 0
  fi
  mkdir -p "$dest"
  rsync -a --delete "$@" "$source"/ "$dest"/
}

copy_file_if_exists() {
  local source="$1"
  local dest="$2"
  if [ ! -f "$source" ]; then
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  if [ -e "$dest" ]; then
    chmod u+w "$dest" 2>/dev/null || true
  fi
  cp -p "$source" "$dest"
  chmod u+rw "$dest"
}

tracked_secret_excludes=(
  --exclude ".env"
  --exclude ".env.*"
  --exclude "*.env"
  --exclude "*.key"
  --exclude "*.pem"
  --exclude "*.token"
  --exclude "*token*"
  --exclude "*secret*"
)

sync_admin() {
  write_admin_scaffold
  mkdir -p "$admin_repo/root/etc" "$admin_repo/system"
  copy_dir_if_exists /etc/nixos "$admin_repo/root/etc/nixos" --exclude .git --exclude result "${tracked_secret_excludes[@]}"
  copy_dir_if_exists /etc/fauxnix "$admin_repo/root/etc/fauxnix" -L --exclude .git "${tracked_secret_excludes[@]}"
  copy_dir_if_exists /etc/fennix "$admin_repo/root/etc/fennix" -L --exclude .git "${tracked_secret_excludes[@]}"
  copy_dir_if_exists /etc/faux-pass "$admin_repo/root/etc/faux-pass" -L --exclude .git "${tracked_secret_excludes[@]}"
  copy_file_if_exists /etc/sway/config "$admin_repo/root/etc/sway/config"
  find "$admin_repo/root" -type f -exec chmod u+rw {} +

  {
    echo "# Fauxnix System Snapshot"
    echo
    echo "- host: $(hostname)"
    echo "- generation: $(readlink -f /run/current-system 2>/dev/null || true)"
    echo "- kernel: $(uname -r)"
    echo "- nixos: $(nixos-version 2>/dev/null || true)"
  } > "$admin_repo/system/status.md"
}

sync_home() {
  write_home_scaffold
  local home_root="$home_repo/home/chvk"
  mkdir -p "$home_root"

  copy_dir_if_exists "$workspace_root/Knowledge" "$home_root/Fauxnix/Knowledge" --exclude .git
  copy_dir_if_exists "$workspace_root/Cowriter" "$home_root/Fauxnix/Cowriter" --exclude .git
  copy_dir_if_exists "$threads_repo" "$home_root/Fauxnix/Threads" --exclude .git
  copy_file_if_exists "$workspace_root/README.md" "$home_root/Fauxnix/README.md"

  copy_dir_if_exists "/home/chvk/.config/fauxnix" "$home_root/.config/fauxnix" --exclude .git
  copy_dir_if_exists "/home/chvk/.config/sway" "$home_root/.config/sway" --exclude .git
  copy_dir_if_exists "/home/chvk/.config/rofi" "$home_root/.config/rofi" --exclude .git
  copy_dir_if_exists "/home/chvk/.config/alacritty" "$home_root/.config/alacritty" --exclude .git
  copy_dir_if_exists "/home/chvk/.local/share/fennix" "$home_root/.local/share/fennix" --exclude .git
  find "$home_root" -type f -exec chmod u+rw {} +

  {
    echo "# Fauxnix Home Snapshot"
    echo
    echo "- source_home: /home/chvk"
    echo "- scope: curated continuity state"
  } > "$home_repo/SNAPSHOT.md"
}

sync_threads() {
  write_threads_scaffold
}

show_status() {
  local repo="$1"
  ensure_repo "$repo"
  echo
  echo "## $repo"
  git -C "$repo" status --short
}

show_diff() {
  local repo="$1"
  ensure_repo "$repo"
  echo
  echo "## $repo"
  git -C "$repo" diff --stat
}

snapshot_admin() {
  local message="${1:-admin snapshot $(timestamp)}"
  sync_admin
  commit_if_changed "$admin_repo" "$message"
}

snapshot_home() {
  local message="${1:-home snapshot $(timestamp)}"
  sync_home
  commit_if_changed "$home_repo" "$message"
}

snapshot_threads() {
  local message="${1:-threads snapshot $(timestamp)}"
  sync_threads
  commit_if_changed "$threads_repo" "$message"
}

sanitize_thread_id() {
  printf '%s' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9._-]+/-/g; s/^-+//; s/-+$//'
}

new_thread() {
  local raw_id="${1:-}"
  local label="${2:-}"
  if [ -z "$raw_id" ]; then
    echo "usage: fauxnix-git threads new <id> [label]" >&2
    exit 2
  fi
  local id
  id="$(sanitize_thread_id "$raw_id")"
  if [ -z "$id" ]; then
    echo "thread id became empty after sanitizing: $raw_id" >&2
    exit 2
  fi
  [ -n "$label" ] || label="$raw_id"
  sync_threads
  local dir="$threads_repo/$id"
  mkdir -p "$dir/workspace" "$dir/history" "$dir/snapshots"
  if [ ! -e "$dir/thread.toml" ]; then
    cat > "$dir/thread.toml" <<EOF
id = "$id"
label = "$label"
status = "active"
created_at = "$(timestamp)"
workspace = "workspace"
EOF
  fi
  if [ ! -e "$dir/README.md" ]; then
    cat > "$dir/README.md" <<EOF
# $label

Thread id: \`$id\`

Use \`state.md\` for the current working state and \`history/\` for durable
session notes.
EOF
  fi
  if [ ! -e "$dir/state.md" ]; then
    cat > "$dir/state.md" <<EOF
# State

- created_at: $(timestamp)
- status: active
EOF
  fi
  snapshot_threads "new thread: $id"
  echo "$dir"
}

usage() {
  cat <<'EOF'
usage:
  fauxnix-git init
  fauxnix-git status
  fauxnix-git diff
  fauxnix-git snapshot [message]

  fauxnix-git admin sync|status|diff|snapshot [message]
  fauxnix-git home sync|status|diff|snapshot [message]
  fauxnix-git threads status|diff|snapshot [message]
  fauxnix-git threads new <id> [label]
EOF
}

cmd="${1:-status}"
shift || true

case "$cmd" in
  init)
    sync_admin
    sync_home
    sync_threads
    commit_if_changed "$admin_repo" "initialize admin git"
    commit_if_changed "$home_repo" "initialize home git"
    commit_if_changed "$threads_repo" "initialize threads git"
    ;;
  status)
    sync_admin
    sync_home
    sync_threads
    show_status "$admin_repo"
    show_status "$home_repo"
    show_status "$threads_repo"
    ;;
  diff)
    sync_admin
    sync_home
    sync_threads
    show_diff "$admin_repo"
    show_diff "$home_repo"
    show_diff "$threads_repo"
    ;;
  snapshot)
    message="${*:-fauxnix snapshot $(timestamp)}"
    snapshot_admin "$message"
    snapshot_home "$message"
    snapshot_threads "$message"
    ;;
  admin)
    sub="${1:-status}"
    shift || true
    case "$sub" in
      sync) sync_admin ;;
      status) sync_admin; show_status "$admin_repo" ;;
      diff) sync_admin; show_diff "$admin_repo" ;;
      snapshot) snapshot_admin "${*:-admin snapshot $(timestamp)}" ;;
      *) usage; exit 2 ;;
    esac
    ;;
  home)
    sub="${1:-status}"
    shift || true
    case "$sub" in
      sync) sync_home ;;
      status) sync_home; show_status "$home_repo" ;;
      diff) sync_home; show_diff "$home_repo" ;;
      snapshot) snapshot_home "${*:-home snapshot $(timestamp)}" ;;
      *) usage; exit 2 ;;
    esac
    ;;
  threads)
    sub="${1:-status}"
    shift || true
    case "$sub" in
      status) sync_threads; show_status "$threads_repo" ;;
      diff) sync_threads; show_diff "$threads_repo" ;;
      snapshot) snapshot_threads "${*:-threads snapshot $(timestamp)}" ;;
      new) new_thread "$@" ;;
      *) usage; exit 2 ;;
    esac
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage
    exit 2
    ;;
esac
