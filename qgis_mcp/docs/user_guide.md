# QGIS MCP Plugin — User Guide

## Overview

The QGIS MCP plugin starts a TCP socket server inside QGIS that allows an
external MCP server (running in VS Code) to send commands — loading projects,
managing layers, running processing algorithms, applying styles, and rendering
maps.

## Setup

1. **Run your platform setup script** from the repo root to symlink the plugin into your QGIS
   profile (`setup.ps1` for PowerShell, `setup.cmd` for Command Prompt, or `bash ./setup.sh` for Linux/macOS).
2. **Open QGIS** → Plugins → Manage and Install Plugins → enable "QGIS MCP".
3. Click **QGIS MCP** in the Plugins menu (or toolbar) to open the dock widget.
4. Click **Start Server**. The status label should show "Server: Running on port
   9876".
5. By default, **Require auth token** is off for local-only workflows.

## Optional Authentication

Authentication is opt-in. If you want to lock the local socket to explicit
clients:

1. Check **Require auth token** in the dock widget.
2. Click **Start Server**.
3. Copy the displayed token into `QGIS_MCP_TOKEN` for the MCP server process.

You can also set `QGIS_MCP_REQUIRE_AUTH=1` before launching QGIS to make the
checkbox default to enabled.

## Changing the Port

Set the `QGIS_MCP_PORT` environment variable before launching QGIS, or change
the port in the dock widget spin box before clicking Start.

## Verifying Connectivity

In VS Code, switch to Copilot Agent mode and type:

```@qgis-mcp Ping the QGIS server```


You should see a response containing `{"pong": true}`.

## Available Tools

See the [agent definition](../../.github/agents/qgis-mcp.agent.md) for the full
list of 23 tools and workflow examples.

## Troubleshooting

| Symptom | Fix |
| --------- | ----- |
| "Connection refused" | Ensure QGIS is running and the plugin's server is started |
| "Port already in use" | Change `QGIS_MCP_PORT` or stop the other process |
| "AUTH_REQUIRED" from server | Enable auth in the MCP client by setting `QGIS_MCP_TOKEN`, or restart QGIS MCP with auth disabled |
| Plugin not visible | Re-run your platform setup script (`setup.ps1` or `setup.cmd` on Windows, `bash ./setup.sh` on Linux/macOS) to recreate plugin links |
