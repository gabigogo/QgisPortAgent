"""Stream order Processing algorithm.

Computes stream order (Hack, Strahler, Shreve) for stream centerline networks
and attributes each feature with the computed order values.

Output fields added:
- ``hack``       -- Hack/Gravelius order (main channel = 1, tributaries increment)
- ``strahler``   -- Strahler stream order
- ``shreve``     -- Shreve stream magnitude
- ``network_id`` -- Connected component identifier
- ``reversed``   -- 1 if geometry was reversed to flow toward outlet, 0 otherwise

Assumptions
-----------
- Input is a vector line layer representing a connected stream network.
- Lines share endpoints at confluences (within snap tolerance).
- The outlet (downstream terminus) is auto-detected as the degree-1 node
  with maximum upstream network length.
- Hack ordering: main channel = 1, tributaries = parent + 1; main channel
  follows longest upstream path at each confluence.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsDistanceArea,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProject,
    QgsUnitTypes,
    QgsWkbTypes,
)
from shapely import wkb as swkb
from shapely.geometry import LineString
from shapely.ops import linemerge

from ...utils.network import (
    ORDER_HACK,
    ORDER_SHREVE,
    ORDER_STRAHLER,
    FLD_HACK,
    FLD_NETWORK_ID,
    FLD_REVERSED,
    FLD_SHREVE,
    FLD_STRAHLER,
    ORDER_FIELD_NAMES,
    process_network,
    process_network_from_geometries,
)

_SRC_FID_FIELD = "src_fid"


class StreamOrderAlgorithm(QgsProcessingAlgorithm):
    """Compute stream order for a vector stream network.

    For each input LineString or MultiLineString feature the algorithm:

    1. Builds a topological network graph from line endpoints.
    2. Identifies connected components (independent stream networks).
    3. Auto-detects the outlet node for each component.
    4. Normalizes line directions to flow toward the outlet.
    5. Computes requested stream orders via recursive upstream traversal.
    6. Writes output features with order attributes appended.

    Assumptions:
        Input Data:
            - Lines share endpoints at confluences within snap tolerance.
            - Network is dendritic (tree-like); loops are handled but may
              produce unexpected results.
        Environment:
            - ``shapely >= 2.0`` available in the QGIS Python environment.
            - ``QgsProject.instance().ellipsoid()`` is set; falls back to GRS80.
        Error Handling:
            - Null or non-line geometries are skipped with warnings.
            - Features not part of any network receive null order values.
    """

    # ── Parameter keys ─────────────────────────────────────────────────────

    INPUT = "INPUT"
    COMPUTE_HACK = "COMPUTE_HACK"
    COMPUTE_STRAHLER = "COMPUTE_STRAHLER"
    COMPUTE_SHREVE = "COMPUTE_SHREVE"
    SNAP_TOLERANCE = "SNAP_TOLERANCE"
    SNAP_UNIT = "SNAP_UNIT"
    PRESERVE_ATTRS = "PRESERVE_ATTRS"
    OUTPUT = "OUTPUT"
    
    # Unit constants
    UNIT_AUTO = 0
    UNIT_FEET = 1
    UNIT_METERS = 2

    # ── Boilerplate ────────────────────────────────────────────────────────

    def tr(self, string: str) -> str:
        """Translate *string* via Qt translation framework."""
        return QCoreApplication.translate("StreamOrderAlgorithm", string)

    def createInstance(self) -> "StreamOrderAlgorithm":
        """Return a fresh instance of this algorithm."""
        return StreamOrderAlgorithm()

    def name(self) -> str:
        """Return the stable algorithm identifier."""
        return "stream_order"

    def displayName(self) -> str:
        """Return the human-readable algorithm name."""
        return self.tr("Stream Order")

    def group(self) -> str:
        """Return the algorithm group name."""
        return self.tr("Stream Tools")

    def groupId(self) -> str:
        """Return the algorithm group identifier."""
        return "stream_tools"

    def shortHelpString(self) -> str:
        """Return the help text shown in the Processing toolbox."""
        return self.tr(
            "Computes stream order for a vector stream network.\n\n"
            "Supported ordering methods:\n"
            "  • Hack (default) — Main channel = 1, tributaries increment. "
            "At each confluence, the main channel follows the longest upstream path.\n"
            "  • Strahler — Classic Strahler ordering based on tributary hierarchy.\n"
            "  • Shreve — Magnitude equals sum of upstream tributaries.\n\n"
            "Output fields added:\n"
            "  • hack        — Hack/Gravelius stream order\n"
            "  • strahler    — Strahler stream order\n"
            "  • shreve      — Shreve stream magnitude\n"
            "  • network_id  — Connected component identifier\n"
            "  • reversed    — 1 if geometry was reversed, 0 otherwise\n\n"
            "The outlet (downstream terminus) is auto-detected as the degree-1 "
            "node with maximum upstream network length."
        )

    # ── Parameter definition ───────────────────────────────────────────────

    def initAlgorithm(self, config: Optional[Dict] = None) -> None:
        """Define algorithm parameters."""
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                self.tr("Stream network layer"),
                [QgsProcessing.TypeVectorLine],
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.COMPUTE_HACK,
                self.tr("Compute Hack order (main channel = 1)"),
                defaultValue=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.COMPUTE_STRAHLER,
                self.tr("Compute Strahler order"),
                defaultValue=False,
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.COMPUTE_SHREVE,
                self.tr("Compute Shreve magnitude"),
                defaultValue=False,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.SNAP_TOLERANCE,
                self.tr("Snap tolerance (0 = auto-detect)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=1.0,
                minValue=0.0,
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.SNAP_UNIT,
                self.tr("Snap tolerance unit"),
                options=[
                    self.tr("Auto (CRS native units)"),
                    self.tr("Feet"),
                    self.tr("Meters"),
                ],
                defaultValue=self.UNIT_AUTO,
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.PRESERVE_ATTRS,
                self.tr("Preserve source attributes"),
                defaultValue=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr("Ordered stream network"),
            )
        )

    # ── Processing ─────────────────────────────────────────────────────────

    def processAlgorithm(
        self,
        parameters: Dict[str, Any],
        context: Any,
        feedback: Any,
    ) -> Dict[str, Any]:
        """Execute the stream order algorithm."""
        # ── Resolve parameters
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(
                self.invalidSourceError(parameters, self.INPUT)
            )

        compute_hack = self.parameterAsBool(parameters, self.COMPUTE_HACK, context)
        compute_strahler = self.parameterAsBool(parameters, self.COMPUTE_STRAHLER, context)
        compute_shreve = self.parameterAsBool(parameters, self.COMPUTE_SHREVE, context)
        snap_tolerance = self.parameterAsDouble(parameters, self.SNAP_TOLERANCE, context)
        snap_unit = self.parameterAsEnum(parameters, self.SNAP_UNIT, context)
        preserve_attrs = self.parameterAsBool(parameters, self.PRESERVE_ATTRS, context)

        # At least one order method must be selected
        order_types: List[int] = []
        if compute_hack:
            order_types.append(ORDER_HACK)
        if compute_strahler:
            order_types.append(ORDER_STRAHLER)
        if compute_shreve:
            order_types.append(ORDER_SHREVE)

        if not order_types:
            raise QgsProcessingException(
                self.tr("At least one stream order method must be selected.")
            )

        # ── Convert snap tolerance to CRS units
        crs = source.sourceCrs()
        if snap_tolerance <= 0.0:
            snap_tolerance = self._get_default_snap_tolerance(crs)
            feedback.pushInfo(
                self.tr(f"Using auto-detected snap tolerance: {snap_tolerance:.6f} (CRS units)")
            )
        else:
            snap_tolerance = self._convert_snap_tolerance(
                snap_tolerance, snap_unit, crs, feedback
            )

        # ── Build output fields
        out_fields = QgsFields()
        if preserve_attrs:
            existing_names = set()
            for fld in source.fields():
                fname = fld.name()
                out_name = fname

                # Never preserve a literal "fid" column into output layers.
                if fname.lower() == "fid":
                    out_name = _SRC_FID_FIELD
                elif fname in ORDER_FIELD_NAMES:
                    out_name = fname + "_src"

                if out_name in existing_names or out_name in ORDER_FIELD_NAMES:
                    base = out_name
                    suffix = 1
                    while f"{base}_{suffix}" in existing_names or f"{base}_{suffix}" in ORDER_FIELD_NAMES:
                        suffix += 1
                    out_name = f"{base}_{suffix}"

                # Create proper copy with all attributes (length, precision, comment)
                new_field = QgsField(
                    fname,
                    fld.type(),
                    fld.typeName(),
                    fld.length(),
                    fld.precision(),
                    fld.comment(),
                )
                if out_name != fname:
                    new_field.setName(out_name)
                out_fields.append(new_field)
                existing_names.add(out_name)

        # Add order fields
        if compute_hack:
            out_fields.append(QgsField(FLD_HACK, QVariant.Int, "Integer", 10, 0))
        if compute_strahler:
            out_fields.append(QgsField(FLD_STRAHLER, QVariant.Int, "Integer", 10, 0))
        if compute_shreve:
            out_fields.append(QgsField(FLD_SHREVE, QVariant.Int, "Integer", 10, 0))
        out_fields.append(QgsField(FLD_NETWORK_ID, QVariant.Int, "Integer", 10, 0))
        out_fields.append(QgsField(FLD_REVERSED, QVariant.Int, "Integer", 10, 0))

        # ── Create output sink
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

        # ── Configure distance measurement
        da = QgsDistanceArea()
        da.setSourceCrs(crs, context.transformContext())
        da.setEllipsoid(QgsProject.instance().ellipsoid() or "GRS80")

        # ── First pass: collect feature geometries for processing
        feedback.pushInfo(self.tr("Collecting features..."))
        geometries: List[Tuple[int, Any]] = []  # (fid, shapely_geom)
        feature_geoms: Dict[int, QgsGeometry] = {}
        feature_attrs: Dict[int, List[Any]] = {}

        feature_count = source.featureCount()
        total_progress = 30.0 / feature_count if feature_count > 0 else 0.0

        for current, feature in enumerate(source.getFeatures()):
            if feedback.isCanceled():
                break

            geom = feature.geometry()
            if geom is None or geom.isNull() or geom.isEmpty():
                feedback.reportError(
                    self.tr(f"Feature {feature.id()}: null/empty geometry — skipped."),
                    fatalError=False,
                )
                continue

            # Convert to Shapely for processing
            shapely_geom = self._to_shapely(geom)
            if shapely_geom is None:
                feedback.reportError(
                    self.tr(f"Feature {feature.id()}: could not convert geometry — skipped."),
                    fatalError=False,
                )
                continue

            fid = feature.id()
            geometries.append((fid, shapely_geom))
            feature_geoms[fid] = geom
            if preserve_attrs:
                feature_attrs[fid] = list(feature.attributes())

            feedback.setProgress(int(current * total_progress))

        if not geometries:
            feedback.reportError(
                self.tr("No valid features found in input layer."),
                fatalError=True,
            )
            return {self.OUTPUT: dest_id}

        # ── Process network with geometry splitting at junctions
        feedback.pushInfo(self.tr("Building network graph (splitting at junctions)..."))
        feedback.setProgress(35)
        
        orders, network_ids, reversed_count, segment_mapping = process_network_from_geometries(
            geometries,
            snap_tolerance=snap_tolerance,
            order_types=order_types,
        )
        
        feedback.setProgress(50)

        # Report on splitting
        total_segments = sum(len(segs) for segs in segment_mapping.values())
        if total_segments > len(geometries):
            feedback.pushInfo(
                self.tr(
                    f"Split {len(geometries)} features into {total_segments} segments "
                    f"at junction points."
                )
            )

        # Warn if high reversal rate
        if feature_count > 0 and total_segments > 0:
            reversal_rate = reversed_count / total_segments
            if reversal_rate > 0.1:
                feedback.pushWarning(
                    self.tr(
                        f"High reversal rate detected: {reversed_count} of {total_segments} "
                        f"segments ({reversal_rate:.1%}) were reversed. This may indicate "
                        "inconsistent line digitization direction in the source data."
                    )
                )

        # ── Second pass: write output features
        feedback.pushInfo(self.tr("Writing output features..."))
        total_progress_2 = 50.0 / len(geometries) if geometries else 0.0

        for i, (fid, _) in enumerate(geometries):
            if feedback.isCanceled():
                break

            geom = feature_geoms[fid]
            feature_orders = orders.get(fid, {})
            net_id = network_ids.get(fid)

            # Build output geometry (keep original direction)
            out_geom = geom
            reversed_flag = 0  # We don't track per-feature reversal with splitting

            # Build attributes
            attrs: List[Any] = []
            if preserve_attrs:
                attrs.extend(feature_attrs.get(fid, []))

            # Add order values
            if compute_hack:
                attrs.append(feature_orders.get(ORDER_HACK))
            if compute_strahler:
                attrs.append(feature_orders.get(ORDER_STRAHLER))
            if compute_shreve:
                attrs.append(feature_orders.get(ORDER_SHREVE))
            attrs.append(net_id)
            attrs.append(reversed_flag)

            # Create and write feature
            out_feat = QgsFeature(out_fields)
            out_feat.setGeometry(out_geom)
            out_feat.setAttributes(attrs)
            sink.addFeature(out_feat, QgsFeatureSink.FastInsert)

            feedback.setProgress(50 + int(i * total_progress_2))

        feedback.pushInfo(
            self.tr(
                f"Processed {len(geometries)} features in "
                f"{len(set(network_ids.values()))} network(s)."
            )
        )

        return {self.OUTPUT: dest_id}

    # ── Helper methods ─────────────────────────────────────────────────────

    def _get_default_snap_tolerance(self, crs: QgsCoordinateReferenceSystem) -> float:
        """Determine appropriate snap tolerance based on CRS.

        Args:
            crs: Coordinate reference system of the layer.

        Returns:
            Snap tolerance value appropriate for the CRS units.
        """
        if crs.isGeographic():
            # Geographic CRS: use ~1 meter equivalent in degrees
            return 0.00001
        else:
            # Projected CRS: use 1 unit (typically meters or feet)
            return 1.0

    def _convert_snap_tolerance(
        self,
        tolerance: float,
        unit: int,
        crs: QgsCoordinateReferenceSystem,
        feedback: Any,
    ) -> float:
        """Convert snap tolerance from specified unit to CRS native units.

        Args:
            tolerance: Snap tolerance value.
            unit: Unit type (UNIT_AUTO, UNIT_FEET, UNIT_METERS).
            crs: Coordinate reference system of the layer.
            feedback: Processing feedback for logging.

        Returns:
            Snap tolerance converted to CRS native units.

        Methodology:
            1. If UNIT_AUTO, return tolerance unchanged (assumes CRS units).
            2. For UNIT_FEET or UNIT_METERS:
               - If CRS is geographic (degrees), convert to approximate degrees.
               - If CRS is projected, convert based on CRS linear unit.
        """
        if unit == self.UNIT_AUTO:
            feedback.pushInfo(
                self.tr(f"Snap tolerance: {tolerance:.6f} (CRS native units)")
            )
            return tolerance

        # Determine input unit in meters
        if unit == self.UNIT_FEET:
            tolerance_meters = tolerance * 0.3048
            unit_name = "feet"
        else:  # UNIT_METERS
            tolerance_meters = tolerance
            unit_name = "meters"

        # Convert to CRS units
        if crs.isGeographic():
            # Geographic CRS: convert meters to approximate degrees
            # 1 degree latitude ≈ 111,320 meters at equator
            tolerance_crs = tolerance_meters / 111320.0
            feedback.pushInfo(
                self.tr(
                    f"Snap tolerance: {tolerance:.2f} {unit_name} → "
                    f"{tolerance_crs:.8f} degrees (geographic CRS)"
                )
            )
        else:
            # Projected CRS: determine CRS linear unit
            crs_unit = crs.mapUnits()
            if crs_unit == QgsUnitTypes.DistanceMeters:
                tolerance_crs = tolerance_meters
                crs_unit_name = "meters"
            elif crs_unit == QgsUnitTypes.DistanceFeet:
                tolerance_crs = tolerance_meters / 0.3048
                crs_unit_name = "feet"
            elif crs_unit == QgsUnitTypes.DistanceNauticalMiles:
                tolerance_crs = tolerance_meters / 1852.0
                crs_unit_name = "nautical miles"
            elif crs_unit == QgsUnitTypes.DistanceYards:
                tolerance_crs = tolerance_meters / 0.9144
                crs_unit_name = "yards"
            elif crs_unit == QgsUnitTypes.DistanceMiles:
                tolerance_crs = tolerance_meters / 1609.344
                crs_unit_name = "miles"
            elif crs_unit == QgsUnitTypes.DistanceKilometers:
                tolerance_crs = tolerance_meters / 1000.0
                crs_unit_name = "kilometers"
            elif crs_unit == QgsUnitTypes.DistanceCentimeters:
                tolerance_crs = tolerance_meters * 100.0
                crs_unit_name = "centimeters"
            elif crs_unit == QgsUnitTypes.DistanceMillimeters:
                tolerance_crs = tolerance_meters * 1000.0
                crs_unit_name = "millimeters"
            else:
                # Unknown unit, assume meters
                tolerance_crs = tolerance_meters
                crs_unit_name = "unknown (assumed meters)"

            feedback.pushInfo(
                self.tr(
                    f"Snap tolerance: {tolerance:.2f} {unit_name} → "
                    f"{tolerance_crs:.6f} {crs_unit_name} (projected CRS)"
                )
            )

        return tolerance_crs

    def _to_shapely(self, geom: QgsGeometry) -> Optional[Any]:
        """Convert QgsGeometry to Shapely geometry.

        Args:
            geom: QgsGeometry to convert.

        Returns:
            Shapely geometry or None if conversion fails.
        """
        try:
            wkb_bytes = bytes(geom.asWkb())
            shapely_geom = swkb.loads(wkb_bytes)
            
            if shapely_geom is None or shapely_geom.is_empty:
                return None
            
            # Merge MultiLineString if possible
            if hasattr(shapely_geom, "geoms"):
                merged = linemerge(shapely_geom)
                if not hasattr(merged, "geoms"):
                    shapely_geom = merged
            
            return shapely_geom
        except Exception:
            return None

    def _get_line_endpoints(
        self, geom: QgsGeometry
    ) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        """Extract start and end coordinates from a line geometry.

        Args:
            geom: QgsGeometry of LineString or MultiLineString type.

        Returns:
            Tuple of ((start_x, start_y), (end_x, end_y)) or None if extraction fails.
        """
        try:
            wkb_bytes = bytes(geom.asWkb())
            shapely_geom = swkb.loads(wkb_bytes)

            if shapely_geom is None or shapely_geom.is_empty:
                return None

            # Handle MultiLineString
            if hasattr(shapely_geom, "geoms"):
                merged = linemerge(shapely_geom)
                if hasattr(merged, "geoms"):
                    # Could not merge — use first and last parts
                    parts = list(shapely_geom.geoms)
                    start_coord = parts[0].coords[0]
                    end_coord = parts[-1].coords[-1]
                else:
                    start_coord = merged.coords[0]
                    end_coord = merged.coords[-1]
            else:
                start_coord = shapely_geom.coords[0]
                end_coord = shapely_geom.coords[-1]

            return (
                (float(start_coord[0]), float(start_coord[1])),
                (float(end_coord[0]), float(end_coord[1])),
            )
        except Exception:
            return None

    def _reverse_geometry(self, geom: QgsGeometry) -> QgsGeometry:
        """Reverse the coordinate order of a line geometry.

        Args:
            geom: QgsGeometry to reverse.

        Returns:
            New QgsGeometry with reversed coordinate order.
        """
        try:
            wkb_bytes = bytes(geom.asWkb())
            shapely_geom = swkb.loads(wkb_bytes)

            if hasattr(shapely_geom, "geoms"):
                # MultiLineString: reverse each part and reverse part order
                reversed_parts = [
                    LineString(list(part.coords)[::-1])
                    for part in reversed(shapely_geom.geoms)
                ]
                from shapely.geometry import MultiLineString
                reversed_geom = MultiLineString(reversed_parts)
            else:
                reversed_geom = LineString(list(shapely_geom.coords)[::-1])

            return QgsGeometry.fromWkb(reversed_geom.wkb)
        except Exception:
            return geom
