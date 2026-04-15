"""Workspace-root conftest — stubs the ``qgis`` namespace so that pytest can
collect tests inside QGIS plugin packages without a live QGIS environment."""
import sys
import types
from unittest.mock import MagicMock

# Build stub modules with MagicMock so that ``from qgis.core import Qgis``
# and similar import-from statements succeed (any attribute access returns a
# new MagicMock).
for _name in (
    "qgis",
    "qgis.core",
    "qgis.gui",
    "qgis.utils",
    "qgis.PyQt",
    "qgis.PyQt.QtCore",
    "qgis.PyQt.QtGui",
    "qgis.PyQt.QtWidgets",
):
    sys.modules.setdefault(_name, MagicMock())
