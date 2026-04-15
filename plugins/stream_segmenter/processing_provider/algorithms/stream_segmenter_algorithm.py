"""Stream segmentation Processing algorithm.

Segments stream centerline features (LineString / MultiLineString) into
equal-length intervals measured from the downstream endpoint outward.
Each output segment receives three new attribute fields:

- ``seg_num``       -- integer, 1-based index from the downstream end.
- ``mile_range``    -- string range label, e.g. ``"0-1 mi"`` or ``"0-1 km"``.
- ``stream_seg_id`` -- unique identifier, e.g. ``"Bear_Creek_mile_01"``.

Assumptions
-----------
- One stream name per input feature (no cross-feature grouping).
- The **last vertex** of a LineString (or the last vertex of the last part
  of a MultiLineString) is the most **downstream** point.
- MultiLineString parts must form a topologically connected chain; features
  where the chain cannot be resolved are skipped with a non-fatal warning.
- Input layer CRS is projected or geographic; length is always measured
  geodetically via ``QgsDistanceArea`` (returns metres) so that segment
  boundaries are accurate in real-world units regardless of source CRS.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsDistanceArea,
    QgsFeature,
    QgsFeatureRequest,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProject,
    QgsUnitTypes,
    QgsVectorLayer,
    QgsWkbTypes,
)
from ...utils.geometry import (
    FLD_LENGTH_MI,
    FLD_MILE_RANGE,
    FLD_SEG_NUM,
    FLD_STREAM_SEG_ID,
    KM_TO_METRES,
    MILES_TO_METRES,
    NEW_FIELD_NAMES,
    cut_fraction,
    fmt_distance,
    sanitize_name,
    to_oriented_line,
)

# ── Private aliases  (keep body code readable with short _ names) ─────────────
_FLD_SEG_NUM = FLD_SEG_NUM
_FLD_MILE_RANGE = FLD_MILE_RANGE
_FLD_STREAM_SEG_ID = FLD_STREAM_SEG_ID
_FLD_LENGTH_MI = FLD_LENGTH_MI
_KM_TO_METRES = KM_TO_METRES
_MILES_TO_METRES = MILES_TO_METRES
_NEW_FIELD_NAMES = NEW_FIELD_NAMES
_sanitize_name = sanitize_name
_cut_fraction = cut_fraction
_fmt = fmt_distance
_to_oriented_line_from_wkb = to_oriented_line
_SRC_FID_FIELD = "src_fid"


# ── Algorithm class ───────────────────────────────────────────────────────────


class StreamSegmenterAlgorithm(QgsProcessingAlgorithm):
    """Divide stream centerlines into equal-length segments from the downstream end.

    For each input LineString or MultiLineString feature the algorithm:

    1. Orients the geometry so processing starts at the downstream endpoint
       (defined as the last vertex of the input line / last part's last vertex).
    2. Measures the total geodetic length via ``QgsDistanceArea`` (metres).
    3. Cuts the oriented line into ``ceil(total / segment_length)`` equal chunks
       using ``shapely.ops.substring`` with normalised fractional positions.
    4. Writes each chunk to the output sink with ``seg_num``, ``mile_range``,
       and ``stream_seg_id`` fields appended (plus optionally all source fields).

    Assumptions:
        Input Data:
            - One stream name value per input feature.
            - Last vertex = downstream endpoint (single-part and multi-part).
            - MultiLineString parts form a topologically connected chain that
              ``shapely.ops.linemerge`` can resolve to a single LineString.
        Environment:
            - ``shapely >= 2.0`` available in the QGIS Python environment.
            - ``QgsProject.instance().ellipsoid()`` is set; falls back to GRS80.
        Error Handling:
            - Null geometry, non-line geometry, zero-length lines, and
              unresolvable MultiLineStrings are skipped with non-fatal warnings.
    """

    # ── Parameter keys ─────────────────────────────────────────────────────

    INPUT = "INPUT"
    NAME_FIELD = "NAME_FIELD"
    SELECTED_ONLY = "SELECTED_ONLY"
    SEGMENT_LENGTH = "SEGMENT_LENGTH"
    USE_KM = "USE_KM"
    PRESERVE_ATTRS = "PRESERVE_ATTRS"
    OUTPUT = "OUTPUT"

    # ── Boilerplate ────────────────────────────────────────────────────────

    def tr(self, string: str) -> str:
        """Translate *string* via Qt translation framework.

        Args:
            string (str): Source string to translate.

        Returns:
            str: Translated string (falls back to the original if no translation).
        """
        return QCoreApplication.translate("StreamSegmenterAlgorithm", string)

    def createInstance(self) -> "StreamSegmenterAlgorithm":
        """Return a fresh instance of this algorithm.

        Returns:
            StreamSegmenterAlgorithm: New instance.
        """
        return StreamSegmenterAlgorithm()

    def name(self) -> str:
        """Return the stable algorithm identifier (no spaces, lowercase).

        Returns:
            str: Algorithm id used internally by QGIS Processing.
        """
        return "stream_segmenter"

    def displayName(self) -> str:
        """Return the human-readable algorithm name shown in the toolbox.

        Returns:
            str: Translated display name.
        """
        return self.tr("Stream Segmenter")

    def group(self) -> str:
        """Return the algorithm group display name.

        Returns:
            str: Translated group name.
        """
        return self.tr("Stream Tools")

    def groupId(self) -> str:
        """Return the stable algorithm group identifier.

        Returns:
            str: Group id string.
        """
        return "stream_tools"

    def shortHelpString(self) -> str:
        """Return a brief description shown in the Processing dialog help panel.

        Returns:
            str: Translated short help string.
        """
        return self.tr(
            "Segments stream centerline features (LineString / MultiLineString) "
            "into equal-length intervals measured from the downstream endpoint "
            "outward.\n\n"
            "Each output segment receives three new fields:\n"
            "  • seg_num        — integer segment index (1 = most downstream)\n"
            "  • mile_range     — range label, e.g. '0-1 mi' or '0-1 km'\n"
            "  • stream_seg_id  — unique ID, e.g. 'Bear_Creek_mile_01'\n\n"
            "The downstream endpoint is the LAST vertex of the input line (or "
            "the last vertex of the last part for MultiLineString features).\n\n"
            "MultiLineString parts must form a connected chain; features that "
            "cannot be merged are skipped with a warning."
        )

    # ── Parameter definitions ──────────────────────────────────────────────

    def initAlgorithm(self, config: Optional[Dict] = None) -> None:
        """Declare all input and output parameters for the algorithm.

        Args:
            config (Optional[Dict]): Unused configuration dictionary supplied
                by the Processing framework.

        Methodology:
            1. Source layer — TypeVectorLine, accepts any OGR-readable format
               or QGIS in-memory layer.
            2. Stream name field — any field type (string IDs and integer unit
               numbers are both valid stream name sources).
            3. Selected-only boolean — restricts to selected features.
            4. Segment length — positive double, default 1.0.
            5. Unit toggle (km) — switches label suffix and conversion factor.
            6. Preserve source attributes — copies original fields to output.
            7. Output sink — LineString, inherits source CRS.
        """
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                self.tr("Stream centerline layer"),
                [QgsProcessing.TypeVectorLine],
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.NAME_FIELD,
                self.tr("Stream name field"),
                parentLayerParameterName=self.INPUT,
                type=QgsProcessingParameterField.Any,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.SELECTED_ONLY,
                self.tr("Process selected features only"),
                defaultValue=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SEGMENT_LENGTH,
                self.tr("Segment length"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=1.0,
                minValue=0.01,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.USE_KM,
                self.tr("Use kilometres instead of miles"),
                defaultValue=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.PRESERVE_ATTRS,
                self.tr("Preserve source attributes in output"),
                defaultValue=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr("Segmented streams"),
            )
        )

    # ── Core processing ────────────────────────────────────────────────────

    @staticmethod
    def _length_to_meters(length_native: float, crs: Any) -> float:
        """Convert a CRS-native length value to meters."""
        if length_native <= 0.0:
            return 0.0

        try:
            from qgis.core import Qgis

            units = crs.mapUnits()

            # Prefer QGIS' built-in unit conversion table for projected CRS units.
            # Avoid using a constant conversion for degrees/unknown units.
            if units not in (Qgis.DistanceUnit.Degrees, Qgis.DistanceUnit.Unknown):
                factor = QgsUnitTypes.fromUnitToUnitFactor(
                    units, Qgis.DistanceUnit.Meters
                )
                if factor > 0.0:
                    return length_native * factor

            if units == QgsUnitTypes.DistanceMeters:
                return length_native
            if units == QgsUnitTypes.DistanceFeet:
                return length_native * 0.3048
            if units == QgsUnitTypes.DistanceNauticalMiles:
                return length_native * 1852.0
            if units == QgsUnitTypes.DistanceYards:
                return length_native * 0.9144
            if units == QgsUnitTypes.DistanceMiles:
                return length_native * 1609.344
            if units == QgsUnitTypes.DistanceKilometers:
                return length_native * 1000.0
            if units == QgsUnitTypes.DistanceCentimeters:
                return length_native * 0.01
            if units == QgsUnitTypes.DistanceMillimeters:
                return length_native * 0.001
            # US Survey Feet (QGIS 3.30+  Qgis.DistanceUnit.FeetUSSurvey)
            # 1 US survey foot = 1200/3937 metres exactly.
            try:
                if units == Qgis.DistanceUnit.FeetUSSurvey:
                    return length_native * (1200.0 / 3937.0)
            except (AttributeError, ImportError):
                pass
        except Exception:
            pass

        return length_native

    def processAlgorithm(
        self,
        parameters: Dict[str, Any],
        context: Any,
        feedback: Any,
    ) -> Dict[str, Any]:
        """Execute the segmentation workflow.

        Args:
            parameters (Dict[str, Any]): Algorithm parameter values keyed by
                their parameter name constants.
            context: QGIS processing context providing CRS transform context
                and project reference.
            feedback: QGIS feedback object for progress reporting and
                cancellation checks.

        Returns:
            Dict[str, Any]: Output dictionary mapping ``OUTPUT`` to the
                destination layer identifier string.

        Raises:
            QgsProcessingException: If the source layer cannot be opened or
                the output sink cannot be created.

        Methodology:
            1. Resolve all parameter values.
            2. Build the output field schema (optionally prepend source fields).
            3. Open the output sink (LineString, same CRS as source).
            4. Configure ``QgsDistanceArea`` for geodetic length measurement.
            5. Determine the feature iterator: all features or selected only.
            6. For each feature:
               a. Skip null / non-line geometries with a non-fatal warning.
               b. Sanitize the stream name.
               c. Convert the QgsGeometry to an oriented shapely LineString
                  (downstream end = first coordinate).
               d. Measure geodetic total length in metres.
               e. Compute ``n_segs = ceil(total_m / seg_m)``.
               f. For each segment, cut using normalised shapely substring,
                  compute the three new field values, and write to the sink.
            7. Report per-feature progress.

        Examples:
            Typical invocation via the QGIS Python console::

                import processing
                result = processing.run(
                    "stream_segmenter:stream_segmenter",
                    {
                        "INPUT": "/data/channels.gpkg|layername=centerlines",
                        "NAME_FIELD": "stream_name",
                        "SELECTED_ONLY": False,
                        "SEGMENT_LENGTH": 1.0,
                        "USE_KM": False,
                        "PRESERVE_ATTRS": False,
                        "OUTPUT": "TEMPORARY_OUTPUT",
                    },
                )
                layer = result["OUTPUT"]
        """
        # ── Resolve parameters ─────────────────────────────────────────────
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(
                self.invalidSourceError(parameters, self.INPUT)
            )

        name_field: str = self.parameterAsString(
            parameters, self.NAME_FIELD, context
        )
        selected_only: bool = self.parameterAsBool(
            parameters, self.SELECTED_ONLY, context
        )
        segment_length: float = self.parameterAsDouble(
            parameters, self.SEGMENT_LENGTH, context
        )
        use_km: bool = self.parameterAsBool(parameters, self.USE_KM, context)
        preserve_attrs: bool = self.parameterAsBool(
            parameters, self.PRESERVE_ATTRS, context
        )

        # ── Unit configuration ─────────────────────────────────────────────
        if use_km:
            seg_m = segment_length * _KM_TO_METRES
            unit_label = "km"
            id_unit = "_km_"
        else:
            seg_m = segment_length * _MILES_TO_METRES
            unit_label = "mi"
            id_unit = "_mile_"

        # ── Output field schema ────────────────────────────────────────────
        out_fields = QgsFields()
        if preserve_attrs:
            existing_names = set()
            for field in source.fields():
                fname = field.name()
                out_name = fname

                # Never preserve a literal "fid" column into output layers.
                if fname.lower() == "fid":
                    out_name = _SRC_FID_FIELD
                elif fname in _NEW_FIELD_NAMES:
                    out_name = fname + "_src"

                if out_name in existing_names or out_name in _NEW_FIELD_NAMES:
                    base = out_name
                    suffix = 1
                    while f"{base}_{suffix}" in existing_names or f"{base}_{suffix}" in _NEW_FIELD_NAMES:
                        suffix += 1
                    out_name = f"{base}_{suffix}"

                # Create proper copy with all attributes (length, precision, comment)
                new_field = QgsField(
                    fname,
                    field.type(),
                    field.typeName(),
                    field.length(),
                    field.precision(),
                    field.comment(),
                )
                if out_name != fname:
                    new_field.setName(out_name)
                out_fields.append(new_field)
                existing_names.add(out_name)
        out_fields.append(QgsField(_FLD_SEG_NUM, QVariant.Int, "Integer", 10, 0))
        out_fields.append(QgsField(_FLD_MILE_RANGE, QVariant.String, "String", 30, 0))
        out_fields.append(QgsField(_FLD_STREAM_SEG_ID, QVariant.String, "String", 100, 0))
        out_fields.append(QgsField(_FLD_LENGTH_MI, QVariant.Double, "Real", 12, 4))

        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            out_fields,
            QgsWkbTypes.LineString,
            source.sourceCrs(),
        )
        if sink is None:
            raise QgsProcessingException(
                self.invalidSinkError(parameters, self.OUTPUT)
            )

        # ── Geodetic distance calculator ───────────────────────────────────
        da = QgsDistanceArea()
        da.setSourceCrs(source.sourceCrs(), context.transformContext())
        ellipsoid: str = QgsProject.instance().ellipsoid() or "GRS80"
        da.setEllipsoid(ellipsoid)

        if not da.willUseEllipsoid():
            feedback.pushWarning(
                self.tr(
                    "The layer CRS does not support ellipsoidal measurement. "
                    "Segment lengths are computed in CRS native units. "
                    "For accurate mile/km results, use a projected CRS in metres or feet."
                )
            )

        # ── Feature iteration ──────────────────────────────────────────────
        layer: Optional[QgsVectorLayer] = self.parameterAsVectorLayer(
            parameters, self.INPUT, context
        )

        if selected_only and layer is not None:
            sel_ids = layer.selectedFeatureIds()
            if sel_ids:
                request = QgsFeatureRequest().setFilterFids(sel_ids)
                features = layer.getFeatures(request)
                feature_count = len(sel_ids)
            else:
                feedback.pushWarning(
                    self.tr(
                        "Selected features only is enabled but no features are "
                        "selected in the input layer. Processing all features."
                    )
                )
                features = source.getFeatures()
                feature_count = source.featureCount()
        else:
            features = source.getFeatures()
            feature_count = source.featureCount()

        total_progress = 100.0 / feature_count if feature_count > 0 else 0.0

        # ── Main loop ──────────────────────────────────────────────────────
        for current, feature in enumerate(features):
            if feedback.isCanceled():
                break

            # ── Input validation ───────────────────────────────────────────
            geom = feature.geometry()
            if geom is None or geom.isNull():
                feedback.reportError(
                    self.tr(f"Feature {feature.id()}: null geometry — skipped."),
                    fatalError=False,
                )
                continue

            if geom.type() != QgsWkbTypes.LineGeometry:
                feedback.reportError(
                    self.tr(
                        f"Feature {feature.id()}: not a line geometry "
                        f"(type={geom.type()}) — skipped."
                    ),
                    fatalError=False,
                )
                continue

            # ── Stream name ────────────────────────────────────────────────
            raw_name = feature[name_field]
            stream_name = _sanitize_name(str(raw_name) if raw_name is not None else "")
            if not stream_name:
                stream_name = f"feature_{feature.id()}"

            # ── Orient geometry: start = downstream ────────────────────────
            oriented, err = _to_oriented_line_from_wkb(bytes(geom.asWkb()))
            if err:
                feedback.reportError(
                    self.tr(
                        f"Feature {feature.id()} ('{stream_name}'): {err} — skipped."
                    ),
                    fatalError=False,
                )
                continue

            # ── Total length (meters) via geodetic measurement ─────────────────
            # Always use QgsDistanceArea.measureLength so that geographic-CRS
            # layers (e.g. EPSG:4326, units=degrees) return correct metre values
            # instead of Euclidean degree-valued lengths that cause n_segs=1 and
            # make the entire line output as a single un-segmented feature.
            total_m: float = da.measureLength(geom)

            # In non-ellipsoidal mode, QgsDistanceArea returns CRS-native units.
            # Normalize to metres so segment-length math remains unit-safe.
            if total_m > 0.0 and not da.willUseEllipsoid():
                total_m = self._length_to_meters(total_m, source.sourceCrs())

            # Last-resort fallback for CRS unsupported by QgsDistanceArea.
            if total_m <= 0.0:
                total_native = float(oriented.length)
                total_m = self._length_to_meters(total_native, source.sourceCrs())

            if total_m <= 0.0:
                feedback.reportError(
                    self.tr(
                        f"Feature {feature.id()} ('{stream_name}'): "
                        "zero-length geometry — skipped."
                    ),
                    fatalError=False,
                )
                continue

            # ── Segment count and zero-pad width ───────────────────────────
            n_segs = math.ceil(total_m / seg_m)
            total_user_units: float = total_m / (
                _KM_TO_METRES if use_km else _MILES_TO_METRES
            )
            pad = max(2, len(str(n_segs)))

            # ── Cut and write segments ─────────────────────────────────────
            for i in range(n_segs):
                if feedback.isCanceled():
                    break

                start_frac = (i * seg_m) / total_m
                end_frac = min(((i + 1) * seg_m) / total_m, 1.0)

                seg_shapely = _cut_fraction(oriented, start_frac, end_frac)
                if seg_shapely is None:
                    continue

                seg_qgs = QgsGeometry()
                seg_qgs.fromWkb(bytes(seg_shapely.wkb))

                # Compute geodetic length of this segment in miles (or km).
                seg_da = QgsDistanceArea()
                seg_da.setSourceCrs(source.sourceCrs(), context.transformContext())
                seg_da.setEllipsoid(ellipsoid)
                seg_length_m = seg_da.measureLength(seg_qgs)
                if seg_length_m > 0.0 and not seg_da.willUseEllipsoid():
                    seg_length_m = self._length_to_meters(
                        seg_length_m, source.sourceCrs()
                    )
                if seg_length_m <= 0.0:
                    # Fallback: proportional estimate from total.
                    seg_length_m = total_m * (end_frac - start_frac)
                seg_length_mi = seg_length_m / _MILES_TO_METRES

                seg_num = i + 1
                start_u = i * segment_length
                end_u = min((i + 1) * segment_length, total_user_units)
                mile_range = f"{_fmt(start_u)}-{_fmt(end_u)} {unit_label}"
                stream_seg_id = f"{stream_name}{id_unit}{seg_num:0{pad}d}"

                out_feat = QgsFeature(out_fields)
                out_feat.setGeometry(seg_qgs)

                attrs: List[Any] = []
                if preserve_attrs:
                    # Keep source-attribute ordering aligned with source field order.
                    attrs.extend(feature.attributes())
                attrs.extend([seg_num, mile_range, stream_seg_id, round(seg_length_mi, 4)])

                if len(attrs) != out_fields.count():
                    feedback.reportError(
                        self.tr(
                            f"Feature {feature.id()} segment {seg_num}: "
                            f"attribute count mismatch ({len(attrs)} values, "
                            f"{out_fields.count()} fields) — skipped."
                        ),
                        fatalError=False,
                    )
                    continue

                assign_failed = False
                for idx, value in enumerate(attrs):
                    if not out_feat.setAttribute(idx, value):
                        fld = out_fields.at(idx)
                        feedback.reportError(
                            self.tr(
                                f"Feature {feature.id()} segment {seg_num}: "
                                f"failed to set attributes (field '{fld.name()}' "
                                f"type='{fld.typeName()}' value={value!r} "
                                f"pytype={type(value).__name__}) — skipped."
                            ),
                            fatalError=False,
                        )
                        assign_failed = True
                        break
                if assign_failed:
                    continue

                if not sink.addFeature(out_feat, QgsFeatureSink.FastInsert):
                    feedback.reportError(
                        self.tr(
                            f"Feature {feature.id()} segment {seg_num}: "
                            "failed to add feature to sink — skipped."
                        ),
                        fatalError=False,
                    )
                    continue

            feedback.setProgress(int(current * total_progress))
            feedback.pushInfo(
                self.tr(
                    f"  {stream_name}: {n_segs} segment(s) "
                    f"({_fmt(total_user_units)} {unit_label} total)."
                )
            )

        return {self.OUTPUT: dest_id}
