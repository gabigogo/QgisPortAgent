---
applyTo: "qgis_mcp/**"
---

# QGIS MCP — Copilot Context

## Architecture

The QGIS MCP system has two components:

1. **QGIS Plugin** (`qgis_mcp/qgis_mcp_plugin.py`) — runs inside QGIS, listens on a
   TCP socket (default port 9876), dispatches JSON commands to PyQGIS handlers.
2. **MCP Server** (`qgis_mcp/src/qgis_mcp_server.py`) — runs outside QGIS, spawned by
   VS Code via `uv run`. Exposes `@mcp.tool()` functions that forward commands to the
   QGIS plugin over the socket.

Communication uses length-prefixed framing (4-byte big-endian header + JSON payload)
with a raw-JSON fallback for simple clients.

## Tool Inventory (23 tools)

### Base (15)
ping, get_qgis_info, load_project, create_new_project, get_project_info,
add_vector_layer, add_raster_layer, get_layers, remove_layer, zoom_to_layer,
get_layer_features, execute_processing, save_project, render_map, execute_code

### Extended (8)
get_layer_fields, set_layer_style, set_layer_labels, set_map_extent,
add_layer_to_group, set_layer_visibility, get_processing_algorithms,
export_print_layout

## Plugin Algorithm IDs

These Processing providers are available when their plugins are enabled:

- `stream_segmenter:stream_segmenter` — segment streams by distance
- `stream_segmenter:batch_stream_segmenter` — batch variant
- `stream_segmenter:extract_source_channels` — extract source channels
- `dem_bathy_review:dem_bathy_review` — DEM bathymetry comparison

Use `get_processing_algorithms(provider_filter="stream_segmenter")` to discover
full parameter schemas at runtime.

## Common Parameters

| Algorithm | Key Parameters |
|-----------|---------------|
| `stream_segmenter:stream_segmenter` | INPUT, SEGMENT_LENGTH, USE_KM, PRESERVE_ATTRS, OUTPUT |
| `stream_segmenter:batch_stream_segmenter` | INPUT, SEGMENT_LENGTH, USE_KM, FILTER_MODE, OUTPUT |
| `dem_bathy_review:dem_bathy_review` | DEM_LAYER, BATHY_LAYER, OUTPUT_DIR |

## Distance-Based Processing Guardrails

Shared policy reference:
- [Authoritative Shared Guardrails](./geoprocessing_guardrails.instructions.md)
- [Repository Mirror](../.github/geoprocessing-guardrails.md)

When executing distance-based algorithms remotely (for example `stream_segmenter:*`):

1. Inspect input layer CRS and map units before running.
2. Treat algorithm display labels (`mile_range`, etc.) as secondary outputs; validate against physical geometry lengths.
3. For QA runs, sample output features and compare computed geometry length against expected segment target (for example approximately 1.0 mi for full segments).
4. If discrepancy is systematic (for example approximately 0.3 mi while labeled 1 mi), suspect CRS-native-to-meter conversion issues first.

## MCP Geoprocessing Execution Checklist

For any MCP attempt that executes geoprocessing:

1. Preflight connectivity using `ping` and `get_qgis_info`.
2. Inspect algorithm schema with `get_processing_algorithms(...)` before execution.
3. Inspect input layers and CRS/field assumptions using `get_layers()` and `get_layer_fields()`.
4. Execute with explicit parameters; do not rely on ambiguous defaults for distance-sensitive fields.
5. Validate that output layers were created and contain plausible feature counts.
6. Perform a sample geometry-vs-label length audit for distance-sensitive outputs.

## Socket Protocol

- Default port: 9876 (configurable via `QGIS_MCP_PORT` env var)
- Framing: `[4-byte length][JSON payload]`
- Command format: `{"type": "<handler_name>", "params": {...}}`
- Response format: `{"status": "success"|"error", "result": {...}}` or `{"status": "error", "message": "..."}`
