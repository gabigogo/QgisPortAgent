"""Populate `channel` in GeoPackages from `stream_seg_id`.

For each .gpkg in an input folder, this script reads all feature layers,
adds or overwrites a `channel` column, and sets:

    channel = prefix before "_mile" in stream_seg_id

If `_mile` is not present, the full `stream_seg_id` is used.
If `stream_seg_id` is null, `channel` is set to null.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Tuple

import fiona
import geopandas as gpd
import pandas as pd


def derive_channel(series: pd.Series) -> pd.Series:
    """Return channel values parsed from stream segment ids."""
    text = series.astype("string")
    channel = text.str.extract(r"^(.*?)(?=_mile)", expand=False)
    channel = channel.fillna(text)
    channel = channel.where(~text.isna(), pd.NA)
    return channel


def process_gpkg(gpkg_path: Path) -> Tuple[int, int]:
    """Process all layers in one GeoPackage.

    Returns:
        tuple[int, int]: (layers_updated, populated_rows)
    """
    layers = fiona.listlayers(gpkg_path)
    if not layers:
        return 0, 0

    tmp_path = gpkg_path.with_suffix(".tmp.gpkg")
    if tmp_path.exists():
        tmp_path.unlink()

    layers_updated = 0
    populated_rows = 0

    try:
        for idx, layer_name in enumerate(layers):
            gdf = gpd.read_file(gpkg_path, layer=layer_name)

            if "stream_seg_id" in gdf.columns:
                gdf["channel"] = derive_channel(gdf["stream_seg_id"])
                layers_updated += 1
                populated_rows += int(gdf["channel"].notna().sum())

            mode = "w" if idx == 0 else "a"
            gdf.to_file(tmp_path, layer=layer_name, driver="GPKG", mode=mode)

        os.replace(tmp_path, gpkg_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    return layers_updated, populated_rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add/overwrite channel field parsed from stream_seg_id in GeoPackages."
    )
    parser.add_argument(
        "--folder",
        default=r"D:\02_projects\p-wpt-2\gdbs\draft\miles",
        help="Folder containing .gpkg files.",
    )
    args = parser.parse_args()

    root = Path(args.folder)
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Folder not found: {root}")

    gpkg_files = sorted(root.glob("*.gpkg"))
    if not gpkg_files:
        print(f"No .gpkg files found in: {root}")
        return

    total_files = 0
    total_layers = 0
    total_rows = 0

    for gpkg in gpkg_files:
        layers_updated, populated_rows = process_gpkg(gpkg)
        total_files += 1
        total_layers += layers_updated
        total_rows += populated_rows
        print(
            f"UPDATED {gpkg.name} | layers_updated={layers_updated} | "
            f"channel_non_null_rows={populated_rows}"
        )

    print("---")
    print(f"Processed files: {total_files}")
    print(f"Layers updated: {total_layers}")
    print(f"Total non-null channel rows: {total_rows}")


if __name__ == "__main__":
    main()
