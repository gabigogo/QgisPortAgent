"""Processing provider registration for the Stream Segmenter plugin."""

from qgis.core import QgsProcessingProvider

from .algorithms.stream_segmenter_algorithm import StreamSegmenterAlgorithm
from .algorithms.batch_stream_segmenter_algorithm import BatchStreamSegmenterAlgorithm
from .algorithms.stream_segment_filter_algorithm import StreamSegmentFilterAlgorithm
from .algorithms.batch_stream_segment_filter_algorithm import (
    BatchStreamSegmentFilterAlgorithm,
)
from .algorithms.stream_segment_table_filter_algorithm import (
    StreamSegmentTableFilterAlgorithm,
)
from .algorithms.batch_stream_segment_table_filter_algorithm import (
    BatchStreamSegmentTableFilterAlgorithm,
)
from .algorithms.stream_order_algorithm import StreamOrderAlgorithm
from .algorithms.batch_stream_order_algorithm import BatchStreamOrderAlgorithm


class StreamSegmenterProvider(QgsProcessingProvider):
    """Registers Stream Segmenter algorithms in the QGIS Processing toolbox."""

    def loadAlgorithms(self) -> None:
        """Load plugin algorithms into this provider."""
        self.addAlgorithm(StreamSegmenterAlgorithm())
        self.addAlgorithm(BatchStreamSegmenterAlgorithm())
        self.addAlgorithm(StreamSegmentFilterAlgorithm())
        self.addAlgorithm(BatchStreamSegmentFilterAlgorithm())
        self.addAlgorithm(StreamSegmentTableFilterAlgorithm())
        self.addAlgorithm(BatchStreamSegmentTableFilterAlgorithm())
        self.addAlgorithm(StreamOrderAlgorithm())
        self.addAlgorithm(BatchStreamOrderAlgorithm())

    def id(self) -> str:
        """Return the stable provider identifier used by QGIS.

        Returns:
            str: Provider id string.
        """
        return "stream_segmenter"

    def name(self) -> str:
        """Return the provider display name shown in the Processing toolbox.

        Returns:
            str: Human-readable provider name.
        """
        return "Stream Segmenter"

    def longName(self) -> str:
        """Return verbose provider name for UI contexts that support it.

        Returns:
            str: Verbose provider name.
        """
        return self.name()
