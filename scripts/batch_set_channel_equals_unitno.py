"""Batch set channel field equal to UnitNo for all GeoPackages in folder(s)."""

from __future__ import annotations

import argparse
from pathlib import Path

from qgis.PyQt.QtCore import QVariant
from qgis.core import QgsApplication, QgsField, QgsVectorLayer


def _find_field_idx(layer: QgsVectorLayer, name: str) -> int:
    target = name.lower()
    for i, fld in enumerate(layer.fields()):
        if fld.name().lower() == target:
            return i
    return -1


def update_folder(folder: Path) -> tuple[int, int, int]:
    updated = 0
    skipped = 0
    failed = 0

    gpkg_files = sorted(folder.glob("*.gpkg"))
    if not gpkg_files:
        print(f"[info] No .gpkg files found in {folder}")
        return updated, skipped, failed

    for gpkg in gpkg_files:
        layer = QgsVectorLayer(str(gpkg), gpkg.stem, "ogr")
        if not layer.isValid():
            print(f"[skip] invalid layer: {gpkg.name}")
            skipped += 1
            continue

        unit_idx = _find_field_idx(layer, "UnitNo")
        if unit_idx < 0:
            print(f"[skip] no UnitNo field: {gpkg.name}")
            skipped += 1
            continue

        channel_idx = _find_field_idx(layer, "channel")
        if channel_idx < 0:
            ok = layer.dataProvider().addAttributes(
                [QgsField("channel", QVariant.String, "String", 64, 0)]
            )
            layer.updateFields()
            channel_idx = _find_field_idx(layer, "channel")
            if (not ok) or channel_idx < 0:
                print(f"[fail] could not add channel field: {gpkg.name}")
                failed += 1
                continue

        if not layer.startEditing():
            print(f"[fail] could not start editing: {gpkg.name}")
            failed += 1
            continue

        change_count = 0
        for feat in layer.getFeatures():
            unit_val = feat[unit_idx]
            channel_val = "" if unit_val is None else str(unit_val)
            if layer.changeAttributeValue(feat.id(), channel_idx, channel_val):
                change_count += 1

        if layer.commitChanges():
            print(f"[ok] {gpkg.name}: updated {change_count} feature(s)")
            updated += 1
        else:
            layer.rollBack()
            print(f"[fail] commit failed: {gpkg.name}")
            failed += 1

    return updated, skipped, failed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Set channel field equal to UnitNo for GeoPackages in folder(s)."
    )
    parser.add_argument(
        "folders",
        nargs="+",
        help="One or more folders containing .gpkg files",
    )
    args = parser.parse_args()

    qgs = QgsApplication([], False)
    qgs.initQgis()

    try:
        total_updated = 0
        total_skipped = 0
        total_failed = 0

        for folder_str in args.folders:
            folder = Path(folder_str)
            if not folder.is_dir():
                print(f"[skip] not a directory: {folder}")
                total_skipped += 1
                continue

            print(f"\nProcessing folder: {folder}")
            u, s, f = update_folder(folder)
            total_updated += u
            total_skipped += s
            total_failed += f

        print("\nDone")
        print(f"updated_files={total_updated}")
        print(f"skipped_files={total_skipped}")
        print(f"failed_files={total_failed}")
        return 0 if total_failed == 0 else 1
    finally:
        qgs.exitQgis()


if __name__ == "__main__":
    raise SystemExit(main())
