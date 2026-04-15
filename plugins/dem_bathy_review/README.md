# DEM Bathymetry Comparison Report

QGIS 3.44 Processing plugin that compares two DEM rasters within buffered channel centreline corridors and generates a polished, self-contained HTML report.

## MVP Features

- Per-feature zonal DEM comparison using regular sample points.
- Grouped per-feature reporting by optional centerline attribute field.
- Configurable buffer distance and sample spacing.
- Configurable absolute mean-bias significance threshold for conditional report messaging.
- Automatic CRS harmonization (default target is DEM A CRS).
- Optional feature ID field for report labels.
- NoData-aware calculations and reporting.
- Optional export of all sampled points to vector format.
- Embedded CSS HTML reporting with pure CSS sort views (no JavaScript).

## Processing Parameters

Algorithm 1: DEM Bathymetry Comparison Report

- DEM A raster.
- DEM B raster.
- Channel centrelines (LineString or MultiLineString only).
- Buffer distance.
- Sample spacing.
- Feature ID field (optional).
- Target CRS (optional; defaults silently to DEM A CRS).
- Output sample points (optional).
- Output HTML report (required).

Algorithm 2: DEM Bathymetry Grouped Comparison Report

- DEM A raster.
- DEM B raster.
- Channel centrelines (LineString or MultiLineString only).
- Buffer distance.
- Sample spacing.
- Feature ID field (optional).
- Group By field (optional). If blank, all features are grouped as `All Features`.
- Mean Bias Significance Threshold (absolute). A feature is flagged significant when `|bias| > threshold`.
- Vertical Units (meters, feet, or source units) to annotate difference/error values in the grouped report.
- Target CRS (optional; defaults silently to DEM A CRS).
- Output sample points (optional, with `group_value` attribute).
- Output HTML report (required).

If the input centreline layer has selected features, the algorithm processes only the selected subset.

## Outputs

- Standard algorithm HTML report with run metadata, summary statistics, and per-feature statistics.
- Grouped algorithm HTML report with one summary section per group value and per-feature rows under each group.
- Optional point vector output containing every generated sample point with:
  - feature_id
  - group_value (grouped algorithm)
  - elev_a
  - elev_b
  - diff
  - is_nodata

## Technical Notes

- Intermediate raster reprojection uses rasterio MemoryFile and is never written to disk.
- Zones with fewer than 3 valid sample points are skipped with warnings.
- Numeric report values are formatted to 4 decimal places.

## Dependencies

Install the dependencies listed in requirements.txt into the QGIS Python environment:

- geopandas
- jinja2
- numpy
- pyogrio
- rasterio
- shapely

## Packaging

From plugin root:

```bash
python scripts/package_plugin.py
```

This writes dist/dem_bathy_review.zip and excludes development-only directories.
