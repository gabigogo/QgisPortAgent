"""Batch table-driven filter for segmented stream files.

Applies table-based matching logic to all matching vector files in an input
folder and writes one filtered GeoPackage per source file.
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
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterString,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

from ...utils.geometry import collect_files, load_reference_values, matches_reference

_collect_files = collect_files
_load_reference_values = load_reference_values
_matches_reference = matches_reference
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


class BatchStreamSegmentTableFilterAlgorithm(QgsProcessingAlgorithm):
    """Filter segmented stream files in bulk using CSV/XLSX reference values."""

    INPUT_FOLDER = "INPUT_FOLDER"
    FILE_FILTER = "FILE_FILTER"
    MATCH_FIELD = "MATCH_FIELD"
    REFERENCE_FILE = "REFERENCE_FILE"
    TABLE_COLUMN = "TABLE_COLUMN"
    HAS_HEADER = "HAS_HEADER"
    MATCH_MODE = "MATCH_MODE"
    FILTER_ACTION = "FILTER_ACTION"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"

    MODE_PARTIAL = 0
    MODE_EXACT = 1
    _MATCH_MODE_LABELS = [
        "Partial match (feature contains reference value)",
        "Exact match (feature equals reference value)",
    ]

    ACTION_KEEP_MATCHING = 0
    ACTION_DELETE_MATCHING = 1
    _ACTION_LABELS = [
        "Keep matching features",
        "Delete matching features",
    ]

    def tr(self, string: str) -> str:
        return QCoreApplication.translate("BatchStreamSegmentTableFilterAlgorithm", string)

    def createInstance(self) -> "BatchStreamSegmentTableFilterAlgorithm":
        return BatchStreamSegmentTableFilterAlgorithm()

    def name(self) -> str:
        return "batch_stream_segment_table_filter"

    def displayName(self) -> str:
        return self.tr("Batch Stream Segment Table Filter")

    def group(self) -> str:
        return self.tr("Stream Tools")

    def groupId(self) -> str:
        return "stream_tools"

    def shortHelpString(self) -> str:
        return self.tr(
            "Filters all matching segmented stream files in a folder using a "
            "CSV/XLSX reference table. Outputs are written as "
            "<source_stem>_table_filtered.gpkg."
        )

    def initAlgorithm(self, config: Optional[Dict] = None) -> None:
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_FOLDER,
                self.tr("Input folder"),
                behavior=QgsProcessingParameterFile.Folder,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.FILE_FILTER,
                self.tr("File filter (space-separated globs)"),
                defaultValue="*_segmented.gpkg *.gpkg *.shp *.geojson *.fgb",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.MATCH_FIELD,
                self.tr("Feature field to match"),
                defaultValue="stream_seg_id",
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.REFERENCE_FILE,
                self.tr("Reference table (CSV or XLSX)"),
                behavior=QgsProcessingParameterFile.File,
                fileFilter="CSV/XLSX (*.csv *.xlsx *.xlsm *.xltx *.xltm)",
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.TABLE_COLUMN,
                self.tr("Reference column name or zero-based index"),
                defaultValue="0",
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.HAS_HEADER,
                self.tr("Reference table has header row"),
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.MATCH_MODE,
                self.tr("Match mode"),
                options=self._MATCH_MODE_LABELS,
                defaultValue=self.MODE_PARTIAL,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.FILTER_ACTION,
                self.tr("Filter action"),
                options=self._ACTION_LABELS,
                defaultValue=self.ACTION_KEEP_MATCHING,
            )
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_FOLDER,
                self.tr("Output folder"),
            )
        )

    def processAlgorithm(
        self,
        parameters: Dict[str, Any],
        context: Any,
        feedback: Any,
    ) -> Dict[str, Any]:
        input_folder = Path(self.parameterAsString(parameters, self.INPUT_FOLDER, context))
        file_filter = self.parameterAsString(parameters, self.FILE_FILTER, context)
        match_field = self.parameterAsString(parameters, self.MATCH_FIELD, context).strip()
        reference_file = self.parameterAsString(parameters, self.REFERENCE_FILE, context)
        table_column = self.parameterAsString(parameters, self.TABLE_COLUMN, context).strip()
        has_header = self.parameterAsBool(parameters, self.HAS_HEADER, context)
        match_mode = self.parameterAsEnum(parameters, self.MATCH_MODE, context)
        filter_action = self.parameterAsEnum(parameters, self.FILTER_ACTION, context)
        output_folder = Path(self.parameterAsString(parameters, self.OUTPUT_FOLDER, context))

        if not input_folder.is_dir():
            raise QgsProcessingException(
                self.tr(f"Input folder does not exist: {input_folder}")
            )
        if not match_field:
            raise QgsProcessingException(self.tr("Feature match field cannot be empty."))

        try:
            reference_values = _load_reference_values(reference_file, table_column, has_header)
        except ValueError as exc:
            raise QgsProcessingException(self.tr(str(exc))) from exc

        if not reference_values:
            feedback.pushWarning(
                self.tr("No non-empty values were found in the selected reference column.")
            )

        output_folder.mkdir(parents=True, exist_ok=True)
        files = _collect_files(input_folder, file_filter or "")
        if not files:
            feedback.pushWarning(
                self.tr(f"No files matching '{file_filter}' found in {input_folder}.")
            )
            return {self.OUTPUT_FOLDER: str(output_folder)}

        exact = match_mode == self.MODE_EXACT
        keep_matches = filter_action == self.ACTION_KEEP_MATCHING
        file_step = 100.0 / len(files)

        for file_idx, src_path in enumerate(files):
            if feedback.isCanceled():
                break

            layer = QgsVectorLayer(str(src_path), src_path.stem, "ogr")
            if not layer.isValid():
                feedback.reportError(
                    self.tr(f"Cannot open '{src_path.name}' as a vector layer - skipped."),
                    fatalError=False,
                )
                feedback.setProgress(int((file_idx + 1) * file_step))
                continue

            layer_crs = layer.crs()
            if not layer_crs.isValid():
                feedback.reportError(
                    self.tr(f"'{src_path.name}' has an invalid CRS - skipped."),
                    fatalError=False,
                )
                feedback.setProgress(int((file_idx + 1) * file_step))
                continue

            field_names = [f.name() for f in layer.fields()]
            if match_field not in field_names:
                feedback.reportError(
                    self.tr(
                        f"Required field '{match_field}' not found in '{src_path.name}' - skipped."
                    ),
                    fatalError=False,
                )
                feedback.setProgress(int((file_idx + 1) * file_step))
                continue

            out_path = output_folder / f"{src_path.stem}.gpkg"
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
                    self.tr(f"Failed to create output file '{out_path.name}' - skipped."),
                    fatalError=False,
                )
                feedback.setProgress(int((file_idx + 1) * file_step))
                continue

            writer_error = writer.hasError()
            if writer_error != QgsVectorFileWriter.NoError:
                error_msg = writer.errorMessage()
                feedback.reportError(
                    self.tr(
                        f"Failed to create output file '{out_path.name}': {error_msg} - skipped."
                    ),
                    fatalError=False,
                )
                del writer
                feedback.setProgress(int((file_idx + 1) * file_step))
                continue

            feature_count = layer.featureCount()
            feat_step = file_step / feature_count if feature_count > 0 else 0.0

            matched = 0
            written = 0

            for feat_idx, feature in enumerate(layer.getFeatures()):
                if feedback.isCanceled():
                    break

                is_match = _matches_reference(feature[match_field], reference_values, exact)
                if is_match:
                    matched += 1

                keep = is_match if keep_matches else not is_match
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
                        written += 1

                feedback.setProgress(int(file_idx * file_step + feat_idx * feat_step))

            del writer

            feedback.pushInfo(
                self.tr(
                    f"{src_path.name}: matched {matched}, written {written}."
                )
            )
            feedback.setProgress(int((file_idx + 1) * file_step))

        return {self.OUTPUT_FOLDER: str(output_folder)}
