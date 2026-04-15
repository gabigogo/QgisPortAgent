"""Reproduce and validate Batch Stream Segmenter using the posted QGIS log parameters.

Run this from a QGIS Python environment (QGIS Python Console, or OSGeo4W shell with QGIS env):

    python scripts/debug_batch_stream_segmenter_from_log.py

The script:
1. Runs the batch algorithm with parameters copied from the provided log.
2. Scans all produced *_segmented.gpkg layers.
3. Verifies every output layer contains required fields.
4. Verifies every segment has valid attribution values.
5. Fails with a non-zero exit if validation fails.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from qgis.core import QgsFeatureRequest, QgsVectorLayer


DEFAULT_INPUT_FOLDER = r"D:\02_projects\p-wpt-2\gdbs\draft\order"
DEFAULT_OUTPUT_FOLDER = r"D:\02_projects\p-wpt-2\gdbs\draft\miles"
DEFAULT_FILE_FILTER = "*.gpkg *.shp *.geojson *.fgb"
DEFAULT_NAME_FIELD = "UnitNo"
DEFAULT_SEGMENT_LENGTH = 1.0
DEFAULT_USE_KM = False
DEFAULT_PRESERVE_ATTRS = True

RANGE_RE = re.compile(r"^\d+(?:\.\d+)?-\d+(?:\.\d+)?\s+(mi|km)$")


def _collect_input_files(input_folder: Path, file_filter: str) -> List[Path]:
    """Collect input files using the same style of space-separated globs as the algorithm."""
    patterns = [p.strip() for p in file_filter.split() if p.strip()]
    if not patterns:
        patterns = ["*.gpkg", "*.shp", "*.geojson", "*.fgb"]

    files: List[Path] = []
    seen = set()
    for pattern in patterns:
        for p in sorted(input_folder.glob(pattern)):
            key = p.resolve().as_posix().lower()
            if key not in seen and p.is_file():
                files.append(p)
                seen.add(key)
    return files


def _output_path_for_input(output_folder: Path, in_path: Path) -> Path:
    return output_folder / f"{in_path.stem}_segmented.gpkg"


def _validate_output_layer(out_path: Path, use_km: bool) -> Tuple[int, List[str]]:
    """Return (segment_count, validation_errors) for one output layer."""
    errors: List[str] = []

    layer = QgsVectorLayer(str(out_path), out_path.stem, "ogr")
    if not layer.isValid():
        return 0, [f"Invalid output layer: {out_path}"]

    field_names = [f.name() for f in layer.fields()]
    required = ["seg_num", "mile_range", "stream_seg_id"]
    for req in required:
        if req not in field_names:
            errors.append(f"Missing required field '{req}' in {out_path.name}")

    if errors:
        return 0, errors

    unit_suffix = "km" if use_km else "mi"
    seg_count = 0

    for feat in layer.getFeatures(QgsFeatureRequest()):
        seg_count += 1

        seg_num = feat["seg_num"]
        mile_range = feat["mile_range"]
        stream_seg_id = feat["stream_seg_id"]

        if seg_num is None or int(seg_num) < 1:
            errors.append(
                f"{out_path.name}: feature {feat.id()} has invalid seg_num={seg_num!r}"
            )

        if mile_range is None or not RANGE_RE.match(str(mile_range)):
            errors.append(
                f"{out_path.name}: feature {feat.id()} has invalid mile_range={mile_range!r}"
            )
        elif not str(mile_range).endswith(f" {unit_suffix}"):
            errors.append(
                f"{out_path.name}: feature {feat.id()} has wrong unit in mile_range={mile_range!r}"
            )

        if stream_seg_id is None or not str(stream_seg_id).strip():
            errors.append(
                f"{out_path.name}: feature {feat.id()} has empty stream_seg_id"
            )

    if seg_count == 0:
        errors.append(f"{out_path.name}: wrote zero segments")

    return seg_count, errors


def run_debug(args: argparse.Namespace) -> int:
    try:
        import processing
    except Exception as exc:  # pragma: no cover - runtime guard
        print("ERROR: Could not import QGIS processing module.")
        print(f"DETAIL: {exc}")
        return 2

    input_folder = Path(args.input_folder)
    output_folder = Path(args.output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    input_files = _collect_input_files(input_folder, args.file_filter)
    print(f"Discovered {len(input_files)} input file(s) using filter: {args.file_filter}")

    if args.expected_input_count is not None and len(input_files) != args.expected_input_count:
        print(
            f"ERROR: Expected {args.expected_input_count} input files but found {len(input_files)}"
        )
        return 1

    params: Dict[str, object] = {
        "INPUT_FOLDER": str(input_folder),
        "FILE_FILTER": args.file_filter,
        "NAME_FIELD": args.name_field,
        "OUTPUT_FOLDER": str(output_folder),
        "PRESERVE_ATTRS": bool(args.preserve_attrs),
        "SEGMENT_LENGTH": float(args.segment_length),
        "USE_KM": bool(args.use_km),
    }

    print("Running algorithm stream_segmenter:batch_stream_segmenter ...")
    result = processing.run("stream_segmenter:batch_stream_segmenter", params)
    print(f"Processing result: {result}")

    total_segments = 0
    all_errors: List[str] = []

    for in_path in input_files:
        out_path = _output_path_for_input(output_folder, in_path)
        if not out_path.exists():
            all_errors.append(f"Missing output file: {out_path}")
            continue

        seg_count, errors = _validate_output_layer(out_path, use_km=bool(args.use_km))
        total_segments += seg_count
        all_errors.extend(errors)

    print(f"Validated {len(input_files)} output file(s).")
    print(f"Total written segments found: {total_segments}")

    if all_errors:
        print("\nVALIDATION FAILED")
        for err in all_errors[:200]:
            print(f"  - {err}")
        if len(all_errors) > 200:
            print(f"  ... {len(all_errors) - 200} more errors")
        return 1

    print("\nVALIDATION PASSED: all outputs are split and attributed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run and validate Batch Stream Segmenter using parameters copied "
            "from the provided QGIS failure log."
        )
    )
    parser.add_argument("--input-folder", default=DEFAULT_INPUT_FOLDER)
    parser.add_argument("--output-folder", default=DEFAULT_OUTPUT_FOLDER)
    parser.add_argument("--file-filter", default=DEFAULT_FILE_FILTER)
    parser.add_argument("--name-field", default=DEFAULT_NAME_FIELD)
    parser.add_argument("--segment-length", type=float, default=DEFAULT_SEGMENT_LENGTH)
    parser.add_argument("--use-km", action="store_true", default=DEFAULT_USE_KM)
    parser.add_argument("--preserve-attrs", action="store_true", default=DEFAULT_PRESERVE_ATTRS)
    parser.add_argument("--expected-input-count", type=int, default=23)
    return parser


if __name__ == "__main__":
    parser = build_parser()
    exit_code = run_debug(parser.parse_args())
    raise SystemExit(exit_code)
