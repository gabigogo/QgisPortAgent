"""Batch downstream segment filter for stream segmenter output folders.

Scans a folder for OGR-readable segmented stream files and applies the same
downstream filter logic as ``StreamSegmentFilterAlgorithm`` to every file.

Each output file is written to the output folder as
``<original_stem>_filtered.gpkg``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

from ...utils.geometry import FLD_MILE_RANGE, FLD_SEG_NUM, collect_files, parse_range_start

# Private aliases to keep the body concise.
_FLD_SEG_NUM = FLD_SEG_NUM
_FLD_MILE_RANGE = FLD_MILE_RANGE
_collect_files = collect_files
_parse_range_start = parse_range_start
_SRC_FID_FIELD = "src_fid"


def _build_safe_output_fields(source_fields: QgsFields) -> QgsFields:
    """Clone source fields while remapping fid to src_fid for output writers."""
    out_fields = QgsFields()
    existing_names = set()

    for field in source_fields:
        fname = field.name()
        out_name = _SRC_FID_FIELD if fname.lower() == "fid" else fname

        if out_name in existing_names:
            base = out_name
            suffix = 1
            while f"{base}_{suffix}" in existing_names:
                suffix += 1
            out_name = f"{base}_{suffix}"

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

    return out_fields


class BatchStreamSegmentFilterAlgorithm(QgsProcessingAlgorithm):
    """Filter segmented stream files in bulk to first N segments or X distance.

    This algorithm is intended for folders produced by
    ``BatchStreamSegmenterAlgorithm`` but can process any line layers that
    include the expected ``seg_num`` and/or ``mile_range`` fields.
    """

    INPUT_FOLDER = "INPUT_FOLDER"
    FILE_FILTER = "FILE_FILTER"
    FILTER_MODE = "FILTER_MODE"
    N_SEGMENTS = "N_SEGMENTS"
    MAX_DISTANCE = "MAX_DISTANCE"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"

    MODE_BY_COUNT = 0
    MODE_BY_DISTANCE = 1
    _FILTER_MODE_LABELS = [
        "First N segments per channel  (uses 'seg_num' field)",
        "First X distance per channel  (uses 'mile_range' field)",
    ]

    def tr(self, string: str) -> str:
        return QCoreApplication.translate("BatchStreamSegmentFilterAlgorithm", string)

    def createInstance(self) -> "BatchStreamSegmentFilterAlgorithm":
        return BatchStreamSegmentFilterAlgorithm()

    def name(self) -> str:
        return "batch_stream_segment_filter"

    def displayName(self) -> str:
        return self.tr("Batch Stream Segment Filter")

    def group(self) -> str:
        return self.tr("Stream Tools")

    def groupId(self) -> str:
        return "stream_tools"

    def shortHelpString(self) -> str:
        return self.tr(
            "Filters all segmented stream files in a folder and writes a new "
            "GeoPackage per input file to the output folder.\n\n"
            "Use this after Batch Stream Segmenter.\n\n"
            "Two modes are available:\n"
            "  • First N segments — keeps features where seg_num ≤ N\n"
            "  • First X distance — keeps features where mile_range start < X\n\n"
            "Input files are discovered via file filter globs and processed "
            "non-recursively from the input folder root."
        )

    def initAlgorithm(self, config: Optional[Dict] = None) -> None:
        """Declare batch input, filter controls, and output destination."""
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_FOLDER,
                self.tr("Input folder (batch segmented outputs)"),
                behavior=QgsProcessingParameterFile.Folder,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.FILE_FILTER,
                self.tr("File filter (space-separated globs, e.g. '*_segmented.gpkg')"),
                defaultValue="*_segmented.gpkg *.gpkg *.shp *.geojson *.fgb",
                optional=True,
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
                    "Maximum start distance to keep (mode: First X distance; "
                    "same units used by segmentation output)"
                ),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=5.0,
                minValue=0.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_FOLDER,
                self.tr("Output folder (filtered GeoPackages written here)"),
            )
        )

    def processAlgorithm(
        self,
        parameters: Dict[str, Any],
        context: Any,
        feedback: Any,
    ) -> Dict[str, Any]:
        """Run the batch filter process over all matching files.

        Raises:
            QgsProcessingException: If the input folder is missing or not a
                directory.
        """
        input_folder = Path(self.parameterAsString(parameters, self.INPUT_FOLDER, context))
        filter_str = self.parameterAsString(parameters, self.FILE_FILTER, context)
        filter_mode = self.parameterAsEnum(parameters, self.FILTER_MODE, context)
        n_segments = self.parameterAsInt(parameters, self.N_SEGMENTS, context)
        max_distance = self.parameterAsDouble(parameters, self.MAX_DISTANCE, context)
        output_folder = Path(self.parameterAsString(parameters, self.OUTPUT_FOLDER, context))

        if not input_folder.is_dir():
            raise QgsProcessingException(
                self.tr(f"Input folder does not exist: {input_folder}")
            )

        output_folder.mkdir(parents=True, exist_ok=True)

        files = _collect_files(input_folder, filter_str or "")
        if not files:
            feedback.pushWarning(
                self.tr(f"No files matching '{filter_str}' found in {input_folder}.")
            )
            return {self.OUTPUT_FOLDER: str(output_folder)}

        feedback.pushInfo(
            self.tr(f"Found {len(files)} file(s) to process in {input_folder}.")
        )

        file_step = 100.0 / len(files)

        for file_idx, src_path in enumerate(files):
            if feedback.isCanceled():
                break

            feedback.pushInfo(self.tr(f"\n[{file_idx + 1}/{len(files)}] {src_path.name}"))

            layer = QgsVectorLayer(str(src_path), src_path.stem, "ogr")
            if not layer.isValid():
                feedback.reportError(
                    self.tr(f"  Cannot open '{src_path.name}' as a vector layer - skipped."),
                    fatalError=False,
                )
                feedback.setProgress(int((file_idx + 1) * file_step))
                continue

            layer_crs = layer.crs()
            if not layer_crs.isValid():
                feedback.reportError(
                    self.tr(
                        f"  '{src_path.name}' has an invalid CRS and cannot be written "
                        "with source CRS metadata - skipped."
                    ),
                    fatalError=False,
                )
                feedback.setProgress(int((file_idx + 1) * file_step))
                continue

            field_names = [f.name() for f in layer.fields()]
            required_field = _FLD_SEG_NUM if filter_mode == self.MODE_BY_COUNT else _FLD_MILE_RANGE
            if required_field not in field_names:
                feedback.reportError(
                    self.tr(
                        f"  Required field '{required_field}' not found in '{src_path.name}' - skipped."
                    ),
                    fatalError=False,
                )
                feedback.setProgress(int((file_idx + 1) * file_step))
                continue

            out_path = output_folder / f"{src_path.stem}_filtered.gpkg"
            if out_path.exists():
                out_path.unlink()

            out_fields = _build_safe_output_fields(layer.fields())

            save_opts = QgsVectorFileWriter.SaveVectorOptions()
            save_opts.driverName = "GPKG"
            save_opts.fileEncoding = "UTF-8"

            writer = QgsVectorFileWriter.create(
                fileName=str(out_path),
                fields=out_fields,
                geometryType=layer.wkbType(),
                srs=layer_crs,
                transformContext=context.transformContext(),
                options=save_opts,
            )

            if writer is None:
                feedback.reportError(
                    self.tr(f"  Failed to create output file '{out_path.name}' - skipped."),
                    fatalError=False,
                )
                feedback.setProgress(int((file_idx + 1) * file_step))
                continue

            writer_error = writer.hasError()
            if writer_error != QgsVectorFileWriter.NoError:
                error_msg = writer.errorMessage()
                feedback.reportError(
                    self.tr(
                        f"  Failed to create output file '{out_path.name}': {error_msg} - skipped."
                    ),
                    fatalError=False,
                )
                del writer
                feedback.setProgress(int((file_idx + 1) * file_step))
                continue

            feature_count = layer.featureCount()
            feat_step = file_step / feature_count if feature_count > 0 else 0.0

            kept = 0
            skipped = 0

            for feat_idx, feature in enumerate(layer.getFeatures()):
                if feedback.isCanceled():
                    break

                keep = False
                if filter_mode == self.MODE_BY_COUNT:
                    raw_seg = feature[_FLD_SEG_NUM]
                    if raw_seg is None:
                        feedback.reportError(
                            self.tr(
                                f"  Feature {feature.id()} in '{src_path.name}': null "
                                f"'{_FLD_SEG_NUM}' value - skipped."
                            ),
                            fatalError=False,
                        )
                        skipped += 1
                    else:
                        keep = int(raw_seg) <= n_segments
                else:
                    raw_range = feature[_FLD_MILE_RANGE]
                    if raw_range is None:
                        feedback.reportError(
                            self.tr(
                                f"  Feature {feature.id()} in '{src_path.name}': null "
                                f"'{_FLD_MILE_RANGE}' value - skipped."
                            ),
                            fatalError=False,
                        )
                        skipped += 1
                    else:
                        start = _parse_range_start(str(raw_range))
                        if start is None:
                            feedback.reportError(
                                self.tr(
                                    f"  Feature {feature.id()} in '{src_path.name}': could not "
                                    f"parse '{_FLD_MILE_RANGE}' value '{raw_range}' - skipped."
                                ),
                                fatalError=False,
                            )
                            skipped += 1
                        else:
                            keep = start < max_distance

                if keep:
                    out_feat = QgsFeature(out_fields)
                    out_feat.setGeometry(feature.geometry())
                    out_feat.setAttributes(feature.attributes())
                    
                    if not writer.addFeature(out_feat, QgsFeatureSink.FastInsert):
                        if writer.hasError() != QgsVectorFileWriter.NoError:
                            feedback.reportError(
                                self.tr(
                                    f"  Feature {feature.id()}: Writer error: "
                                    f"{writer.errorMessage()} — skipped."
                                ),
                                fatalError=False,
                            )
                    else:
                        kept += 1

                feedback.setProgress(int(file_idx * file_step + feat_idx * feat_step))

            del writer

            mode_label = (
                f"seg_num <= {n_segments}"
                if filter_mode == self.MODE_BY_COUNT
                else f"start < {max_distance}"
            )
            feedback.pushInfo(
                self.tr(
                    f"  -> {out_path.name}: {kept} kept, {skipped} skipped ({mode_label})."
                )
            )
            feedback.setProgress(int((file_idx + 1) * file_step))

        feedback.pushInfo(self.tr("\nBatch filtering complete."))
        return {self.OUTPUT_FOLDER: str(output_folder)}
