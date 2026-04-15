"""pytest configuration and shared fixtures for stream_segmenter tests.

The helper functions under test (sanitize_name, fmt_distance, to_oriented_line,
cut_fraction) are pure Python / shapely and do not require a running QGIS
environment.  QGIS-dependent tests are guarded with a ``qgis`` mark and
skipped automatically when the QGIS Python bindings are unavailable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Make the plugin root importable when running pytest from the workspace root.
# ---------------------------------------------------------------------------
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT.parent))  # workspace root → enables stream_segmenter.*


# ---------------------------------------------------------------------------
# Mark: skip tests that require a running QGIS environment
# ---------------------------------------------------------------------------
def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "qgis: mark test as requiring a QGIS environment (skipped when unavailable)",
    )


def pytest_collection_modifyitems(config, items):
    try:
        import qgis  # noqa: F401
    except ImportError:
        skip_qgis = pytest.mark.skip(reason="QGIS Python bindings not available")
        for item in items:
            if "qgis" in item.keywords:
                item.add_marker(skip_qgis)


# ---------------------------------------------------------------------------
# Shared shapely fixtures (no QGIS required)
# ---------------------------------------------------------------------------
@pytest.fixture()
def simple_line():
    """Horizontal LineString from (0,0) to (10,0) — total length 10 units.

    Convention: last vertex (10, 0) is downstream.
    """
    from shapely.geometry import LineString

    return LineString([(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)])


@pytest.fixture()
def diagonal_line():
    """Diagonal LineString from (0,0) to (3,4) — total Euclidean length 5.

    Convention: last vertex (3, 4) is downstream.
    """
    from shapely.geometry import LineString

    return LineString([(0.0, 0.0), (3.0, 4.0)])


@pytest.fixture()
def connected_multiline():
    """Connected MultiLineString: part1 (0,0)→(5,0), part2 (5,0)→(10,0).

    Downstream endpoint = (10, 0) = last coord of last part.
    """
    from shapely.geometry import MultiLineString

    return MultiLineString([[(0.0, 0.0), (5.0, 0.0)], [(5.0, 0.0), (10.0, 0.0)]])
