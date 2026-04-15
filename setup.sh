#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS_PATH="$REPO_ROOT/.vscode/settings.json"
ENV_FILE="$REPO_ROOT/.env"
ENV_EXAMPLE="$REPO_ROOT/.env.example"
MCP_DIR="$REPO_ROOT/.mcp"
LINK_SCRIPT="$REPO_ROOT/scripts/setup_plugins.sh"

QGIS_PYTHON=""
UV_VERSION="(not installed)"
GH_MCP_INSTALLED=0
GH_MCP_BINARY="$MCP_DIR/github-mcp-server"
PLUGIN_LINKED_COUNT=0
PLUGINS_DIR=""

print_step() {
    printf '\n=== %s ===\n' "$1"
}

status_line() {
    local label="$1"
    local ok="$2"
    local detail="$3"

    if [[ "$ok" -eq 1 ]]; then
        printf '  [OK]   %-16s %s\n' "$label" "$detail"
    else
        printf '  [WARN] %-16s %s\n' "$label" "$detail"
    fi
}

qgis_profile_base() {
    if [[ "$OSTYPE" == darwin* ]]; then
        printf '%s' "$HOME/Library/Application Support/QGIS/QGIS3/profiles"
    else
        printf '%s' "$HOME/.local/share/QGIS/QGIS3/profiles"
    fi
}

detect_qgis_python() {
    local -a candidates=()

    if [[ -n "${QGIS_PYTHON:-}" ]]; then
        candidates+=("$QGIS_PYTHON")
    fi

    if command -v python3 >/dev/null 2>&1; then
        candidates+=("$(command -v python3)")
    fi

    if command -v python >/dev/null 2>&1; then
        candidates+=("$(command -v python)")
    fi

    candidates+=(
        "/usr/bin/python3"
        "/usr/local/bin/python3"
        "/opt/homebrew/bin/python3"
        "/Applications/QGIS-LTR.app/Contents/MacOS/bin/python3"
        "/Applications/QGIS.app/Contents/MacOS/bin/python3"
    )

    for candidate in "${candidates[@]}"; do
        if [[ -n "$candidate" && -x "$candidate" ]]; then
            QGIS_PYTHON="$candidate"
            break
        fi
    done

    if [[ -z "$QGIS_PYTHON" ]]; then
        echo "  Could not auto-detect QGIS Python. Common locations checked:"
        for candidate in "${candidates[@]}"; do
            if [[ -n "$candidate" ]]; then
                echo "    - $candidate"
            fi
        done
        read -r -p "  Enter the full path to your QGIS Python executable: " QGIS_PYTHON
        if [[ ! -x "$QGIS_PYTHON" ]]; then
            echo "  ERROR: Path does not exist or is not executable: $QGIS_PYTHON"
            exit 1
        fi
    fi

    echo "  Found: $QGIS_PYTHON"
}

update_vscode_interpreter() {
    if [[ -f "$SETTINGS_PATH" ]]; then
        local escaped
        escaped="$(printf '%s' "$QGIS_PYTHON" | sed -e 's/[\/&]/\\&/g')"
        sed -E -i.bak "s|(\"python\.defaultInterpreterPath\"[[:space:]]*:[[:space:]]*\")[^\"]*(\")|\1${escaped}\2|" "$SETTINGS_PATH"
        rm -f "$SETTINGS_PATH.bak"
        echo "  Updated .vscode/settings.json interpreter path"
    fi
}

select_mcp_asset() {
    local target_os="$1"
    local target_arch="$2"

    "$QGIS_PYTHON" - "$target_os" "$target_arch" <<'PY'
import json
import re
import sys

target_os = sys.argv[1].lower()
target_arch = sys.argv[2].lower()
data = json.load(sys.stdin)
assets = data.get("assets", [])

patterns = [
    re.compile(rf"{target_os}[_-]{target_arch}.*\.(?:tar\.gz|tgz|zip)$", re.I),
    re.compile(rf"{target_os}.*{target_arch}.*\.(?:tar\.gz|tgz|zip)$", re.I),
]

for pattern in patterns:
    for asset in assets:
        name = asset.get("name", "")
        if pattern.search(name):
            print(name)
            print(asset.get("browser_download_url", ""))
            raise SystemExit(0)

raise SystemExit(1)
PY
}

download_github_mcp() {
    local target_os
    local target_arch

    case "$(uname -s)" in
        Linux*)
            target_os="linux"
            ;;
        Darwin*)
            target_os="darwin"
            ;;
        *)
            target_os="linux"
            ;;
    esac

    case "$(uname -m)" in
        x86_64|amd64)
            target_arch="amd64"
            ;;
        aarch64|arm64)
            target_arch="arm64"
            ;;
        *)
            target_arch="amd64"
            ;;
    esac

    mkdir -p "$MCP_DIR"

    echo "  Fetching latest release info ..."
    local release_info
    if ! release_info="$(curl -fsSL "https://api.github.com/repos/github/github-mcp-server/releases/latest")"; then
        echo "  WARNING: Failed to fetch release metadata from GitHub."
        return 1
    fi

    local asset_info
    asset_info="$(printf '%s' "$release_info" | select_mcp_asset "$target_os" "$target_arch" 2>/dev/null || true)"
    if [[ -z "$asset_info" ]]; then
        echo "  WARNING: Could not find a ${target_os}/${target_arch} release asset."
        return 1
    fi

    local asset_name
    local asset_url
    asset_name="$(printf '%s\n' "$asset_info" | sed -n '1p')"
    asset_url="$(printf '%s\n' "$asset_info" | sed -n '2p')"

    if [[ -z "$asset_name" || -z "$asset_url" ]]; then
        echo "  WARNING: Release metadata was missing asset details."
        return 1
    fi

    local archive_path="$MCP_DIR/$asset_name"
    echo "  Downloading $asset_name ..."
    if ! curl -fL "$asset_url" -o "$archive_path"; then
        echo "  WARNING: Failed to download $asset_name."
        return 1
    fi

    case "$asset_name" in
        *.zip)
            if command -v unzip >/dev/null 2>&1; then
                unzip -o "$archive_path" -d "$MCP_DIR" >/dev/null
            else
                echo "  WARNING: unzip is required to extract $asset_name."
                rm -f "$archive_path"
                return 1
            fi
            ;;
        *.tar.gz|*.tgz)
            tar -xzf "$archive_path" -C "$MCP_DIR"
            ;;
        *)
            echo "  WARNING: Unsupported archive format: $asset_name"
            rm -f "$archive_path"
            return 1
            ;;
    esac

    rm -f "$archive_path"

    local extracted_binary
    extracted_binary="$(find "$MCP_DIR" -type f -name "github-mcp-server*" | head -n 1 || true)"

    if [[ -n "$extracted_binary" ]]; then
        if [[ "$extracted_binary" != "$GH_MCP_BINARY" ]]; then
            mv -f "$extracted_binary" "$GH_MCP_BINARY"
        fi
        chmod +x "$GH_MCP_BINARY" || true
        GH_MCP_INSTALLED=1
        echo "  Installed: $GH_MCP_BINARY"
        return 0
    fi

    echo "  WARNING: Download succeeded but github-mcp-server was not found after extraction."
    return 1
}

print_step "Step 1: Detect QGIS Python interpreter"
detect_qgis_python
update_vscode_interpreter

print_step "Step 2: Check / install uv"
if command -v uv >/dev/null 2>&1; then
    UV_VERSION="$(uv --version 2>&1 || true)"
    echo "  uv already installed: $UV_VERSION"
else
    echo "  Installing uv ..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        echo "  WARNING: curl/wget not found. Install uv manually from https://docs.astral.sh/uv/"
    fi

    export PATH="$HOME/.local/bin:$PATH"
    if command -v uv >/dev/null 2>&1; then
        UV_VERSION="$(uv --version 2>&1 || true)"
        echo "  Installed: $UV_VERSION"
    else
        UV_VERSION="(restart terminal)"
        echo "  WARNING: uv installed but not found on PATH. Restart your terminal."
    fi
fi

print_step "Step 3: GitHub MCP Server (optional)"
if [[ -f "$GH_MCP_BINARY" ]]; then
    echo "  Already present: $GH_MCP_BINARY"
    GH_MCP_INSTALLED=1
else
    read -r -p "  Download GitHub MCP Server for repo/issue/PR tools? (Y/n) " install_choice
    if [[ "${install_choice:-Y}" =~ ^[Nn]$ ]]; then
        echo "  Skipped. GitHub MCP tools will not be available."
    else
        download_github_mcp || true
    fi
fi

print_step "Step 4: Symlink QGIS plugins"
PROFILE_NAME="default"
PROFILE_BASE="$(qgis_profile_base)"
PLUGINS_DIR="$PROFILE_BASE/$PROFILE_NAME/python/plugins"

if [[ ! -d "$PLUGINS_DIR" ]]; then
    read -r -p "  QGIS plugins directory not found at default profile. Enter your QGIS profile name (or press Enter for 'default'): " PROFILE_NAME
    PROFILE_NAME="${PROFILE_NAME:-default}"
    PLUGINS_DIR="$PROFILE_BASE/$PROFILE_NAME/python/plugins"
fi

if [[ -f "$LINK_SCRIPT" ]]; then
    if link_output="$(bash "$LINK_SCRIPT" --repo-root "$REPO_ROOT" --profile "$PROFILE_NAME" --category source 2>&1)"; then
        printf '%s\n' "$link_output"
        linked_count_text="$(printf '%s\n' "$link_output" | awk -F': ' '/^[[:space:]]*Linked:/ {print $2}' | tail -n 1)"
        plugins_dir_text="$(printf '%s\n' "$link_output" | awk -F': ' '/QGIS plugins dir:/ {print $2}' | tail -n 1)"
        if [[ "$linked_count_text" =~ ^[0-9]+$ ]]; then
            PLUGIN_LINKED_COUNT="$linked_count_text"
        fi
        if [[ -n "$plugins_dir_text" ]]; then
            PLUGINS_DIR="$plugins_dir_text"
        fi
    else
        echo "  FAIL plugin linking via scripts/setup_plugins.sh"
        printf '%s\n' "$link_output"
        echo "       Run scripts/setup_plugins.sh manually if needed."
    fi
else
    echo "  WARN scripts/setup_plugins.sh not found; skipping plugin link step."
fi

print_step "Step 5: Environment file"
if [[ -f "$ENV_FILE" ]]; then
    echo "  .env already exists - skipping."
elif [[ -f "$ENV_EXAMPLE" ]]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    echo "  Created .env from .env.example"
    echo "  Edit .env to add your GitHub PAT (optional, for GitHub MCP tools)."
else
    echo "  .env.example not found - skipping .env creation."
fi

print_step "Setup Summary"
status_line "QGIS Python" $([[ -n "$QGIS_PYTHON" ]] && echo 1 || echo 0) "$QGIS_PYTHON"
status_line "uv" $([[ -n "$(command -v uv 2>/dev/null || true)" ]] && echo 1 || echo 0) "$UV_VERSION"
status_line "GitHub MCP" "$GH_MCP_INSTALLED" "$([[ "$GH_MCP_INSTALLED" -eq 1 ]] && echo "$GH_MCP_BINARY" || echo "Not installed")"
status_line "Plugin links" $([[ "$PLUGIN_LINKED_COUNT" -gt 0 ]] && echo 1 || echo 0) "$PLUGIN_LINKED_COUNT linked ($PLUGINS_DIR)"
status_line ".env" $([[ -f "$ENV_FILE" ]] && echo 1 || echo 0) "$([[ -f "$ENV_FILE" ]] && echo "Exists" || echo "Missing")"

print_step "Next Steps"
echo "  1. Open QGIS -> Plugins -> Manage and Install -> Enable 'QGIS MCP'"
echo "  2. In QGIS, click 'QGIS MCP' in the Plugins menu -> Start Server"
echo "  3. Open VS Code -> Copilot Chat -> Switch to Agent mode"
echo "  4. Type: @qgis-mcp Ping the QGIS server"
echo
