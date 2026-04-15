"""Grouped DEM comparison algorithm with per-group summaries and bias threshold flags."""

from __future__ import annotations

import datetime as dt
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import geopandas as gpd
import numpy as np
from jinja2 import Environment
from shapely import wkb
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeatureRequest,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QCoreApplication, QVariant

from .dem_bathy_review_algorithm import DemBathyReviewAlgorithm


class DemBathyGroupedReviewAlgorithm(DemBathyReviewAlgorithm):
    """Compare two DEMs and organize report results by an optional group field."""

    GROUP_FIELD = "GROUP_FIELD"
    MEAN_BIAS_THRESHOLD = "MEAN_BIAS_THRESHOLD"
    VERTICAL_UNITS = "VERTICAL_UNITS"
    EXCLUDE_OUTLIER_THRESHOLD = "EXCLUDE_OUTLIER_THRESHOLD"

    UNIT_METERS = 0
    UNIT_FEET = 1
    UNIT_UNKNOWN = 2

    _VERTICAL_UNIT_LABELS = [
        "Meters (m)",
        "Feet (ft)",
        "Unknown / Source Units",
    ]

    def tr(self, text: str) -> str:
        """Translate user-facing text for this grouped algorithm."""
        return QCoreApplication.translate("DemBathyReviewGrouped", text)

    def createInstance(self) -> QgsProcessingAlgorithm:
        """Create algorithm instance for QGIS Processing registry."""
        return DemBathyGroupedReviewAlgorithm()

    def name(self) -> str:
        """Return stable algorithm id."""
        return "dem_bathy_grouped_review_report"

    def displayName(self) -> str:
        """Return algorithm display name."""
        return self.tr("DEM Bathymetry Grouped Comparison Report")

    def shortHelpString(self) -> str:
        """Return algorithm help text displayed by QGIS."""
        return self.tr(
            """
<h3>DEM Bathymetry Grouped Comparison Report</h3>
<p>
Compares DEM A and DEM B inside buffered centreline corridors and groups report output by an optional
attribute field from the centreline layer. Each group gets its own summary table and per-feature table.
</p>

<h4>Difference Convention</h4>
<p><b>diff = DEM A - DEM B</b></p>

<h4>Grouping and Significance</h4>
<ul>
    <li><b>Group Field</b> is optional. If empty, all features are reported under one group.</li>
    <li><b>Mean Bias Threshold</b> flags per-feature significant deviation when <code>|bias| &gt; threshold</code>.</li>
    <li><b>Vertical Units</b> annotates report tables and statistics to clarify units of elevation differences.</li>
    <li>Each group section shows the number of significant features and a conditional warning banner.</li>
    <li>Group summaries are point-weighted (computed from all valid point differences in each group).</li>
</ul>
            """
        )

    def initAlgorithm(self, config: Optional[Dict[str, Any]] = None) -> None:
        """Define parameters for grouped DEM comparison workflow."""
        super().initAlgorithm(config)
        self.addParameter(
            QgsProcessingParameterField(
                self.GROUP_FIELD,
                self.tr("Group By Field (optional)"),
                parentLayerParameterName=self.INPUT_CENTERLINES,
                type=QgsProcessingParameterField.Any,
                allowMultiple=False,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MEAN_BIAS_THRESHOLD,
                self.tr("Mean Bias Significance Threshold (absolute)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.5,
                minValue=0.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.VERTICAL_UNITS,
                self.tr("Vertical Units"),
                options=self._VERTICAL_UNIT_LABELS,
                defaultValue=self.UNIT_METERS,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.EXCLUDE_OUTLIER_THRESHOLD,
                self.tr("Exclude Sample Points with |Diff| Greater Than (optional, 0 = no exclusion)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=12.0,
                minValue=0.0,
                optional=True,
            )
        )

    def processAlgorithm(
        self,
        parameters: Dict[str, Any],
        context: Any,
        feedback: Any,
    ) -> Dict[str, Any]:
        """Execute grouped DEM comparison and reporting workflow."""
        dem_a_layer = self.parameterAsRasterLayer(parameters, self.INPUT_DEM_A, context)
        dem_b_layer = self.parameterAsRasterLayer(parameters, self.INPUT_DEM_B, context)
        centerline_layer = self.parameterAsVectorLayer(parameters, self.INPUT_CENTERLINES, context)
        buffer_distance = self.parameterAsDouble(parameters, self.BUFFER_DISTANCE, context)
        sample_spacing = self.parameterAsDouble(parameters, self.SAMPLE_SPACING, context)
        feature_id_field = self.parameterAsString(parameters, self.FEATURE_ID_FIELD, context)
        group_field = self.parameterAsString(parameters, self.GROUP_FIELD, context)
        target_crs = self.parameterAsCrs(parameters, self.TARGET_CRS, context)
        bias_threshold = self.parameterAsDouble(parameters, self.MEAN_BIAS_THRESHOLD, context)
        vertical_units_index = self.parameterAsEnum(parameters, self.VERTICAL_UNITS, context)
        exclude_outlier_threshold = self.parameterAsDouble(parameters, self.EXCLUDE_OUTLIER_THRESHOLD, context)
        output_points_path = self.parameterAsOutputLayer(parameters, self.OUTPUT_POINTS, context)
        output_html_path = self.parameterAsFileOutput(parameters, self.OUTPUT_HTML, context)
        vertical_units_label = self._vertical_unit_label(vertical_units_index)

        self._validate_inputs(
            dem_a_layer=dem_a_layer,
            dem_b_layer=dem_b_layer,
            centerline_layer=centerline_layer,
            buffer_distance=buffer_distance,
            sample_spacing=sample_spacing,
            output_html_path=output_html_path,
        )

        if bias_threshold < 0:
            raise QgsProcessingException(self.tr("Mean bias threshold must be non-negative."))

        if group_field and centerline_layer.fields().indexOf(group_field) < 0:
            raise QgsProcessingException(self.tr(f"Group field '{group_field}' was not found in centerline layer."))

        if not target_crs.isValid():
            target_crs = dem_a_layer.crs()

        dem_a_path = self._raster_path_from_layer(dem_a_layer)
        dem_b_path = self._raster_path_from_layer(dem_b_layer)

        feature_stats: List[Dict[str, Any]] = []
        grouped_diffs: Dict[str, List[float]] = {}
        grouped_nodata_count: Dict[str, int] = {}
        grouped_valid_points: Dict[str, int] = {}
        grouped_feature_count: Dict[str, int] = {}
        grouped_flagged_count: Dict[str, int] = {}
        grouped_excluded_count: Dict[str, int] = {}

        sample_count = 0
        point_sink = None
        output_points_dest = None
        point_fields: Optional[QgsFields] = None

        if output_points_path:
            point_fields = self._build_grouped_point_output_fields()
            point_sink, output_points_dest = self.parameterAsSink(
                parameters,
                self.OUTPUT_POINTS,
                context,
                point_fields,
                QgsWkbTypes.Point,
                target_crs,
            )
            if point_sink is None:
                raise QgsProcessingException(self.tr("Unable to create output sample point sink."))

        import rasterio

        with rasterio.open(dem_a_path) as dem_a_src, rasterio.open(dem_b_path) as dem_b_src:
            target_grid = self._build_target_grid(dem_a_src, target_crs)

            mem_a, ds_a = self._reproject_to_memory(dem_a_src, target_grid)
            mem_b, ds_b = self._reproject_to_memory(dem_b_src, target_grid)
            try:
                centerlines_gdf = self._qgs_layer_to_grouped_geodataframe(
                    layer=centerline_layer,
                    feature_id_field=feature_id_field,
                    group_field=group_field,
                    target_crs=target_crs,
                    selected_only=centerline_layer.selectedFeatureCount() > 0,
                )
                buffer_gdf = centerlines_gdf.copy()
                buffer_gdf["geometry"] = buffer_gdf.geometry.buffer(
                    buffer_distance,
                    cap_style=2,
                    join_style=1,
                )

                feature_count = len(buffer_gdf)
                if feature_count == 0:
                    feedback.pushInfo(self.tr("Input centerline layer has zero features."))

                for idx, row in enumerate(buffer_gdf.itertuples(index=False), start=1):
                    if feedback.isCanceled():
                        break

                    polygon = row.geometry
                    feature_id = getattr(row, "feature_id")
                    group_value = getattr(row, "group_value")
                    zone_points = self._generate_points_within_polygon(polygon, sample_spacing)

                    if not zone_points:
                        feedback.pushWarning(
                            self.tr(
                                f"Feature '{feature_id}' produced no sample points after buffering; skipped."
                            )
                        )
                        self._set_progress(feedback, idx, feature_count)
                        continue

                    zone_rows = self._sample_zone(
                        feature_id=feature_id,
                        points=zone_points,
                        dem_a_dataset=ds_a,
                        dem_b_dataset=ds_b,
                    )
                    for zone_row in zone_rows:
                        zone_row["group_value"] = group_value
                        # Mark points as excluded if they exceed the outlier threshold
                        is_excluded = (
                            exclude_outlier_threshold > 0
                            and not zone_row["is_nodata"]
                            and not math.isnan(zone_row.get("diff", float("nan")))
                            and abs(zone_row["diff"]) > exclude_outlier_threshold
                        )
                        zone_row["is_excluded"] = is_excluded

                    sample_count += len(zone_rows)
                    if point_sink is not None:
                        for record in zone_rows:
                            if not self._write_grouped_point_feature(point_sink, point_fields, record):
                                raise QgsProcessingException(
                                    self.tr(
                                        f"Failed to write sample point for feature '{record.get('feature_id', '')}'."
                                    )
                                )

                    valid_diffs = np.array(
                        [
                            record["diff"]
                            for record in zone_rows
                            if not record["is_nodata"] and not math.isnan(record["diff"])
                        ],
                        dtype=float,
                    )
                    nodata_count = int(sum(1 for record in zone_rows if record["is_nodata"]))

                    if valid_diffs.size < 3:
                        feedback.pushWarning(
                            self.tr(
                                f"Feature '{feature_id}' has fewer than 3 valid sample points; skipped."
                            )
                        )
                        self._set_progress(feedback, idx, feature_count)
                        continue

                    # Apply outlier exclusion if threshold is set
                    excluded_count = 0
                    filtered_diffs = valid_diffs
                    if exclude_outlier_threshold > 0:
                        outlier_mask = np.abs(valid_diffs) <= exclude_outlier_threshold
                        filtered_diffs = valid_diffs[outlier_mask]
                        excluded_count = int(valid_diffs.size - filtered_diffs.size)
                        
                        if filtered_diffs.size < 3:
                            feedback.pushWarning(
                                self.tr(
                                    f"Feature '{feature_id}' has fewer than 3 valid sample points after outlier exclusion; skipped."
                                )
                            )
                            self._set_progress(feedback, idx, feature_count)
                            continue

                    mean_diff = float(np.mean(filtered_diffs))
                    is_significant = bool(abs(mean_diff) > bias_threshold)

                    feature_row = {
                        "feature_id": feature_id,
                        "group_value": group_value,
                        "nodata_count": nodata_count,
                        "excluded_count": excluded_count,
                        "max_diff": float(np.max(valid_diffs)),
                        "min_diff": float(np.min(valid_diffs)),
                        "std_dev": float(np.std(filtered_diffs)),
                        "bias": mean_diff,
                        "rmse": float(np.sqrt(np.mean(np.square(filtered_diffs)))),
                        "is_significant": is_significant,
                    }
                    feature_stats.append(feature_row)

                    grouped_diffs.setdefault(group_value, []).extend(filtered_diffs.tolist())
                    grouped_nodata_count[group_value] = grouped_nodata_count.get(group_value, 0) + nodata_count
                    grouped_valid_points[group_value] = grouped_valid_points.get(group_value, 0) + int(filtered_diffs.size)
                    grouped_feature_count[group_value] = grouped_feature_count.get(group_value, 0) + 1
                    grouped_flagged_count[group_value] = grouped_flagged_count.get(group_value, 0) + int(is_significant)
                    grouped_excluded_count[group_value] = grouped_excluded_count.get(group_value, 0) + excluded_count

                    self._set_progress(feedback, idx, feature_count)
            finally:
                ds_a.close()
                ds_b.close()
                mem_a.close()
                mem_b.close()

        groups = self._build_grouped_summaries(
            grouped_diffs=grouped_diffs,
            grouped_nodata_count=grouped_nodata_count,
            grouped_valid_points=grouped_valid_points,
            grouped_feature_count=grouped_feature_count,
            grouped_flagged_count=grouped_flagged_count,
            grouped_excluded_count=grouped_excluded_count,
            feature_stats=feature_stats,
            bias_threshold=bias_threshold,
        )

        run_metadata = {
            "dem_a_path": dem_a_layer.name(),
            "dem_b_path": dem_b_layer.name(),
            "centerlines_name": centerline_layer.name(),
            "selection_mode": "Selected features" if centerline_layer.selectedFeatureCount() > 0 else "All features",
            "buffer_distance": f'{round(buffer_distance, 2):,.3f}',
            "sample_spacing": f'{round(sample_spacing, 2):,.3f}' ,
            "target_crs": target_crs.authid() or target_crs.toWkt(),
            "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "feature_count": len(feature_stats),
            "sample_count": sample_count,
            "group_field": group_field if group_field else "(not specified)",
            "group_label": self._to_title_case_label(group_field) if group_field else "Group",
            "vertical_units": vertical_units_label,
            "bias_threshold": bias_threshold,
            "exclude_outlier_threshold": exclude_outlier_threshold if exclude_outlier_threshold > 0 else "None",
            "group_count": len(groups),
        }
        run_metadata['group_label_lower'] = run_metadata['group_label'].lower()

        html_output = self._render_grouped_report(run_metadata, groups)
        self._write_text_file(output_html_path, html_output)
        self._open_report_in_edge(output_html_path, feedback)

        results: Dict[str, Any] = {self.OUTPUT_HTML: output_html_path}

        if output_points_dest:
            if sample_count <= 0:
                raise QgsProcessingException(
                    self.tr(
                        "Output Sample Points was requested, but no points were generated. "
                        "Check DEM overlap, buffer distance, sample spacing, and centerline selection."
                    )
                )
            del point_sink
            results[self.OUTPUT_POINTS] = output_points_dest

        feedback.pushInfo(self.tr(f"Grouped report written: {output_html_path}"))

        return results

    def _qgs_layer_to_grouped_geodataframe(
        self,
        layer: QgsVectorLayer,
        feature_id_field: str,
        group_field: str,
        target_crs: QgsCoordinateReferenceSystem,
        selected_only: bool,
    ) -> gpd.GeoDataFrame:
        """Convert QGIS line layer to GeoDataFrame with feature_id and group value."""
        field_names = [field.name() for field in layer.fields()]
        records: List[Dict[str, Any]] = []

        selected_ids = layer.selectedFeatureIds() if selected_only else []
        if selected_only and not selected_ids:
            raise QgsProcessingException("No selected centerline features were found to process.")

        feature_iter = (
            layer.getFeatures(QgsFeatureRequest().setFilterFids(selected_ids))
            if selected_only
            else layer.getFeatures()
        )

        for feature in feature_iter:
            geom = feature.geometry()
            if geom is None or geom.isEmpty():
                continue
            attrs = {name: feature[name] for name in field_names}
            attrs["_fid"] = feature.id()
            attrs["geometry"] = wkb.loads(bytes(geom.asWkb()))
            records.append(attrs)

        if not records:
            raise QgsProcessingException("Centerline layer does not contain valid line geometries.")

        src_crs = layer.crs().toWkt() if layer.crs().isValid() else None
        gdf = gpd.GeoDataFrame(records, geometry="geometry", crs=src_crs)
        if gdf.crs is None:
            raise QgsProcessingException("Centerline layer CRS is undefined.")

        gdf = gdf.to_crs(target_crs.toWkt())

        if feature_id_field and feature_id_field in gdf.columns:
            gdf["feature_id"] = gdf[feature_id_field].astype(str)
        else:
            gdf["feature_id"] = gdf["_fid"].astype(str)

        if group_field and group_field in gdf.columns:
            gdf["group_value"] = gdf[group_field].apply(self._normalize_group_value)
        else:
            gdf["group_value"] = "All Features"

        return gdf[["feature_id", "group_value", "geometry"]]

    @staticmethod
    def _normalize_group_value(value: Any) -> str:
        """Normalize group labels for deterministic report sections."""
        if value is None:
            return "UNASSIGNED"
        text = str(value).strip()
        if not text:
            return "UNASSIGNED"
        return text

    @staticmethod
    def _to_title_case_label(field_name: str) -> str:
        """Convert a field name to a title-cased report label."""
        cleaned = str(field_name).strip().replace("_", " ")
        if not cleaned:
            return "Group"
        return cleaned.title()

    def _vertical_unit_label(self, unit_index: int) -> str:
        """Return compact vertical unit label used in the report."""
        if unit_index == self.UNIT_FEET:
            return "ft"
        if unit_index == self.UNIT_UNKNOWN:
            return "source units"
        return "m"

    def _build_grouped_summaries(
        self,
        grouped_diffs: Dict[str, List[float]],
        grouped_nodata_count: Dict[str, int],
        grouped_valid_points: Dict[str, int],
        grouped_feature_count: Dict[str, int],
        grouped_flagged_count: Dict[str, int],
        grouped_excluded_count: Dict[str, int],
        feature_stats: Sequence[Dict[str, Any]],
        bias_threshold: float,
    ) -> List[Dict[str, Any]]:
        """Build group summary records and attach grouped feature rows."""
        groups: List[Dict[str, Any]] = []
        for group_name in sorted(grouped_feature_count.keys(), key=lambda x: str(x).lower()):
            diffs = np.array(grouped_diffs.get(group_name, []), dtype=float)
            if diffs.size == 0:
                continue

            group_feature_rows = [
                row for row in feature_stats if str(row.get("group_value", "")) == str(group_name)
            ]
            group_feature_rows = sorted(group_feature_rows, key=lambda row: str(row.get("feature_id", "")))

            groups.append(
                {
                    "group_value": group_name,
                    "summary": {
                        "feature_count": int(grouped_feature_count.get(group_name, 0)),
                        "valid_point_count": int(grouped_valid_points.get(group_name, 0)),
                        "nodata_count_total": int(grouped_nodata_count.get(group_name, 0)),
                        "excluded_count_total": int(grouped_excluded_count.get(group_name, 0)),
                        "min_diff": float(np.min(diffs)),
                        "median_diff": float(np.median(diffs)),
                        "max_diff": float(np.max(diffs)),
                        "std_dev": float(np.std(diffs)),
                        "bias": float(np.mean(diffs)),
                        "rmse": float(np.sqrt(np.mean(np.square(diffs)))),
                        "flagged_feature_count": int(grouped_flagged_count.get(group_name, 0)),
                        "flagged_feature_ratio": float(
                            grouped_flagged_count.get(group_name, 0)
                            / max(1, grouped_feature_count.get(group_name, 1))
                        ),
                    },
                    "feature_rows": group_feature_rows,
                    "bias_threshold": float(bias_threshold),
                }
            )

        return groups

    def _render_grouped_report(
        self,
        metadata: Dict[str, Any],
        groups: Sequence[Dict[str, Any]],
    ) -> str:
        """Render grouped HTML report with per-group summary and feature details."""

        def fmt(value: Any) -> str:
            if value is None:
                return "-"
            if isinstance(value, (float, np.floating)):
                if np.isnan(value):
                    return "nan"
                return f"{float(value):,.4f}"
            if isinstance(value, (int, np.integer)):
                return f"{int(value):,}"
            return str(value)

        rendered_groups: List[Dict[str, Any]] = []
        for group in groups:
            summary = group["summary"]
            feature_rows = [
                {
                    "feature_id": fmt(row.get("feature_id")),
                    "nodata_count": fmt(row.get("nodata_count")),
                    "excluded_count": fmt(row.get("excluded_count")),
                    "max_diff": fmt(row.get("max_diff")),
                    "min_diff": fmt(row.get("min_diff")),
                    "std_dev": fmt(row.get("std_dev")),
                    "bias": fmt(row.get("bias")),
                    "rmse": fmt(row.get("rmse")),
                    "significance": "YES" if bool(row.get("is_significant", False)) else "NO",
                }
                for row in group["feature_rows"]
            ]

            rendered_groups.append(
                {
                    "group_value": fmt(group["group_value"]),
                    "bias_threshold": fmt(group.get("bias_threshold")),
                    "feature_rows": feature_rows,
                    "has_significant": int(summary["flagged_feature_count"]) > 0,
                    "summary": {
                        "feature_count": fmt(summary.get("feature_count")),
                        "valid_point_count": fmt(summary.get("valid_point_count")),
                        "nodata_count_total": fmt(summary.get("nodata_count_total")),
                        "excluded_count_total": fmt(summary.get("excluded_count_total")),
                        "min_diff": fmt(summary.get("min_diff")),
                        "median_diff": fmt(summary.get("median_diff")),
                        "max_diff": fmt(summary.get("max_diff")),
                        "std_dev": fmt(summary.get("std_dev")),
                        "bias": fmt(summary.get("bias")),
                        "rmse": fmt(summary.get("rmse")),
                        "flagged_feature_count": fmt(summary.get("flagged_feature_count")),
                        "flagged_feature_ratio": fmt(summary.get("flagged_feature_ratio")),
                    },
                }
            )

        template = """
<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <title>DEM Bathymetry Grouped Comparison Report</title>
  <style>
    :root {
      --ink: #1f2d2d;
      --muted: #5f6d6d;
      --line: #d8dfdf;
      --bg: #f8fbfb;
      --head: #e6f0ed;
      --paper: #ffffff;
      --warn-bg: #fff4e6;
      --warn-line: #ffcf99;
      --ok-bg: #e9f7ef;
      --ok-line: #b7e1c5;
    }
    body {
      margin: 0;
      padding: 24px;
      font-family: "Segoe UI", "Helvetica Neue", sans-serif;
      color: var(--ink);
      background: linear-gradient(180deg, #f7fbfa 0%, #f0f7f4 100%);
    }
    .report {
      max-width: 1320px;
      margin: 0 auto;
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 12px;
      box-shadow: 0 10px 28px rgba(20, 48, 39, 0.08);
      overflow: hidden;
    }
    .head {
      background: var(--head);
      border-bottom: 1px solid var(--line);
      padding: 22px 24px;
    }
    .head h1 {
      margin: 0 0 6px 0;
      font-size: 24px;
    }
    .meta {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 10px 16px;
      padding: 18px 24px;
      border-bottom: 1px solid var(--line);
      background: var(--bg);
      font-size: 13px;
    }
    .meta strong {
      color: var(--muted);
    }
    .section {
      padding: 20px 24px;
      border-bottom: 1px solid #eef3f1;
    }
    .section h2 {
      margin: 0 0 12px 0;
      font-size: 20px;
    }
    .notice {
      border: 1px solid var(--ok-line);
      background: var(--ok-bg);
      border-radius: 8px;
      padding: 10px 12px;
      margin-bottom: 12px;
      font-size: 13px;
    }
    .notice.warn {
      border-color: var(--warn-line);
      background: var(--warn-bg);
    }
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }
    .summary-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fafdfc;
      font-size: 13px;
    }
    .summary-card h3 {
      margin: 0 0 8px 0;
      font-size: 14px;
    }
    .table-wrap {
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #fff;
    }
    table {
      border-collapse: collapse;
      width: 100%;
      min-width: 980px;
      font-size: 13px;
    }
    thead th {
      background: #edf5f2;
      border-bottom: 1px solid var(--line);
      padding: 10px;
      text-align: left;
      white-space: nowrap;
    }
    tbody td {
      border-top: 1px solid #edf1f1;
      padding: 9px 10px;
      white-space: nowrap;
    }
    tbody tr:nth-child(even) {
      background: #fbfdfd;
    }
    .pill {
      border-radius: 999px;
      display: inline-block;
      padding: 2px 8px;
      font-size: 11px;
      border: 1px solid #d6dfdb;
      background: #f8fcfa;
    }
    .pill.yes {
      border-color: #f0b27a;
      background: #fff4e6;
      color: #9c4f00;
      font-weight: 700;
    }
    .pill.no {
      border-color: #b7e1c5;
      background: #e9f7ef;
      color: #1e6b3f;
      font-weight: 700;
    }
  </style>
  <script>
        window.MathJax = {
            tex: {
                inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
                displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']]
            },
            svg: { fontCache: 'global' },
            options: {
                skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
            }
        };
  </script>
  <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
</head>
<body>
  <article class=\"report\">
    <header class=\"head\">
      <h1>DEM Bathymetry Grouped Comparison Report</h1>
      <div>Created: {{ metadata.generated_at }}</div>
    </header>

    <section class=\"meta\">
      <div><strong>DEM A:</strong> {{ metadata.dem_a_path }}</div>
      <div><strong>DEM B:</strong> {{ metadata.dem_b_path }}</div>
      <div><strong>Centerline Layer:</strong> {{ metadata.centerlines_name }}</div>
      <div><strong>Processing Scope:</strong> {{ metadata.selection_mode }}</div>
      <div><strong>Target CRS:</strong> {{ metadata.target_crs }}</div>
      <div><strong>Group Field:</strong> {{ metadata.group_field }}</div>
    <div><strong>Vertical Units:</strong> {{ metadata.vertical_units }}</div>
      <div><strong>Bias Threshold:</strong> {{ metadata.bias_threshold }}</div>
      <div><strong>Outlier Exclusion Threshold:</strong> {{ metadata.exclude_outlier_threshold }}</div>
      <div><strong>Buffer Distance:</strong> {{ metadata.buffer_distance }}</div>
      <div><strong>Sample Spacing:</strong> {{ metadata.sample_spacing }}</div>
      <div><strong>Group Count:</strong> {{ metadata.group_count }}</div>
      <div><strong>Total Feature Count:</strong> {{ metadata.feature_count }}</div>
      <div><strong>Total Sample Points:</strong> {{ metadata.sample_count }}</div>
    </section>
    
    <section class="section">
        <h2>Difference Definition</h2>
        <div class="equation">$$\Delta z = z_A - z_B$$</div>
        <p>Where $z_A$ is sampled elevation from DEM A and $z_B$ is sampled elevation from DEM B.</p>
    </section>

    {% for group in groups %}
    <section class=\"section\">
            <h2>{{ metadata.group_label }}: {{ group.group_value }}</h2>

      {% if group.has_significant %}
      <div class=\"notice warn\">
        <b>Indicates strong evidence for needed topography correction of {{ metadata.group_label_lower }} {{ group.group_value }}.</b><br>
        Significant deviation detected in this {{ metadata.group_label_lower }} {{ group.summary.flagged_feature_count }} of {{ group.summary.feature_count }}
        feature(s) exceeded rule: "$|bias| > {{ group.bias_threshold }}$".

      </div>
      {% else %}
      <div class=\"notice\">
        <b>Indicates lack of strong evidence for needed topography correction of {{ metadata.group_label_lower }} {{ group.group_value }}.</b><br>
        No significant deviation detected in this {{ metadata.group_label_lower }} using rule: "$|bias| > {{ group.bias_threshold }}$".
        
      </div>
      {% endif %}

      <div class=\"summary-grid\">
        <article class=\"summary-card\">
          <h3>Coverage</h3>
          <div><strong>Features:</strong> {{ group.summary.feature_count }}</div>
          <div><strong>Valid Points:</strong> {{ group.summary.valid_point_count }}</div>
          <div><strong>NoData Total:</strong> {{ group.summary.nodata_count_total }}</div>
          <div><strong>Excluded Outliers:</strong> {{ group.summary.excluded_count_total }}</div>
        </article>
        <article class=\"summary-card\">
          <h3>Difference</h3>
                    <div><strong>Min:</strong> {{ group.summary.min_diff }} {{ metadata.vertical_units }}</div>
                    <div><strong>Median:</strong> {{ group.summary.median_diff }} {{ metadata.vertical_units }}</div>
                    <div><strong>Max:</strong> {{ group.summary.max_diff }} {{ metadata.vertical_units }}</div>
        </article>
        <article class=\"summary-card\">
          <h3>Summary Metrics</h3>
                    <div><strong>Standard Deviation:</strong> {{ group.summary.std_dev }} {{ metadata.vertical_units }}</div>
                    <div><strong>Bias:</strong> {{ group.summary.bias }} {{ metadata.vertical_units }}</div>
                    <div><strong>RMSE:</strong> {{ group.summary.rmse }} {{ metadata.vertical_units }}</div>
        </article>
        <article class=\"summary-card\">
          <h3>Significance</h3>
          <div><strong>Total Features:</strong> {{ group.summary.feature_count }}</div>
          <div><strong>Significant Feature Count:</strong> {{ group.summary.flagged_feature_count }}</div>
          <div><strong>Rule:</strong> $|bias| &gt; {{ group.bias_threshold }}$</div>
        </article>
      </div>

      <div class=\"table-wrap\">
        <table>
          <thead>
            <tr>
              <th>Feature ID</th>
              <th>NoData Count</th>
              <th>Excluded Count</th>
                            <th>Max Diff ({{ metadata.vertical_units }})</th>
                            <th>Min Diff ({{ metadata.vertical_units }})</th>
                            <th>Std Dev ({{ metadata.vertical_units }})</th>
                            <th>Bias ({{ metadata.vertical_units }})</th>
                            <th>RMSE ({{ metadata.vertical_units }})</th>
              <th>Significant</th>
            </tr>
          </thead>
          <tbody>
            {% for row in group.feature_rows %}
            <tr>
              <td>{{ row.feature_id }}</td>
              <td>{{ row.nodata_count }}</td>
              <td>{{ row.excluded_count }}</td>
              <td>{{ row.max_diff }}</td>
              <td>{{ row.min_diff }}</td>
              <td>{{ row.std_dev }}</td>
              <td>{{ row.bias }}</td>
              <td>{{ row.rmse }}</td>
              <td>
                {% if row.significance == "YES" %}
                <span class=\"pill yes\">YES</span>
                {% else %}
                <span class=\"pill no\">NO</span>
                {% endif %}
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </section>
    {% endfor %}
  </article>
</body>
</html>
"""

        env = Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)
        return env.from_string(template).render(metadata=metadata, groups=rendered_groups)

    @staticmethod
    def _build_grouped_point_output_fields() -> QgsFields:
        """Return output schema for grouped sampled point features."""
        fields = QgsFields()
        fields.append(QgsField("feature_id", QVariant.String))
        fields.append(QgsField("group_value", QVariant.String))
        fields.append(QgsField("elev_a", QVariant.Double))
        fields.append(QgsField("elev_b", QVariant.Double))
        fields.append(QgsField("diff", QVariant.Double))
        fields.append(QgsField("is_nodata", QVariant.Int))
        fields.append(QgsField("is_excluded", QVariant.Int))
        return fields

    @staticmethod
    def _write_grouped_point_feature(
        sink: QgsFeatureSink,
        fields: Optional[QgsFields],
        record: Dict[str, Any],
    ) -> bool:
        """Write a single grouped sampled point record to the output sink."""
        from qgis.core import QgsFeature, QgsGeometry, QgsPointXY

        feature = QgsFeature(fields)
        feature.setGeometry(
            QgsGeometry.fromPointXY(
                QgsPointXY(
                    float(record["x"]),
                    float(record["y"]),
                )
            )
        )
        is_nodata = bool(record.get("is_nodata", False))
        is_excluded = bool(record.get("is_excluded", False))
        elev_a = None if is_nodata else record.get("elev_a")
        elev_b = None if is_nodata else record.get("elev_b")
        diff = None if is_nodata else record.get("diff")

        feature.setAttributes(
            [
                str(record.get("feature_id", "")),
                str(record.get("group_value", "")),
                elev_a,
                elev_b,
                diff,
                1 if is_nodata else 0,
                1 if is_excluded else 0,
            ]
        )
        if sink.addFeature(feature, QgsFeatureSink.FastInsert):
            return True
        return sink.addFeature(feature)
