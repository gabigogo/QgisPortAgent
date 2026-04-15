"""Main plugin lifecycle class for the Stream Segmenter plugin."""

from qgis.core import QgsApplication

from .processing_provider.provider import StreamSegmenterProvider


class StreamSegmenterPlugin:
    """Registers and unregisters the Processing provider for this plugin."""

    def __init__(self, iface) -> None:
        """Store the QGIS interface reference and prepare provider state.

        Args:
            iface: QGIS interface object supplied by QGIS at load time.
        """
        self.iface = iface
        self.provider = None

    def initGui(self) -> None:
        """Initialize GUI hooks by registering the Processing provider."""
        self.provider = StreamSegmenterProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self) -> None:
        """Unload GUI hooks by removing the Processing provider."""
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
