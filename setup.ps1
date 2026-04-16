<#
.SYNOPSIS
    QgisPortAgent first-run bootstrap script.

.DESCRIPTION
    Automates environment detection and configuration so a novice can clone
    the repo and start using the VS Code + GitHub Copilot agent workflow
    with QGIS MCP in minutes.

    Steps performed:
      1. Detect QGIS Python interpreter
      2. Install 'uv' (Python package runner) if missing
      3. Optionally download the GitHub MCP Server binary
      4. Symlink QGIS plugins into the active QGIS profile
      5. Create .env from .env.example if absent
      6. Print a summary and next-steps message

.NOTES
    Run from the repo root:  .\setup.ps1
    Some steps (symlinks) require an elevated (admin) terminal.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = $PSScriptRoot

# ─────────────────────────────────────────────────────────────────────────────
# 1. Detect QGIS Python interpreter
# ─────────────────────────────────────────────────────────────────────────────
Write-Host "`n=== Step 1: Detect QGIS Python interpreter ===" -ForegroundColor Cyan

$PythonCandidates = @(
    "C:\OSGeo4W\apps\Python312\python.exe",
    "C:\Program Files\QGIS 3.44\apps\Python312\python.exe",
    "C:\Program Files\QGIS 3.44.0\apps\Python312\python.exe"
)

# Also try registry
$RegPaths = @(
    "HKLM:\SOFTWARE\QGIS",
    "HKLM:\SOFTWARE\OSGeo4W"
)
foreach ($rp in $RegPaths) {
    if (Test-Path $rp) {
        $installDir = (Get-ItemProperty $rp -ErrorAction SilentlyContinue).InstallPath
        if ($installDir) {
            $PythonCandidates += Join-Path $installDir "apps\Python312\python.exe"
        }
    }
}

$QgisPython = $null
foreach ($candidate in $PythonCandidates) {
    if (Test-Path $candidate) {
        $QgisPython = $candidate
        break
    }
}

if (-not $QgisPython) {
    Write-Host "  Could not auto-detect QGIS Python. Common locations checked:" -ForegroundColor Yellow
    foreach ($c in $PythonCandidates) { Write-Host "    - $c" -ForegroundColor DarkGray }
    $QgisPython = Read-Host "  Enter the full path to your QGIS Python executable"
    if (-not (Test-Path $QgisPython)) {
        Write-Host "  ERROR: Path does not exist: $QgisPython" -ForegroundColor Red
        exit 1
    }
}

Write-Host "  Found: $QgisPython" -ForegroundColor Green

# Update .vscode/settings.json interpreter path
$SettingsPath = Join-Path $RepoRoot ".vscode\settings.json"
if (Test-Path $SettingsPath) {
    $settingsContent = Get-Content $SettingsPath -Raw
    $escaped = $QgisPython -replace '\\', '\\\\'
    $settingsContent = $settingsContent -replace '(?<="python\.defaultInterpreterPath":\s*")[^"]+', $escaped
    Set-Content $SettingsPath -Value $settingsContent -NoNewline
    Write-Host "  Updated .vscode/settings.json interpreter path" -ForegroundColor Green
}

# ─────────────────────────────────────────────────────────────────────────────
# 2. Install uv if missing
# ─────────────────────────────────────────────────────────────────────────────
Write-Host "`n=== Step 2: Check / install uv ===" -ForegroundColor Cyan

if (Get-Command uv -ErrorAction SilentlyContinue) {
    $uvVer = & uv --version 2>&1
    Write-Host "  uv already installed: $uvVer" -ForegroundColor Green
} else {
    Write-Host "  Installing uv ..." -ForegroundColor Yellow
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    # Refresh PATH so uv is available in this session
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        $uvVer = & uv --version 2>&1
        Write-Host "  Installed: $uvVer" -ForegroundColor Green
    } else {
        Write-Host "  WARNING: uv installed but not found on PATH. Restart your terminal." -ForegroundColor Yellow
        $uvVer = "(restart terminal)"
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# 3. Optionally download standalone GitHub MCP binary
# ─────────────────────────────────────────────────────────────────────────────
Write-Host "`n=== Step 3: Standalone GitHub MCP binary (optional) ===" -ForegroundColor Cyan

$McpDir = Join-Path $RepoRoot ".mcp"
$McpBinary = Join-Path $McpDir "github-mcp-server.exe"
$GhMcpInstalled = $false

if (Test-Path $McpBinary) {
    Write-Host "  Already present: $McpBinary" -ForegroundColor Green
    $GhMcpInstalled = $true
} else {
    Write-Host "  Copilot CLI already includes a built-in GitHub MCP server." -ForegroundColor DarkGray
    $install = Read-Host "  Download the standalone github-mcp-server binary for manual workspace registration? (Y/n)"
    if ($install -ne 'n' -and $install -ne 'N') {
        if (-not (Test-Path $McpDir)) { New-Item -ItemType Directory -Path $McpDir -Force | Out-Null }

        Write-Host "  Fetching latest release info ..." -ForegroundColor Yellow
        $releaseInfo = Invoke-RestMethod "https://api.github.com/repos/github/github-mcp-server/releases/latest"
        $asset = $releaseInfo.assets | Where-Object {
            $_.name -match '(?i)windows[_-](amd64|x86_64).*\.zip$'
        } | Select-Object -First 1

        if ($asset) {
            $zipPath = Join-Path $McpDir "github-mcp-server.zip"
            Write-Host "  Downloading $($asset.name) ..." -ForegroundColor Yellow
            Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath
            Expand-Archive -Path $zipPath -DestinationPath $McpDir -Force
            Remove-Item $zipPath -Force

            # The archive may extract into a subdirectory — find the exe
            $exe = Get-ChildItem -Path $McpDir -Filter "github-mcp-server.exe" -Recurse | Select-Object -First 1
            if ($exe -and $exe.FullName -ne $McpBinary) {
                Move-Item $exe.FullName $McpBinary -Force
            }

            if (Test-Path $McpBinary) {
                Write-Host "  Installed: $McpBinary" -ForegroundColor Green
                $GhMcpInstalled = $true
            } else {
                Write-Host "  WARNING: Download succeeded but exe not found." -ForegroundColor Yellow
            }
        } else {
            Write-Host "  WARNING: Could not find a compatible Windows x86_64/amd64 asset in the latest release." -ForegroundColor Yellow
        }
    } else {
        Write-Host "  Skipped. Copilot CLI still has its built-in GitHub MCP server; this only skips the standalone workspace binary." -ForegroundColor DarkGray
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# 4. Symlink QGIS plugins
# ─────────────────────────────────────────────────────────────────────────────
Write-Host "`n=== Step 4: Symlink QGIS plugins ===" -ForegroundColor Cyan

$DefaultProfile = "default"
$ProfileBase = Join-Path $env:APPDATA "QGIS\QGIS3\profiles"
$PluginsDir = Join-Path $ProfileBase "$DefaultProfile\python\plugins"

$profileName = $DefaultProfile

if (-not (Test-Path $PluginsDir)) {
    $profileName = Read-Host "  QGIS plugins directory not found at default profile. Enter your QGIS profile name (or press Enter for 'default')"
    if ([string]::IsNullOrWhiteSpace($profileName)) { $profileName = $DefaultProfile }
    $PluginsDir = Join-Path $ProfileBase "$profileName\python\plugins"
}

$SymlinksCreated = @()
$LinkScript = Join-Path $RepoRoot "scripts\setup_plugins.ps1"

if (Test-Path $LinkScript) {
    try {
        $linkResult = & $LinkScript -RepoRoot $RepoRoot -Profile $profileName -Category source
        if ($linkResult -and $linkResult.Linked) {
            $SymlinksCreated = @($linkResult.Linked)
        }
        $PluginsDir = $linkResult.PluginsDir
    } catch {
        Write-Host "  FAIL plugin linking via scripts/setup_plugins.ps1" -ForegroundColor Red
        Write-Host "       $($_.Exception.Message)" -ForegroundColor DarkGray
        Write-Host "       Run scripts/setup_plugins.ps1 manually as Administrator if needed." -ForegroundColor DarkGray
    }
} else {
    Write-Host "  WARN scripts/setup_plugins.ps1 not found; skipping plugin link step." -ForegroundColor Yellow
}

# ─────────────────────────────────────────────────────────────────────────────
# 5. Create .env from template
# ─────────────────────────────────────────────────────────────────────────────
Write-Host "`n=== Step 5: Environment file ===" -ForegroundColor Cyan

$EnvFile = Join-Path $RepoRoot ".env"
$EnvExample = Join-Path $RepoRoot ".env.example"

if (Test-Path $EnvFile) {
    Write-Host "  .env already exists - skipping." -ForegroundColor Green
} elseif (Test-Path $EnvExample) {
    Copy-Item $EnvExample $EnvFile
    Write-Host "  Created .env from .env.example" -ForegroundColor Green
    Write-Host "  Edit .env to add your GitHub PAT if you plan to use a manual workspace GitHub MCP server." -ForegroundColor Yellow
} else {
    Write-Host "  .env.example not found - skipping .env creation." -ForegroundColor Yellow
}

# ─────────────────────────────────────────────────────────────────────────────
# 6. Summary
# ─────────────────────────────────────────────────────────────────────────────
Write-Host "`n===  Setup Summary  ===" -ForegroundColor Cyan

function StatusIcon($ok) { if ($ok) { return [char]0x2713 } else { return [char]0x2717 } }

$rows = @(
    @{ Component = "QGIS Python";     Status = [bool]$QgisPython;    Detail = "$QgisPython" },
    @{ Component = "uv";              Status = [bool](Get-Command uv -ErrorAction SilentlyContinue); Detail = "$uvVer" },
    @{ Component = "GitHub MCP bin";  Status = $GhMcpInstalled;      Detail = if ($GhMcpInstalled) { $McpBinary } else { "Not installed (Copilot CLI built-in still available)" } },
    @{ Component = "Plugin symlinks"; Status = ($SymlinksCreated.Count -gt 0); Detail = ($SymlinksCreated -join ", ") },
    @{ Component = ".env";            Status = (Test-Path $EnvFile); Detail = if (Test-Path $EnvFile) { "Exists" } else { "Missing" } }
)

foreach ($r in $rows) {
    $icon = StatusIcon $r.Status
    $color = if ($r.Status) { "Green" } else { "Yellow" }
    Write-Host ("  {0} {1,-18} {2}" -f $icon, $r.Component, $r.Detail) -ForegroundColor $color
}

Write-Host "  Note: Copilot CLI includes a built-in GitHub MCP server. This setup step only manages the optional standalone workspace binary." -ForegroundColor DarkGray

Write-Host "`n===  Next Steps  ===" -ForegroundColor Cyan
Write-Host "  1. Open QGIS -> Plugins -> Manage and Install -> Enable 'QGIS MCP'" -ForegroundColor White
Write-Host "  2. In QGIS, click 'QGIS MCP' in the Plugins menu -> Start Server" -ForegroundColor White
Write-Host "  3. If uv was just installed while VS Code was open, run Developer: Reload Window" -ForegroundColor White
Write-Host "  4. In VS Code, run MCP: List Servers -> trust/start 'qgis'" -ForegroundColor White
Write-Host "  5. Open VS Code -> Copilot Chat (Ctrl+Alt+I) -> Switch to Agent mode" -ForegroundColor White
Write-Host "  6. Type: @qgis-mcp Ping the QGIS server" -ForegroundColor White
Write-Host ""
