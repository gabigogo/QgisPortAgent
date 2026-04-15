"""QGIS plugin entry point for dem_bathy_review."""

from .dem_bathy_review_plugin import DemBathyReviewPlugin


def classFactory(iface):  # pylint: disable=invalid-name
    """Instantiate the plugin class for QGIS.

    Args:
        iface: QGIS interface instance supplied by QGIS at load time.

    Returns:
        DemBathyReviewPlugin: Plugin controller instance.
    """
    return DemBathyReviewPlugin(iface)
