# examples/tbx_binary/pointtools/

**Source**: [Dan-Patterson/Tools_for_ArcGIS_Pro](https://github.com/Dan-Patterson/Tools_for_ArcGIS_Pro)  
**File**: `PointTools.tbx`  
**Format**: Binary ArcMap OLE Compound File (`.tbx`, magic: `D0 CF 11 E0`)  
**Size**: ~392 KB  
**ArcGIS License**: Basic–Standard

---

## What this toolbox contains

A collection of point geometry analysis and manipulation tools for ArcMap / ArcGIS
Desktop, covering nearest neighbour analysis, point-in-polygon testing, random
point generation, and coordinate transformations.

---

## Why this example is important

This is the only format that **cannot** be opened without specialised tooling.
It uses Microsoft's OLE Compound Document format — the same binary container as
`.doc` and `.xls` files from the Office 97–2003 era.

QgisPortAgent handles it via `research/tbx_parser.py`, a standalone reverse-
engineered parser with **zero ArcGIS / COM / Windows dependencies**.

---

## Migration scenarios exercised

| Scenario | QgisPortAgent behaviour |
|---|---|
| Binary OLE detection (Phase 0 pre-flight) | Reads first 4 bytes; confirms `D0 CF 11 E0` |
| `research/tbx_parser.py` fast-path (Phase 1.2) | `parse_tbx()` extracts tool names, parameters, GP types |
| GP_TYPE_MAP crosswalk (143 entries) | Maps `GPFeatureLayer` → `ParameterFeatureSource` etc. |
| ModelBuilder tools (type 1/2) | No execute logic available → scaffold + TODO stubs |
| Script tools (type 3) | `script_path` field extracted → proceed to Phase 1.5 |
| `__parse_error_N__` parameters | Flagged for manual review in migration report |

## Expected confidence range

`0.65–0.85` depending on whether tools are ModelBuilder (lower) or Script tools (higher).

## Quick start

```
/migrate_tool "examples/tbx_binary/pointtools/PointTools.tbx"
```

---

## Technical notes

If `tbx_parser.py` cannot decode a tool, QgisPortAgent falls back to the
`tbx-pyt-translator` path (requires ArcGIS Desktop 10.1+ on Windows) or
manual ModelBuilder export.  See the agent instructions for full fallback
documentation.
