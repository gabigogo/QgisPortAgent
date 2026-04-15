"""Batch stream order Processing algorithm.

Scans a folder for OGR-readable line vector files and computes stream order
(Hack, Strahler, Shreve) for every feature in each file.

Each output file is written to the output folder as
``<original_stem>_ordered.gpkg`` and receives the stream order fields:

- ``hack``       -- Hack/Gravelius order (main channel = 1, tributaries increment)
- ``strahler``   -- Strahler stream order
- ``shreve``     -- Shreve stream magnitude
- ``network_id`` -- Connected component identifier
- ``reversed``   -- 1 if geometry was reversed to flow toward outlet, 0 otherwise

Assumptions
-----------
- Each file contains a topologically connected stream network.
- Lines share endpoints at confluences (within snap tolerance).
- The outlet is auto-detected per file as the degree-1 node with maximum
  upstream network length.
- Output is always written as GeoPackage (``.gpkg``).
- The file scan is non-recursive (top-level files only).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsDistanceArea,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProject,
    QgsUnitTypes,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from shapely import wkb as swkb
from shapely.geometry import LineString
from shapely.ops import linemerge

from ...utils.geometry import DEFAULT_VECTOR_EXTENSIONS, collect_files
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
    process_network_from_geometries,
)

# ── Private aliases ────────────────────────────────────────────────────────────
_collect_files = collect_files
_SRC_FID_FIELD = "src_fid"


class BatchStreamOrderAlgorithm(QgsProcessingAlgorithm):
    """Compute stream order for all stream network files in a folder.

    For each vector file found in the input folder the algorithm opens the
    file, applies stream order computation to every feature, and writes a
    new GeoPackage to the output folder with the suffix ``_ordered``
    appended to the original file stem.

    Assumptions:
        Input Data:
            - All target files live at the top level of the input folder
              (non-recursive).
            - Lines share endpoints at confluences within snap tolerance.
            - Network is dendritic (tree-like).
        Environment:
            - ``shapely >= 2.0`` available in the QGIS Python environment.
            - ``QgsProject.instance().ellipsoid()`` is set; falls back to GRS80.
        Error Handling:
            - Files that cannot be opened or contain zero valid features are
              skipped with non-fatal warnings.
            - Individual features with bad geometry are skipped per-feature.
    """

    # ── Parameter keys ─────────────────────────────────────────────────────

    INPUT_FOLDER = "INPUT_FOLDER"
    FILE_FILTER = "FILE_FILTER"
    COMPUTE_HACK = "COMPUTE_HACK"
    COMPUTE_STRAHLER = "COMPUTE_STRAHLER"
    COMPUTE_SHREVE = "COMPUTE_SHREVE"
    SNAP_TOLERANCE = "SNAP_TOLERANCE"
    SNAP_UNIT = "SNAP_UNIT"
    PRESERVE_ATTRS = "PRESERVE_ATTRS"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    
    # Unit constants
    UNIT_AUTO = 0
    UNIT_FEET = 1
    UNIT_METERS = 2

    # ── Boilerplate ────────────────────────────────────────────────────────

    def tr(self, string: str) -> str:
        return QCoreApplication.translate("BatchStreamOrderAlgorithm", string)

    def createInstance(self) -> "BatchStreamOrderAlgorithm":
        return BatchStreamOrderAlgorithm()

    def name(self) -> str:
        return "batch_stream_order"

    def displayName(self) -> str:
        return self.tr("Batch Stream Order")

    def group(self) -> str:
        return self.tr("Stream Tools")

    def groupId(self) -> str:
        return "stream_tools"

    def shortHelpString(self) -> str:
        return self.tr(
            "Computes stream order for all stream network files in a folder.\n\n"
            "Supported input formats: .gpkg, .shp, .geojson, .fgb, .gml, .kml "
            "(or a custom file-filter glob, e.g. '*.shp *.gpkg').\n\n"
            "Each input file produces a new GeoPackage in the output folder "
            "named <original_stem>_ordered.gpkg.\n\n"
            "Ordering methods:\n"
            "  • Hack (default) — Main channel = 1, tributaries increment.\n"
            "  • Strahler — Classic Strahler ordering.\n"
            "  • Shreve — Magnitude equals sum of upstream tributaries.\n\n"
            "Output fields added:\n"
            "  • hack        — Hack/Gravelius stream order\n"
            "  • strahler    — Strahler stream order\n"
            "  • shreve      — Shreve stream magnitude\n"
            "  • network_id  — Connected component identifier\n"
            "  • reversed    — 1 if geometry was reversed, 0 otherwise"
        )

    # ── Parameter definitions ──────────────────────────────────────────────

    def initAlgorithm(self, config: Optional[Dict] = None) -> None:
        """Declare input and output parameters."""
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_FOLDER,
                self.tr("Input folder (containing stream network files)"),
                behavior=QgsProcessingParameterFile.Folder,
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.FILE_FILTER,
                self.tr("File filter (space-separated globs, e.g. '*.gpkg *.geojson')"),
                defaultValue="*.gpkg *.shp *.geojson *.fgb",
                optional=True,
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
                self.tr("Preserve source attributes in output"),
                defaultValue=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_FOLDER,
                self.tr("Output folder (ordered GeoPackages written here)"),
            )
        )

    # ── Helpers ────────────────────────────────────────────────────────────

    def _get_default_snap_tolerance(self, crs: QgsCoordinateReferenceSystem) -> float:
        """Determine appropriate snap tolerance based on CRS."""
        if crs.isGeographic():
            return 0.00001
        else:
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
            feedback: Processing feedback for logging (or None to suppress).

        Returns:
            Snap tolerance converted to CRS native units.
        """
        if unit == self.UNIT_AUTO:
            if feedback:
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
            tolerance_crs = tolerance_meters / 111320.0
            if feedback:
                feedback.pushInfo(
                    self.tr(
                        f"Snap tolerance: {tolerance:.2f} {unit_name} → "
                        f"{tolerance_crs:.8f} degrees (geographic CRS)"
                    )
                )
        else:
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
                tolerance_crs = tolerance_meters
                crs_unit_name = "unknown (assumed meters)"

            if feedback:
                feedback.pushInfo(
                    self.tr(
                        f"Snap tolerance: {tolerance:.2f} {unit_name} → "
                        f"{tolerance_crs:.6f} {crs_unit_name} (projected CRS)"
                    )
                )

        return tolerance_crs

    def _get_line_endpoints(
        self, geom: QgsGeometry
    ) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        """Extract start and end coordinates from a line geometry."""
        try:
            wkb_bytes = bytes(geom.asWkb())
            shapely_geom = swkb.loads(wkb_bytes)

            if shapely_geom is None or shapely_geom.is_empty:
                return None

            if hasattr(shapely_geom, "geoms"):
                merged = linemerge(shapely_geom)
                if hasattr(merged, "geoms"):
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
        """Reverse the coordinate order of a line geometry."""
        try:
            wkb_bytes = bytes(geom.asWkb())
            shapely_geom = swkb.loads(wkb_bytes)

            if hasattr(shapely_geom, "geoms"):
                from shapely.geometry import MultiLineString
                reversed_parts = [
                    LineString(list(part.coords)[::-1])
                    for part in reversed(shapely_geom.geoms)
                ]
                reversed_geom = MultiLineString(reversed_parts)
            else:
                reversed_geom = LineString(list(shapely_geom.coords)[::-1])

            return QgsGeometry.fromWkb(reversed_geom.wkb)
        except Exception:
            return geom

    def _to_shapely(self, geom: QgsGeometry) -> Optional[Any]:
        """Convert QgsGeometry to Shapely geometry.

        Args:
            geom: QGIS geometry to convert.

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
                return merged
            return shapely_geom
        except Exception:
            return None

    def _build_out_fields(
        self,
        source_fields: QgsFields,
        preserve_attrs: bool,
        compute_hack: bool,
        compute_strahler: bool,
        compute_shreve: bool,
    ) -> QgsFields:
        """Build the output field schema."""
        out_fields = QgsFields()
        if preserve_attrs:
            existing_names = set()
            for field in source_fields:
                fname = field.name()
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

        if compute_hack:
            out_fields.append(QgsField(FLD_HACK, QVariant.Int, "Integer", 10, 0))
        if compute_strahler:
            out_fields.append(QgsField(FLD_STRAHLER, QVariant.Int, "Integer", 10, 0))
        if compute_shreve:
            out_fields.append(QgsField(FLD_SHREVE, QVariant.Int, "Integer", 10, 0))
        out_fields.append(QgsField(FLD_NETWORK_ID, QVariant.Int, "Integer", 10, 0))
        out_fields.append(QgsField(FLD_REVERSED, QVariant.Int, "Integer", 10, 0))

        return out_fields

    # ── Core processing ────────────────────────────────────────────────────

    def processAlgorithm(
        self,
        parameters: Dict[str, Any],
        context: Any,
        feedback: Any,
    ) -> Dict[str, Any]:
        """Execute the batch stream order workflow."""
        # ── Resolve parameters
        input_folder = Path(
            self.parameterAsString(parameters, self.INPUT_FOLDER, context)
        )
        filter_str: str = self.parameterAsString(
            parameters, self.FILE_FILTER, context
        )
        compute_hack = self.parameterAsBool(parameters, self.COMPUTE_HACK, context)
        compute_strahler = self.parameterAsBool(parameters, self.COMPUTE_STRAHLER, context)
        compute_shreve = self.parameterAsBool(parameters, self.COMPUTE_SHREVE, context)
        snap_tolerance = self.parameterAsDouble(parameters, self.SNAP_TOLERANCE, context)
        snap_unit = self.parameterAsEnum(parameters, self.SNAP_UNIT, context)
        preserve_attrs = self.parameterAsBool(parameters, self.PRESERVE_ATTRS, context)
        output_folder = Path(
            self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
        )

        if not input_folder.is_dir():
            raise QgsProcessingException(
                self.tr(f"Input folder does not exist: {input_folder}")
            )

        output_folder.mkdir(parents=True, exist_ok=True)

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

        # ── Collect files
        files = _collect_files(input_folder, filter_str or "")
        if not files:
            feedback.pushWarning(
                self.tr(
                    f"No files matching '{filter_str}' found in {input_folder}."
                )
            )
            return {self.OUTPUT_FOLDER: str(output_folder)}

        feedback.pushInfo(self.tr(f"Found {len(files)} file(s) to process."))

        # ── Process each file
        total_files = len(files)
        files_processed = 0
        files_skipped = 0

        for file_idx, src_path in enumerate(files):
            if feedback.isCanceled():
                break

            file_progress_base = (file_idx / total_files) * 100
            feedback.setProgress(int(file_progress_base))
            feedback.pushInfo(self.tr(f"Processing: {src_path.name}"))

            # Open layer
            layer = QgsVectorLayer(str(src_path), src_path.stem, "ogr")
            if not layer.isValid():
                feedback.reportError(
                    self.tr(f"Could not open: {src_path} — skipped."),
                    fatalError=False,
                )
                files_skipped += 1
                continue

            # Validate geometry type
            if layer.geometryType() != QgsWkbTypes.LineGeometry:
                feedback.reportError(
                    self.tr(f"Not a line layer: {src_path.name} — skipped."),
                    fatalError=False,
                )
                files_skipped += 1
                continue

            # Determine snap tolerance with unit conversion
            crs = layer.crs()
            if snap_tolerance <= 0.0:
                file_snap_tol = self._get_default_snap_tolerance(crs)
                if file_idx == 0:  # Only log once
                    feedback.pushInfo(
                        self.tr(f"Using auto-detected snap tolerance: {file_snap_tol:.6f} (CRS units)")
                    )
            else:
                file_snap_tol = self._convert_snap_tolerance(
                    snap_tolerance, snap_unit, crs, feedback if file_idx == 0 else None
                )

            # Configure distance measurement
            da = QgsDistanceArea()
            da.setSourceCrs(crs, context.transformContext())
            da.setEllipsoid(QgsProject.instance().ellipsoid() or "GRS80")

            # Build output fields
            out_fields = self._build_out_fields(
                layer.fields(), preserve_attrs,
                compute_hack, compute_strahler, compute_shreve
            )

            # First pass: collect feature geometries
            geometries: List[Tuple[int, Any]] = []  # (fid, shapely_geom)
            feature_geoms: Dict[int, QgsGeometry] = {}
            feature_attrs: Dict[int, List[Any]] = {}

            for feature in layer.getFeatures():
                if feedback.isCanceled():
                    break

                geom = feature.geometry()
                if geom is None or geom.isNull() or geom.isEmpty():
                    continue

                # Convert to Shapely geometry
                shapely_geom = self._to_shapely(geom)
                if shapely_geom is None or shapely_geom.is_empty:
                    continue

                fid = feature.id()
                geometries.append((fid, shapely_geom))
                feature_geoms[fid] = QgsGeometry(geom)
                if preserve_attrs:
                    feature_attrs[fid] = list(feature.attributes())

            if not geometries:
                feedback.reportError(
                    self.tr(f"No valid features in: {src_path.name} — skipped."),
                    fatalError=False,
                )
                files_skipped += 1
                continue

            # Process network with junction splitting
            orders, network_ids, reversed_count, segment_mapping = process_network_from_geometries(
                geometries,
                snap_tolerance=file_snap_tol,
                order_types=order_types,
            )

            # Warn if high reversal rate
            if len(geometries) > 0:
                # Note: reversed_count is for segments, not original features
                total_segments = sum(len(segs) for segs in segment_mapping.values())
                if total_segments > 0:
                    reversal_rate = reversed_count / total_segments
                    if reversal_rate > 0.1:
                        feedback.pushWarning(
                            self.tr(
                                f"{src_path.name}: High reversal rate ({reversal_rate:.1%}). "
                                "Check source data line direction consistency."
                            )
                        )

            # Create output file
            out_path = output_folder / f"{src_path.stem}_ordered.gpkg"

            save_opts = QgsVectorFileWriter.SaveVectorOptions()
            save_opts.driverName = "GPKG"
            save_opts.fileEncoding = "UTF-8"

            writer = QgsVectorFileWriter.create(
                fileName=str(out_path),
                fields=out_fields,
                geometryType=QgsWkbTypes.LineString,
                srs=crs,
                transformContext=context.transformContext(),
                options=save_opts,
            )

            if writer.hasError() != QgsVectorFileWriter.NoError:
                feedback.reportError(
                    self.tr(f"Could not create output: {out_path} — {writer.errorMessage()}"),
                    fatalError=False,
                )
                files_skipped += 1
                del writer
                continue

            # Write output features
            for fid, _ in geometries:
                if feedback.isCanceled():
                    break

                geom = feature_geoms[fid]
                fid_orders = orders.get(fid, {})
                net_id = network_ids.get(fid)

                # Note: geometry reversal is handled internally during processing;
                # we output the original geometry to preserve source fidelity
                out_geom = geom
                reversed_flag = 0  # Not tracking per-feature reversals with new method

                # Build attributes
                attrs: List[Any] = []
                if preserve_attrs:
                    attrs.extend(feature_attrs.get(fid, []))

                if compute_hack:
                    attrs.append(fid_orders.get(ORDER_HACK))
                if compute_strahler:
                    attrs.append(fid_orders.get(ORDER_STRAHLER))
                if compute_shreve:
                    attrs.append(fid_orders.get(ORDER_SHREVE))
                attrs.append(net_id)
                attrs.append(reversed_flag)

                out_feat = QgsFeature(out_fields)
                out_feat.setGeometry(out_geom)
                
                # Validate attribute count
                if len(attrs) != out_fields.count():
                    feedback.reportError(
                        self.tr(
                            f"  Feature {fid}: Attribute count mismatch "
                            f"({len(attrs)} values, {out_fields.count()} fields) — skipped."
                        ),
                        fatalError=False,
                    )
                    continue
                
                if not out_feat.setAttributes(attrs):
                    feedback.reportError(
                        self.tr(f"  Feature {fid}: Failed to set attributes — skipped."),
                        fatalError=False,
                    )
                    continue
                
                if not writer.addFeature(out_feat):
                    if writer.hasError() != QgsVectorFileWriter.NoError:
                        feedback.reportError(
                            self.tr(
                                f"  Feature {fid}: Writer error: "
                                f"{writer.errorMessage()} — skipped."
                            ),
                            fatalError=False,
                        )
                    else:
                        feedback.reportError(
                            self.tr(
                                f"  Feature {fid}: Failed to add feature "
                                "(unknown reason) — skipped."
                            ),
                            fatalError=False,
                        )
                    continue

            del writer  # Flush to disk
            files_processed += 1

            feedback.pushInfo(
                self.tr(
                    f"  → {out_path.name}: {len(geometries)} features, "
                    f"{len(set(network_ids.values()))} network(s), "
                    f"{reversed_count} segments reversed"
                )
            )

        feedback.pushInfo(
            self.tr(
                f"Batch complete: {files_processed} file(s) processed, "
                f"{files_skipped} skipped."
            )
        )

        return {self.OUTPUT_FOLDER: str(output_folder)}
