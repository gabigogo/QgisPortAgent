# examples/py/nrcs_avg_slope/

**Source**: [USDA-NRCS/SUPPORT](https://github.com/USDA-NRCS/SUPPORT)  
**File**: `Calculate_Average_Slope.py`  
**ArcGIS License**: Basic–Standard  
**Size**: ~6 KB

---

## What this script does

Calculates the average slope of a land parcel from a DEM using
`arcpy.ddd.SurfaceParameters` (3D Analyst) or `arcpy.sa.Slope` (Spatial Analyst).
Writes the average slope value to a feature class attribute field.

## Migration scenarios exercised

| Scenario | QgisPortAgent behaviour |
|---|---|
| `arcpy.sa.Slope` | Crosswalks to `native:slope` (QGIS native) or rasterio + numpy |
| `arcpy.da.SearchCursor` | Rewritten as `layer.getFeatures()` or geopandas `read_file()` |
| Zonal statistics pattern | Crosswalks to `native:zonalstatisticsfb` |
| `arcpy.management.AddField` + `UpdateCursor` | Vectorised geopandas column assignment |

## Expected confidence range

`0.88–0.95` — Core operations map cleanly to QGIS native algorithms.

## Quick start

```
/migrate_tool examples/py/nrcs_avg_slope/Calculate_Average_Slope.py
```
