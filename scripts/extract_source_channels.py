"""Extract the 'Source Channel' feature class from every File Geodatabase in a
folder and write one GeoJSON FeatureCollection per GDB to an output directory.

Usage
-----
    python extract_source_channels.py                      # uses built-in defaults
    python extract_source_channels.py --input  D:/path/to/gdbs  --output D:/path/out
    python extract_source_channels.py --layer "My Layer"   # override layer name

Dependencies
------------
    pip install geopandas pyogrio
    (pyogrio is the preferred engine; fiona is used as an automatic fallback)
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_INPUT  = r"D:\02_projects\p-wpt-2\gdbs\draft"
DEFAULT_OUTPUT = r"D:\02_projects\p-wpt-2\gdbs\draft\geojson"
DEFAULT_LAYER  = "Source_Channels"


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_gdbs(folder: Path) -> list[Path]:
    """Return every *.gdb directory directly under *folder* (non-recursive).

    File Geodatabases are directories, not files, so Path.glob is used to find
    entries whose suffix is '.gdb' and that are actually directories.

    Args:
        folder (Path): Top-level directory to scan.

    Returns:
        list[Path]: Sorted list of .gdb paths found.
    """
    return sorted(p for p in folder.glob("*.gdb") if p.is_dir())


def list_layers(gdb_path: Path, engine: str) -> list[str]:
    """Return the layer names available in a File Geodatabase.

    Args:
        gdb_path (Path): Path to the .gdb directory.
        engine (str): ``"pyogrio"`` or ``"fiona"``.

    Returns:
        list[str]: Layer names, or an empty list on error.
    """
    try:
        if engine == "pyogrio":
            from pyogrio import list_layers as _list
            return [row[0] for row in _list(str(gdb_path))]
        else:
            import fiona
            return fiona.listlayers(str(gdb_path))
    except Exception:
        return []


def read_layer(gdb_path: Path, layer: str, engine: str):
    """Read a single layer from a File Geodatabase into a GeoDataFrame.

    Args:
        gdb_path (Path): Path to the .gdb directory.
        layer (str): Exact layer name to read.
        engine (str): ``"pyogrio"`` or ``"fiona"``.

    Returns:
        geopandas.GeoDataFrame: The layer contents.

    Raises:
        Exception: Any read error is propagated to the caller.
    """
    import geopandas as gpd

    return gpd.read_file(str(gdb_path), layer=layer, engine=engine)


def detect_engine() -> str:
    """Return the best available GeoDataFrame I/O engine.

    Returns:
        str: ``"pyogrio"`` if available, else ``"fiona"``.

    Raises:
        ImportError: If neither pyogrio nor fiona is installed.
    """
    try:
        import pyogrio  # noqa: F401
        return "pyogrio"
    except ImportError:
        pass
    try:
        import fiona  # noqa: F401
        return "fiona"
    except ImportError:
        raise ImportError(
            "Neither 'pyogrio' nor 'fiona' is installed.\n"
            "Install one with:  pip install pyogrio  or  pip install fiona"
        )


# ── Main ──────────────────────────────────────────────────────────────────────

def main(input_folder: Path, output_folder: Path, layer_name: str) -> None:
    """Run the extraction for all GDBs in *input_folder*.

    Args:
        input_folder (Path): Directory containing one or more .gdb folders.
        output_folder (Path): Destination directory for output GeoJSON files.
        layer_name (str): Feature class name to extract from each GDB.
    """
    # ── Validate input ─────────────────────────────────────────────────────
    if not input_folder.is_dir():
        print(f"ERROR: Input folder does not exist: {input_folder}", file=sys.stderr)
        sys.exit(1)

    engine = detect_engine()
    print(f"I/O engine : {engine}")

    gdbs = find_gdbs(input_folder)
    if not gdbs:
        print(f"No .gdb directories found in: {input_folder}")
        return

    print(f"Found {len(gdbs)} geodatabase(s) in {input_folder}\n")

    output_folder.mkdir(parents=True, exist_ok=True)

    # ── Per-GDB loop ───────────────────────────────────────────────────────
    ok = 0
    skipped = 0

    for gdb in gdbs:
        stem        = gdb.stem                          # e.g. "Watershed_A"
        out_path    = output_folder / f"{stem}.geojson"

        print(f"[{ok + skipped + 1}/{len(gdbs)}] {gdb.name}")

        # ── Check that the layer exists ────────────────────────────────────
        available = list_layers(gdb, engine)
        if layer_name not in available:
            # Case-insensitive fallback search
            match = next(
                (n for n in available if n.lower() == layer_name.lower()), None
            )
            if match:
                print(f"  NOTE: Layer '{layer_name}' not found; using '{match}' (case-insensitive match).")
                layer_name_used = match
            else:
                print(f"  SKIP: Layer '{layer_name}' not found.")
                if available:
                    print(f"        Available layers: {', '.join(available)}")
                skipped += 1
                continue
        else:
            layer_name_used = layer_name

        # ── Read and write ─────────────────────────────────────────────────
        try:
            gdf = read_layer(gdb, layer_name_used, engine)
        except Exception as exc:
            print(f"  ERROR reading layer: {exc}")
            skipped += 1
            continue

        if gdf.empty:
            print(f"  SKIP: Layer '{layer_name_used}' is empty.")
            skipped += 1
            continue

        n_features = len(gdf)

        # Reproject to WGS-84 if needed — GeoJSON spec requires geographic CRS
        if gdf.crs is not None and not gdf.crs.equals("EPSG:4326"):
            gdf = gdf.to_crs("EPSG:4326")

        try:
            gdf.to_file(str(out_path), driver="GeoJSON")
        except Exception as exc:
            print(f"  ERROR writing GeoJSON: {exc}")
            skipped += 1
            continue

        print(f"  → {out_path.name}  ({n_features} feature(s))")
        ok += 1

    # ── Summary ────────────────────────────────────────────────────────────
    print(f"\nDone — {ok} GeoJSON file(s) written to {output_folder}")
    if skipped:
        print(f"       {skipped} geodatabase(s) skipped (see messages above).")


# ── Entry point ───────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract a named feature class from every File Geodatabase in a "
            "folder and save each result as a GeoJSON FeatureCollection."
        )
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        default=Path(DEFAULT_INPUT),
        metavar="FOLDER",
        help=f"Folder containing .gdb directories (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path(DEFAULT_OUTPUT),
        metavar="FOLDER",
        help=f"Output folder for GeoJSON files (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--layer", "-l",
        default=DEFAULT_LAYER,
        metavar="NAME",
        help=f"Feature class name to extract (default: '{DEFAULT_LAYER}')",
    )
    return parser.parse_args()


if __name__ == "__main__":
    # Suppress pyogrio's benign warning about Measured (M) geometry downcast
    warnings.filterwarnings("ignore", message="Measured.*geometry", category=UserWarning)
    args = _parse_args()
    main(
        input_folder=args.input,
        output_folder=args.output,
        layer_name=args.layer,
    )
