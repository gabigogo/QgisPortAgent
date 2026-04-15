# Stream Segmenter

A QGIS 3.44 Processing plugin that segments stream centerline features
(LineString / MultiLineString) into equal-length intervals measured from the
**downstream endpoint** outward.

Each output segment receives three new attribute fields:

| Field | Example |
|---|---|
| `seg_num` | `1` (most downstream) |
| `mile_range` | `"0-1 mi"` |
| `stream_seg_id` | `"Bear_Creek_mile_01"` |

---

## Features

- Downstream-anchored segmentation — segment 1 always starts at the channel mouth
- MultiLineString support via `shapely.ops.linemerge`
- Configurable segment length (default 1.0) with miles / kilometres toggle
- Selected-features-only mode for iterative workflows
- Optional preservation of all source attributes
- Geodetic length measurement via `QgsDistanceArea` (accurate regardless of input CRS)
- Progress reporting and mid-run cancellation support

---

## Requirements

| Dependency | Version |
|---|---|
| QGIS | 3.44 LTR |
| Python | 3.12+ |
| shapely | ≥ 2.0.0 |

`shapely` is bundled with QGIS 3.44.  No additional installation is required.

---

## Installation

**From zip (recommended):**

1. Run `python scripts/package_plugin.py` to create `dist/stream_segmenter.zip`.
2. In QGIS: **Plugins → Manage and Install Plugins → Install from ZIP**.
3. Enable the plugin in the Plugin Manager.

**From source:**

Copy the `stream_segmenter/` directory to your QGIS plugins folder:

```
Windows:  %APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\
Linux:    ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/
macOS:    ~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/
```

---

## Usage

Find the algorithm in the Processing Toolbox:

**Stream Tools → Stream Segmenter**

See [docs/user_guide.md](docs/user_guide.md) for full parameter documentation,
examples, and troubleshooting.

---

## Downstream Convention

The **last vertex** of a LineString (or the last vertex of the last part of a
MultiLineString) is treated as the downstream (outlet) endpoint.
Segment 1 and range label `"0-1 mi"` always originate from that point.

To verify or fix line orientation use **Vector → Geometry Tools → Reverse Line
Direction** on any features that appear to be digitized the wrong way.

---

## Tests

```bash
# Run pure-Python tests (no QGIS required):
pytest stream_segmenter/tests/ -v -m "not qgis"

# Run all tests including QGIS integration (requires qgis_testing environment):
pytest stream_segmenter/tests/ -v
```

---

## Project structure

```
stream_segmenter/
├── metadata.txt
├── __init__.py
├── stream_segmenter_plugin.py
├── requirements.txt
├── processing_provider/
│   ├── __init__.py
│   ├── provider.py
│   └── algorithms/
│       ├── __init__.py
│       └── stream_segmenter_algorithm.py
├── utils/
│   └── __init__.py
├── resources/
│   └── resources.qrc
├── tests/
│   ├── conftest.py
│   └── test_stream_segmenter.py
├── docs/
│   └── user_guide.md
└── scripts/
    └── package_plugin.py
```

---

## License

GPL-2.0-or-later — see [LICENSE](LICENSE).

## Author

Gabriela Govea — gabriela.govea@atkinsrealis.com — AtkinsRealis
