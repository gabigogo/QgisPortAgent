#!/usr/bin/env python3
"""
QGIS MCP Server — FastMCP server that translates MCP tool calls into
TCP socket commands for the QGIS MCP plugin.

Spawned by VS Code via `uv run qgis_mcp_server.py`.
"""

import json
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any

from mcp.server.fastmcp import FastMCP, Context

from qgis_socket_client import QgisSocketClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("QgisMCPServer")

# ── Connection management ───────────────────────────────────────────────────

_qgis_connection: QgisSocketClient | None = None


def get_qgis_connection() -> QgisSocketClient:
    """Get or create a persistent connection to the QGIS MCP plugin."""
    global _qgis_connection

    port = int(os.environ.get("QGIS_MCP_PORT", "9876"))
    token = os.environ.get("QGIS_MCP_TOKEN", "").strip()

    if _qgis_connection is not None:
        try:
            _qgis_connection.socket.sendall(b"")
            return _qgis_connection
        except Exception as e:
            logger.warning(f"Existing connection invalid: {e}")
            try:
                _qgis_connection.disconnect()
            except Exception:
                pass
            _qgis_connection = None

    _qgis_connection = QgisSocketClient(host="localhost", port=port)
    if not _qgis_connection.connect():
        _qgis_connection = None
        raise ConnectionError(
            f"Cannot connect to QGIS on localhost:{port}. "
            "Is QGIS running with the MCP plugin started?"
        )

    # Authenticate only when a token is explicitly configured.
    if token:
        result = _qgis_connection.send_command("authenticate", {"token": token})
        if not result or result.get("status") != "success":
            msg = (result or {}).get("message", "unknown error")
            _qgis_connection.disconnect()
            _qgis_connection = None
            raise ConnectionError(f"QGIS MCP authentication failed: {msg}")
        logger.info("Authenticated with QGIS MCP plugin")

    return _qgis_connection


# ── Lifespan ────────────────────────────────────────────────────────────────


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    logger.info("QgisMCPServer starting up")
    try:
        qgis = get_qgis_connection()
        logger.info("Verified QGIS connection on startup")
    except Exception as e:
        logger.warning(f"Could not connect to QGIS on startup: {e}")
        logger.warning("Ensure the QGIS MCP plugin is running before using tools")
    yield {}
    global _qgis_connection
    if _qgis_connection:
        logger.info("Disconnecting from QGIS on shutdown")
        _qgis_connection.disconnect()
        _qgis_connection = None
    logger.info("QgisMCPServer shut down")


# ── MCP Server ──────────────────────────────────────────────────────────────

def _create_mcp_server() -> FastMCP:
    """Build a FastMCP server, supporting both old and new constructor signatures."""
    kwargs = {"lifespan": server_lifespan}
    try:
        return FastMCP(
            "qgis_mcp",
            description="Control QGIS remotely via the Model Context Protocol",
            **kwargs,
        )
    except TypeError:
        logger.warning(
            "FastMCP constructor does not accept 'description'; using compatibility mode"
        )
        return FastMCP("qgis_mcp", **kwargs)


mcp = _create_mcp_server()


# ═══════════════════════════════════════════════════════════════════════════
# Base 15 tools
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
def ping(ctx: Context) -> str:
    """Ping the QGIS MCP plugin to check connectivity."""
    qgis = get_qgis_connection()
    result = qgis.send_command("ping")
    return json.dumps(result, indent=2)


@mcp.tool()
def get_qgis_info(ctx: Context) -> str:
    """Get QGIS version, profile folder, and active plugin count."""
    qgis = get_qgis_connection()
    result = qgis.send_command("get_qgis_info")
    return json.dumps(result, indent=2)


@mcp.tool()
def load_project(ctx: Context, path: str) -> str:
    """Load a QGIS project (.qgz / .qgs) from the given path."""
    qgis = get_qgis_connection()
    result = qgis.send_command("load_project", {"path": path})
    return json.dumps(result, indent=2)


@mcp.tool()
def create_new_project(ctx: Context, path: str) -> str:
    """Create a new empty QGIS project and save it at the given path."""
    qgis = get_qgis_connection()
    result = qgis.send_command("create_new_project", {"path": path})
    return json.dumps(result, indent=2)


@mcp.tool()
def get_project_info(ctx: Context) -> str:
    """Get current project filename, title, CRS, layer count, and first 10 layers."""
    qgis = get_qgis_connection()
    result = qgis.send_command("get_project_info")
    return json.dumps(result, indent=2)


@mcp.tool()
def add_vector_layer(
    ctx: Context, path: str, provider: str = "ogr", name: str = None
) -> str:
    """Add a vector layer (shapefile, GeoPackage, GeoJSON, etc.) to the project."""
    qgis = get_qgis_connection()
    params = {"path": path, "provider": provider}
    if name:
        params["name"] = name
    result = qgis.send_command("add_vector_layer", params)
    return json.dumps(result, indent=2)


@mcp.tool()
def add_raster_layer(
    ctx: Context, path: str, provider: str = "gdal", name: str = None
) -> str:
    """Add a raster layer (GeoTIFF, etc.) to the project."""
    qgis = get_qgis_connection()
    params = {"path": path, "provider": provider}
    if name:
        params["name"] = name
    result = qgis.send_command("add_raster_layer", params)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_layers(ctx: Context) -> str:
    """Retrieve all layers in the current project with type, visibility, and feature count."""
    qgis = get_qgis_connection()
    result = qgis.send_command("get_layers")
    return json.dumps(result, indent=2)


@mcp.tool()
def remove_layer(ctx: Context, layer_id: str) -> str:
    """Remove a layer from the project by its ID."""
    qgis = get_qgis_connection()
    result = qgis.send_command("remove_layer", {"layer_id": layer_id})
    return json.dumps(result, indent=2)


@mcp.tool()
def zoom_to_layer(ctx: Context, layer_id: str) -> str:
    """Zoom the map canvas to a layer's full extent."""
    qgis = get_qgis_connection()
    result = qgis.send_command("zoom_to_layer", {"layer_id": layer_id})
    return json.dumps(result, indent=2)


@mcp.tool()
def get_layer_features(ctx: Context, layer_id: str, limit: int = 10) -> str:
    """Retrieve up to *limit* features (attributes + WKT geometry) from a vector layer."""
    qgis = get_qgis_connection()
    result = qgis.send_command(
        "get_layer_features", {"layer_id": layer_id, "limit": limit}
    )
    return json.dumps(result, indent=2)


@mcp.tool()
def execute_processing(ctx: Context, algorithm: str, parameters: dict) -> str:
    """Execute a QGIS Processing algorithm. Layer names are resolved automatically."""
    qgis = get_qgis_connection()
    result = qgis.send_command(
        "execute_processing", {"algorithm": algorithm, "parameters": parameters}
    )
    return json.dumps(result, indent=2)


@mcp.tool()
def save_project(ctx: Context, path: str = None) -> str:
    """Save the current project. Optionally specify a new path."""
    qgis = get_qgis_connection()
    params = {}
    if path:
        params["path"] = path
    result = qgis.send_command("save_project", params)
    return json.dumps(result, indent=2)


@mcp.tool()
def render_map(ctx: Context, path: str, width: int = 800, height: int = 600) -> str:
    """Render the current map canvas to an image file (PNG, JPG, etc.)."""
    qgis = get_qgis_connection()
    result = qgis.send_command(
        "render_map", {"path": path, "width": width, "height": height}
    )
    return json.dumps(result, indent=2)


@mcp.tool(
    annotations={
        "title": "Execute PyQGIS Code",
        "readOnlyHint": False,
        "destructiveHint": True,
        "openWorldHint": True,
    }
)
def execute_code(ctx: Context, code: str) -> str:
    """Execute arbitrary PyQGIS code inside QGIS.

    ⚠️ This tool runs arbitrary code in the QGIS process. The QGIS plugin may
    reject the request if code execution has been disabled via the dock widget.
    """
    qgis = get_qgis_connection()
    result = qgis.send_command("execute_code", {"code": code})
    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2: 8 new tools
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_layer_fields(ctx: Context, layer_id: str) -> str:
    """Return field names, types, and up to 3 sample values for a vector layer."""
    qgis = get_qgis_connection()
    result = qgis.send_command("get_layer_fields", {"layer_id": layer_id})
    return json.dumps(result, indent=2)


@mcp.tool()
def set_layer_style(
    ctx: Context,
    layer_id: str,
    style_path: str = None,
    field: str = None,
    method: str = None,
    num_classes: int = 5,
    color_ramp: str = None,
) -> str:
    """Apply a QML style file or build a graduated renderer on a layer.

    Either provide *style_path* to load a QML file, or provide *field* (+
    optional *method*, *num_classes*, *color_ramp*) to create a graduated
    classification.
    """
    qgis = get_qgis_connection()
    params = {"layer_id": layer_id}
    if style_path:
        params["style_path"] = style_path
    if field:
        params["field"] = field
    if method:
        params["method"] = method
    if num_classes != 5:
        params["num_classes"] = num_classes
    if color_ramp:
        params["color_ramp"] = color_ramp
    result = qgis.send_command("set_layer_style", params)
    return json.dumps(result, indent=2)


@mcp.tool()
def set_layer_labels(
    ctx: Context,
    layer_id: str,
    field_name: str,
    font_size: int = 10,
    color: str = "#000000",
    placement: str = "OverPoint",
) -> str:
    """Configure labeling on a vector layer."""
    qgis = get_qgis_connection()
    result = qgis.send_command(
        "set_layer_labels",
        {
            "layer_id": layer_id,
            "field_name": field_name,
            "font_size": font_size,
            "color": color,
            "placement": placement,
        },
    )
    return json.dumps(result, indent=2)


@mcp.tool()
def set_map_extent(
    ctx: Context,
    xmin: float = None,
    ymin: float = None,
    xmax: float = None,
    ymax: float = None,
    layer_id: str = None,
    buffer_pct: float = 10,
) -> str:
    """Set the map canvas extent by bounding box coordinates or by a layer's extent."""
    qgis = get_qgis_connection()
    params = {"buffer_pct": buffer_pct}
    if layer_id:
        params["layer_id"] = layer_id
    if xmin is not None:
        params["xmin"] = xmin
    if ymin is not None:
        params["ymin"] = ymin
    if xmax is not None:
        params["xmax"] = xmax
    if ymax is not None:
        params["ymax"] = ymax
    result = qgis.send_command("set_map_extent", params)
    return json.dumps(result, indent=2)


@mcp.tool()
def add_layer_to_group(
    ctx: Context, layer_id: str, group_name: str, create_group: bool = True
) -> str:
    """Move a layer into a layer-tree group, creating the group if it doesn't exist."""
    qgis = get_qgis_connection()
    result = qgis.send_command(
        "add_layer_to_group",
        {
            "layer_id": layer_id,
            "group_name": group_name,
            "create_group": create_group,
        },
    )
    return json.dumps(result, indent=2)


@mcp.tool()
def set_layer_visibility(ctx: Context, layer_id: str, visible: bool) -> str:
    """Toggle a layer's visibility in the layer tree."""
    qgis = get_qgis_connection()
    result = qgis.send_command(
        "set_layer_visibility", {"layer_id": layer_id, "visible": visible}
    )
    return json.dumps(result, indent=2)


@mcp.tool()
def get_processing_algorithms(ctx: Context, provider_filter: str = None) -> str:
    """List available Processing algorithms with parameters.

    Optionally filter by provider ID (e.g. 'stream_segmenter', 'native', 'gdal').
    """
    qgis = get_qgis_connection()
    params = {}
    if provider_filter:
        params["provider_filter"] = provider_filter
    result = qgis.send_command("get_processing_algorithms", params)
    return json.dumps(result, indent=2)


@mcp.tool()
def export_print_layout(
    ctx: Context,
    path: str,
    width: int = 800,
    height: int = 600,
    dpi: int = 150,
    title: str = None,
) -> str:
    """Export the current map view to a PDF or image via a print layout."""
    qgis = get_qgis_connection()
    params = {"path": path, "width": width, "height": height, "dpi": dpi}
    if title:
        params["title"] = title
    result = qgis.send_command("export_print_layout", params)
    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# MCP Prompts — reusable workflow templates
# ═══════════════════════════════════════════════════════════════════════════


@mcp.prompt()
def load_project(path: str) -> str:
    """Load a QGIS project, list its layers, and zoom to the full extent.

    Use this prompt to quickly open a project and get an overview of its contents.
    """
    return (
        f"Please perform the following steps:\n"
        f"1. Call load_project with path=\"{path}\"\n"
        f"2. Call get_project_info to list all layers\n"
        f"3. Call get_layers to get detailed layer metadata\n"
        f"4. Summarise the project: filename, CRS, layer count, and a table of layers "
        f"with name, type, feature count, and visibility\n"
    )


@mcp.prompt()
def dem_comparison(dem_layer: str, bathy_layer: str, output_dir: str) -> str:
    """Run the DEM bathymetry review algorithm on a pair of DEM layers.

    Executes dem_bathy_review:dem_bathy_review, then summarises the output.
    """
    return (
        f"Please perform the following steps:\n"
        f"1. Call execute_processing with algorithm=\"dem_bathy_review:dem_bathy_review\" "
        f"and parameters={{\"DEM_LAYER\": \"{dem_layer}\", \"BATHY_LAYER\": \"{bathy_layer}\", "
        f"\"OUTPUT_DIR\": \"{output_dir}\"}}\n"
        f"2. Report the result: output path, any warnings, and whether the HTML report was generated\n"
    )


@mcp.prompt()
def segment_streams(
    input_layer: str,
    segment_length: float = 1.0,
    use_km: bool = False,
    preserve_attrs: bool = True,
) -> str:
    """Run the stream segmenter batch pipeline on a stream centerline layer.

    Segments streams into equal-length intervals measured from downstream.
    """
    return (
        f"Please perform the following steps:\n"
        f"1. Call execute_processing with algorithm=\"stream_segmenter:batch_stream_segmenter\" "
        f"and parameters={{\"INPUT\": \"{input_layer}\", \"SEGMENT_LENGTH\": {segment_length}, "
        f"\"USE_KM\": {use_km}, \"PRESERVE_ATTRS\": {preserve_attrs}, "
        f"\"OUTPUT\": \"TEMPORARY_OUTPUT\"}}\n"
        f"2. Call get_layers to find the output layer\n"
        f"3. Call get_layer_fields on the output layer to show the new segment fields\n"
        f"4. Summarise: total features, segment count, and field schema\n"
    )


@mcp.prompt()
def apply_graduated_style(
    layer_name: str,
    field: str,
    method: str = "quantile",
    num_classes: int = 5,
    color_ramp: str = "Spectral",
) -> str:
    """Apply graduated symbology to a numeric field on a layer.

    Supports quantile, equal_interval, jenks, pretty, and stddev methods.
    """
    return (
        f"Please perform the following steps:\n"
        f"1. Call get_layers and find the layer named \"{layer_name}\"\n"
        f"2. Call get_layer_fields on that layer to confirm the field \"{field}\" exists and is numeric\n"
        f"3. Call set_layer_style with the layer ID, field=\"{field}\", method=\"{method}\", "
        f"num_classes={num_classes}, color_ramp=\"{color_ramp}\"\n"
        f"4. Call render_map to produce a preview image\n"
        f"5. Report the style settings applied\n"
    )


# ═══════════════════════════════════════════════════════════════════════════
# MCP Resources — contextual data Copilot can attach
# ═══════════════════════════════════════════════════════════════════════════


@mcp.resource("qgis://algorithms")
def resource_algorithms() -> str:
    """Available processing algorithms from the workspace's QGIS plugins.

    Returns algorithm IDs, display names, and parameter schemas for
    stream_segmenter and dem_bathy_review providers.
    """
    try:
        qgis = get_qgis_connection()
        result = qgis.send_command("get_processing_algorithms")
        if result and result.get("status") == "success":
            # Filter to workspace-relevant providers
            algos = result.get("result", [])
            filtered = [
                a for a in algos
                if a.get("provider") in ("stream_segmenter", "dem_bathy_review")
            ]
            if filtered:
                return json.dumps(filtered, indent=2)
            return json.dumps(algos, indent=2)
    except Exception as e:
        logger.warning(f"Could not fetch algorithms for resource: {e}")
    return json.dumps({"error": "QGIS not connected — start the MCP plugin first"})


@mcp.resource("qgis://project-info")
def resource_project_info() -> str:
    """Current QGIS project layers, CRS, and extent (dynamic)."""
    try:
        qgis = get_qgis_connection()
        result = qgis.send_command("get_project_info")
        if result and result.get("status") == "success":
            return json.dumps(result["result"], indent=2)
    except Exception as e:
        logger.warning(f"Could not fetch project info for resource: {e}")
    return json.dumps({"error": "QGIS not connected — start the MCP plugin first"})


# ── Entry point ─────────────────────────────────────────────────────────────


def main():
    """Run the MCP server (called by `uv run qgis_mcp_server.py`)."""
    mcp.run()


if __name__ == "__main__":
    main()
