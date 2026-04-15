"""Filter stream features by Hack order and proximity to outfall.

This script keeps features where:
1. Hack order is less than or equal to a threshold (default: 3), and
2. The feature is within a threshold distance (default: 10 miles) of the
   network outfall, measured along the network.

For each connected network in each input layer, the script:
- splits lines at junctions,
- builds a topological graph,
- identifies the network outfall,
- normalizes edge direction toward the outfall,
- computes distance-to-outfall for each segment,
- maps segment distances back to original features.

Usage:
    python scripts/filter_hack3_within_outfall_10mi.py \
      --input-folder "D:\\02_projects\\p-wpt-2\\gdbs\\draft\\order"

Dependencies:
    geopandas, shapely
"""

from __future__ import annotations

import argparse
import heapq
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import geopandas as gpd
from shapely.geometry import LineString, MultiLineString

# Allow importing from repository when script is run from repo root.
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stream_segmenter.utils.network import (  # noqa: E402
    GraphEdge,
    GraphNode,
    build_graph,
    find_connected_components,
    find_outlet_node,
    normalize_directions,
    split_lines_at_junctions,
)


def _iter_input_files(input_folder: Path) -> Iterable[Path]:
    """Yield vector files to process from the input folder."""
    patterns = ("*.gpkg", "*.geojson", "*.shp", "*.fgb")
    for pattern in patterns:
        yield from input_folder.glob(pattern)


def _read_layer(path: Path) -> gpd.GeoDataFrame:
    """Read vector file into GeoDataFrame."""
    return gpd.read_file(path)


def _to_line_like(geom: Any) -> Optional[Any]:
    """Return a line-compatible geometry or None."""
    if geom is None or geom.is_empty:
        return None
    if isinstance(geom, (LineString, MultiLineString)):
        return geom
    return None


def _mile_to_crs_units(miles: float, crs: Any) -> float:
    """Convert miles to native CRS units.

    Assumes projected CRS units are linear (meters/feet/etc.).
    For geographic CRS, converts miles to degrees approximately.
    """
    meters = miles * 1609.344

    if crs is None:
        return meters

    try:
        if crs.is_geographic:
            return meters / 111320.0

        units_name = (getattr(crs, "axis_info", None) or [None])[0]
        units_name = getattr(units_name, "unit_name", "").lower() if units_name else ""

        if "foot" in units_name or "feet" in units_name:
            return meters / 0.3048
        if "metre" in units_name or "meter" in units_name:
            return meters
        if "kilomet" in units_name:
            return meters / 1000.0
        if "mile" in units_name:
            return miles

        # Fallback: assume meters.
        return meters
    except Exception:
        return meters


def _build_undirected_adjacency(
    nodes: Dict[int, GraphNode],
    edges: Dict[int, GraphEdge],
    component_edge_ids: Set[int],
) -> Dict[int, List[Tuple[int, float]]]:
    """Build undirected adjacency list for one component."""
    adjacency: Dict[int, List[Tuple[int, float]]] = defaultdict(list)
    for edge_id in component_edge_ids:
        edge = edges[edge_id]
        adjacency[edge.start_node_id].append((edge.end_node_id, edge.length))
        adjacency[edge.end_node_id].append((edge.start_node_id, edge.length))
    return adjacency


def _shortest_path_distances(
    adjacency: Dict[int, List[Tuple[int, float]]],
    start_node_id: int,
) -> Dict[int, float]:
    """Compute shortest path distances from start node using Dijkstra."""
    distances: Dict[int, float] = {start_node_id: 0.0}
    queue: List[Tuple[float, int]] = [(0.0, start_node_id)]

    while queue:
        cur_dist, node_id = heapq.heappop(queue)
        if cur_dist > distances.get(node_id, float("inf")):
            continue

        for nbr, weight in adjacency.get(node_id, []):
            cand = cur_dist + weight
            if cand < distances.get(nbr, float("inf")):
                distances[nbr] = cand
                heapq.heappush(queue, (cand, nbr))

    return distances


def _resolve_hack_field(columns: Iterable[str], requested: str) -> Optional[str]:
    """Resolve the Hack field with case-insensitive matching."""
    lower_map = {c.lower(): c for c in columns}
    return lower_map.get(requested.lower())


def filter_file(
    src_path: Path,
    out_path: Path,
    hack_field: str,
    max_hack: int,
    max_miles: float,
    snap_tolerance: float,
) -> Tuple[int, int]:
    """Filter one file and write the filtered output.

    Returns:
        (kept_count, total_count)
    """
    gdf = _read_layer(src_path)
    if gdf.empty:
        gdf.to_file(out_path, driver="GPKG")
        return 0, 0

    resolved_hack = _resolve_hack_field(gdf.columns, hack_field)
    if not resolved_hack:
        raise ValueError(f"Hack field '{hack_field}' not found in {src_path.name}")

    # Keep original index as feature id for mapping.
    gdf = gdf.reset_index(drop=False).rename(columns={"index": "src_fid"})

    geom_records: List[Tuple[int, Any]] = []
    for row in gdf.itertuples(index=False):
        geom = _to_line_like(row.geometry)
        if geom is None:
            continue
        geom_records.append((int(row.src_fid), geom))

    if not geom_records:
        out = gdf.iloc[0:0].copy()
        out.to_file(out_path, driver="GPKG")
        return 0, len(gdf)

    # Split at junctions so mid-line confluences become topological nodes.
    split_result = split_lines_at_junctions(geom_records, snap_tolerance)

    # Build edge tuples with stable segment IDs.
    features: List[Tuple[int, Tuple[float, float], Tuple[float, float], float]] = []
    segment_to_original: Dict[int, int] = {}
    original_to_segments: Dict[int, List[int]] = defaultdict(list)

    for original_fid, segments in split_result:
        for seg_idx, (start, end, length) in enumerate(segments):
            seg_id = original_fid * 100000 + seg_idx
            features.append((seg_id, start, end, length))
            segment_to_original[seg_id] = original_fid
            original_to_segments[original_fid].append(seg_id)

    nodes, edges = build_graph(features, snap_tolerance)
    components = find_connected_components(nodes, edges)

    # Distance to outfall in CRS units at feature level.
    # Use each channel's downstream node distance to the network outfall.
    # For split features, keep the minimum downstream-node distance among
    # segments to represent the original feature's downstream outfall node.
    feature_dist_to_outfall: Dict[int, float] = {}

    for component_edge_ids in components:
        outlet_node_id = find_outlet_node(nodes, edges, component_edge_ids)
        if outlet_node_id is None:
            continue

        normalize_directions(nodes, edges, component_edge_ids, outlet_node_id)

        adjacency = _build_undirected_adjacency(nodes, edges, component_edge_ids)
        node_dist = _shortest_path_distances(adjacency, outlet_node_id)

        for seg_id in component_edge_ids:
            edge = edges[seg_id]
            # Directed edges flow toward outlet after normalize_directions().
            # start_node_id is upstream (farther), end_node_id is downstream.
            seg_dist = node_dist.get(edge.end_node_id, float("inf"))
            original_fid = segment_to_original.get(seg_id)
            if original_fid is None:
                continue

            cur = feature_dist_to_outfall.get(original_fid, float("inf"))
            if seg_dist < cur:
                feature_dist_to_outfall[original_fid] = seg_dist

    max_distance = _mile_to_crs_units(max_miles, gdf.crs)

    keep_mask: List[bool] = []
    for row in gdf.itertuples(index=False):
        hack_val = getattr(row, resolved_hack)
        fid = int(row.src_fid)
        dist_val = feature_dist_to_outfall.get(fid, float("inf"))

        try:
            hack_ok = float(hack_val) <= float(max_hack)
        except Exception:
            hack_ok = False

        dist_ok = dist_val <= max_distance
        keep_mask.append(bool(hack_ok and dist_ok))

    out = gdf.loc[keep_mask].copy()
    out = out.drop(columns=["src_fid"])
    out.to_file(out_path, driver="GPKG")

    return int(out.shape[0]), int(gdf.shape[0])


def main() -> None:
    """Run folder-level filtering workflow."""
    parser = argparse.ArgumentParser(
        description=(
            "Keep features where hack order <= max-hack and distance-to-outfall "
            "<= max-miles for each input vector file in a folder."
        )
    )
    parser.add_argument(
        "--input-folder",
        default=r"D:\02_projects\p-wpt-2\gdbs\draft\order",
        help="Folder containing input vector files",
    )
    parser.add_argument(
        "--output-folder",
        default="",
        help="Folder for output files (default: <input-folder>/filtered_hack3_10mi)",
    )
    parser.add_argument(
        "--hack-field",
        default="hack",
        help="Name of the Hack order field (case-insensitive)",
    )
    parser.add_argument(
        "--max-hack",
        type=int,
        default=3,
        help="Maximum Hack order to keep",
    )
    parser.add_argument(
        "--max-miles",
        type=float,
        default=10.0,
        help="Maximum along-network miles from outfall to keep",
    )
    parser.add_argument(
        "--snap-tolerance",
        type=float,
        default=1.0,
        help="Snap tolerance in CRS native units",
    )
    args = parser.parse_args()

    input_folder = Path(args.input_folder)
    if not input_folder.exists() or not input_folder.is_dir():
        raise SystemExit(f"Input folder does not exist: {input_folder}")

    if args.output_folder:
        output_folder = Path(args.output_folder)
    else:
        output_folder = input_folder / "filtered_hack3_10mi"
    output_folder.mkdir(parents=True, exist_ok=True)

    files = sorted(set(_iter_input_files(input_folder)))
    if not files:
        print(f"No supported vector files found in: {input_folder}")
        return

    print(f"Found {len(files)} file(s) in {input_folder}")

    total_kept = 0
    total_rows = 0
    for src_path in files:
        out_name = f"{src_path.stem}_hack{args.max_hack}_within_{args.max_miles:g}mi.gpkg"
        out_path = output_folder / out_name

        try:
            kept, total = filter_file(
                src_path=src_path,
                out_path=out_path,
                hack_field=args.hack_field,
                max_hack=args.max_hack,
                max_miles=args.max_miles,
                snap_tolerance=args.snap_tolerance,
            )
            total_kept += kept
            total_rows += total
            print(f"[OK] {src_path.name}: kept {kept}/{total} -> {out_path.name}")
        except Exception as exc:
            print(f"[SKIP] {src_path.name}: {exc}")

    print("\nDone.")
    print(f"Total kept: {total_kept}/{total_rows}")
    print(f"Output folder: {output_folder}")


if __name__ == "__main__":
    main()
