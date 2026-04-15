"""Batch stream segmentation Processing algorithm.

Scans a folder for OGR-readable line vector files and segments every
LineString / MultiLineString feature in each file into equal-length
intervals measured from the downstream endpoint outward.

Each output file is written to the output folder as
``<original_stem>_segmented.gpkg`` and receives the same three new
attribute fields that the single-layer algorithm produces:

- ``seg_num``       -- integer, 1-based index from the downstream end.
- ``mile_range``    -- range label, e.g. ``"0-1 mi"`` or ``"0-1 km"``.
- ``stream_seg_id`` -- unique identifier, e.g. ``"Bear_Creek_mile_01"``.

Assumptions
-----------
- All files in the input folder share the same stream-name field name.
- The last vertex convention and MultiLineString chain assumption are
  identical to ``StreamSegmenterAlgorithm``.
- Output is always written as GeoPackage (``.gpkg``).
- The file scan is non-recursive (top-level files only).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
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

from ...utils.geometry import (
    DEFAULT_VECTOR_EXTENSIONS,
    FLD_LENGTH_MI,
    FLD_MILE_RANGE,
    FLD_SEG_NUM,
    FLD_STREAM_SEG_ID,
    KM_TO_METRES,
    MILES_TO_METRES,
    NEW_FIELD_NAMES,
    collect_files,
    cut_fraction,
    fmt_distance,
    sanitize_name,
    to_oriented_line,
)

# ── Private aliases ────────────────────────────────────────────────────────────
_FLD_SEG_NUM = FLD_SEG_NUM
_FLD_MILE_RANGE = FLD_MILE_RANGE
_FLD_STREAM_SEG_ID = FLD_STREAM_SEG_ID
_FLD_LENGTH_MI = FLD_LENGTH_MI
_KM_TO_METRES = KM_TO_METRES
_MILES_TO_METRES = MILES_TO_METRES
_NEW_FIELD_NAMES = NEW_FIELD_NAMES
_collect_files = collect_files
_sanitize_name = sanitize_name
_cut_fraction = cut_fraction
_fmt = fmt_distance
_to_oriented_line_from_wkb = to_oriented_line
_SRC_FID_FIELD = "src_fid"

# ── Algorithm class ────────────────────────────────────────────────────────────


class BatchStreamSegmenterAlgorithm(QgsProcessingAlgorithm):
    """Segment all stream centerline files in a folder in a single run.

    For each vector file found in the input folder the algorithm opens the
    file, applies ``StreamSegmenterAlgorithm``-equivalent logic to every
    feature, and writes a new GeoPackage to the output folder with the
    suffix ``_segmented`` appended to the original file stem.

    Assumptions:
        Input Data:
            - All target files live at the top level of the input folder
              (non-recursive).
            - Every file contains a field whose name matches ``NAME_FIELD``.
              Files missing the field are skipped with a non-fatal warning.
            - Same downstream-vertex convention as the single-layer algorithm.
        Environment:
            - ``shapely >= 2.0`` available in the QGIS Python environment.
            - ``QgsProject.instance().ellipsoid()`` is set; falls back to GRS80.
        Error Handling:
            - Files that cannot be opened, lack the name field, or contain
              zero valid features are skipped with non-fatal warnings.
            - Individual features with bad geometry are skipped per-feature.
    """

    # ── Parameter keys ─────────────────────────────────────────────────────

    INPUT_FOLDER = "INPUT_FOLDER"
    FILE_FILTER = "FILE_FILTER"
    NAME_FIELD = "NAME_FIELD"
    SEGMENT_LENGTH = "SEGMENT_LENGTH"
    USE_KM = "USE_KM"
    PRESERVE_ATTRS = "PRESERVE_ATTRS"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"

    # ── Boilerplate ────────────────────────────────────────────────────────

    def tr(self, string: str) -> str:
        return QCoreApplication.translate("BatchStreamSegmenterAlgorithm", string)

    def createInstance(self) -> "BatchStreamSegmenterAlgorithm":
        return BatchStreamSegmenterAlgorithm()

    def name(self) -> str:
        return "batch_stream_segmenter"

    def displayName(self) -> str:
        return self.tr("Batch Stream Segmenter")

    def group(self) -> str:
        return self.tr("Stream Tools")

    def groupId(self) -> str:
        return "stream_tools"

    def shortHelpString(self) -> str:
        return self.tr(
            "Segments all stream centerline files in a folder into equal-length "
            "intervals measured from the downstream endpoint outward.\n\n"
            "Supported input formats: .gpkg, .shp, .geojson, .fgb, .gml, .kml "
            "(or a custom file-filter glob, e.g. '*.shp *.gpkg').\n\n"
            "Each input file produces a new GeoPackage in the output folder "
            "named <original_stem>_segmented.gpkg.\n\n"
            "Three fields are added to every output feature:\n"
            "  • seg_num        — integer segment index (1 = most downstream)\n"
            "  • mile_range     — range label, e.g. '0-1 mi'\n"
            "  • stream_seg_id  — unique ID, e.g. 'Bear_Creek_mile_01'\n\n"
            "All files must share the same stream-name field name."
        )

    # ── Parameter definitions ──────────────────────────────────────────────

    def initAlgorithm(self, config: Optional[Dict] = None) -> None:
        """Declare input and output parameters.

        Args:
            config (Optional[Dict]): Unused framework-supplied config dict.

        Parameters declared:
            INPUT_FOLDER  — folder containing source vector files.
            FILE_FILTER   — space-separated glob patterns (default all common
                            OGR formats).
            NAME_FIELD    — attribute field name present in every file.
            SEGMENT_LENGTH — positive double, default 1.0.
            USE_KM        — switch labels and conversion to kilometres.
            PRESERVE_ATTRS — copy all source fields to each output file.
            OUTPUT_FOLDER  — destination folder for segmented GeoPackages.
        """
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_FOLDER,
                self.tr("Input folder (containing stream centerline files)"),
                behavior=QgsProcessingParameterFile.Folder,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.FILE_FILTER,
                self.tr("File filter (space-separated globs, e.g. '*.gpkg *.shp')"),
                defaultValue="*.gpkg *.shp *.geojson *.fgb",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.NAME_FIELD,
                self.tr("Stream name field (must exist in every input file)"),
                defaultValue="stream_name",
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
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_FOLDER,
                self.tr("Output folder (segmented GeoPackages written here)"),
            )
        )

    # ── Helpers ────────────────────────────────────────────────────────────

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

    @staticmethod
    def _build_out_fields(
        source_fields: QgsFields, preserve_attrs: bool
    ) -> QgsFields:
        """Build the output field schema.

        Args:
            source_fields (QgsFields): Fields from the input layer.
            preserve_attrs (bool): Whether to prepend source fields.

        Returns:
            QgsFields: Combined field schema for the output layer.
        """
        out_fields = QgsFields()
        if preserve_attrs:
            existing_names = set()
            for field in source_fields:
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
        return out_fields

    # ── Core processing ────────────────────────────────────────────────────

    def processAlgorithm(
        self,
        parameters: Dict[str, Any],
        context: Any,
        feedback: Any,
    ) -> Dict[str, Any]:
        """Execute the batch segmentation workflow.

        Args:
            parameters (Dict[str, Any]): Parameter values keyed by constant names.
            context: QGIS processing context (CRS transform context, project).
            feedback: QGIS feedback object for progress and cancellation.

        Returns:
            Dict[str, Any]: ``{"OUTPUT_FOLDER": <resolved output folder path>}``.

        Raises:
            QgsProcessingException: If the input folder does not exist or is
                not a directory.

        Methodology:
            1. Resolve all parameters.
            2. Scan the input folder for files matching the filter globs.
            3. For each file:
               a. Open as ``QgsVectorLayer`` (line geometry expected).
               b. Validate the name field exists in the layer.
               c. Build the output field schema.
               d. Create the output GeoPackage path.
               e. Configure ``QgsDistanceArea`` for geodetic measurement.
               f. Iterate features, orient geometry, cut segments, write output
                  via ``QgsVectorFileWriter``.
            4. Report per-file and per-feature progress.
            5. Return the output folder path.

        Examples:
            Via QGIS Python console::

                import processing
                result = processing.run(
                    "stream_segmenter:batch_stream_segmenter",
                    {
                        "INPUT_FOLDER": "/data/streams",
                        "FILE_FILTER": "*.gpkg *.shp",
                        "NAME_FIELD": "stream_name",
                        "SEGMENT_LENGTH": 1.0,
                        "USE_KM": False,
                        "PRESERVE_ATTRS": False,
                        "OUTPUT_FOLDER": "/data/streams/output",
                    },
                )
        """
        # ── Resolve parameters ─────────────────────────────────────────────
        input_folder = Path(
            self.parameterAsString(parameters, self.INPUT_FOLDER, context)
        )
        filter_str: str = self.parameterAsString(
            parameters, self.FILE_FILTER, context
        )
        name_field: str = self.parameterAsString(
            parameters, self.NAME_FIELD, context
        ).strip()
        segment_length: float = self.parameterAsDouble(
            parameters, self.SEGMENT_LENGTH, context
        )
        use_km: bool = self.parameterAsBool(parameters, self.USE_KM, context)
        preserve_attrs: bool = self.parameterAsBool(
            parameters, self.PRESERVE_ATTRS, context
        )
        output_folder = Path(
            self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
        )

        feedback.pushInfo(
            self.tr(
                "DEBUG build marker: batch_stream_segmenter_algorithm.py v2026-03-30c"
            )
        )

        if not input_folder.is_dir():
            raise QgsProcessingException(
                self.tr(f"Input folder does not exist: {input_folder}")
            )

        output_folder.mkdir(parents=True, exist_ok=True)

        # ── Unit configuration ─────────────────────────────────────────────
        if use_km:
            seg_m = segment_length * _KM_TO_METRES
            unit_label = "km"
            id_unit = "_km_"
        else:
            seg_m = segment_length * _MILES_TO_METRES
            unit_label = "mi"
            id_unit = "_mile_"

        # ── Collect files ──────────────────────────────────────────────────
        files = _collect_files(input_folder, filter_str or "")
        if not files:
            feedback.pushWarning(
                self.tr(
                    f"No files matching '{filter_str}' found in {input_folder}."
                )
            )
            return {self.OUTPUT_FOLDER: str(output_folder)}

        feedback.pushInfo(
            self.tr(f"Found {len(files)} file(s) to process in {input_folder}.")
        )

        file_step = 100.0 / len(files)
        ellipsoid: str = QgsProject.instance().ellipsoid() or "GRS80"

        # ── Per-file loop ──────────────────────────────────────────────────
        for file_idx, src_path in enumerate(files):
            if feedback.isCanceled():
                break

            feedback.pushInfo(self.tr(f"\n[{file_idx + 1}/{len(files)}] {src_path.name}"))

            # Open layer ───────────────────────────────────────────────────
            layer = QgsVectorLayer(str(src_path), src_path.stem, "ogr")
            if not layer.isValid():
                feedback.reportError(
                    self.tr(f"  Cannot open '{src_path.name}' as a vector layer — skipped."),
                    fatalError=False,
                )
                feedback.setProgress(int((file_idx + 1) * file_step))
                continue

            # Validate geometry type ────────────────────────────────────────
            geom_type = layer.geometryType()
            if geom_type != QgsWkbTypes.LineGeometry:
                feedback.reportError(
                    self.tr(
                        f"  '{src_path.name}' is not a line layer "
                        f"(geometry type={geom_type}) — skipped."
                    ),
                    fatalError=False,
                )
                feedback.setProgress(int((file_idx + 1) * file_step))
                continue

            # Validate name field ───────────────────────────────────────────
            field_names = [f.name() for f in layer.fields()]
            if name_field not in field_names:
                feedback.reportError(
                    self.tr(
                        f"  Field '{name_field}' not found in '{src_path.name}' "
                        f"(available: {', '.join(field_names)}) — skipped."
                    ),
                    fatalError=False,
                )
                feedback.setProgress(int((file_idx + 1) * file_step))
                continue

            # Build output field schema ─────────────────────────────────────
            out_fields = self._build_out_fields(layer.fields(), preserve_attrs)

            # Prepare output GeoPackage ─────────────────────────────────────
            out_path = output_folder / f"{src_path.stem}_segmented.gpkg"

            out_crs = QgsCoordinateReferenceSystem(layer.crs())
            if not out_crs.isValid():
                feedback.pushWarning(
                    self.tr(
                        f"  '{src_path.name}': input CRS is invalid/undefined; "
                        "output CRS metadata may be undefined."
                    )
                )
            else:
                feedback.pushInfo(
                    self.tr(f"  Using output CRS: {out_crs.authid() or out_crs.description()}")
                )

            save_opts = QgsVectorFileWriter.SaveVectorOptions()
            save_opts.driverName = "GPKG"
            save_opts.fileEncoding = "UTF-8"
            save_opts.layerName = src_path.stem

            # Use positional arguments here to avoid SIP keyword-binding edge cases
            # that can result in undefined CRS metadata in some environments.
            writer = QgsVectorFileWriter.create(
                str(out_path),
                out_fields,
                QgsWkbTypes.LineString,
                out_crs,
                context.transformContext(),
                save_opts,
            )

            if writer is None:
                feedback.reportError(
                    self.tr(
                        f"  Failed to create output file '{out_path.name}' — skipped."
                    ),
                    fatalError=False,
                )
                feedback.setProgress(int((file_idx + 1) * file_step))
                continue

            writer_error = writer.hasError()
            if writer_error != QgsVectorFileWriter.NoError:
                error_msg = writer.errorMessage()
                feedback.reportError(
                    self.tr(
                        f"  Failed to create output file '{out_path.name}': "
                        f"{error_msg} — skipped."
                    ),
                    fatalError=False,
                )
                del writer
                feedback.setProgress(int((file_idx + 1) * file_step))
                continue

            # Configure distance calculator ────────────────────────────────
            da = QgsDistanceArea()
            da.setSourceCrs(layer.crs(), context.transformContext())
            da.setEllipsoid(ellipsoid)

            if not da.willUseEllipsoid():
                feedback.pushWarning(
                    self.tr(
                        f"  '{src_path.name}': CRS does not support ellipsoidal "
                        "measurement — lengths computed in CRS native units."
                    )
                )

            # Feature loop ─────────────────────────────────────────────────
            feature_count = layer.featureCount()
            feat_step = file_step / feature_count if feature_count > 0 else 0.0
            total_segments_written = 0

            for feat_idx, feature in enumerate(layer.getFeatures()):
                if feedback.isCanceled():
                    break

                geom = feature.geometry()
                if geom is None or geom.isNull():
                    feedback.reportError(
                        self.tr(
                            f"  Feature {feature.id()} in '{src_path.name}': "
                            "null geometry — skipped."
                        ),
                        fatalError=False,
                    )
                    continue

                if geom.type() != QgsWkbTypes.LineGeometry:
                    feedback.reportError(
                        self.tr(
                            f"  Feature {feature.id()} in '{src_path.name}': "
                            f"not a line geometry — skipped."
                        ),
                        fatalError=False,
                    )
                    continue

                raw_name = feature[name_field]
                stream_name = _sanitize_name(
                    str(raw_name) if raw_name is not None else ""
                )
                if not stream_name:
                    stream_name = f"feature_{feature.id()}"

                oriented, err = _to_oriented_line_from_wkb(bytes(geom.asWkb()))
                if err:
                    feedback.reportError(
                        self.tr(
                            f"  Feature {feature.id()} ('{stream_name}') "
                            f"in '{src_path.name}': {err} — skipped."
                        ),
                        fatalError=False,
                    )
                    continue

                # Always use QgsDistanceArea.measureLength so that geographic-CRS
                # layers (e.g. EPSG:4326, units=degrees) return correct metre values
                # instead of Euclidean degree-valued lengths that cause n_segs=1 and
                # make the entire line output as a single un-segmented feature.
                total_m: float = da.measureLength(geom)
                if total_m > 0.0 and not da.willUseEllipsoid():
                    # In non-ellipsoidal mode, QgsDistanceArea returns
                    # CRS-native units. Normalize to metres.
                    total_m = self._length_to_meters(total_m, layer.crs())
                if total_m <= 0.0:
                    # Last-resort fallback for CRS unsupported by QgsDistanceArea.
                    total_native = float(oriented.length)
                    total_m = self._length_to_meters(total_native, layer.crs())
                if total_m <= 0.0:
                    feedback.reportError(
                        self.tr(
                            f"  Feature {feature.id()} ('{stream_name}') "
                            f"in '{src_path.name}': zero-length geometry — skipped."
                        ),
                        fatalError=False,
                    )
                    continue

                n_segs = math.ceil(total_m / seg_m)
                total_user_units: float = total_m / (
                    _KM_TO_METRES if use_km else _MILES_TO_METRES
                )
                pad = max(2, len(str(n_segs)))

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

                    # Compute geodetic length of this segment in miles.
                    seg_da = QgsDistanceArea()
                    seg_da.setSourceCrs(layer.crs(), context.transformContext())
                    seg_da.setEllipsoid(ellipsoid)
                    seg_length_m = seg_da.measureLength(seg_qgs)
                    if seg_length_m > 0.0 and not seg_da.willUseEllipsoid():
                        seg_length_m = self._length_to_meters(
                            seg_length_m, layer.crs()
                        )
                    if seg_length_m <= 0.0:
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
                    
                    # Validate attribute count matches field count
                    if len(attrs) != out_fields.count():
                        feedback.reportError(
                            self.tr(
                                f"  Feature {feature.id()} segment {seg_num}: "
                                f"Attribute count mismatch ({len(attrs)} values, "
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
                                    f"  Feature {feature.id()} segment {seg_num}: "
                                    f"Failed to set attributes (field '{fld.name()}' "
                                    f"type='{fld.typeName()}' value={value!r} "
                                    f"pytype={type(value).__name__}) — skipped."
                                ),
                                fatalError=False,
                            )
                            assign_failed = True
                            break
                    if assign_failed:
                        continue
                    
                    if not writer.addFeature(out_feat):
                        # Check for writer errors
                        if writer.hasError() != QgsVectorFileWriter.NoError:
                            feedback.reportError(
                                self.tr(
                                    f"  Feature {feature.id()} segment {seg_num}: "
                                    f"Writer error: {writer.errorMessage()} — skipped."
                                ),
                                fatalError=False,
                            )
                        else:
                            feedback.reportError(
                                self.tr(
                                    f"  Feature {feature.id()} segment {seg_num}: "
                                    f"Failed to add feature (unknown reason) — skipped."
                                ),
                                fatalError=False,
                            )
                        continue
                    
                    total_segments_written += 1

                feedback.setProgress(
                    int(file_idx * file_step + feat_idx * feat_step)
                )

            # Close writer (flushes GeoPackage) ────────────────────────────
            del writer

            feedback.pushInfo(
                self.tr(
                    f"  → {out_path.name}: {total_segments_written} segment(s) written."
                )
            )
            feedback.setProgress(int((file_idx + 1) * file_step))

        feedback.pushInfo(self.tr("\nBatch segmentation complete."))
        return {self.OUTPUT_FOLDER: str(output_folder)}
