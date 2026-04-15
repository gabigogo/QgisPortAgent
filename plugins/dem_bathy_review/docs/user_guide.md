# DEM Bathymetry Comparison Report - User Guide

## Overview

This Processing algorithm compares two DEM rasters across buffered channel centreline corridors to quantify terrain and bathymetric change at feature scale. For each centreline feature, a buffer polygon is created, sample points are generated at fixed spacing, both DEMs are sampled, and difference statistics are calculated.

The plugin now provides two related algorithms:

- `DEM Bathymetry Comparison Report`: baseline per-feature report.
- `DEM Bathymetry Grouped Comparison Report`: grouped report with per-group summaries and significance flags.

Difference convention:

$\Delta z = z_A - z_B$

Where:

- $z_A$ is elevation sampled from DEM A.
- $z_B$ is elevation sampled from DEM B.
- Positive values indicate DEM A elevations greater than DEM B.
- Negative values indicate DEM A elevations lower than DEM B.

## Inputs and Outputs

### Inputs

- DEM A raster layer (Survey A).
- DEM B raster layer (Survey B).
- Channel centrelines vector layer (LineString or MultiLineString only).
- Buffer distance.
- Sample spacing.
- Optional feature ID field.
- Optional target CRS.

Grouped algorithm adds:

- Optional `Group By Field` from the centerline layer.
- `Mean Bias Significance Threshold (absolute)`.
- `Vertical Units` option to label reported elevation-difference metrics (meters, feet, or source units).

If the centreline input layer has selected features, only selected features are processed.

### Outputs

- HTML report file (`.html`).
- Optional sample point output (`.gpkg`, `.shp`, or other OGR-supported extension).

Sample point output attributes:

- `feature_id`
- `group_value` (grouped algorithm output)
- `elev_a`
- `elev_b`
- `diff`
- `is_nodata`

## Workflow

1. Validate input layers and numeric parameters.
2. Determine target CRS (user-selected or DEM A CRS by default).
3. Reproject both DEMs to a shared in-memory grid.
4. Reproject centerlines to target CRS.
5. Buffer each centreline using flat end-caps and rounded joins.
6. Generate fixed-spacing sample points inside each zone.
7. Sample both DEMs for each point.
8. Classify NoData points where either DEM value is NoData.
9. Compute per-feature statistics from valid points only.
10. Compute overall summary statistics.
11. Write HTML report and optional sample points layer.

## Statistics

Per-feature metrics:

- `nodata_count`
- `max_diff`
- `min_diff`
- `mean_diff`
- `std_dev`
- `bias` (mean signed error)
- `rmse`

For the grouped report's per-feature table, `mean_diff` is omitted because `bias` is the same value; only `bias` is shown.

RMSE is computed as:

$$
\text{RMSE} = \sqrt{\frac{1}{n}\sum_{i=1}^{n}(d_i)^2}
$$

where $d_i$ are valid per-point differences.

Additional summary statistics are reported across all processed features:

- Overall minimum and maximum difference.
- RMSE minimum, maximum, and mean.
- Bias minimum, maximum, and mean.
- Standard deviation minimum, maximum, and mean.

For the grouped algorithm, each unique group value receives its own summary block where metrics are computed from all valid sample-point differences in that group (point-weighted aggregation).

### Grouped Significance Rule

In grouped reports, each feature is evaluated with:

$$
|\text{bias}| > T
$$

where $T$ is the user-provided absolute mean-bias threshold.

- If true, the feature is marked significant.
- If at least one feature in a group is significant, the group section displays a warning banner.
- The report also shows flagged feature count and flagged ratio per group.

## NoData Behavior

- A sample is marked NoData if either DEM returns NoData.
- NoData samples are written to the optional output points layer with `is_nodata = True` and numeric values set to NaN.
- NoData samples are excluded from statistics.
- `nodata_count` is reported per feature.

## Important Constraints

- Intermediate reprojected rasters are in-memory only.
- At least 3 valid points are required to compute per-feature statistics.
- Features with fewer than 3 valid points are skipped with a warning.
- Report numeric values are formatted to 4 decimal places.
- Report sorting does not use JavaScript.

Grouped report sections are rendered without JavaScript and include one per-group summary table followed by the group's feature-level statistics.

## In-Tool Help

The Processing algorithm includes extended help text directly in QGIS with:

- Input assumptions and validation expectations.
- Stepwise methodology.
- Interpretation guidance for metrics.
- Typical failure states and corrective actions.
- Example usage guidance for repeatable runs.

## Troubleshooting

- If processing fails early, verify all input layers are valid and readable.
- If no feature statistics are produced, increase buffer distance or reduce spacing to produce more valid sample points.
- If point export fails, verify write permissions and destination folder existence.
- If output differences look implausible, confirm both DEMs refer to the same vertical datum and time frame.
- If spacing is too coarse for narrow channels, reduce sample spacing or increase buffer distance.
