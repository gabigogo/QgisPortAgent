# Stream Segmenter — User Guide

## Overview

**Stream Segmenter** is a QGIS 3.44 Processing algorithm that divides stream
centerline features into equal-length intervals measured outward from the
**downstream endpoint** of each feature.

Each output segment receives three new attribute fields:

| Field | Type | Description | Example |
|---|---|---|---|
| `seg_num` | Integer | Segment index, 1 = most downstream | `1` |
| `mile_range` | String | Range label | `"0-1 mi"` |
| `stream_seg_id` | String | Unique stream–segment identifier | `"Bear_Creek_mile_01"` |

---

## Installation

1. Copy the `stream_segmenter/` folder into your QGIS plugins directory, or
   install from the `.zip` in `dist/` via **Plugins → Manage and Install
   Plugins → Install from ZIP**.
2. Enable the plugin in the Plugin Manager.
3. The algorithm appears in the Processing Toolbox under **Stream Tools →
   Stream Segmenter**.

---

## Parameters

### Input stream centerline layer
Any OGR-readable vector source containing **LineString** or **MultiLineString**
features.  QGIS in-memory layers are also supported.

> **Downstream convention:** The **last vertex** of each feature (or the last
> vertex of the last part for MultiLineString) is treated as the downstream
> endpoint.  Segment numbering and range labels originate from that point.

### Stream name field
The attribute field whose value identifies each stream.  String and integer
field types are both accepted.  The value is sanitized for use in the
`stream_seg_id` field: surrounding whitespace is stripped and interior spaces
are replaced with underscores (e.g., `"Bear Creek"` → `"Bear_Creek"`).

### Process selected features only
When **checked**, only features currently selected in the input layer are
processed.  If the layer has no selection and this option is checked, all
features are processed with a warning.  Default: **unchecked**.

### Segment length
Distance of each segment in the chosen unit (miles or kilometres).
Default: **1.0**.  Minimum: 0.01.

The last segment of each feature will typically be shorter than the specified
length (the "remainder" of the total channel length).

### Use kilometres instead of miles
When **checked**, the segment length is interpreted as kilometres and all
labels use the `km` suffix.  The `stream_seg_id` field uses `_km_` instead of
`_mile_`.  Default: **unchecked** (miles).

### Preserve source attributes in output
When **checked**, all attribute fields from the input layer are copied to every
output segment row before the three new fields.  If a source field shares a
name with one of the new fields (`seg_num`, `mile_range`, `stream_seg_id`), a
`_src` suffix is appended to the copy.  Default: **unchecked**.

### Segmented streams (output)
Output vector layer (LineString) with the CRS inherited from the input.

---

## Output field details

### `stream_seg_id` format

```
<stream_name><unit_suffix><NN>
```

- `<stream_name>` — sanitized stream name (spaces → underscores).
- `<unit_suffix>` — `_mile_` for miles, `_km_` for kilometres.
- `<NN>` — zero-padded integer, minimum 2 digits, expanding to 3+ when the
  total segment count per feature exceeds 99.

**Examples:**

| Stream name | Length | Segment length | First ID | Last ID |
|---|---|---|---|---|
| Bear Creek | 5 mi | 1 mi | `Bear_Creek_mile_01` | `Bear_Creek_mile_05` |
| Brays Bayou | 25 mi | 5 mi | `Brays_Bayou_mile_01` | `Brays_Bayou_mile_05` |
| Test Channel | 3 km | 1 km | `Test_Channel_km_01` | `Test_Channel_km_03` |

---

## MultiLineString handling

Features with **MultiLineString** geometry are handled as follows:

1. `shapely.ops.linemerge` attempts to assemble the parts into a single
   connected chain.
2. If the merge succeeds, the resulting line is oriented from the original
   downstream endpoint (last coord of last part) and segmented normally.
3. If the parts are **topologically disconnected** (linemerge cannot resolve a
   single chain), the feature is **skipped** with a non-fatal warning in the
   log.  Inspect disconnected features and repair topology before re-running.

---

## Length measurement

Segment boundaries are computed using **geodetic length** via
`QgsDistanceArea`.  The QGIS project ellipsoid (defaulting to GRS80) is used,
so segment lengths are accurate in real-world miles/km regardless of the input
layer's projected CRS.

> **Tip:** For best results, use an input layer in a projected CRS whose linear
> units are metres (e.g., UTM or State Plane Meters).  If an equal-area or
> geographic CRS is detected, a warning is pushed to the log.

---

## Troubleshooting

| Symptom | Likely cause | Resolution |
|---|---|---|
| Feature skipped — "disconnected" warning | MultiLineString parts do not share endpoints | Repair geometry topology in the input layer |
| Segments numbered from the wrong end | Input line is digitized upstream-to-downstream | Reverse the line geometry (Vector → Geometry Tools → Reverse Line Direction) |
| Segment count differs from expected | Length measured geodetically vs. planar | Expected at small scales with geographic CRS; use a projected input |
| `stream_seg_id` shows `feature_<id>` | Stream name field contains NULL or empty values | Populate the name field before running |

---

## Example — QGIS Python Console

```python
import processing

result = processing.run(
    "stream_segmenter:stream_segmenter",
    {
        "INPUT": "/data/channels/hcfcd_centerlines.gpkg|layername=centerlines",
        "NAME_FIELD": "unit_number",
        "SELECTED_ONLY": False,
        "SEGMENT_LENGTH": 1.0,
        "USE_KM": False,
        "PRESERVE_ATTRS": True,
        "OUTPUT": "TEMPORARY_OUTPUT",
    },
)

layer = result["OUTPUT"]
print(f"Created {layer.featureCount()} segments")
```
