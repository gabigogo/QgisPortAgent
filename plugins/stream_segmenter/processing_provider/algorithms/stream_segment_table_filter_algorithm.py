"""Table-driven filter for segmented stream layers.

Filters a segmented stream layer by comparing values in a selected feature
field against values loaded from a CSV/XLSX reference table column.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsFeatureSink,
    QgsFeatureRequest,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFile,
    QgsProcessingParameterString,
    QgsVectorLayer,
)

from ...utils.geometry import load_reference_values, matches_reference

_load_reference_values = load_reference_values
_matches_reference = matches_reference


class StreamSegmentTableFilterAlgorithm(QgsProcessingAlgorithm):
    """Filter stream segment features using reference values from CSV/XLSX."""

    INPUT = "INPUT"
    MATCH_FIELD = "MATCH_FIELD"
    SELECTED_ONLY = "SELECTED_ONLY"
    REFERENCE_FILE = "REFERENCE_FILE"
    TABLE_COLUMN = "TABLE_COLUMN"
    HAS_HEADER = "HAS_HEADER"
    MATCH_MODE = "MATCH_MODE"
    FILTER_ACTION = "FILTER_ACTION"
    OUTPUT = "OUTPUT"

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
        return QCoreApplication.translate("StreamSegmentTableFilterAlgorithm", string)

    def createInstance(self) -> "StreamSegmentTableFilterAlgorithm":
        return StreamSegmentTableFilterAlgorithm()

    def name(self) -> str:
        return "stream_segment_table_filter"

    def displayName(self) -> str:
        return self.tr("Stream Segment Table Filter")

    def group(self) -> str:
        return self.tr("Stream Tools")

    def groupId(self) -> str:
        return "stream_tools"

    def shortHelpString(self) -> str:
        return self.tr(
            "Filters a segmented stream layer by comparing a selected feature field "
            "against values loaded from a CSV/XLSX reference table column.\n\n"
            "Choose partial or exact matching, then decide whether to keep or "
            "delete matches."
        )

    def initAlgorithm(self, config: Optional[Dict] = None) -> None:
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                self.tr("Segmented stream layer"),
                [QgsProcessing.TypeVectorLine],
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.MATCH_FIELD,
                self.tr("Feature field to match"),
                parentLayerParameterName=self.INPUT,
                type=QgsProcessingParameterField.Any,
                defaultValue="stream_seg_id",
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
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr("Filtered segments"),
            )
        )

    def processAlgorithm(
        self,
        parameters: Dict[str, Any],
        context: Any,
        feedback: Any,
    ) -> Dict[str, Any]:
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))

        source_crs = source.sourceCrs()
        if not source_crs.isValid():
            raise QgsProcessingException(
                self.tr("Input layer CRS is not valid.")
            )

        match_field = self.parameterAsString(parameters, self.MATCH_FIELD, context).strip()
        selected_only = self.parameterAsBool(parameters, self.SELECTED_ONLY, context)
        reference_file = self.parameterAsString(parameters, self.REFERENCE_FILE, context)
        table_column = self.parameterAsString(parameters, self.TABLE_COLUMN, context).strip()
        has_header = self.parameterAsBool(parameters, self.HAS_HEADER, context)
        match_mode = self.parameterAsEnum(parameters, self.MATCH_MODE, context)
        filter_action = self.parameterAsEnum(parameters, self.FILTER_ACTION, context)

        if not match_field:
            raise QgsProcessingException(self.tr("Feature match field cannot be empty."))

        field_names = [f.name() for f in source.fields()]
        if match_field not in field_names:
            raise QgsProcessingException(
                self.tr(
                    f"Feature field '{match_field}' not found in input layer."
                )
            )

        try:
            reference_values = _load_reference_values(reference_file, table_column, has_header)
        except ValueError as exc:
            raise QgsProcessingException(self.tr(str(exc))) from exc

        if not reference_values:
            feedback.pushWarning(
                self.tr("No non-empty values were found in the selected reference column.")
            )

        sink, dest_id = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            source.fields(),
            source.wkbType(),
            source_crs,
        )
        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT))

        source_layer: Optional[QgsVectorLayer] = self.parameterAsVectorLayer(
            parameters, self.INPUT, context
        )
        if selected_only and source_layer is not None and source_layer.selectedFeatureIds():
            selected_ids = source_layer.selectedFeatureIds()
            request = QgsFeatureRequest().setFilterFids(selected_ids)
            features = source.getFeatures(request)
            feature_count = len(selected_ids)
        else:
            features = source.getFeatures()
            feature_count = source.featureCount()

        total_progress = 100.0 / feature_count if feature_count > 0 else 0.0
        matched = 0
        written = 0

        exact = match_mode == self.MODE_EXACT
        keep_matches = filter_action == self.ACTION_KEEP_MATCHING

        for current, feature in enumerate(features):
            if feedback.isCanceled():
                break

            is_match = _matches_reference(feature[match_field], reference_values, exact)
            if is_match:
                matched += 1

            keep = is_match if keep_matches else not is_match
            if keep:
                sink.addFeature(feature, QgsFeatureSink.FastInsert)
                written += 1

            feedback.setProgress(int(current * total_progress))

        feedback.pushInfo(
            self.tr(
                f"Table filter complete. Input: {feature_count}, matched: {matched}, written: {written}."
            )
        )
        return {self.OUTPUT: dest_id}
