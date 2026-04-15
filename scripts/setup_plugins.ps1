<#
.SYNOPSIS
    Link local plugin folders into a QGIS profile plugin directory.

.DESCRIPTION
    Discovers plugin directories by looking for metadata.txt and creates
    directory junctions under the active QGIS profile plugin folder.

    Source roots (category=source):
      - plugins/source/*
      - <repo-root>/* (legacy source plugins at root)

    Generated roots (category=generated):
      - plugins/generated/*
      - qgis-tools/* (legacy generated location, optional)
#>

[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$Profile = "default",
    [ValidateSet("source", "generated", "all")]
    [string]$Category = "source",
    [switch]$IncludeLegacyGenerated,
    [switch]$Force,
    [string]$PluginName
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-QgisPluginsDir {
    param([string]$ProfileName)

    $profileBase = Join-Path $env:APPDATA "QGIS\QGIS3\profiles"
    $pluginsDir = Join-Path $profileBase "$ProfileName\python\plugins"

    if (-not (Test-Path $pluginsDir)) {
        New-Item -ItemType Directory -Path $pluginsDir -Force | Out-Null
    }

    return $pluginsDir
}

function Test-IsPluginDirectory {
    param([string]$DirectoryPath)

    if (-not (Test-Path $DirectoryPath -PathType Container)) {
        return $false
    }

    $metadataFile = Join-Path $DirectoryPath "metadata.txt"
    return (Test-Path $metadataFile -PathType Leaf)
}

function Add-CandidatesFromRoot {
    param(
        [string]$RootPath,
        [hashtable]$Candidates,
        [string[]]$ExcludeNames = @()
    )

    if (-not (Test-Path $RootPath -PathType Container)) {
        return
    }

    $excludeLookup = @{}
    foreach ($name in $ExcludeNames) {
        $excludeLookup[$name.ToLowerInvariant()] = $true
    }

    $dirs = Get-ChildItem -Path $RootPath -Directory -ErrorAction SilentlyContinue
    foreach ($dir in $dirs) {
        $name = $dir.Name
        if ($excludeLookup.ContainsKey($name.ToLowerInvariant())) {
            continue
        }

        if (Test-IsPluginDirectory -DirectoryPath $dir.FullName) {
            if (-not $Candidates.ContainsKey($name)) {
                $Candidates[$name] = $dir.FullName
            }
        }
    }
}

function Get-PluginCandidates {
    param(
        [string]$Root,
        [string]$CategoryName,
        [bool]$UseLegacyGenerated
    )

    $candidates = @{}

    if ($CategoryName -in @("source", "all")) {
        $sourceRoot = Join-Path $Root "plugins\source"
        Add-CandidatesFromRoot -RootPath $sourceRoot -Candidates $candidates

        $excluded = @(
            ".git",
            ".github",
            ".mcp",
            ".vscode",
            "atbx",
            "examples",
            "plugins",
            "py",
            "pyt",
            "qgis-tools",
            "research",
            "scripts",
            "tbx_binary",
            "test"
        )
        Add-CandidatesFromRoot -RootPath $Root -Candidates $candidates -ExcludeNames $excluded
    }

    if ($CategoryName -in @("generated", "all")) {
        $generatedRoot = Join-Path $Root "plugins\generated"
        Add-CandidatesFromRoot -RootPath $generatedRoot -Candidates $candidates

        if ($UseLegacyGenerated) {
            $legacyRoot = Join-Path $Root "qgis-tools"
            Add-CandidatesFromRoot -RootPath $legacyRoot -Candidates $candidates
        }
    }

    return $candidates
}

function New-PluginJunction {
    param(
        [string]$SourcePath,
        [string]$TargetPath,
        [switch]$Overwrite
    )

    if (Test-Path $TargetPath) {
        $item = Get-Item -Path $TargetPath -Force
        $isReparsePoint = [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)

        if ($isReparsePoint) {
            if ($Overwrite) {
                Remove-Item -Path $TargetPath -Force
            } else {
                return "exists-link"
            }
        } else {
            return "exists-regular"
        }
    }

    New-Item -ItemType Junction -Path $TargetPath -Target $SourcePath -Force | Out-Null
    return "linked"
}

$pluginsDir = Get-QgisPluginsDir -ProfileName $Profile
$candidates = Get-PluginCandidates -Root $RepoRoot -CategoryName $Category -UseLegacyGenerated $IncludeLegacyGenerated.IsPresent

if ($PluginName) {
    if ($candidates.ContainsKey($PluginName)) {
        $selected = @{}
        $selected[$PluginName] = $candidates[$PluginName]
        $candidates = $selected
    } else {
        Write-Host "Plugin not found in selected category: $PluginName" -ForegroundColor Yellow
        Write-Host "QGIS plugins directory: $pluginsDir" -ForegroundColor DarkGray
        return [PSCustomObject]@{
            PluginsDir = $pluginsDir
            Linked = @()
            Skipped = @($PluginName)
            Failed = @()
        }
    }
}

$linked = @()
$skipped = @()
$failed = @()

if ($candidates.Count -eq 0) {
    Write-Host "No plugin directories discovered for category '$Category'." -ForegroundColor Yellow
}

foreach ($entry in $candidates.GetEnumerator() | Sort-Object Name) {
    $name = $entry.Key
    $source = $entry.Value
    $target = Join-Path $pluginsDir $name

    try {
        $result = New-PluginJunction -SourcePath $source -TargetPath $target -Overwrite:$Force
        switch ($result) {
            "linked" {
                Write-Host "OK   $name -> $target" -ForegroundColor Green
                $linked += $name
            }
            "exists-link" {
                Write-Host "SKIP $name (link already exists)" -ForegroundColor DarkGray
                $skipped += $name
            }
            "exists-regular" {
                Write-Host "WARN $name (target exists and is not a link): $target" -ForegroundColor Yellow
                $skipped += $name
            }
            default {
                Write-Host "WARN $name (unknown result: $result)" -ForegroundColor Yellow
                $skipped += $name
            }
        }
    } catch {
        Write-Host "FAIL ${name}: $($_.Exception.Message)" -ForegroundColor Red
        $failed += $name
    }
}

Write-Host ""
Write-Host "Plugin link summary" -ForegroundColor Cyan
Write-Host "  Profile: $Profile" -ForegroundColor White
Write-Host "  QGIS plugins dir: $pluginsDir" -ForegroundColor White
Write-Host "  Linked: $($linked.Count)" -ForegroundColor White
Write-Host "  Skipped: $($skipped.Count)" -ForegroundColor White
Write-Host "  Failed: $($failed.Count)" -ForegroundColor White

return [PSCustomObject]@{
    PluginsDir = $pluginsDir
    Linked = $linked
    Skipped = $skipped
    Failed = $failed
}
