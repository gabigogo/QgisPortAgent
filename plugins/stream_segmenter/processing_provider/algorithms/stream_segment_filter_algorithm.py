"""Downstream segment filter for stream segmenter output layers.

Takes the output of ``StreamSegmenterAlgorithm`` (or
``BatchStreamSegmenterAlgorithm``) and keeps only the most-downstream
segments of each channel, using one of two filter modes:

**Mode A — By Segment Count**
    Keep every feature whose ``seg_num`` value is ≤ N.  Because ``seg_num``
    is 1-based and resets to 1 for each original input feature (1 = most
    downstream), this selects the first *N* segments per channel without any
    explicit grouping step.

**Mode B — By Distance**
    Keep every feature whose range *starts* before a given distance threshold.
    The start distance is parsed directly from the ``mile_range`` field
    (e.g. ``"4-5 mi"`` → start = 4.0).  The threshold is interpreted in the
    same units that the original algorithm used (miles or km), so no unit
    conversion is needed.

Assumptions
-----------
- The input layer was produced by ``StreamSegmenterAlgorithm`` or
  ``BatchStreamSegmenterAlgorithm`` and therefore contains the fields
  ``seg_num`` (integer) and ``mile_range`` (string).
- ``seg_num`` is 1-based and resets per original channel feature.
- ``mile_range`` format is ``"{start}-{end} {unit}"`` (e.g. ``"0-1 mi"``).
- No grouping by channel name is required; the per-feature numbering scheme
  makes both filters channel-aware by design.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
)

from ...utils.geometry import FLD_MILE_RANGE, FLD_SEG_NUM, parse_range_start

# ── Private aliases ────────────────────────────────────────────────────────────
_FLD_SEG_NUM = FLD_SEG_NUM
_FLD_MILE_RANGE = FLD_MILE_RANGE
_parse_range_start = parse_range_start


# ── Algorithm class ────────────────────────────────────────────────────────────


class StreamSegmentFilterAlgorithm(QgsProcessingAlgorithm):
    """Filter a segmented stream layer to the most-downstream N segments or X distance.

    Operates on a layer that was produced by ``StreamSegmenterAlgorithm`` and
    passes through all features that satisfy the chosen downstream filter,
    preserving all input fields and geometries unchanged.

    Assumptions:
        Input Data:
            - Input layer contains ``seg_num`` (int) and ``mile_range`` (str)
              fields written by StreamSegmenterAlgorithm.
            - ``seg_num = 1`` is the most-downstream segment of each original
              channel feature (numbering resets per source feature).
            - ``mile_range`` label format: ``"{start}-{end} {unit}"``.
        Error Handling:
            - Missing ``seg_num`` or ``mile_range`` fields raise a
              ``QgsProcessingException``.
            - Features with null / unparseable field values are skipped with
              a non-fatal warning.
    """

    # ── Parameter keys ─────────────────────────────────────────────────────

    INPUT = "INPUT"
    FILTER_MODE = "FILTER_MODE"
    N_SEGMENTS = "N_SEGMENTS"
    MAX_DISTANCE = "MAX_DISTANCE"
    OUTPUT = "OUTPUT"

    # ── Filter mode constants ──────────────────────────────────────────────

    MODE_BY_COUNT = 0
    MODE_BY_DISTANCE = 1
    _FILTER_MODE_LABELS = [
        "First N segments per channel  (uses 'seg_num' field)",
        "First X distance per channel  (uses 'mile_range' field)",
    ]

    # ── Boilerplate ────────────────────────────────────────────────────────

    def tr(self, string: str) -> str:
        return QCoreApplication.translate("StreamSegmentFilterAlgorithm", string)

    def createInstance(self) -> "StreamSegmentFilterAlgorithm":
        return StreamSegmentFilterAlgorithm()

    def name(self) -> str:
        return "stream_segment_filter"

    def displayName(self) -> str:
        return self.tr("Stream Segment Filter")

    def group(self) -> str:
        return self.tr("Stream Tools")

    def groupId(self) -> str:
        return "stream_tools"

    def shortHelpString(self) -> str:
        return self.tr(
            "Filters the output of Stream Segmenter to keep only the most-"
            "downstream segments of each channel.\n\n"
            "Two modes are available:\n\n"
            "  • First N segments — keeps every feature where seg_num ≤ N.\n"
            "    seg_num resets to 1 (most downstream) for each original "
            "channel, so no grouping step is required.\n\n"
            "  • First X distance — keeps every feature whose mile_range label "
            "starts before the given distance threshold (in the same units "
            "used when the layer was segmented — miles or km).\n\n"
            "All input fields and geometries are passed through unchanged."
        )

    # ── Parameter definitions ──────────────────────────────────────────────

    def initAlgorithm(self, config: Optional[Dict] = None) -> None:
        """Declare input and output parameters.

        Args:
            config (Optional[Dict]): Unused framework-supplied config dict.

        Parameters declared:
            INPUT        — segmented line layer (must contain seg_num and
                           mile_range fields).
            FILTER_MODE  — enum: 0 = by segment count, 1 = by distance.
            N_SEGMENTS   — integer threshold for mode 0 (default 5).
            MAX_DISTANCE — double threshold for mode 1 (default 5.0, in the
                           same units written to mile_range).
            OUTPUT       — output sink; inherits all source fields and CRS.
        """
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                self.tr("Segmented stream layer (output of Stream Segmenter)"),
                [QgsProcessing.TypeVectorLine],
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.FILTER_MODE,
                self.tr("Filter mode"),
                options=self._FILTER_MODE_LABELS,
                defaultValue=self.MODE_BY_COUNT,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.N_SEGMENTS,
                self.tr("Number of segments to keep (mode: First N segments)"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=5,
                minValue=1,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_DISTANCE,
                self.tr(
                    "Maximum start distance to keep  —  in miles or km, "
                    "matching the unit used during segmentation "
                    "(mode: First X distance)"
                ),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=5.0,
                minValue=0.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr("Filtered segments"),
            )
        )

    # ── Core processing ────────────────────────────────────────────────────

    def processAlgorithm(
        self,
        parameters: Dict[str, Any],
        context: Any,
        feedback: Any,
    ) -> Dict[str, Any]:
        """Execute the filter workflow.

        Args:
            parameters (Dict[str, Any]): Parameter values keyed by constant names.
            context: QGIS processing context.
            feedback: QGIS feedback object for progress and cancellation.

        Returns:
            Dict[str, Any]: ``{"OUTPUT": dest_id}`` where *dest_id* is the
                output layer identifier.

        Raises:
            QgsProcessingException: If the source cannot be opened, required
                fields are missing, or the output sink cannot be created.

        Methodology:
            1. Resolve all parameters.
            2. Validate that the required field (``seg_num`` for mode 0,
               ``mile_range`` for mode 1) is present in the input layer.
            3. Create the output sink with the same field schema and CRS as
               the input.
            4. Iterate over all features; for each feature evaluate the filter
               condition and copy passing features to the sink unchanged.
            5. Report progress and feature counts.

        Examples:
            Via QGIS Python console::

                import processing
                result = processing.run(
                    "stream_segmenter:stream_segment_filter",
                    {
                        "INPUT": segmented_layer,
                        "FILTER_MODE": 0,
                        "N_SEGMENTS": 3,
                        "MAX_DISTANCE": 5.0,
                        "OUTPUT": "TEMPORARY_OUTPUT",
                    },
                )
        """
        # ── Resolve parameters ─────────────────────────────────────────────
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(
                self.invalidSourceError(parameters, self.INPUT)
            )
        source_crs = source.sourceCrs()
        if not source_crs.isValid():
            raise QgsProcessingException(
                self.tr(
                    "Input layer CRS is not valid. "
                    "A valid source CRS is required to create the filtered output."
                )
            )

        filter_mode: int = self.parameterAsEnum(
            parameters, self.FILTER_MODE, context
        )
        n_segments: int = self.parameterAsInt(
            parameters, self.N_SEGMENTS, context
        )
        max_distance: float = self.parameterAsDouble(
            parameters, self.MAX_DISTANCE, context
        )

        # ── Validate required fields ───────────────────────────────────────
        field_names = [f.name() for f in source.fields()]

        if filter_mode == self.MODE_BY_COUNT:
            if _FLD_SEG_NUM not in field_names:
                raise QgsProcessingException(
                    self.tr(
                        f"Required field '{_FLD_SEG_NUM}' not found in the input "
                        "layer. Ensure the layer was produced by Stream Segmenter."
                    )
                )
        else:
            if _FLD_MILE_RANGE not in field_names:
                raise QgsProcessingException(
                    self.tr(
                        f"Required field '{_FLD_MILE_RANGE}' not found in the "
                        "input layer. Ensure the layer was produced by "
                        "Stream Segmenter."
                    )
                )

        # ── Create output sink (same schema + CRS as input) ────────────────
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            source.fields(),
            source.wkbType(),
            source_crs,
        )
        if sink is None:
            raise QgsProcessingException(
                self.invalidSinkError(parameters, self.OUTPUT)
            )

        # ── Feature iteration ──────────────────────────────────────────────
        feature_count = source.featureCount()
        total_progress = 100.0 / feature_count if feature_count > 0 else 0.0
        kept = 0
        skipped = 0

        for current, feature in enumerate(source.getFeatures()):
            if feedback.isCanceled():
                break

            keep = False

            if filter_mode == self.MODE_BY_COUNT:
                raw_seg = feature[_FLD_SEG_NUM]
                if raw_seg is None:
                    feedback.reportError(
                        self.tr(
                            f"Feature {feature.id()}: null '{_FLD_SEG_NUM}' "
                            "value — skipped."
                        ),
                        fatalError=False,
                    )
                    skipped += 1
                else:
                    keep = int(raw_seg) <= n_segments

            else:  # MODE_BY_DISTANCE
                raw_range = feature[_FLD_MILE_RANGE]
                if raw_range is None:
                    feedback.reportError(
                        self.tr(
                            f"Feature {feature.id()}: null '{_FLD_MILE_RANGE}' "
                            "value — skipped."
                        ),
                        fatalError=False,
                    )
                    skipped += 1
                else:
                    start = _parse_range_start(str(raw_range))
                    if start is None:
                        feedback.reportError(
                            self.tr(
                                f"Feature {feature.id()}: could not parse "
                                f"'{_FLD_MILE_RANGE}' value '{raw_range}' — skipped."
                            ),
                            fatalError=False,
                        )
                        skipped += 1
                    else:
                        keep = start < max_distance

            if keep:
                sink.addFeature(feature, QgsFeatureSink.FastInsert)
                kept += 1

            feedback.setProgress(int(current * total_progress))

        mode_label = (
            f"seg_num ≤ {n_segments}"
            if filter_mode == self.MODE_BY_COUNT
            else f"start < {max_distance}"
        )
        feedback.pushInfo(
            self.tr(
                f"Filter complete ({mode_label}): "
                f"{kept} feature(s) kept, {skipped} skipped."
            )
        )

        return {self.OUTPUT: dest_id}
