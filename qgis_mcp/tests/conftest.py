"""Conftest for qgis_mcp tests — adds src/ to sys.path so the socket client
can be imported without pulling in the QGIS plugin package.

QGIS stubs are provided by the workspace-root conftest.py (MagicMock).
"""
import os
import sys

# Add src/ so that ``from qgis_socket_client import ...`` works
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
