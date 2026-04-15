"""Processing algorithm for DEM comparison along buffered channel centrelines."""

from __future__ import annotations

import datetime as dt
import math
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import geopandas as gpd
import numpy as np
import rasterio
from jinja2 import Environment
from rasterio.crs import CRS as RioCRS
from rasterio.io import DatasetReader, MemoryFile
from rasterio.warp import Resampling, calculate_default_transform, reproject
from shapely import wkb
from shapely.geometry import Point
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureRequest,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterCrs,
    QgsProcessingParameterDistance,
    QgsProcessingParameterField,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterVectorDestination,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)


@dataclass
class TargetGrid:
    """Defines the shared grid used for raster reprojection and sampling.

    Attributes:
        crs (rasterio.crs.CRS): Target CRS for both DEM rasters.
        transform (Affine): Affine transform for pixel-to-map conversion.
        width (int): Target raster width in pixels.
        height (int): Target raster height in pixels.
        dtype (str): Raster data type for output in-memory datasets.
        nodata (Optional[float]): Target NoData value for output datasets.
    """

    crs: RioCRS
    transform: Any
    width: int
    height: int
    dtype: str
    nodata: Optional[float]


class DemBathyReviewAlgorithm(QgsProcessingAlgorithm):
    """Compare two DEM rasters within buffered zones around channel centrelines.

    This algorithm harmonizes DEM and vector CRS in memory, generates regular sample
    grids inside per-feature buffers, computes DEM A - DEM B statistics for each
    zone, exports sampled points, and writes a self-contained HTML report.

    Assumptions:
        - DEM inputs are single-band rasters containing elevation values.
        - Centreline features are LineString or MultiLineString geometry types.
        - Inputs provide valid CRS definitions, or execution stops with an error.
        - Python dependencies listed in requirements are available in QGIS.
        - Input paths are readable and output folders are writable.

    Methodology:
        1. Validate parameter values, raster readability, CRS, and geometry type.
        2. Determine a shared target CRS and shared raster sampling grid.
        3. Reproject both DEMs into in-memory rasters on the shared grid.
        4. Convert centreline features to GeoDataFrame and reproject to target CRS.
        5. Buffer each centreline feature and generate fixed-spacing sample points.
        6. Sample both DEMs at each point and flag NoData values.
        7. Compute per-feature statistics from valid samples only.
        8. Aggregate global summary metrics across per-feature outputs.
        9. Render HTML report from Jinja2 template with embedded CSS.
        10. Write report and optional sample-point vector output.

    Examples:
        - Run from QGIS Processing Toolbox using two GeoTIFF DEMs and a line layer.
        - Batch process multiple watersheds by iterating model inputs in Processing.
    """

    INPUT_DEM_A = "INPUT_DEM_A"
    INPUT_DEM_B = "INPUT_DEM_B"
    INPUT_CENTERLINES = "INPUT_CENTERLINES"
    BUFFER_DISTANCE = "BUFFER_DISTANCE"
    SAMPLE_SPACING = "SAMPLE_SPACING"
    FEATURE_ID_FIELD = "FEATURE_ID_FIELD"
    TARGET_CRS = "TARGET_CRS"
    OUTPUT_POINTS = "OUTPUT_POINTS"
    OUTPUT_HTML = "OUTPUT_HTML"

    def tr(self, text: str) -> str:
        """Translate user-facing text.

        Args:
            text (str): Source message.

        Returns:
            str: Translated message for current locale.
        """
        return QCoreApplication.translate("DemBathyReview", text)

    def createInstance(self) -> "DemBathyReviewAlgorithm":
        """Create algorithm instance for QGIS Processing registry.

        Returns:
            DemBathyReviewAlgorithm: Fresh algorithm instance.
        """
        return DemBathyReviewAlgorithm()

    def name(self) -> str:
        """Return stable algorithm id.

        Returns:
            str: Algorithm id.
        """
        return "dem_bathy_review_report"

    def displayName(self) -> str:
        """Return algorithm display name.

        Returns:
            str: User-visible algorithm name.
        """
        return self.tr("DEM Bathymetry Comparison Report")

    def group(self) -> str:
        """Return Processing group display name.

        Returns:
            str: Group name for toolbox organization.
        """
        return self.tr("DEM Bathymetry Review")

    def groupId(self) -> str:
        """Return stable group id.

        Returns:
            str: Group id.
        """
        return "dem_bathy_review"

    def flags(self) -> QgsProcessingAlgorithm.Flags:
        """Return algorithm flags.

        Returns:
            QgsProcessingAlgorithm.Flags: Flags with no-threading to avoid UI-thread
            violations and native-library instability in worker threads.
        """
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def shortHelpString(self) -> str:
        """Return algorithm help text displayed by QGIS.

        Returns:
            str: Short usage guide for toolbox users.
        """
        return self.tr(
            """
<h3>DEM Bathymetry Comparison Report</h3>
<p>
Compares two DEM rasters (A and B) within buffered channel centreline corridors, computes
per-feature statistics from fixed-spacing sample points, and writes a self-contained HTML report.
</p>

<h4>Difference Convention</h4>
<p><b>diff = DEM A - DEM B</b></p>

<h4>Inputs</h4>
<ul>
    <li><b>DEM A</b>: Reference raster for default CRS and difference numerator.</li>
    <li><b>DEM B</b>: Comparison raster.</li>
    <li><b>Channel Centrelines</b>: LineString/MultiLineString features only.</li>
    <li><b>Buffer Distance</b>: Corridor half-width around each centreline.</li>
    <li><b>Sample Spacing</b>: Fixed spacing for regular sampling grid inside each buffer.</li>
    <li><b>Feature ID Field</b>: Optional label used in report tables (falls back to FID).</li>
    <li><b>Target CRS</b>: Optional; defaults silently to DEM A CRS.</li>
    <li><b>Output Sample Points</b>: Optional point export with values and NoData flag.</li>
    <li><b>Output HTML Report</b>: Required final report path.</li>
</ul>

<h4>Behavior Notes</h4>
<ul>
    <li>If centreline layer has selected features, only selected features are processed.</li>
    <li>Points where either DEM is NoData are excluded from statistics and tracked as NoData.</li>
    <li>Minimum 3 valid points are required per feature; otherwise feature is skipped with warning.</li>
    <li>All numeric report values are formatted to 4 decimal places.</li>
    <li>No intermediate rasters are written to disk; reprojection is done in memory.</li>
</ul>

<h4>Outputs</h4>
<ul>
    <li><b>HTML report</b> with run metadata, summary statistics, and per-feature table.</li>
    <li><b>Optional point layer</b> with attributes: feature_id, elev_a, elev_b, diff, is_nodata.</li>
</ul>

<h4>Failure States</h4>
<ul>
    <li>Invalid or unreadable DEM inputs.</li>
    <li>Missing CRS on either DEM or centreline layer.</li>
    <li>Non-line centreline geometry type.</li>
    <li>Non-positive buffer distance or sample spacing.</li>
    <li>Output path not writable.</li>
</ul>
            """
        )

    def initAlgorithm(self, config: Optional[Dict[str, Any]] = None) -> None:
        """Define Processing parameters for DEM comparison workflow.

        Args:
            config (Optional[Dict[str, Any]]): Optional Processing config.

        Returns:
            None: Parameters are registered in place.
        """
        del config
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_DEM_A,
                self.tr("DEM A"),
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_DEM_B,
                self.tr("DEM B"),
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_CENTERLINES,
                self.tr("Channel Centrelines"),
                [QgsProcessing.TypeVectorLine],
            )
        )
        self.addParameter(
            QgsProcessingParameterDistance(
                self.BUFFER_DISTANCE,
                self.tr("Buffer Distance (map units in target CRS)"),
                defaultValue=50.0,
                minValue=0.0001,
                parentParameterName=self.INPUT_CENTERLINES,
            )
        )
        self.addParameter(
            QgsProcessingParameterDistance(
                self.SAMPLE_SPACING,
                self.tr("Sample Spacing (map units in target CRS)"),
                defaultValue=10.0,
                minValue=0.0001,
                parentParameterName=self.INPUT_CENTERLINES,
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.FEATURE_ID_FIELD,
                self.tr("Feature ID Field (optional)"),
                parentLayerParameterName=self.INPUT_CENTERLINES,
                type=QgsProcessingParameterField.Any,
                allowMultiple=False,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterCrs(
                self.TARGET_CRS,
                self.tr("Target CRS (optional, defaults to DEM A CRS)"),
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.OUTPUT_POINTS,
                self.tr("Output Sample Points (optional)"),
                type=QgsProcessing.TypeVectorPoint,
                optional=True,
                createByDefault=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_HTML,
                self.tr("Output HTML Report"),
                fileFilter="HTML files (*.html)",
            )
        )

    def processAlgorithm(
        self,
        parameters: Dict[str, Any],
        context: Any,
        feedback: Any,
    ) -> Dict[str, Any]:
        """Execute DEM comparison and reporting workflow.

        Args:
            parameters (Dict[str, Any]): Processing runtime parameters.
            context (Any): QGIS Processing execution context.
            feedback (Any): Feedback object for logs, cancellation, progress.

        Returns:
            Dict[str, Any]: Output path dictionary containing report and optional points.

        Raises:
            QgsProcessingException: For invalid inputs, file I/O failures, or processing errors.

        Assumptions:
            - Input DEMs overlap spatially after reprojection.
            - The selected target CRS uses linear units suitable for spacing and buffer.
            - At least one zone may be processed; empty stats are still reported.

        Methodology:
            1. Resolve and validate all parameters.
            2. Open rasters and create a shared reprojection grid.
            3. Reproject DEM A and DEM B into MemoryFile datasets.
            4. Buffer each centreline, generate sample points, and sample both rasters.
            5. Compute zone statistics when valid sample count >= 3.
            6. Write report HTML and optional sample point vector output.
        """
        dem_a_layer = self.parameterAsRasterLayer(parameters, self.INPUT_DEM_A, context)
        dem_b_layer = self.parameterAsRasterLayer(parameters, self.INPUT_DEM_B, context)
        centerline_layer = self.parameterAsVectorLayer(parameters, self.INPUT_CENTERLINES, context)
        buffer_distance = self.parameterAsDouble(parameters, self.BUFFER_DISTANCE, context)
        sample_spacing = self.parameterAsDouble(parameters, self.SAMPLE_SPACING, context)
        feature_id_field = self.parameterAsString(parameters, self.FEATURE_ID_FIELD, context)
        target_crs = self.parameterAsCrs(parameters, self.TARGET_CRS, context)
        output_points_path = self.parameterAsOutputLayer(parameters, self.OUTPUT_POINTS, context)
        output_html_path = self.parameterAsFileOutput(parameters, self.OUTPUT_HTML, context)

        self._validate_inputs(
            dem_a_layer=dem_a_layer,
            dem_b_layer=dem_b_layer,
            centerline_layer=centerline_layer,
            buffer_distance=buffer_distance,
            sample_spacing=sample_spacing,
            output_html_path=output_html_path,
        )

        if not target_crs.isValid():
            target_crs = dem_a_layer.crs()

        dem_a_path = self._raster_path_from_layer(dem_a_layer)
        dem_b_path = self._raster_path_from_layer(dem_b_layer)

        feature_stats: List[Dict[str, Any]] = []
        sample_count = 0
        point_sink = None
        output_points_dest = None
        point_fields: Optional[QgsFields] = None

        if output_points_path:
            point_fields = self._build_point_output_fields()
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

        with rasterio.open(dem_a_path) as dem_a_src, rasterio.open(dem_b_path) as dem_b_src:
            target_grid = self._build_target_grid(dem_a_src, target_crs)

            mem_a, ds_a = self._reproject_to_memory(dem_a_src, target_grid)
            mem_b, ds_b = self._reproject_to_memory(dem_b_src, target_grid)
            try:
                centerlines_gdf = self._qgs_layer_to_geodataframe(
                    layer=centerline_layer,
                    feature_id_field=feature_id_field,
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

                    sample_count += len(zone_rows)
                    if point_sink is not None:
                        for record in zone_rows:
                            if not self._write_point_feature(point_sink, point_fields, record):
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

                    feature_stats.append(
                        {
                            "feature_id": feature_id,
                            "nodata_count": nodata_count,
                            "max_diff": float(np.max(valid_diffs)),
                            "min_diff": float(np.min(valid_diffs)),
                            "mean_diff": float(np.mean(valid_diffs)),
                            "std_dev": float(np.std(valid_diffs)),
                            "bias": float(np.mean(valid_diffs)),
                            "rmse": float(np.sqrt(np.mean(np.square(valid_diffs)))),
                        }
                    )
                    self._set_progress(feedback, idx, feature_count)
            finally:
                ds_a.close()
                ds_b.close()
                mem_a.close()
                mem_b.close()

        summary_stats = self._compute_summary_stats(feature_stats)

        run_metadata = {
            "dem_a_path": dem_a_path,
            "dem_b_path": dem_b_path,
            "centerlines_name": centerline_layer.name(),
            "selection_mode": "Selected features" if centerline_layer.selectedFeatureCount() > 0 else "All features",
            "buffer_distance": buffer_distance,
            "sample_spacing": sample_spacing,
            "target_crs": target_crs.authid() or target_crs.toWkt(),
            "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "feature_count": len(feature_stats),
            "sample_count": sample_count,
        }

        html_output = self._render_report(run_metadata, feature_stats, summary_stats)
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
            # Ensure buffered writes are flushed before QGIS attempts to load the output.
            del point_sink
            results[self.OUTPUT_POINTS] = output_points_dest

        feedback.pushInfo(self.tr(f"Report written: {output_html_path}"))

        return results

    @staticmethod
    def _set_progress(feedback: Any, current: int, total: int) -> None:
        """Set integer progress for Processing feedback.

        Args:
            feedback (Any): QGIS Processing feedback object.
            current (int): Current step number.
            total (int): Total number of steps.

        Returns:
            None: Updates feedback in place.
        """
        if total <= 0:
            feedback.setProgress(0)
            return
        progress = max(0, min(100, int((current / total) * 100)))
        feedback.setProgress(progress)

    def _validate_inputs(
        self,
        dem_a_layer: Optional[QgsRasterLayer],
        dem_b_layer: Optional[QgsRasterLayer],
        centerline_layer: Optional[QgsVectorLayer],
        buffer_distance: float,
        sample_spacing: float,
        output_html_path: str,
    ) -> None:
        """Validate raster, vector, numeric, and output-path parameters.

        Args:
            dem_a_layer (Optional[QgsRasterLayer]): DEM A raster layer.
            dem_b_layer (Optional[QgsRasterLayer]): DEM B raster layer.
            centerline_layer (Optional[QgsVectorLayer]): Centreline vector layer.
            buffer_distance (float): Buffer distance to apply per centerline.
            sample_spacing (float): Sampling spacing inside each buffered zone.
            output_html_path (str): Destination report path.

        Returns:
            None: Raises on invalid configuration.

        Raises:
            QgsProcessingException: If any input is invalid.
        """
        if dem_a_layer is None or not dem_a_layer.isValid():
            raise QgsProcessingException(self.tr("DEM A is missing or invalid."))
        if dem_b_layer is None or not dem_b_layer.isValid():
            raise QgsProcessingException(self.tr("DEM B is missing or invalid."))
        if centerline_layer is None or not centerline_layer.isValid():
            raise QgsProcessingException(self.tr("Channel centrelines layer is missing or invalid."))
        if not dem_a_layer.crs().isValid() or not dem_b_layer.crs().isValid():
            raise QgsProcessingException(self.tr("Both DEM rasters must have valid CRS definitions."))
        if buffer_distance <= 0:
            raise QgsProcessingException(self.tr("Buffer distance must be greater than zero."))
        if sample_spacing <= 0:
            raise QgsProcessingException(self.tr("Sample spacing must be greater than zero."))
        if not output_html_path:
            raise QgsProcessingException(self.tr("Output HTML path is required."))

        geom_type = QgsWkbTypes.geometryType(centerline_layer.wkbType())
        if geom_type != QgsWkbTypes.LineGeometry:
            raise QgsProcessingException(
                self.tr("Centerline input must contain LineString or MultiLineString features.")
            )

    @staticmethod
    def _raster_path_from_layer(layer: QgsRasterLayer) -> str:
        """Extract physical raster path from a QGIS raster layer source string.

        Args:
            layer (QgsRasterLayer): Input raster layer.

        Returns:
            str: Filesystem path to raster dataset.

        Raises:
            QgsProcessingException: If raster path cannot be read.
        """
        source = layer.source()
        path = source.split("|")[0]
        if not os.path.exists(path):
            raise QgsProcessingException(f"Raster path not found: {path}")
        return path

    @staticmethod
    def _build_target_grid(src_dataset: DatasetReader, target_crs: QgsCoordinateReferenceSystem) -> TargetGrid:
        """Build target raster grid definition from DEM A and selected CRS.

        Args:
            src_dataset (DatasetReader): Open rasterio dataset for DEM A.
            target_crs (QgsCoordinateReferenceSystem): Target CRS selected by user.

        Returns:
            TargetGrid: Shared grid used to reproject both DEMs.
        """
        rio_target_crs = RioCRS.from_wkt(target_crs.toWkt())
        source_nodata = src_dataset.nodata

        if src_dataset.crs == rio_target_crs:
            return TargetGrid(
                crs=rio_target_crs,
                transform=src_dataset.transform,
                width=src_dataset.width,
                height=src_dataset.height,
                dtype=src_dataset.dtypes[0],
                nodata=source_nodata,
            )

        transform, width, height = calculate_default_transform(
            src_dataset.crs,
            rio_target_crs,
            src_dataset.width,
            src_dataset.height,
            *src_dataset.bounds,
            resolution=src_dataset.res,
        )
        return TargetGrid(
            crs=rio_target_crs,
            transform=transform,
            width=width,
            height=height,
            dtype=src_dataset.dtypes[0],
            nodata=source_nodata,
        )

    @staticmethod
    def _reproject_to_memory(src_dataset: DatasetReader, grid: TargetGrid) -> Tuple[MemoryFile, DatasetReader]:
        """Reproject a source raster into an in-memory dataset aligned to target grid.

        Args:
            src_dataset (DatasetReader): Open source raster dataset.
            grid (TargetGrid): Shared destination grid definition.

        Returns:
            Tuple[MemoryFile, DatasetReader]: Backing memory file and open dataset handle.
        """
        memfile = MemoryFile()
        dst_dataset = memfile.open(
            driver="GTiff",
            width=grid.width,
            height=grid.height,
            count=1,
            dtype=grid.dtype,
            crs=grid.crs,
            transform=grid.transform,
            nodata=grid.nodata,
        )
        reproject(
            source=rasterio.band(src_dataset, 1),
            destination=rasterio.band(dst_dataset, 1),
            src_transform=src_dataset.transform,
            src_crs=src_dataset.crs,
            src_nodata=src_dataset.nodata,
            dst_transform=grid.transform,
            dst_crs=grid.crs,
            dst_nodata=grid.nodata,
            resampling=Resampling.bilinear,
        )
        return memfile, dst_dataset

    def _qgs_layer_to_geodataframe(
        self,
        layer: QgsVectorLayer,
        feature_id_field: str,
        target_crs: QgsCoordinateReferenceSystem,
        selected_only: bool,
    ) -> gpd.GeoDataFrame:
        """Convert QGIS line layer to GeoDataFrame and harmonize CRS.

        Args:
            layer (QgsVectorLayer): Input centerline layer.
            feature_id_field (str): Optional feature id field for report labels.
            target_crs (QgsCoordinateReferenceSystem): Processing CRS.
            selected_only (bool): True when only selected input features should be processed.

        Returns:
            geopandas.GeoDataFrame: Reprojected centerline features with feature_id column.

        Raises:
            QgsProcessingException: If the layer contains no usable geometries.
        """
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

        return gdf[["feature_id", "geometry"]]

    @staticmethod
    def _generate_points_within_polygon(polygon: Any, spacing: float) -> List[Tuple[float, float]]:
        """Generate a regular grid of sample points within a polygon boundary.

        Args:
            polygon (Any): Shapely polygon geometry.
            spacing (float): Grid spacing distance in map units.

        Returns:
            List[Tuple[float, float]]: Point coordinates inside or on polygon boundary.
        """
        minx, miny, maxx, maxy = polygon.bounds
        x_values = np.arange(minx, maxx + (spacing * 0.5), spacing)
        y_values = np.arange(miny, maxy + (spacing * 0.5), spacing)

        points: List[Tuple[float, float]] = []
        for x in x_values:
            for y in y_values:
                point = Point(float(x), float(y))
                if polygon.covers(point):
                    points.append((float(x), float(y)))
        return points

    def _sample_zone(
        self,
        feature_id: str,
        points: Sequence[Tuple[float, float]],
        dem_a_dataset: DatasetReader,
        dem_b_dataset: DatasetReader,
    ) -> List[Dict[str, Any]]:
        """Sample both DEM rasters at zone points and return per-point records.

        Args:
            feature_id (str): Feature identifier label.
            points (Sequence[Tuple[float, float]]): Zone sample coordinates.
            dem_a_dataset (DatasetReader): Reprojected DEM A dataset.
            dem_b_dataset (DatasetReader): Reprojected DEM B dataset.

        Returns:
            List[Dict[str, Any]]: Per-point sampling records including NoData flags.
        """
        samples_a = dem_a_dataset.sample(points, indexes=1, masked=True)
        samples_b = dem_b_dataset.sample(points, indexes=1, masked=True)

        nodata_a = dem_a_dataset.nodata
        nodata_b = dem_b_dataset.nodata

        rows: List[Dict[str, Any]] = []
        for (x, y), val_a_raw, val_b_raw in zip(points, samples_a, samples_b):
            val_a = float(val_a_raw[0]) if not np.ma.getmaskarray(val_a_raw)[0] else np.nan
            val_b = float(val_b_raw[0]) if not np.ma.getmaskarray(val_b_raw)[0] else np.nan

            is_nodata = (
                bool(np.ma.getmaskarray(val_a_raw)[0])
                or bool(np.ma.getmaskarray(val_b_raw)[0])
                or self._is_nodata_value(val_a, nodata_a)
                or self._is_nodata_value(val_b, nodata_b)
            )

            if is_nodata:
                diff = np.nan
                val_a = np.nan
                val_b = np.nan
            else:
                diff = float(val_a - val_b)

            rows.append(
                {
                    "feature_id": feature_id,
                    "x": float(x),
                    "y": float(y),
                    "elev_a": float(val_a),
                    "elev_b": float(val_b),
                    "diff": float(diff),
                    "is_nodata": bool(is_nodata),
                }
            )

        return rows

    @staticmethod
    def _is_nodata_value(value: float, nodata: Optional[float]) -> bool:
        """Check whether a sampled value should be treated as NoData.

        Args:
            value (float): Sampled raster value.
            nodata (Optional[float]): Dataset nodata marker.

        Returns:
            bool: True when value is nodata-equivalent.
        """
        if math.isnan(value):
            return True
        if nodata is None:
            return False
        return bool(np.isclose(value, float(nodata), equal_nan=True))

    @staticmethod
    def _compute_summary_stats(feature_stats: Sequence[Dict[str, Any]]) -> Dict[str, float]:
        """Aggregate overall summary metrics across all per-feature statistics.

        Args:
            feature_stats (Sequence[Dict[str, Any]]): Per-feature metric rows.

        Returns:
            Dict[str, float]: Summary metric values with NaN defaults when empty.
        """
        if not feature_stats:
            nan = float("nan")
            return {
                "overall_min_diff": nan,
                "overall_max_diff": nan,
                "rmse_min": nan,
                "rmse_max": nan,
                "rmse_mean": nan,
                "bias_min": nan,
                "bias_max": nan,
                "bias_mean": nan,
                "std_dev_min": nan,
                "std_dev_max": nan,
                "std_dev_mean": nan,
            }

        min_diff = np.array([row["min_diff"] for row in feature_stats], dtype=float)
        max_diff = np.array([row["max_diff"] for row in feature_stats], dtype=float)
        rmse = np.array([row["rmse"] for row in feature_stats], dtype=float)
        bias = np.array([row["bias"] for row in feature_stats], dtype=float)
        std_dev = np.array([row["std_dev"] for row in feature_stats], dtype=float)

        return {
            "overall_min_diff": float(np.min(min_diff)),
            "overall_max_diff": float(np.max(max_diff)),
            "rmse_min": float(np.min(rmse)),
            "rmse_max": float(np.max(rmse)),
            "rmse_mean": float(np.mean(rmse)),
            "bias_min": float(np.min(bias)),
            "bias_max": float(np.max(bias)),
            "bias_mean": float(np.mean(bias)),
            "std_dev_min": float(np.min(std_dev)),
            "std_dev_max": float(np.max(std_dev)),
            "std_dev_mean": float(np.mean(std_dev)),
        }

    def _render_report(
        self,
        metadata: Dict[str, Any],
        feature_stats: Sequence[Dict[str, Any]],
        summary_stats: Dict[str, float],
    ) -> str:
        """Render full HTML report with embedded CSS and sortable stat views.

        Args:
            metadata (Dict[str, Any]): Runtime metadata shown in report header.
            feature_stats (Sequence[Dict[str, Any]]): Per-feature stat rows.
            summary_stats (Dict[str, float]): Aggregated summary metrics.

        Returns:
            str: Full HTML document as UTF-8 text.

        Notes:
            Sorting is implemented without JavaScript by rendering pre-sorted table
            views and toggling display through CSS :target selectors.
        """
        def fmt(value: Any) -> str:
            if value is None:
                return "-"
            if isinstance(value, (float, np.floating)):
                if np.isnan(value):
                    return "nan"
                return f"{float(value):.4f}"
            if isinstance(value, (int, np.integer)):
                return str(int(value))
            return str(value)

        sortable_columns = [
            ("feature_id", "Feature ID", False),
            ("nodata_count", "NoData Count", True),
            ("max_diff", "Max Diff", True),
            ("min_diff", "Min Diff", True),
            ("mean_diff", "Mean Diff", True),
            ("std_dev", "Std Dev", True),
            ("bias", "Bias", True),
            ("rmse", "RMSE", True),
        ]

        formatted_rows: List[Dict[str, str]] = []
        for row in feature_stats:
            formatted_rows.append({
                "feature_id": fmt(row.get("feature_id")),
                "nodata_count": fmt(row.get("nodata_count")),
                "max_diff": fmt(row.get("max_diff")),
                "min_diff": fmt(row.get("min_diff")),
                "mean_diff": fmt(row.get("mean_diff")),
                "std_dev": fmt(row.get("std_dev")),
                "bias": fmt(row.get("bias")),
                "rmse": fmt(row.get("rmse")),
            })

        sort_views = [
            {
                "view_id": "sort_default",
                "label": "Default Order",
                "rows": formatted_rows,
            }
        ]

        for key, label, numeric in sortable_columns:
            asc_rows = sorted(
                feature_stats,
                key=lambda row: self._sort_value(row.get(key), numeric),
            )
            desc_rows = sorted(
                feature_stats,
                key=lambda row: self._sort_value(row.get(key), numeric),
                reverse=True,
            )
            sort_views.append(
                {
                    "view_id": f"sort_{key}_asc",
                    "label": f"{label} Asc",
                    "rows": [self._format_feature_row(row) for row in asc_rows],
                }
            )
            sort_views.append(
                {
                    "view_id": f"sort_{key}_desc",
                    "label": f"{label} Desc",
                    "rows": [self._format_feature_row(row) for row in desc_rows],
                }
            )

        summary = {
            "overall_min_diff": fmt(summary_stats.get("overall_min_diff")),
            "overall_max_diff": fmt(summary_stats.get("overall_max_diff")),
            "rmse_min": fmt(summary_stats.get("rmse_min")),
            "rmse_max": fmt(summary_stats.get("rmse_max")),
            "rmse_mean": fmt(summary_stats.get("rmse_mean")),
            "bias_min": fmt(summary_stats.get("bias_min")),
            "bias_max": fmt(summary_stats.get("bias_max")),
            "bias_mean": fmt(summary_stats.get("bias_mean")),
            "std_dev_min": fmt(summary_stats.get("std_dev_min")),
            "std_dev_max": fmt(summary_stats.get("std_dev_max")),
            "std_dev_mean": fmt(summary_stats.get("std_dev_mean")),
        }

        template = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
    <title>DEM Bathymetry Comparison Report</title>
  <style>
    :root {
      --ink: #1f2d2d;
      --muted: #5f6d6d;
      --line: #d8dfdf;
      --bg: #f8fbfb;
      --head: #e6f0ed;
      --accent: #23694d;
      --paper: #ffffff;
    }
    body {
      margin: 0;
      padding: 24px;
      font-family: "Segoe UI", "Helvetica Neue", sans-serif;
      color: var(--ink);
      background: linear-gradient(180deg, #f7fbfa 0%, #f0f7f4 100%);
    }
    .report {
      max-width: 1240px;
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
      padding: 20px 24px 26px 24px;
    }
    .section h2 {
      margin: 0 0 12px 0;
      font-size: 18px;
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
      min-width: 860px;
      font-size: 13px;
    }
    thead th {
      background: #edf5f2;
      color: #1c2f2f;
      position: sticky;
      top: 0;
      z-index: 1;
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
    .sort-links a {
      margin-right: 8px;
      color: var(--accent);
      text-decoration: none;
      font-size: 12px;
    }
    .sort-links a:hover {
      text-decoration: underline;
    }
        .sort-pair a {
            color: var(--accent);
            text-decoration: none;
            margin-left: 4px;
            font-size: 11px;
            font-weight: 700;
        }
        .sort-pair a:hover {
            text-decoration: underline;
        }
    .view {
      display: none;
    }
    .view:target {
      display: block;
    }
    #sort_default {
      display: block;
    }
    body:has(.view:target) #sort_default {
      display: none;
    }
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      margin-top: 12px;
    }
    .summary-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fafdfc;
      font-size: 13px;
    }
    .summary-card h3 {
      margin: 0 0 8px 0;
      font-size: 14px;
      color: #27433a;
    }
        .equation {
            font-size: 17px;
            margin: 8px 0;
        }
        .equation-note {
            color: var(--muted);
            font-size: 12px;
        }
  </style>
    <script>
        window.MathJax = {
            tex: {
                inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
                displayMath: [['$$', '$$'], ['\\\\\[', '\\\\]']]
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
  <article class="report">
    <header class="head">
            <h1>DEM Bathymetry Comparison Report</h1>
      <div>Generated {{ metadata.generated_at }}</div>
    </header>

    <section class="meta">
      <div><strong>DEM A:</strong> {{ metadata.dem_a_path }}</div>
      <div><strong>DEM B:</strong> {{ metadata.dem_b_path }}</div>
      <div><strong>Centerline Layer:</strong> {{ metadata.centerlines_name }}</div>
            <div><strong>Processing Scope:</strong> {{ metadata.selection_mode }}</div>
      <div><strong>Target CRS:</strong> {{ metadata.target_crs }}</div>
      <div><strong>Buffer Distance:</strong> {{ metadata.buffer_distance }}</div>
      <div><strong>Sample Spacing:</strong> {{ metadata.sample_spacing }}</div>
      <div><strong>Feature Stats Count:</strong> {{ metadata.feature_count }}</div>
      <div><strong>Total Sample Points:</strong> {{ metadata.sample_count }}</div>
    </section>

        <section class="section">
            <h2>Difference Definition</h2>
            <div class="equation">$$\Delta z = z_A - z_B$$</div>
            <p>Where $z_A$ is sampled elevation from DEM A and $z_B$ is sampled elevation from DEM B.</p>
            <p class="equation-note">Math rendering uses MathJax CDN and requires internet access.</p>
        </section>

        <section class="section">
            <h2>Summary Statistics</h2>
            <div class="summary-grid">
                <article class="summary-card">
                    <h3>Difference Range</h3>
                    <div><strong>Overall Min:</strong> {{ summary.overall_min_diff }}</div>
                    <div><strong>Overall Max:</strong> {{ summary.overall_max_diff }}</div>
                </article>
                <article class="summary-card">
                    <h3>RMSE</h3>
                    <div><strong>Min:</strong> {{ summary.rmse_min }}</div>
                    <div><strong>Max:</strong> {{ summary.rmse_max }}</div>
                    <div><strong>Mean:</strong> {{ summary.rmse_mean }}</div>
                </article>
                <article class="summary-card">
                    <h3>Bias</h3>
                    <div><strong>Min:</strong> {{ summary.bias_min }}</div>
                    <div><strong>Max:</strong> {{ summary.bias_max }}</div>
                    <div><strong>Mean:</strong> {{ summary.bias_mean }}</div>
                </article>
                <article class="summary-card">
                    <h3>Std Dev</h3>
                    <div><strong>Min:</strong> {{ summary.std_dev_min }}</div>
                    <div><strong>Max:</strong> {{ summary.std_dev_max }}</div>
                    <div><strong>Mean:</strong> {{ summary.std_dev_mean }}</div>
                </article>
            </div>
        </section>

    <section class="section">
      <h2>Per-Feature Statistics</h2>
      {% for view in sort_views %}
      <div id="{{ view.view_id }}" class="view table-wrap">
        <table>
          <thead>
            <tr>
                            <th>
                                Feature ID
                                <span class="sort-pair">
                                    <a href="#sort_feature_id_asc" title="Sort Feature ID ascending">▲</a>
                                    <a href="#sort_feature_id_desc" title="Sort Feature ID descending">▼</a>
                                </span>
                            </th>
                            <th>
                                NoData Count
                                <span class="sort-pair">
                                    <a href="#sort_nodata_count_asc" title="Sort NoData Count ascending">▲</a>
                                    <a href="#sort_nodata_count_desc" title="Sort NoData Count descending">▼</a>
                                </span>
                            </th>
                            <th>
                                Max Diff
                                <span class="sort-pair">
                                    <a href="#sort_max_diff_asc" title="Sort Max Diff ascending">▲</a>
                                    <a href="#sort_max_diff_desc" title="Sort Max Diff descending">▼</a>
                                </span>
                            </th>
                            <th>
                                Min Diff
                                <span class="sort-pair">
                                    <a href="#sort_min_diff_asc" title="Sort Min Diff ascending">▲</a>
                                    <a href="#sort_min_diff_desc" title="Sort Min Diff descending">▼</a>
                                </span>
                            </th>
                            <th>
                                Mean Diff
                                <span class="sort-pair">
                                    <a href="#sort_mean_diff_asc" title="Sort Mean Diff ascending">▲</a>
                                    <a href="#sort_mean_diff_desc" title="Sort Mean Diff descending">▼</a>
                                </span>
                            </th>
                            <th>
                                Std Dev
                                <span class="sort-pair">
                                    <a href="#sort_std_dev_asc" title="Sort Std Dev ascending">▲</a>
                                    <a href="#sort_std_dev_desc" title="Sort Std Dev descending">▼</a>
                                </span>
                            </th>
                            <th>
                                Bias
                                <span class="sort-pair">
                                    <a href="#sort_bias_asc" title="Sort Bias ascending">▲</a>
                                    <a href="#sort_bias_desc" title="Sort Bias descending">▼</a>
                                </span>
                            </th>
                            <th>
                                RMSE
                                <span class="sort-pair">
                                    <a href="#sort_rmse_asc" title="Sort RMSE ascending">▲</a>
                                    <a href="#sort_rmse_desc" title="Sort RMSE descending">▼</a>
                                </span>
                            </th>
            </tr>
          </thead>
          <tbody>
            {% for row in view.rows %}
            <tr>
              <td>{{ row.feature_id }}</td>
              <td>{{ row.nodata_count }}</td>
              <td>{{ row.max_diff }}</td>
              <td>{{ row.min_diff }}</td>
              <td>{{ row.mean_diff }}</td>
              <td>{{ row.std_dev }}</td>
              <td>{{ row.bias }}</td>
              <td>{{ row.rmse }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      {% endfor %}
    </section>

  </article>
</body>
</html>
"""

        env = Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)
        rendered = env.from_string(template).render(
            metadata=metadata,
            sort_views=sort_views,
            summary=summary,
        )
        return rendered

    @staticmethod
    def _sort_value(value: Any, numeric: bool) -> Any:
        """Normalize values for deterministic sorting in report table views.

        Args:
            value (Any): Field value to sort.
            numeric (bool): Whether field should sort numerically.

        Returns:
            Any: Sort key.
        """
        if value is None:
            return float("inf") if numeric else ""
        if numeric:
            if isinstance(value, (float, np.floating)) and np.isnan(value):
                return float("inf")
            return float(value)
        return str(value)

    @staticmethod
    def _format_feature_row(row: Dict[str, Any]) -> Dict[str, str]:
        """Format a raw feature stat row into string values for HTML output.

        Args:
            row (Dict[str, Any]): Raw stats row.

        Returns:
            Dict[str, str]: Formatted row with fixed decimal precision.
        """
        def fmt(value: Any) -> str:
            if value is None:
                return "-"
            if isinstance(value, (float, np.floating)):
                if np.isnan(value):
                    return "nan"
                return f"{float(value):.4f}"
            if isinstance(value, (int, np.integer)):
                return str(int(value))
            return str(value)

        return {
            "feature_id": fmt(row.get("feature_id")),
            "nodata_count": fmt(row.get("nodata_count")),
            "max_diff": fmt(row.get("max_diff")),
            "min_diff": fmt(row.get("min_diff")),
            "mean_diff": fmt(row.get("mean_diff")),
            "std_dev": fmt(row.get("std_dev")),
            "bias": fmt(row.get("bias")),
            "rmse": fmt(row.get("rmse")),
        }

    @staticmethod
    def _write_text_file(path: str, content: str) -> None:
        """Write UTF-8 text to disk, creating parent directories as needed.

        Args:
            path (str): Destination file path.
            content (str): File contents.

        Returns:
            None
        """
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(content)

    @staticmethod
    def _open_report_in_edge(output_html_path: str, feedback: Any) -> None:
        """Open generated report in Microsoft Edge.

        Args:
            output_html_path (str): Path to generated HTML report.
            feedback (Any): Processing feedback for warnings.

        Returns:
            None
        """
        try:
            edge_path = shutil.which("msedge")
            if edge_path:
                subprocess.Popen([edge_path, output_html_path])
                return

            fallback_paths = [
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            ]
            for path in fallback_paths:
                if os.path.exists(path):
                    subprocess.Popen([path, output_html_path])
                    return

            feedback.pushWarning(
                "Microsoft Edge was not found on this machine. "
                "Report file was created but not automatically opened."
            )
        except Exception as exc:  # pragma: no cover - environment dependent
            feedback.pushWarning(f"Could not auto-open report in Edge: {exc}")

    @staticmethod
    def _build_point_output_fields() -> QgsFields:
        """Return output schema for sampled point features.

        Returns:
            QgsFields: Field definitions used by output sample point sink.
        """
        fields = QgsFields()
        fields.append(QgsField("feature_id", QVariant.String))
        fields.append(QgsField("elev_a", QVariant.Double))
        fields.append(QgsField("elev_b", QVariant.Double))
        fields.append(QgsField("diff", QVariant.Double))
        fields.append(QgsField("is_nodata", QVariant.Int))
        return fields

    @staticmethod
    def _write_point_feature(
        sink: QgsFeatureSink,
        fields: Optional[QgsFields],
        record: Dict[str, Any],
    ) -> bool:
        """Write a single sampled point record to the output sink.

        Args:
            sink (QgsFeatureSink): Destination sink created by QGIS Processing.
            fields (Optional[QgsFields]): Output field definitions for the sink.
            record (Dict[str, Any]): Sample point record with x/y and attribute values.

        Returns:
            bool: True when the feature was inserted into the sink.
        """
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
        elev_a = None if is_nodata else record.get("elev_a")
        elev_b = None if is_nodata else record.get("elev_b")
        diff = None if is_nodata else record.get("diff")

        feature.setAttributes(
            [
                str(record.get("feature_id", "")),
                elev_a,
                elev_b,
                diff,
                1 if is_nodata else 0,
            ]
        )
        if sink.addFeature(feature, QgsFeatureSink.FastInsert):
            return True
        # Some providers reject FastInsert for temporary outputs; retry default insertion.
        return sink.addFeature(feature)

