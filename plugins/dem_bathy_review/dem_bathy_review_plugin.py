"""Main plugin lifecycle class for DEM bathymetry review."""

from qgis.core import QgsApplication

from .processing_provider.provider import DemBathyReviewProvider


class DemBathyReviewPlugin:
    """Registers and unregisters the Processing provider for this plugin."""

    def __init__(self, iface):
        """Store QGIS interface and prepare provider state.

        Args:
            iface: QGIS interface object provided by QGIS.
        """
        self.iface = iface
        self.provider = None

    def initGui(self):
        """Initialize plugin GUI hooks by registering the Processing provider."""
        self.provider = DemBathyReviewProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        """Unload plugin GUI hooks by removing the Processing provider."""
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
