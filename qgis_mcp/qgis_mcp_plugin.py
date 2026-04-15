"""
QGIS MCP Plugin — Socket server that exposes QGIS to MCP-compatible AI agents.

Adapted from jjsantos01/qgis_mcp, ported to QGIS 3.44 / Qt6, extended with
additional tool handlers (styling, labeling, layout export, field introspection,
layer organisation, algorithm listing).
"""

import io
import json
import os
import secrets
import socket
import struct
import sys
import traceback

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsGraduatedSymbolRenderer,
    QgsMapLayerType,
    QgsMapRendererParallelJob,
    QgsMapSettings,
    QgsPalLayerSettings,
    QgsPrintLayout,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsRendererRange,
    QgsStyle,
    QgsSymbol,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
)
from qgis.gui import QgsLayoutDesignerInterface  # noqa: F401 — used by exec
from qgis.PyQt.QtCore import QObject, QSize, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont, QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QCheckBox,
    QDockWidget,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from qgis.utils import active_plugins

# Length-prefix helpers (Phase 4.1) ──────────────────────────────────────────
_HEADER_FMT = "!I"  # 4-byte big-endian unsigned int
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)


def _send_framed(sock, data: bytes) -> None:
    """Send *data* preceded by a 4-byte big-endian length prefix."""
    sock.sendall(struct.pack(_HEADER_FMT, len(data)) + data)


# ── Structured errors ──────────────────────────────────────────────────────


class _MCPError(Exception):
    """Error with a machine-readable code for structured error responses."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _require_layer(layer_id: str):
    """Return the map layer or raise ``_MCPError`` with ``LAYER_NOT_FOUND``."""
    project = QgsProject.instance()
    if layer_id not in project.mapLayers():
        raise _MCPError(f"Layer not found: {layer_id}", "LAYER_NOT_FOUND")
    return project.mapLayer(layer_id)


def _require_vector_layer(layer_id: str):
    """Return a vector layer or raise ``_MCPError``."""
    layer = _require_layer(layer_id)
    if layer.type() != QgsMapLayerType.VectorLayer:
        raise _MCPError(f"Not a vector layer: {layer_id}", "INVALID_LAYER_TYPE")
    return layer


def _require_file(path: str, label: str = "File"):
    """Raise ``_MCPError`` with ``FILE_NOT_FOUND`` if *path* does not exist."""
    if not os.path.exists(path):
        raise _MCPError(f"{label} not found: {path}", "FILE_NOT_FOUND")


def _clamp(value, lo, hi, name: str):
    """Return *value* clamped to [lo, hi], raising ``_MCPError`` if out of range."""
    v = type(lo)(value)
    if v < lo or v > hi:
        raise _MCPError(
            f"{name} must be between {lo} and {hi}, got {v}",
            "INVALID_PARAMETER",
        )
    return v


# ── Server ──────────────────────────────────────────────────────────────────

class QgisMCPServer(QObject):
    """TCP socket server that accepts JSON commands and dispatches them to
    handler methods that call PyQGIS in the main thread."""

    def __init__(self, host="localhost", port=9876, iface=None):
        super().__init__()
        self.host = host
        self.port = port
        self.iface = iface
        self.running = False
        self.socket = None
        self.client = None
        self.buffer = b""
        self.timer = None
        self.auth_required = False
        self.auth_token: str | None = None
        self.client_authenticated = False
        self.code_execution_enabled = True

    # ── lifecycle ───────────────────────────────────────────────────────────

    def start(self):
        self.running = True
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Configure per-session auth only when explicitly enabled.
        self.auth_token = secrets.token_hex(16) if self.auth_required else None
        self.client_authenticated = False

        try:
            self.socket.bind((self.host, self.port))
            self.socket.listen(1)
            self.socket.setblocking(False)

            self.timer = QTimer()
            self.timer.timeout.connect(self.process_server)
            self.timer.start(100)

            QgsMessageLog = _log()
            QgsMessageLog.logMessage(
                f"QGIS MCP server started on {self.host}:{self.port}",
                "QGIS MCP",
            )
            return True
        except Exception as e:
            _log().logMessage(
                f"Failed to start server: {e}", "QGIS MCP", Qgis.Critical
            )
            self.stop()
            return False

    def stop(self):
        self.running = False
        if self.timer:
            self.timer.stop()
            self.timer = None
        if self.client:
            self.client.close()
        if self.socket:
            self.socket.close()
        self.socket = None
        self.client = None
        self.client_authenticated = False
        self.buffer = b""
        _log().logMessage("QGIS MCP server stopped", "QGIS MCP")

    # ── poll loop ───────────────────────────────────────────────────────────

    def process_server(self):
        if not self.running:
            return

        try:
            # Accept new connections
            if not self.client and self.socket:
                try:
                    self.client, address = self.socket.accept()
                    self.client.setblocking(False)
                    _log().logMessage(f"Connected to client: {address}", "QGIS MCP")
                except BlockingIOError:
                    pass
                except Exception as e:
                    _log().logMessage(
                        f"Error accepting connection: {e}",
                        "QGIS MCP",
                        Qgis.Warning,
                    )

            # Process existing connection
            if self.client:
                try:
                    try:
                        data = self.client.recv(65536)
                        if data:
                            self.buffer += data
                            self._try_process_buffer()
                        else:
                            _log().logMessage("Client disconnected", "QGIS MCP")
                            self.client.close()
                            self.client = None
                            self.client_authenticated = False
                            self.buffer = b""
                    except BlockingIOError:
                        pass
                    except Exception as e:
                        _log().logMessage(
                            f"Error receiving data: {e}",
                            "QGIS MCP",
                            Qgis.Warning,
                        )
                        self.client.close()
                        self.client = None
                        self.buffer = b""
                except Exception as e:
                    _log().logMessage(
                        f"Error with client: {e}", "QGIS MCP", Qgis.Warning
                    )
                    if self.client:
                        self.client.close()
                        self.client = None
                    self.buffer = b""
        except Exception as e:
            _log().logMessage(f"Server error: {e}", "QGIS MCP", Qgis.Critical)

    # Maximum message size: 50 MB (protects against corrupt length headers)
    _MAX_MSG_SIZE = 50 * 1024 * 1024

    def _try_process_buffer(self):
        """Extract and process all complete messages from the buffer.

        Supports two framing modes:
        1. Length-prefixed (4-byte big-endian header) — preferred.
        2. Raw JSON (legacy / simple clients) — fallback.

        Loops until no more complete framed messages remain so that
        back-to-back requests in a single recv are fully drained.
        """
        while True:
            # ── length-prefixed ────────────────────────────────────────────
            if len(self.buffer) >= _HEADER_SIZE:
                (msg_len,) = struct.unpack(_HEADER_FMT, self.buffer[:_HEADER_SIZE])

                if msg_len > self._MAX_MSG_SIZE:
                    _log().logMessage(
                        f"Rejected oversized message ({msg_len} bytes)",
                        "QGIS MCP",
                        Qgis.Warning,
                    )
                    self.buffer = b""
                    return

                total = _HEADER_SIZE + msg_len
                if len(self.buffer) < total:
                    return  # incomplete — wait for more data

                payload = self.buffer[_HEADER_SIZE:total]
                self.buffer = self.buffer[total:]
                try:
                    command = json.loads(payload.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    _log().logMessage(
                        f"Invalid JSON in framed message: {exc}",
                        "QGIS MCP",
                        Qgis.Warning,
                    )
                    continue  # skip corrupt message, try next

                response = self.execute_command(command)
                response_bytes = json.dumps(response).encode("utf-8")
                _send_framed(self.client, response_bytes)
                continue  # drain any remaining messages

            # ── raw JSON (fallback) ────────────────────────────────────────
            try:
                command = json.loads(self.buffer.decode("utf-8"))
                self.buffer = b""
                response = self.execute_command(command)
                response_json = json.dumps(response)
                self.client.sendall(response_json.encode("utf-8"))
            except json.JSONDecodeError:
                pass  # incomplete data, keep accumulating
            return  # raw JSON is a single message; exit loop

    # ── command dispatch ────────────────────────────────────────────────────

    def execute_command(self, command):
        try:
            cmd_type = command.get("type")
            params = command.get("params", {})

            # ── Authentication gate ────────────────────────────────────────
            if cmd_type == "authenticate":
                if not self.auth_token:
                    self.client_authenticated = True
                    return {
                        "status": "success",
                        "result": {
                            "authenticated": True,
                            "auth_required": False,
                        },
                    }

                token = params.get("token", "")
                if secrets.compare_digest(token, self.auth_token or ""):
                    self.client_authenticated = True
                    _log().logMessage("Client authenticated", "QGIS MCP")
                    return {"status": "success", "result": {"authenticated": True}}
                else:
                    _log().logMessage(
                        "Authentication failed — invalid token",
                        "QGIS MCP",
                        Qgis.Warning,
                    )
                    return {
                        "status": "error",
                        "message": "Invalid authentication token",
                        "code": "AUTH_FAILED",
                    }

            # Require auth for all other commands (skip ping for connectivity checks)
            if self.auth_token and not self.client_authenticated and cmd_type != "ping":
                return {
                    "status": "error",
                    "message": "Authentication required. Send {\"type\": \"authenticate\", \"params\": {\"token\": \"...\"}} first.",
                    "code": "AUTH_REQUIRED",
                }

            handlers = {
                # ── base 15 (from upstream qgis_mcp) ──
                "ping": self.ping,
                "get_qgis_info": self.get_qgis_info,
                "load_project": self.load_project,
                "get_project_info": self.get_project_info,
                "execute_code": self.execute_code,
                "add_vector_layer": self.add_vector_layer,
                "add_raster_layer": self.add_raster_layer,
                "get_layers": self.get_layers,
                "remove_layer": self.remove_layer,
                "zoom_to_layer": self.zoom_to_layer,
                "get_layer_features": self.get_layer_features,
                "execute_processing": self.execute_processing,
                "save_project": self.save_project,
                "render_map": self.render_map,
                "create_new_project": self.create_new_project,
                # ── Phase 2: 8 new handlers ──
                "get_layer_fields": self.get_layer_fields,
                "set_layer_style": self.set_layer_style,
                "set_layer_labels": self.set_layer_labels,
                "set_map_extent": self.set_map_extent,
                "add_layer_to_group": self.add_layer_to_group,
                "set_layer_visibility": self.set_layer_visibility,
                "get_processing_algorithms": self.get_processing_algorithms,
                "export_print_layout": self.export_print_layout,
            }

            handler = handlers.get(cmd_type)
            if handler:
                try:
                    _log().logMessage(f"Executing handler for {cmd_type}", "QGIS MCP")
                    result = handler(**params)
                    _log().logMessage("Handler execution complete", "QGIS MCP")
                    return {"status": "success", "result": result}
                except _MCPError as e:
                    _log().logMessage(
                        f"Validation error in {cmd_type}: {e.code} — {e}",
                        "QGIS MCP",
                        Qgis.Warning,
                    )
                    return {
                        "status": "error",
                        "message": str(e),
                        "code": e.code,
                    }
                except Exception as e:
                    _log().logMessage(
                        f"Error in handler: {e}", "QGIS MCP", Qgis.Critical
                    )
                    traceback.print_exc()
                    return {
                        "status": "error",
                        "message": str(e),
                        "code": "INTERNAL_ERROR",
                    }
            else:
                return {
                    "status": "error",
                    "message": f"Unknown command type: {cmd_type}",
                    "code": "UNKNOWN_COMMAND",
                }
        except Exception as e:
            _log().logMessage(
                f"Error executing command: {e}", "QGIS MCP", Qgis.Critical
            )
            traceback.print_exc()
            return {
                "status": "error",
                "message": str(e),
                "code": "INTERNAL_ERROR",
            }

    # ═══════════════════════════════════════════════════════════════════════
    # Base handlers (from upstream qgis_mcp — ported to 3.44 / Qt6)
    # ═══════════════════════════════════════════════════════════════════════

    def ping(self, **kwargs):
        return {"pong": True}

    def get_qgis_info(self, **kwargs):
        return {
            "qgis_version": Qgis.version(),
            "profile_folder": QgsApplication.qgisSettingsDirPath(),
            "plugins_count": len(active_plugins),
        }

    def get_project_info(self, **kwargs):
        project = QgsProject.instance()
        info = {
            "filename": project.fileName(),
            "title": project.title(),
            "layer_count": len(project.mapLayers()),
            "crs": project.crs().authid(),
            "layers": [],
        }
        for i, layer in enumerate(project.mapLayers().values()):
            if i >= 10:
                break
            info["layers"].append(
                {
                    "id": layer.id(),
                    "name": layer.name(),
                    "type": self._get_layer_type(layer),
                    "visible": (
                        layer.isValid()
                        and project.layerTreeRoot()
                        .findLayer(layer.id())
                        .isVisible()
                    ),
                }
            )
        return info

    def _get_layer_type(self, layer):
        if layer.type() == QgsMapLayerType.VectorLayer:
            geom_type = QgsWkbTypes.geometryDisplayString(layer.geometryType())
            return f"vector_{geom_type}"
        elif layer.type() == QgsMapLayerType.RasterLayer:
            return "raster"
        return str(layer.type())

    def execute_code(self, code, **kwargs):
        if not self.code_execution_enabled:
            raise _MCPError(
                "Code execution is disabled. Enable it in the QGIS MCP dock widget.",
                "CODE_EXEC_DISABLED",
            )
        if not isinstance(code, str) or not code.strip():
            raise _MCPError("code must be a non-empty string", "INVALID_PARAMETER")
        _log().logMessage(
            f"execute_code invoked ({len(code)} chars)", "QGIS MCP"
        )
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        try:
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture
            namespace = {
                "qgis": Qgis,
                "QgsProject": QgsProject,
                "iface": self.iface,
                "QgsApplication": QgsApplication,
                "QgsVectorLayer": QgsVectorLayer,
                "QgsRasterLayer": QgsRasterLayer,
                "QgsCoordinateReferenceSystem": QgsCoordinateReferenceSystem,
            }
            exec(code, namespace)  # noqa: S102
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            return {
                "executed": True,
                "stdout": stdout_capture.getvalue(),
                "stderr": stderr_capture.getvalue(),
            }
        except Exception as e:
            error_tb = traceback.format_exc()
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            return {
                "executed": False,
                "error": str(e),
                "traceback": error_tb,
                "stdout": stdout_capture.getvalue(),
                "stderr": stderr_capture.getvalue(),
            }

    def add_vector_layer(self, path, name=None, provider="ogr", **kwargs):
        _require_file(path, "Vector data source")
        if not name:
            name = os.path.basename(path)
        layer = QgsVectorLayer(path, name, provider)
        if not layer.isValid():
            raise _MCPError(f"Layer is not valid: {path}", "INVALID_LAYER")
        QgsProject.instance().addMapLayer(layer)
        return {
            "id": layer.id(),
            "name": layer.name(),
            "type": self._get_layer_type(layer),
            "feature_count": layer.featureCount(),
        }

    def add_raster_layer(self, path, name=None, provider="gdal", **kwargs):
        _require_file(path, "Raster data source")
        if not name:
            name = os.path.basename(path)
        layer = QgsRasterLayer(path, name, provider)
        if not layer.isValid():
            raise _MCPError(f"Layer is not valid: {path}", "INVALID_LAYER")
        QgsProject.instance().addMapLayer(layer)
        return {
            "id": layer.id(),
            "name": layer.name(),
            "type": "raster",
            "width": layer.width(),
            "height": layer.height(),
        }

    def get_layers(self, **kwargs):
        project = QgsProject.instance()
        layers = []
        for layer_id, layer in project.mapLayers().items():
            layer_info = {
                "id": layer_id,
                "name": layer.name(),
                "type": self._get_layer_type(layer),
                "visible": project.layerTreeRoot()
                .findLayer(layer_id)
                .isVisible(),
            }
            if layer.type() == QgsMapLayerType.VectorLayer:
                layer_info["feature_count"] = layer.featureCount()
                layer_info["geometry_type"] = QgsWkbTypes.geometryDisplayString(
                    layer.geometryType()
                )
            elif layer.type() == QgsMapLayerType.RasterLayer:
                layer_info["width"] = layer.width()
                layer_info["height"] = layer.height()
            layers.append(layer_info)
        return layers

    def remove_layer(self, layer_id, **kwargs):
        _require_layer(layer_id)
        QgsProject.instance().removeMapLayer(layer_id)
        return {"removed": layer_id}

    def zoom_to_layer(self, layer_id, **kwargs):
        layer = _require_layer(layer_id)
        self.iface.setActiveLayer(layer)
        self.iface.zoomToActiveLayer()
        return {"zoomed_to": layer_id}

    def get_layer_features(self, layer_id, limit=10, **kwargs):
        layer = _require_vector_layer(layer_id)
        limit = _clamp(limit, 1, 10000, "limit")

        features = []
        for i, feature in enumerate(layer.getFeatures()):
            if i >= limit:
                break
            attrs = {}
            for field in layer.fields():
                val = feature.attribute(field.name())
                # Make JSON-safe
                if val is not None and not isinstance(val, (int, float, str, bool)):
                    val = str(val)
                attrs[field.name()] = val
            geom = None
            if feature.hasGeometry():
                geom = {
                    "type": QgsWkbTypes.geometryDisplayString(
                        feature.geometry().type()
                    ),
                    "wkt": feature.geometry().asWkt(precision=4),
                }
            features.append(
                {"id": feature.id(), "attributes": attrs, "geometry": geom}
            )
        return {
            "layer_id": layer_id,
            "feature_count": layer.featureCount(),
            "features": features,
            "fields": [field.name() for field in layer.fields()],
        }

    def execute_processing(self, algorithm, parameters, **kwargs):
        try:
            import processing

            # Resolve layer names to layer objects
            resolved = {}
            for k, v in parameters.items():
                if isinstance(v, str):
                    matches = QgsProject.instance().mapLayersByName(v)
                    if matches:
                        resolved[k] = matches[0]
                    else:
                        resolved[k] = v
                else:
                    resolved[k] = v

            result = processing.run(algorithm, resolved)
            return {
                "algorithm": algorithm,
                "result": {k: str(v) for k, v in result.items()},
            }
        except Exception as e:
            raise _MCPError(f"Processing error: {e}", "PROCESSING_ERROR")

    def save_project(self, path=None, **kwargs):
        project = QgsProject.instance()
        if not path and not project.fileName():
            raise _MCPError(
                "No project path specified and no current project path",
                "MISSING_PARAMETER",
            )
        save_path = path if path else project.fileName()
        if project.write(save_path):
            return {"saved": save_path}
        raise _MCPError(f"Failed to save project to {save_path}", "PROJECT_SAVE_FAILED")

    def load_project(self, path, **kwargs):
        _require_file(path, "Project file")
        project = QgsProject.instance()
        if project.read(path):
            self.iface.mapCanvas().refresh()
            return {"loaded": path, "layer_count": len(project.mapLayers())}
        raise _MCPError(f"Failed to load project from {path}", "PROJECT_LOAD_FAILED")

    def create_new_project(self, path, **kwargs):
        parent_dir = os.path.dirname(path)
        if parent_dir and not os.path.isdir(parent_dir):
            raise _MCPError(
                f"Directory does not exist: {parent_dir}", "FILE_NOT_FOUND"
            )
        project = QgsProject.instance()
        if project.fileName():
            project.clear()
        project.setFileName(path)
        self.iface.mapCanvas().refresh()
        if project.write():
            return {
                "created": f"Project created and saved successfully at: {path}",
                "layer_count": len(project.mapLayers()),
            }
        raise _MCPError(f"Failed to save project to {path}", "PROJECT_SAVE_FAILED")

    def render_map(self, path, width=800, height=600, **kwargs):
        ms = QgsMapSettings()
        layers = list(QgsProject.instance().mapLayers().values())
        ms.setLayers(layers)
        rect = self.iface.mapCanvas().extent()
        ms.setExtent(rect)
        ms.setOutputSize(QSize(width, height))
        ms.setBackgroundColor(QColor(255, 255, 255))
        ms.setOutputDpi(96)

        render = QgsMapRendererParallelJob(ms)
        render.start()
        render.waitForFinished()

        img = render.renderedImage()
        if img.save(path):
            return {"rendered": True, "path": path, "width": width, "height": height}
        raise _MCPError(f"Failed to save rendered image to {path}", "EXPORT_FAILED")

    # ═══════════════════════════════════════════════════════════════════════
    # Phase 2: Additional handlers
    # ═══════════════════════════════════════════════════════════════════════

    def get_layer_fields(self, layer_id, **kwargs):
        """Return field names, types, and up to 3 sample values."""
        layer = _require_vector_layer(layer_id)

        fields_info = []
        sample_features = list(layer.getFeatures())[:3]
        for field in layer.fields():
            samples = []
            for feat in sample_features:
                val = feat.attribute(field.name())
                if val is not None and not isinstance(val, (int, float, str, bool)):
                    val = str(val)
                samples.append(val)
            fields_info.append(
                {
                    "name": field.name(),
                    "type": field.typeName(),
                    "length": field.length(),
                    "precision": field.precision(),
                    "samples": samples,
                }
            )
        return {"layer_id": layer_id, "fields": fields_info}

    def set_layer_style(
        self,
        layer_id,
        style_path=None,
        field=None,
        method=None,
        num_classes=5,
        color_ramp=None,
        **kwargs,
    ):
        """Apply a QML style file or build a graduated renderer."""
        layer = _require_layer(layer_id)

        if style_path:
            _require_file(style_path, "Style file")
            msg, ok = layer.loadNamedStyle(style_path)
            if not ok:
                raise Exception(f"Failed to load style: {msg}")
            layer.triggerRepaint()
            return {"applied_style": style_path}

        if not field:
            raise _MCPError(
                "Either style_path or field must be provided", "MISSING_PARAMETER"
            )

        # Build graduated renderer
        num_classes = _clamp(num_classes, 2, 20, "num_classes")
        ramp_name = color_ramp or "Spectral"
        ramp = QgsStyle.defaultStyle().colorRamp(ramp_name)
        if not ramp:
            raise _MCPError(f"Color ramp not found: {ramp_name}", "INVALID_PARAMETER")

        classify_method = (method or "quantile").lower()
        method_map = {
            "quantile": QgsGraduatedSymbolRenderer.Quantile,
            "equal_interval": QgsGraduatedSymbolRenderer.EqualInterval,
            "jenks": QgsGraduatedSymbolRenderer.Jenks,
            "pretty": QgsGraduatedSymbolRenderer.Pretty,
            "stddev": QgsGraduatedSymbolRenderer.StdDev,
        }
        mode = method_map.get(classify_method, QgsGraduatedSymbolRenderer.Quantile)

        renderer = QgsGraduatedSymbolRenderer()
        renderer.setClassAttribute(field)
        renderer.setSourceColorRamp(ramp)
        renderer.updateClasses(layer, mode, int(num_classes))
        layer.setRenderer(renderer)
        layer.triggerRepaint()
        return {
            "field": field,
            "method": classify_method,
            "num_classes": int(num_classes),
            "color_ramp": ramp_name,
        }

    def set_layer_labels(
        self,
        layer_id,
        field_name,
        font_size=10,
        color="#000000",
        placement="OverPoint",
        **kwargs,
    ):
        """Configure labeling on a vector layer."""
        layer = _require_vector_layer(layer_id)

        settings = QgsPalLayerSettings()
        settings.fieldName = field_name
        settings.isExpression = False

        text_format = settings.format()
        font = QFont()
        font.setPointSize(int(font_size))
        text_format.setFont(font)
        text_format.setColor(QColor(color))
        settings.setFormat(text_format)

        placement_map = {
            "OverPoint": QgsPalLayerSettings.OverPoint,
            "AroundPoint": QgsPalLayerSettings.AroundPoint,
            "Line": QgsPalLayerSettings.Line,
            "Curved": QgsPalLayerSettings.Curved,
            "Horizontal": QgsPalLayerSettings.Horizontal,
            "Free": QgsPalLayerSettings.Free,
        }
        settings.placement = placement_map.get(
            placement, QgsPalLayerSettings.OverPoint
        )

        labeling = QgsVectorLayerSimpleLabeling(settings)
        layer.setLabeling(labeling)
        layer.setLabelsEnabled(True)
        layer.triggerRepaint()
        return {
            "layer_id": layer_id,
            "field": field_name,
            "font_size": int(font_size),
            "color": color,
            "placement": placement,
        }

    def set_map_extent(
        self,
        xmin=None,
        ymin=None,
        xmax=None,
        ymax=None,
        layer_id=None,
        buffer_pct=10,
        **kwargs,
    ):
        """Set the map canvas extent by coordinates or by a layer's extent."""
        canvas = self.iface.mapCanvas()
        if layer_id:
            layer = _require_layer(layer_id)
            extent = layer.extent()
            buf = extent.width() * (buffer_pct / 100.0)
            extent.grow(buf)
        elif all(v is not None for v in [xmin, ymin, xmax, ymax]):
            extent = QgsRectangle(float(xmin), float(ymin), float(xmax), float(ymax))
        else:
            raise _MCPError(
                "Provide either layer_id or all of xmin/ymin/xmax/ymax",
                "MISSING_PARAMETER",
            )
        canvas.setExtent(extent)
        canvas.refresh()
        return {
            "xmin": extent.xMinimum(),
            "ymin": extent.yMinimum(),
            "xmax": extent.xMaximum(),
            "ymax": extent.yMaximum(),
        }

    def add_layer_to_group(self, layer_id, group_name, create_group=True, **kwargs):
        """Move a layer into a layer tree group, creating it if needed."""
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        _require_layer(layer_id)

        group = root.findGroup(group_name)
        if not group:
            if create_group:
                group = root.addGroup(group_name)
            else:
                raise _MCPError(f"Group not found: {group_name}", "GROUP_NOT_FOUND")

        layer = project.mapLayer(layer_id)
        # Clone the tree node into the group and remove the old one
        tree_layer = root.findLayer(layer_id)
        if tree_layer:
            clone = tree_layer.clone()
            group.insertChildNode(0, clone)
            parent = tree_layer.parent()
            if parent:
                parent.removeChildNode(tree_layer)

        return {"layer_id": layer_id, "group": group_name}

    def set_layer_visibility(self, layer_id, visible, **kwargs):
        """Toggle layer visibility in the layer tree."""
        _require_layer(layer_id)
        root = QgsProject.instance().layerTreeRoot()
        tree_layer = root.findLayer(layer_id)
        if tree_layer:
            tree_layer.setItemVisibilityChecked(bool(visible))
        return {"layer_id": layer_id, "visible": bool(visible)}

    def get_processing_algorithms(self, provider_filter=None, **kwargs):
        """List available processing algorithms, optionally filtered by provider."""
        registry = QgsApplication.processingRegistry()
        results = []
        for alg in registry.algorithms():
            if provider_filter and alg.provider().id() != provider_filter:
                continue
            params = []
            for p in alg.parameterDefinitions():
                params.append(
                    {
                        "name": p.name(),
                        "description": p.description(),
                        "type": p.type(),
                        "default": str(p.defaultValue()) if p.defaultValue() else None,
                    }
                )
            results.append(
                {
                    "id": alg.id(),
                    "name": alg.displayName(),
                    "group": alg.group(),
                    "provider": alg.provider().id(),
                    "parameters": params,
                }
            )
        return results

    def export_print_layout(
        self, path, width=800, height=600, dpi=150, title=None, **kwargs
    ):
        """Export the current map view to an image via a temporary print layout."""
        from qgis.core import QgsLayoutExporter, QgsLayoutItemMap, QgsLayoutSize, QgsUnitTypes

        dpi = _clamp(dpi, 72, 600, "dpi")

        project = QgsProject.instance()
        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        if title:
            layout.setName(title)

        # Add a map item covering the full page
        map_item = QgsLayoutItemMap(layout)
        map_item.setRect(0, 0, width, height)
        page = layout.pageCollection().page(0)
        page.setPageSize(QgsLayoutSize(width, height, QgsUnitTypes.LayoutMillimeters))
        map_item.setExtent(self.iface.mapCanvas().extent())
        map_item.attemptResize(QgsLayoutSize(width, height, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(map_item)

        exporter = QgsLayoutExporter(layout)
        ext = os.path.splitext(path)[1].lower()

        if ext == ".pdf":
            settings = QgsLayoutExporter.PdfExportSettings()
            settings.dpi = dpi
            result = exporter.exportToPdf(path, settings)
        else:
            settings = QgsLayoutExporter.ImageExportSettings()
            settings.dpi = dpi
            result = exporter.exportToImage(path, settings)

        if result != QgsLayoutExporter.Success:
            raise _MCPError(f"Export failed with code {result}", "EXPORT_FAILED")
        return {"exported": path, "dpi": dpi, "format": ext}


# ── Dock Widget ─────────────────────────────────────────────────────────────


class QgisMCPDockWidget(QDockWidget):
    """Dock widget providing start/stop controls for the MCP socket server."""

    closed = pyqtSignal()

    def __init__(self, iface):
        super().__init__("QGIS MCP")
        self.iface = iface
        self.server = None
        self._setup_ui()

    def _setup_ui(self):
        widget = QWidget()
        layout = QVBoxLayout()
        widget.setLayout(layout)

        layout.addWidget(QLabel("Server Port:"))
        self.port_spin = QSpinBox()
        self.port_spin.setMinimum(1024)
        self.port_spin.setMaximum(65535)
        default_port = int(os.environ.get("QGIS_MCP_PORT", "9876"))
        self.port_spin.setValue(default_port)
        layout.addWidget(self.port_spin)

        self.start_button = QPushButton("Start Server")
        self.start_button.clicked.connect(self.start_server)
        layout.addWidget(self.start_button)

        self.stop_button = QPushButton("Stop Server")
        self.stop_button.clicked.connect(self.stop_server)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)

        self.code_exec_checkbox = QCheckBox("Allow execute_code")
        self.code_exec_checkbox.setChecked(True)
        self.code_exec_checkbox.setToolTip(
            "When unchecked, the execute_code MCP tool will be rejected"
        )
        self.code_exec_checkbox.stateChanged.connect(self._toggle_code_exec)
        layout.addWidget(self.code_exec_checkbox)

        require_auth_default = (
            os.environ.get("QGIS_MCP_REQUIRE_AUTH", "0").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self.auth_checkbox = QCheckBox("Require auth token")
        self.auth_checkbox.setChecked(require_auth_default)
        self.auth_checkbox.setToolTip(
            "When checked, clients must authenticate with the displayed token"
        )
        layout.addWidget(self.auth_checkbox)

        self.token_label = QLabel(
            "Auth token: (start server)"
            if self.auth_checkbox.isChecked()
            else "Auth token: (disabled)"
        )
        self.token_label.setWordWrap(True)
        # Qt6 moved text interaction enums under Qt.TextInteractionFlag.
        if hasattr(Qt, "TextInteractionFlag"):
            self.token_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
        else:
            self.token_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.token_label)
        self.auth_checkbox.stateChanged.connect(self._update_auth_label)

        self.status_label = QLabel("Server: Stopped")
        layout.addWidget(self.status_label)

        self.setWidget(widget)

    def start_server(self):
        if not self.server:
            port = self.port_spin.value()
            self.server = QgisMCPServer(port=port, iface=self.iface)
            self.server.code_execution_enabled = self.code_exec_checkbox.isChecked()
            self.server.auth_required = self.auth_checkbox.isChecked()
        if self.server.start():
            self.status_label.setText(
                f"Server: Running on port {self.server.port}"
            )
            if self.server.auth_required and self.server.auth_token:
                self.token_label.setText(f"Auth token: {self.server.auth_token}")
            else:
                self.token_label.setText("Auth token: (disabled)")
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.port_spin.setEnabled(False)
            self.auth_checkbox.setEnabled(False)

    def stop_server(self):
        if self.server:
            self.server.stop()
            self.server = None
        self.status_label.setText("Server: Stopped")
        self.token_label.setText(
            "Auth token: (start server)"
            if self.auth_checkbox.isChecked()
            else "Auth token: (disabled)"
        )
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.port_spin.setEnabled(True)
        self.auth_checkbox.setEnabled(True)

    def _toggle_code_exec(self, state):
        enabled = bool(state)
        if self.server:
            self.server.code_execution_enabled = enabled
        _log().logMessage(
            f"Code execution {'enabled' if enabled else 'disabled'}",
            "QGIS MCP",
        )

    def _update_auth_label(self, _state):
        if self.server:
            return
        self.token_label.setText(
            "Auth token: (start server)"
            if self.auth_checkbox.isChecked()
            else "Auth token: (disabled)"
        )

    def closeEvent(self, event):
        self.stop_server()
        self.closed.emit()
        super().closeEvent(event)


# ── Plugin entry point ──────────────────────────────────────────────────────


class QgisMCPPlugin:
    """Main plugin class registered via ``classFactory``."""

    def __init__(self, iface):
        self.iface = iface
        self.dock_widget = None
        self.action = None

    def initGui(self):
        self.action = QAction("QGIS MCP", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.triggered.connect(self.toggle_dock)
        self.iface.addPluginToMenu("QGIS MCP", self.action)
        self.iface.addToolBarIcon(self.action)

    @staticmethod
    def _right_dock_area():
        """Return the right dock area enum for both Qt5 and Qt6 bindings."""
        if hasattr(Qt, "DockWidgetArea"):
            return Qt.DockWidgetArea.RightDockWidgetArea
        return Qt.RightDockWidgetArea

    def toggle_dock(self, checked):
        if checked:
            if not self.dock_widget:
                self.dock_widget = QgisMCPDockWidget(self.iface)
                self.iface.addDockWidget(self._right_dock_area(), self.dock_widget)
                self.dock_widget.closed.connect(self._dock_closed)
            else:
                self.dock_widget.show()
        else:
            if self.dock_widget:
                self.dock_widget.hide()

    def _dock_closed(self):
        self.action.setChecked(False)

    def unload(self):
        if self.dock_widget:
            self.dock_widget.stop_server()
            self.iface.removeDockWidget(self.dock_widget)
            self.dock_widget = None
        self.iface.removePluginMenu("QGIS MCP", self.action)
        self.iface.removeToolBarIcon(self.action)


def classFactory(iface):  # noqa: N802 — QGIS convention
    return QgisMCPPlugin(iface)


# ── helpers ─────────────────────────────────────────────────────────────────


def _log():
    """Return the QgsMessageLog singleton (imported lazily to avoid circular imports)."""
    from qgis.core import QgsMessageLog

    return QgsMessageLog
