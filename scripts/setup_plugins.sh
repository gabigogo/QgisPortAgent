#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="default"
CATEGORY="source"
INCLUDE_LEGACY_GENERATED=0
FORCE=0
PLUGIN_NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      REPO_ROOT="$2"
      shift 2
      ;;
    --profile)
      PROFILE="$2"
      shift 2
      ;;
    --category)
      CATEGORY="$2"
      shift 2
      ;;
    --include-legacy-generated)
      INCLUDE_LEGACY_GENERATED=1
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --plugin-name)
      PLUGIN_NAME="$2"
      shift 2
      ;;
    -h|--help)
      cat <<'EOF'
Usage: setup_plugins.sh [options]

Options:
  --repo-root <path>                 Repository root (default: parent of scripts/)
  --profile <name>                   QGIS profile name (default: default)
  --category <source|generated|all>  Plugin category to link (default: source)
  --include-legacy-generated         Include legacy qgis-tools generated plugins
  --plugin-name <name>               Link only one plugin
  --force                            Replace existing symlinks
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [[ "$CATEGORY" != "source" && "$CATEGORY" != "generated" && "$CATEGORY" != "all" ]]; then
  echo "Invalid category: $CATEGORY" >&2
  exit 1
fi

qgis_plugins_dir() {
  local profile="$1"
  local path_linux="$HOME/.local/share/QGIS/QGIS3/profiles/$profile/python/plugins"
  local path_macos="$HOME/Library/Application Support/QGIS/QGIS3/profiles/$profile/python/plugins"

  if [[ "$OSTYPE" == darwin* ]]; then
    mkdir -p "$path_macos"
    echo "$path_macos"
  else
    mkdir -p "$path_linux"
    echo "$path_linux"
  fi
}

is_plugin_dir() {
  local dir="$1"
  [[ -d "$dir" && -f "$dir/metadata.txt" ]]
}

declare -A CANDIDATES

add_candidates_from_root() {
  local root="$1"
  shift
  local excludes=("$@")

  [[ -d "$root" ]] || return

  for dir in "$root"/*; do
    [[ -d "$dir" ]] || continue
    local name
    name="$(basename "$dir")"

    local skip=0
    for ex in "${excludes[@]}"; do
      if [[ "$name" == "$ex" ]]; then
        skip=1
        break
      fi
    done
    [[ $skip -eq 1 ]] && continue

    if is_plugin_dir "$dir"; then
      if [[ -z "${CANDIDATES[$name]:-}" ]]; then
        CANDIDATES[$name]="$dir"
      fi
    fi
  done
}

if [[ "$CATEGORY" == "source" || "$CATEGORY" == "all" ]]; then
  add_candidates_from_root "$REPO_ROOT/plugins/source"
  add_candidates_from_root \
    "$REPO_ROOT" \
    ".git" \
    ".github" \
    ".mcp" \
    ".vscode" \
    "atbx" \
    "examples" \
    "plugins" \
    "py" \
    "pyt" \
    "qgis-tools" \
    "research" \
    "scripts" \
    "tbx_binary" \
    "test"
fi

if [[ "$CATEGORY" == "generated" || "$CATEGORY" == "all" ]]; then
  add_candidates_from_root "$REPO_ROOT/plugins/generated"
  if [[ $INCLUDE_LEGACY_GENERATED -eq 1 ]]; then
    add_candidates_from_root "$REPO_ROOT/qgis-tools"
  fi
fi

if [[ -n "$PLUGIN_NAME" ]]; then
  if [[ -z "${CANDIDATES[$PLUGIN_NAME]:-}" ]]; then
    echo "Plugin not found in selected category: $PLUGIN_NAME" >&2
    exit 1
  fi
  declare -A ONLY_ONE
  ONLY_ONE[$PLUGIN_NAME]="${CANDIDATES[$PLUGIN_NAME]}"
  CANDIDATES=()
  for key in "${!ONLY_ONE[@]}"; do
    CANDIDATES[$key]="${ONLY_ONE[$key]}"
  done
fi

PLUGINS_DIR="$(qgis_plugins_dir "$PROFILE")"

linked=0
skipped=0
failed=0

if [[ ${#CANDIDATES[@]} -eq 0 ]]; then
  echo "No plugin directories discovered for category '$CATEGORY'."
fi

for name in "${!CANDIDATES[@]}"; do
  source_path="${CANDIDATES[$name]}"
  target_path="$PLUGINS_DIR/$name"

  if [[ -L "$target_path" ]]; then
    if [[ $FORCE -eq 1 ]]; then
      rm -f "$target_path"
    else
      echo "SKIP $name (symlink already exists)"
      skipped=$((skipped + 1))
      continue
    fi
  elif [[ -e "$target_path" ]]; then
    echo "WARN $name (target exists and is not a symlink): $target_path"
    skipped=$((skipped + 1))
    continue
  fi

  if ln -s "$source_path" "$target_path"; then
    echo "OK   $name -> $target_path"
    linked=$((linked + 1))
  else
    echo "FAIL $name"
    failed=$((failed + 1))
  fi
done

echo
echo "Plugin link summary"
echo "  Profile: $PROFILE"
echo "  QGIS plugins dir: $PLUGINS_DIR"
echo "  Linked: $linked"
echo "  Skipped: $skipped"
echo "  Failed: $failed"
