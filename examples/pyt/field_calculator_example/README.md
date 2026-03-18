# examples/pyt/field_calculator_example/

**Source**: Synthetic — hand-crafted example  
**File**: `FieldCalculatorTools.pyt`  
**Format**: Python Toolbox (`.pyt`)  
**ArcGIS License**: Basic (AddAreaField), Basic (NormalizeField)

---

## What this toolbox contains

Two tools deliberately written with legacy Python 2.7 patterns and row-wise
ArcPy cursor loops.  It is designed to trigger every migration scanner in
QgisPortAgent's Phase 0.2 and Phase 4 checks.

### Tool 1 — AddAreaField
Adds a `DOUBLE` field and populates it with each polygon's planar area.

### Tool 2 — NormalizeField
Rescales a numeric field to the [0, 1] range using min-max normalisation.

---

## Migration scenarios exercised

| Pattern | Phase | QgisPortAgent behaviour |
|---|---|---|
| `print "..."` (no parens) | Phase 0.2 | Rewritten as `print(...)` |
| `basestring` type check | Phase 0.2 | Replaced with `str` |
| `.iteritems()` | Phase 0.2 | Replaced with `.items()` |
| `arcpy.da.UpdateCursor` row-wise loop | Phase 4 | Vectorised → `gdf[field] = gdf[src]` |
| `arcpy.da.SearchCursor` row-by-row min/max | Phase 4 | Vectorised → `gdf[src].min()` / `.max()` |
| `.pyt` class structure | Phase 1.4 | AST-parsed; `getParameterInfo()` → `initAlgorithm()` |

## Expected confidence range

`0.90–0.97` — Operations are simple column assignments with no Advanced-license
dependencies; vectorisation is mechanical.

## Quick start

```
/migrate_tool examples/pyt/field_calculator_example/FieldCalculatorTools.pyt
```
