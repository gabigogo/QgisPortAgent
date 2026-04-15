"""Run stream_segmenter plugin algorithms natively via PyQGIS.

Steps:
1) batch_stream_segmenter -> 1 mile segments
2) batch_stream_segment_filter -> first 5 miles (mile_range start < 5)
3) add/update channel field from UnitNo
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsApplication,
    QgsField,
    QgsProcessingFeedback,
    QgsVectorLayer,
)


REPO_ROOT = Path(r"D:\01_dev\a-Arc2Qgis\QgisPortAgent")
INPUT_FOLDER = Path(r"D:\02_projects\p-wpt-2\gdbs\lsmu\in_list")
MILES_FOLDER = Path(r"D:\02_projects\p-wpt-2\gdbs\lsmu\miles")
FILTERED_FOLDER = Path(r"D:\02_projects\p-wpt-2\gdbs\lsmu\miles-filtered")


def cleanup_previous_outputs(miles_folder: Path, filtered_folder: Path) -> tuple[int, int]:
    """Remove prior plugin-produced files so batch writers can create fresh outputs."""
    removed_miles = 0
    removed_filtered = 0

    miles_folder.mkdir(parents=True, exist_ok=True)
    filtered_folder.mkdir(parents=True, exist_ok=True)

    for p in miles_folder.glob("*_segmented.gpkg"):
        try:
            p.unlink()
            removed_miles += 1
        except OSError:
            pass

    for p in filtered_folder.glob("*_filtered.gpkg"):
        try:
            p.unlink()
            removed_filtered += 1
        except OSError:
            pass

    return removed_miles, removed_filtered


def _channel_from_unitno(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    return s.split("-")[0].split("_")[0]


def _find_field_idx(layer: QgsVectorLayer, target: str) -> int:
    target_lower = target.lower()
    for i, fld in enumerate(layer.fields()):
        if fld.name().lower() == target_lower:
            return i
    return -1


def add_channel_field_for_folder(folder: Path) -> tuple[int, int, int]:
    """Add/update channel field from UnitNo for each GPKG in folder.

    Returns:
        tuple: (updated_files, skipped_files, failed_files)
    """
    updated_files = 0
    skipped_files = 0
    failed_files = 0

    for gpkg in sorted(folder.glob("*.gpkg")):
        layer = QgsVectorLayer(str(gpkg), gpkg.stem, "ogr")
        if not layer.isValid():
            print(f"[channel] SKIP invalid layer: {gpkg.name}")
            skipped_files += 1
            continue

        unit_idx = _find_field_idx(layer, "UnitNo")
        if unit_idx < 0:
            print(f"[channel] SKIP no UnitNo field: {gpkg.name}")
            skipped_files += 1
            continue

        channel_idx = _find_field_idx(layer, "channel")
        if channel_idx < 0:
            ok = layer.dataProvider().addAttributes(
                [QgsField("channel", QVariant.String, "String", 32, 0)]
            )
            layer.updateFields()
            channel_idx = _find_field_idx(layer, "channel")
            if (not ok) or channel_idx < 0:
                print(f"[channel] FAIL add field: {gpkg.name}")
                failed_files += 1
                continue

        if not layer.startEditing():
            print(f"[channel] FAIL start edit: {gpkg.name}")
            failed_files += 1
            continue

        changed = 0
        for feat in layer.getFeatures():
            channel = _channel_from_unitno(feat[unit_idx])
            if layer.changeAttributeValue(feat.id(), channel_idx, channel):
                changed += 1

        if layer.commitChanges():
            print(f"[channel] OK {gpkg.name}: updated {changed} feature(s)")
            updated_files += 1
        else:
            layer.rollBack()
            print(f"[channel] FAIL commit: {gpkg.name}")
            failed_files += 1

    return updated_files, skipped_files, failed_files


def main() -> int:
    # Ensure workspace plugin package is importable.
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    # Ensure Processing plugin is importable in standalone mode.
    qgis_plugins_path = Path(r"C:\OSGeo4W\apps\qgis-qt6\python\plugins")
    if str(qgis_plugins_path) not in sys.path:
        sys.path.append(str(qgis_plugins_path))

    qgs = QgsApplication([], False)
    qgs.initQgis()

    try:
        from processing.core.Processing import Processing
        import processing

        from stream_segmenter.processing_provider.provider import (
            StreamSegmenterProvider,
        )

        Processing.initialize()

        provider = StreamSegmenterProvider()
        QgsApplication.processingRegistry().addProvider(provider)

        feedback = QgsProcessingFeedback()

        removed_miles, removed_filtered = cleanup_previous_outputs(
            MILES_FOLDER, FILTERED_FOLDER
        )
        print(
            f"Cleanup complete: removed {removed_miles} segmented file(s) and "
            f"{removed_filtered} filtered file(s)."
        )

        # 1) Batch segmenter (plugin algorithm)
        seg_params = {
            "INPUT_FOLDER": str(INPUT_FOLDER),
            "FILE_FILTER": "*.gpkg",
            "NAME_FIELD": "UnitNo",
            "SEGMENT_LENGTH": 1.0,
            "USE_KM": False,
            "PRESERVE_ATTRS": True,
            "OUTPUT_FOLDER": str(MILES_FOLDER),
        }
        print("Running stream_segmenter:batch_stream_segmenter ...")
        processing.run("stream_segmenter:batch_stream_segmenter", seg_params, feedback=feedback)

        # 2) Batch filter first 5 miles (plugin algorithm)
        flt_params = {
            "INPUT_FOLDER": str(MILES_FOLDER),
            "FILE_FILTER": "*_segmented.gpkg",
            "FILTER_MODE": 1,  # MODE_BY_DISTANCE
            "N_SEGMENTS": 5,
            "MAX_DISTANCE": 5.0,
            "OUTPUT_FOLDER": str(FILTERED_FOLDER),
        }
        print("Running stream_segmenter:batch_stream_segment_filter ...")
        processing.run("stream_segmenter:batch_stream_segment_filter", flt_params, feedback=feedback)

        # 3) Add channel field from UnitNo on filtered outputs.
        print("Adding channel field from UnitNo on filtered outputs ...")
        upd, skp, fail = add_channel_field_for_folder(FILTERED_FOLDER)
        print(f"channel summary: updated_files={upd}, skipped_files={skp}, failed_files={fail}")

        # Optional: also add/update channel on segmented outputs.
        print("Adding channel field from UnitNo on segmented outputs ...")
        upd2, skp2, fail2 = add_channel_field_for_folder(MILES_FOLDER)
        print(f"channel summary (segmented): updated_files={upd2}, skipped_files={skp2}, failed_files={fail2}")

        print("Pipeline complete.")
        print(f"miles folder: {MILES_FOLDER}")
        print(f"filtered folder: {FILTERED_FOLDER}")
        return 0

    except Exception:
        traceback.print_exc()
        return 1
    finally:
        qgs.exitQgis()


if __name__ == "__main__":
    raise SystemExit(main())
