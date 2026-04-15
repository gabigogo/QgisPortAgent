"""Debug script to investigate stream order issues.

Run from command line:
    python debug_stream_order.py
"""

import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Optional
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from stream_segmenter.utils.network import (
    ORDER_HACK,
    ORDER_STRAHLER,
    ORDER_SHREVE,
    GraphNode,
    GraphEdge,
    build_graph,
    find_connected_components,
    find_outlet_node,
    normalize_directions,
    compute_upstream_lengths,
    compute_stream_orders,
    process_network,
    process_network_from_geometries,
    split_lines_at_junctions,
)


def load_geojson_geometries(filepath: str) -> List[Tuple[int, any, str]]:
    """Load features from GeoJSON with full geometries."""
    from shapely.geometry import shape
    
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    results = []
    for idx, feat in enumerate(data.get('features', [])):
        geom = shape(feat['geometry'])
        if geom.is_empty:
            continue
        
        fid = feat.get('id', idx)
        if fid is None:
            fid = idx
        
        props = feat.get('properties', {})
        name = props.get('UnitNo', props.get('Channel', props.get('name', f'feat_{fid}')))
        
        results.append((fid, geom, name))
    
    return results


def debug_stream_order_with_splitting(filepath: str, snap_tolerance: float = 1.0):
    """Run stream order with geometry splitting at junctions."""
    print(f"\n{'='*60}")
    print(f"DEBUG: Stream Order with Junction Splitting")
    print(f"File: {filepath}")
    print(f"Snap tolerance: {snap_tolerance}")
    print(f"{'='*60}\n")
    
    # Load features with full geometries
    features_with_names = load_geojson_geometries(filepath)
    print(f"Loaded {len(features_with_names)} features\n")
    
    # Create feature name lookup
    fid_to_name = {f[0]: f[2] for f in features_with_names}
    
    # Show features
    print("Features:")
    for fid, geom, name in features_with_names:
        print(f"  {name}: length={geom.length:.2f}")
    print()
    
    # Prepare geometries for processing
    geometries = [(fid, geom) for fid, geom, _ in features_with_names]
    
    # Test the split function
    print("Testing junction splitting...")
    split_result = split_lines_at_junctions(geometries, snap_tolerance)
    
    total_segments = sum(len(segs) for _, segs in split_result)
    print(f"Split {len(geometries)} features into {total_segments} segments\n")
    
    for orig_fid, segments in split_result:
        name = fid_to_name.get(orig_fid, f"feat_{orig_fid}")
        print(f"  {name}: {len(segments)} segment(s)")
        for i, (start, end, length) in enumerate(segments):
            print(f"    Seg {i}: start={start}, end={end}, len={length:.2f}")
    print()
    
    # Now run full processing
    print("Running full stream order computation...")
    orders, network_ids, reversed_count, segment_mapping = process_network_from_geometries(
        geometries,
        snap_tolerance=snap_tolerance,
        order_types=[ORDER_HACK, ORDER_STRAHLER, ORDER_SHREVE],
    )
    
    print(f"\nResults:")
    print(f"  Networks found: {len(set(network_ids.values()))}")
    print(f"  Reversed segments: {reversed_count}")
    print()
    
    print("Stream orders by feature:")
    for fid, geom, name in features_with_names:
        feature_orders = orders.get(fid, {})
        net_id = network_ids.get(fid)
        hack = feature_orders.get(ORDER_HACK, "N/A")
        strahler = feature_orders.get(ORDER_STRAHLER, "N/A")
        shreve = feature_orders.get(ORDER_SHREVE, "N/A")
        print(f"  {name}: hack={hack}, strahler={strahler}, shreve={shreve}, network={net_id}")


if __name__ == "__main__":
    filepath = r"D:\02_projects\p-wpt-2\gdbs\draft\repro\WPT_I_Vince_Bayou.json.geojson"
    
    # Try with snap tolerance of 1 foot
    debug_stream_order_with_splitting(filepath, snap_tolerance=1.0)
