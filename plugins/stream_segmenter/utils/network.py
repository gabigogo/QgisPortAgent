"""Network graph utilities for stream order computation.

This module provides graph data structures and traversal algorithms for
computing stream orders (Hack, Strahler, Shreve) on vector line networks.

All symbols depend only on the Python standard library and ``shapely`` —
no QGIS bindings required. This separation allows helpers to be unit-tested
without a running QGIS environment.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

# ── Order method constants ────────────────────────────────────────────────────

ORDER_HACK: int = 1
ORDER_STRAHLER: int = 2
ORDER_SHREVE: int = 3

ORDER_NAMES: Dict[int, str] = {
    ORDER_HACK: "hack",
    ORDER_STRAHLER: "strahler",
    ORDER_SHREVE: "shreve",
}

# ── Field name constants ──────────────────────────────────────────────────────

FLD_HACK: str = "hack"
FLD_STRAHLER: str = "strahler"
FLD_SHREVE: str = "shreve"
FLD_NETWORK_ID: str = "network_id"
FLD_REVERSED: str = "reversed"

ORDER_FIELD_NAMES: frozenset = frozenset({FLD_HACK, FLD_STRAHLER, FLD_SHREVE,
                                          FLD_NETWORK_ID, FLD_REVERSED})


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class GraphNode:
    """Represents a junction or terminal point in the stream network graph.

    Attributes:
        id: Unique node identifier (typically derived from coordinate hash).
        coords: (x, y) coordinate tuple of this node.
        edge_ids: Set of edge IDs connected to this node.
    """

    id: int
    coords: Tuple[float, float]
    edge_ids: Set[int] = field(default_factory=set)

    @property
    def degree(self) -> int:
        """Number of edges connected to this node."""
        return len(self.edge_ids)


@dataclass
class GraphEdge:
    """Represents a stream segment (line feature) in the network graph.

    Attributes:
        id: Feature ID from the source layer.
        start_node_id: Node ID at the upstream end (after direction normalization).
        end_node_id: Node ID at the downstream end (after direction normalization).
        length: Geodetic length of the edge in meters.
        reversed: True if geometry was reversed to achieve downstream orientation.
        upstream_length: Cumulative length of all upstream edges (computed during traversal).
        orders: Dictionary mapping order method constants to computed order values.
    """

    id: int
    start_node_id: int
    end_node_id: int
    length: float = 0.0
    reversed: bool = False
    upstream_length: float = 0.0
    orders: Dict[int, Optional[int]] = field(default_factory=dict)

    def __post_init__(self):
        """Initialize order values to None."""
        for order_type in (ORDER_HACK, ORDER_STRAHLER, ORDER_SHREVE):
            if order_type not in self.orders:
                self.orders[order_type] = None


# ── Graph builder ─────────────────────────────────────────────────────────────


def _coord_key(x: float, y: float, tolerance: float) -> Tuple[int, int]:
    """Convert coordinates to a grid cell key for snapping.

    Args:
        x: X coordinate.
        y: Y coordinate.
        tolerance: Snap tolerance (grid cell size).

    Returns:
        Tuple of (grid_x, grid_y) indices.
    """
    return (int(round(x / tolerance)), int(round(y / tolerance)))


def split_lines_at_junctions(
    geometries: List[Tuple[int, Any]],
    snap_tolerance: float = 1.0,
) -> List[Tuple[int, List[Tuple[Tuple[float, float], Tuple[float, float], float]]]]:
    """Split line geometries at intersection/junction points.

    Stream networks often have channels that meet at points ALONG the main
    channel, not at endpoints. This function finds all intersection points
    between geometries and splits each line at those points, creating a
    proper topological network where junctions occur at segment endpoints.

    Args:
        geometries: List of (feature_id, shapely_geometry) tuples.
        snap_tolerance: Distance within which points are considered the same.

    Returns:
        List of (original_feature_id, segments) where segments is a list of
        tuples (start_coord, end_coord, length) for each resulting segment.

    Methodology:
        1. Find all intersection points between every pair of geometries.
        2. For each geometry, find where junction points lie along it.
        3. Split geometry at each junction point.
        4. Return the resulting segments maintaining original feature IDs.
    """
    from shapely.geometry import Point, LineString, MultiPoint
    from shapely.ops import split, snap, nearest_points
    
    if not geometries:
        return []
    
    # Collect all junction points (intersections and near-touches)
    junction_points: List[Point] = []
    
    for i, (fid1, geom1) in enumerate(geometries):
        for j, (fid2, geom2) in enumerate(geometries):
            if i >= j:
                continue
            
            # Check for direct intersection
            if geom1.intersects(geom2):
                inter = geom1.intersection(geom2)
                if inter.geom_type == 'Point':
                    junction_points.append(inter)
                elif inter.geom_type == 'MultiPoint':
                    junction_points.extend(inter.geoms)
                elif inter.geom_type == 'LineString':
                    # Lines overlap - use start/end of overlap
                    junction_points.append(Point(inter.coords[0]))
                    junction_points.append(Point(inter.coords[-1]))
            else:
                # Check for near-touch (within snap tolerance)
                p1, p2 = nearest_points(geom1, geom2)
                if p1.distance(p2) <= snap_tolerance:
                    # Use the midpoint as the junction
                    junction_points.append(Point(
                        (p1.x + p2.x) / 2,
                        (p1.y + p2.y) / 2
                    ))
    
    # Also add all original endpoints as junction candidates
    for fid, geom in geometries:
        if hasattr(geom, 'geoms'):
            for part in geom.geoms:
                junction_points.append(Point(part.coords[0]))
                junction_points.append(Point(part.coords[-1]))
        else:
            junction_points.append(Point(geom.coords[0]))
            junction_points.append(Point(geom.coords[-1]))
    
    # Cluster nearby junction points (within snap tolerance)
    clustered_junctions: List[Point] = []
    used = set()
    
    for i, pt in enumerate(junction_points):
        if i in used:
            continue
        
        # Find all points within snap tolerance
        cluster = [pt]
        for j, other in enumerate(junction_points):
            if j != i and j not in used and pt.distance(other) <= snap_tolerance:
                cluster.append(other)
                used.add(j)
        
        # Use centroid of cluster
        if len(cluster) == 1:
            clustered_junctions.append(cluster[0])
        else:
            cx = sum(p.x for p in cluster) / len(cluster)
            cy = sum(p.y for p in cluster) / len(cluster)
            clustered_junctions.append(Point(cx, cy))
        used.add(i)
    
    # Split each geometry at the junction points that lie on it
    result: List[Tuple[int, List[Tuple[Tuple[float, float], Tuple[float, float], float]]]] = []
    
    for fid, geom in geometries:
        # Handle MultiLineString by processing each part
        if hasattr(geom, 'geoms'):
            parts = list(geom.geoms)
        else:
            parts = [geom]
        
        all_segments: List[Tuple[Tuple[float, float], Tuple[float, float], float]] = []
        
        for part in parts:
            # Find junction points that lie on this part
            split_points = []
            for jp in clustered_junctions:
                dist = part.distance(jp)
                if dist <= snap_tolerance:
                    # Find the position along the line
                    proj = part.project(jp)
                    if snap_tolerance < proj < part.length - snap_tolerance:
                        # Point is along the line, not at endpoints
                        split_points.append((proj, jp))
            
            # Sort split points by position along line
            split_points.sort(key=lambda x: x[0])
            
            if not split_points:
                # No splits needed - return original
                coords = list(part.coords)
                all_segments.append((
                    (coords[0][0], coords[0][1]),
                    (coords[-1][0], coords[-1][1]),
                    part.length
                ))
            else:
                # Split the line at each point
                coords = list(part.coords)
                current_start = 0
                current_coords = [coords[0]]
                
                for proj, jp in split_points:
                    # Find where to insert the split point
                    # Walk along the line to find the segment containing proj
                    cumulative = 0.0
                    for k in range(len(coords) - 1):
                        seg_start = Point(coords[k])
                        seg_end = Point(coords[k + 1])
                        seg_len = seg_start.distance(seg_end)
                        
                        if cumulative + seg_len >= proj - snap_tolerance:
                            # This segment contains the split point
                            # Add all coords up to and including this segment start
                            while len(current_coords) <= k:
                                current_coords.append(coords[len(current_coords)])
                            
                            # Add the split point
                            split_coord = (jp.x, jp.y)
                            current_coords.append(split_coord)
                            
                            # Create segment
                            seg_line = LineString(current_coords)
                            all_segments.append((
                                (current_coords[0][0], current_coords[0][1]),
                                split_coord,
                                seg_line.length
                            ))
                            
                            # Start new segment
                            current_coords = [split_coord]
                            break
                        
                        cumulative += seg_len
                
                # Add remaining coords for final segment
                for k in range(len(current_coords), len(coords)):
                    current_coords.append(coords[k])
                
                if len(current_coords) > 1:
                    seg_line = LineString(current_coords)
                    all_segments.append((
                        (current_coords[0][0], current_coords[0][1]),
                        (current_coords[-1][0], current_coords[-1][1]),
                        seg_line.length
                    ))
        
        result.append((fid, all_segments))
    
    return result


def build_graph(
    features: List[Tuple[int, Tuple[float, float], Tuple[float, float], float]],
    snap_tolerance: float = 1.0,
) -> Tuple[Dict[int, GraphNode], Dict[int, GraphEdge]]:
    """Build a network graph from line feature endpoint data.

    Args:
        features: List of tuples (feature_id, start_coord, end_coord, length).
            Each coordinate is (x, y). Length is in meters.
        snap_tolerance: Maximum distance to consider endpoints as connected.
            Should be CRS-appropriate (e.g., 1.0 for projected, 0.00001 for geographic).

    Returns:
        Tuple of (nodes_dict, edges_dict) where:
            - nodes_dict maps node_id -> GraphNode
            - edges_dict maps feature_id -> GraphEdge

    Methodology:
        1. Hash each endpoint coordinate to a grid cell based on snap_tolerance.
        2. Assign a unique node ID to each unique grid cell.
        3. Create GraphEdge for each feature linking its endpoint nodes.
        4. Build adjacency by populating edge_ids on each GraphNode.
    """
    # Map grid cell -> node_id
    cell_to_node: Dict[Tuple[int, int], int] = {}
    # Map node_id -> GraphNode
    nodes: Dict[int, GraphNode] = {}
    # Map feature_id -> GraphEdge
    edges: Dict[int, GraphEdge] = {}

    next_node_id = 0

    def get_or_create_node(coord: Tuple[float, float]) -> int:
        """Get existing node ID for coordinate or create a new one."""
        nonlocal next_node_id
        cell = _coord_key(coord[0], coord[1], snap_tolerance)
        if cell in cell_to_node:
            return cell_to_node[cell]
        node_id = next_node_id
        next_node_id += 1
        cell_to_node[cell] = node_id
        nodes[node_id] = GraphNode(id=node_id, coords=coord)
        return node_id

    # Build nodes and edges
    for fid, start_coord, end_coord, length in features:
        start_node_id = get_or_create_node(start_coord)
        end_node_id = get_or_create_node(end_coord)

        edge = GraphEdge(
            id=fid,
            start_node_id=start_node_id,
            end_node_id=end_node_id,
            length=length,
        )
        edges[fid] = edge

        # Add edge to both endpoint nodes
        nodes[start_node_id].edge_ids.add(fid)
        nodes[end_node_id].edge_ids.add(fid)

    return nodes, edges


# ── Connected components ──────────────────────────────────────────────────────


def find_connected_components(
    nodes: Dict[int, GraphNode],
    edges: Dict[int, GraphEdge],
) -> List[Set[int]]:
    """Find connected components in the network graph.

    Args:
        nodes: Dictionary mapping node_id -> GraphNode.
        edges: Dictionary mapping edge_id -> GraphEdge.

    Returns:
        List of sets, where each set contains edge IDs belonging to one
        connected component.

    Methodology:
        Uses breadth-first search starting from unvisited edges to
        discover all edges reachable through shared nodes.
    """
    visited_edges: Set[int] = set()
    components: List[Set[int]] = []

    for start_edge_id in edges:
        if start_edge_id in visited_edges:
            continue

        # BFS to find all edges in this component
        component: Set[int] = set()
        edge_queue: List[int] = [start_edge_id]

        while edge_queue:
            edge_id = edge_queue.pop(0)
            if edge_id in visited_edges:
                continue

            visited_edges.add(edge_id)
            component.add(edge_id)

            edge = edges[edge_id]
            # Visit edges connected at both endpoints
            for node_id in (edge.start_node_id, edge.end_node_id):
                node = nodes[node_id]
                for neighbor_edge_id in node.edge_ids:
                    if neighbor_edge_id not in visited_edges:
                        edge_queue.append(neighbor_edge_id)

        if component:
            components.append(component)

    return components


# ── Outlet detection ──────────────────────────────────────────────────────────


def find_outlet_node(
    nodes: Dict[int, GraphNode],
    edges: Dict[int, GraphEdge],
    component_edge_ids: Set[int],
) -> Optional[int]:
    """Find the outlet node for a connected component.

    The outlet is the degree-1 node (terminal endpoint) with the maximum
    total upstream network length. This heuristic identifies the downstream
    end of dendritic stream networks.

    Args:
        nodes: Dictionary mapping node_id -> GraphNode.
        edges: Dictionary mapping edge_id -> GraphEdge.
        component_edge_ids: Set of edge IDs in this connected component.

    Returns:
        Node ID of the detected outlet, or None if no suitable outlet found.

    Methodology:
        1. Find all degree-1 nodes within the component.
        2. For each candidate, compute total network length reachable upstream.
        3. Select the candidate with maximum upstream length as the outlet.
    """
    # Get nodes that are part of this component
    component_node_ids: Set[int] = set()
    for edge_id in component_edge_ids:
        edge = edges[edge_id]
        component_node_ids.add(edge.start_node_id)
        component_node_ids.add(edge.end_node_id)

    # Find degree-1 nodes (only count edges within the component)
    candidates: List[int] = []
    for node_id in component_node_ids:
        node = nodes[node_id]
        component_edges_at_node = node.edge_ids & component_edge_ids
        if len(component_edges_at_node) == 1:
            candidates.append(node_id)

    if not candidates:
        # No terminal nodes found — possibly a loop network
        # Fall back to any node in the component
        return next(iter(component_node_ids)) if component_node_ids else None

    if len(candidates) == 1:
        return candidates[0]

    # Multiple candidates — select using network topology heuristics
    # The outlet is one endpoint of the longest path through the network
    # (the "diameter"). We find the two most distant terminals, then
    # use additional heuristics to pick which one is the outlet.
    
    # Step 1: From each terminal, compute max distance to any other terminal
    terminal_max_dist: Dict[int, Tuple[float, int]] = {}  # node_id -> (max_dist, farthest_node)
    
    for candidate_id in candidates:
        distances = _compute_distances_to_all_nodes(
            nodes, edges, component_edge_ids, candidate_id
        )
        max_dist = 0.0
        farthest = candidate_id
        for other_id in candidates:
            if other_id != candidate_id and other_id in distances:
                if distances[other_id] > max_dist:
                    max_dist = distances[other_id]
                    farthest = other_id
        terminal_max_dist[candidate_id] = (max_dist, farthest)
    
    # Step 2: Find the diameter endpoints (two terminals with max distance)
    diameter_endpoints: List[int] = []
    max_diameter = 0.0
    for node_id, (max_dist, farthest) in terminal_max_dist.items():
        if max_dist > max_diameter:
            max_diameter = max_dist
            diameter_endpoints = [node_id, farthest]
    
    if len(diameter_endpoints) == 2:
        # The outlet is one of the diameter endpoints.
        # Heuristic: the outlet has MORE edges reachable at shorter distances
        # (tributaries branch off along the main stem).
        # Use the terminal with LOWER average distance to all edges.
        e1, e2 = diameter_endpoints
        avg1 = _compute_avg_distance_to_edges(nodes, edges, component_edge_ids, e1)
        avg2 = _compute_avg_distance_to_edges(nodes, edges, component_edge_ids, e2)
        return e1 if avg1 <= avg2 else e2
    
    # Fallback: return first candidate
    return candidates[0]


def _compute_distances_to_all_nodes(
    nodes: Dict[int, GraphNode],
    edges: Dict[int, GraphEdge],
    component_edge_ids: Set[int],
    start_node_id: int,
) -> Dict[int, float]:
    """Compute shortest path distances from start node to all reachable nodes.

    Args:
        nodes: Dictionary mapping node_id -> GraphNode.
        edges: Dictionary mapping edge_id -> GraphEdge.
        component_edge_ids: Set of edge IDs in this connected component.
        start_node_id: Node ID to compute distances from.

    Returns:
        Dictionary mapping node_id -> distance from start.
    """
    distances: Dict[int, float] = {start_node_id: 0.0}
    queue: List[Tuple[int, float]] = [(start_node_id, 0.0)]

    while queue:
        node_id, dist = queue.pop(0)
        
        if dist > distances.get(node_id, float('inf')):
            continue

        node = nodes[node_id]
        for edge_id in node.edge_ids:
            if edge_id not in component_edge_ids:
                continue

            edge = edges[edge_id]
            other_node = edge.end_node_id if edge.start_node_id == node_id else edge.start_node_id
            new_dist = dist + edge.length

            if other_node not in distances or new_dist < distances[other_node]:
                distances[other_node] = new_dist
                queue.append((other_node, new_dist))

    return distances


def _compute_avg_distance_to_edges(
    nodes: Dict[int, GraphNode],
    edges: Dict[int, GraphEdge],
    component_edge_ids: Set[int],
    start_node_id: int,
) -> float:
    """Compute average distance from start node to all edge midpoints.

    This helps identify the outlet: the outlet tends to have lower average
    distance to edges because tributaries branch off along the main stem.

    Args:
        nodes: Dictionary mapping node_id -> GraphNode.
        edges: Dictionary mapping edge_id -> GraphEdge.
        component_edge_ids: Set of edge IDs in this connected component.
        start_node_id: Node ID to compute distances from.

    Returns:
        Average distance to edge midpoints.
    """
    node_distances = _compute_distances_to_all_nodes(
        nodes, edges, component_edge_ids, start_node_id
    )
    
    total_dist = 0.0
    count = 0
    
    for edge_id in component_edge_ids:
        edge = edges[edge_id]
        # Distance to edge ~ average of distances to its endpoints
        d1 = node_distances.get(edge.start_node_id, 0.0)
        d2 = node_distances.get(edge.end_node_id, 0.0)
        total_dist += (d1 + d2) / 2.0
        count += 1
    
    return total_dist / count if count > 0 else 0.0


# ── Direction normalization ───────────────────────────────────────────────────


def normalize_directions(
    nodes: Dict[int, GraphNode],
    edges: Dict[int, GraphEdge],
    component_edge_ids: Set[int],
    outlet_node_id: int,
) -> int:
    """Normalize edge directions to flow toward the outlet.

    Traverses the network from the outlet upstream, reversing edges as needed
    so that each edge's end_node_id points toward the outlet.

    Args:
        nodes: Dictionary mapping node_id -> GraphNode.
        edges: Dictionary mapping edge_id -> GraphEdge.
        component_edge_ids: Set of edge IDs in this connected component.
        outlet_node_id: Node ID of the outlet (downstream terminus).

    Returns:
        Number of edges that were reversed.

    Methodology:
        1. Start BFS from the outlet node.
        2. For each edge, ensure end_node_id is the downstream node
           (closer to outlet). Swap start/end and set reversed=True if needed.
        3. Track and return count of reversed edges for diagnostics.
    """
    reversed_count = 0
    visited_edges: Set[int] = set()
    visited_nodes: Set[int] = set()

    # Queue contains (node_id, came_from_edge_id or None)
    queue: List[Tuple[int, Optional[int]]] = [(outlet_node_id, None)]

    while queue:
        current_node_id, _ = queue.pop(0)
        if current_node_id in visited_nodes:
            continue
        visited_nodes.add(current_node_id)

        node = nodes[current_node_id]
        for edge_id in node.edge_ids:
            if edge_id not in component_edge_ids:
                continue
            if edge_id in visited_edges:
                continue

            visited_edges.add(edge_id)
            edge = edges[edge_id]

            # Determine if we need to reverse this edge
            # The end_node should be the current node (downstream direction)
            if edge.end_node_id != current_node_id:
                # Swap start and end
                edge.start_node_id, edge.end_node_id = edge.end_node_id, edge.start_node_id
                edge.reversed = True
                reversed_count += 1

            # Continue traversal from the upstream node
            upstream_node_id = edge.start_node_id
            if upstream_node_id not in visited_nodes:
                queue.append((upstream_node_id, edge_id))

    return reversed_count


# ── Stream order computation ──────────────────────────────────────────────────


def compute_upstream_lengths(
    nodes: Dict[int, GraphNode],
    edges: Dict[int, GraphEdge],
    component_edge_ids: Set[int],
    outlet_node_id: int,
) -> None:
    """Compute cumulative upstream length for each edge.

    After calling this function, each edge's upstream_length attribute contains
    the total length of all edges upstream of it (including itself).

    Args:
        nodes: Dictionary mapping node_id -> GraphNode.
        edges: Dictionary mapping edge_id -> GraphEdge.
        component_edge_ids: Set of edge IDs in this connected component.
        outlet_node_id: Node ID of the outlet.

    Methodology:
        Iterative post-order traversal using explicit stack to avoid
        recursion limits and handle cycles gracefully.
    """
    # Build adjacency: for each node, which edges feed into it
    upstream_edges: Dict[int, List[int]] = defaultdict(list)
    for edge_id in component_edge_ids:
        edge = edges[edge_id]
        # Edge goes from start_node (upstream) to end_node (downstream)
        upstream_edges[edge.end_node_id].append(edge_id)

    # Iterative post-order traversal
    computed: Set[int] = set()
    processing: Set[int] = set()  # Detect cycles

    for start_edge_id in component_edge_ids:
        if start_edge_id in computed:
            continue

        # Stack holds (edge_id, visited_children)
        stack: List[Tuple[int, bool]] = [(start_edge_id, False)]

        while stack:
            edge_id, children_visited = stack.pop()

            if edge_id in computed:
                continue

            if children_visited:
                # All children processed, compute this edge's length
                edge = edges[edge_id]
                upstream_node = edge.start_node_id

                feeding_edges = [
                    eid for eid in upstream_edges.get(upstream_node, [])
                    if eid != edge_id and eid in component_edge_ids
                ]

                total = edge.length
                for feeding_id in feeding_edges:
                    if feeding_id in computed:
                        total += edges[feeding_id].upstream_length

                edge.upstream_length = total
                computed.add(edge_id)
                processing.discard(edge_id)
            else:
                # First visit: check for cycle, then push children
                if edge_id in processing:
                    # Cycle detected, skip
                    continue

                processing.add(edge_id)
                edge = edges[edge_id]
                upstream_node = edge.start_node_id

                feeding_edges = [
                    eid for eid in upstream_edges.get(upstream_node, [])
                    if eid != edge_id and eid in component_edge_ids
                ]

                # Push self back with children_visited=True
                stack.append((edge_id, True))

                # Push children (feeding edges) to process first
                for feeding_id in feeding_edges:
                    if feeding_id not in computed and feeding_id not in processing:
                        stack.append((feeding_id, False))


def compute_stream_orders(
    nodes: Dict[int, GraphNode],
    edges: Dict[int, GraphEdge],
    component_edge_ids: Set[int],
    outlet_node_id: int,
    order_types: List[int],
    recursion_limit: int = 10000,
) -> None:
    """Compute stream orders for all edges in a component.

    Args:
        nodes: Dictionary mapping node_id -> GraphNode.
        edges: Dictionary mapping edge_id -> GraphEdge.
        component_edge_ids: Set of edge IDs in this connected component.
        outlet_node_id: Node ID of the outlet.
        order_types: List of order method constants (ORDER_HACK, ORDER_STRAHLER, ORDER_SHREVE).
        recursion_limit: Python recursion limit to set temporarily (unused, kept for API).

    Methodology:
        **Hack/Gravelius**: Main channel = 1, tributaries = parent + 1.
            At each confluence, the main channel follows the longest upstream path.
        **Strahler**: Leaf = 1. At confluence: if 2+ tributaries share max order i,
            result = i + 1; otherwise result = max(tributary orders).
        **Shreve**: Leaf = 1. At confluence: sum of all tributary orders.
    """
    # First compute upstream lengths if Hack ordering is requested
    if ORDER_HACK in order_types:
        compute_upstream_lengths(nodes, edges, component_edge_ids, outlet_node_id)

    # Build upstream adjacency: for each node, which edges feed into it
    upstream_edges: Dict[int, List[int]] = defaultdict(list)
    for edge_id in component_edge_ids:
        edge = edges[edge_id]
        upstream_edges[edge.end_node_id].append(edge_id)

    # Find the outlet edge(s) - edges whose end_node is the outlet
    outlet_edge_ids = [
        eid for eid in component_edge_ids
        if edges[eid].end_node_id == outlet_node_id
    ]

    if not outlet_edge_ids:
        return

    # Phase 1: Bottom-up traversal for Strahler/Shreve (post-order)
    # We need to process leaves first, then work down to outlet
    if ORDER_STRAHLER in order_types or ORDER_SHREVE in order_types:
        computed: Set[int] = set()
        processing: Set[int] = set()

        for start_edge_id in component_edge_ids:
            if start_edge_id in computed:
                continue

            stack: List[Tuple[int, bool]] = [(start_edge_id, False)]

            while stack:
                edge_id, children_visited = stack.pop()

                if edge_id in computed:
                    continue

                edge = edges[edge_id]
                upstream_node = edge.start_node_id

                tributaries = [
                    eid for eid in upstream_edges.get(upstream_node, [])
                    if eid != edge_id and eid in component_edge_ids
                ]

                if children_visited:
                    # All children processed, compute this edge's orders
                    if not tributaries:
                        # Leaf edge
                        if ORDER_STRAHLER in order_types:
                            edge.orders[ORDER_STRAHLER] = 1
                        if ORDER_SHREVE in order_types:
                            edge.orders[ORDER_SHREVE] = 1
                    else:
                        # Compute based on tributary orders
                        if ORDER_STRAHLER in order_types:
                            trib_strahler = [
                                edges[tid].orders.get(ORDER_STRAHLER, 1)
                                for tid in tributaries if tid in computed
                            ]
                            if trib_strahler:
                                max_order = max(trib_strahler)
                                if trib_strahler.count(max_order) >= 2:
                                    edge.orders[ORDER_STRAHLER] = max_order + 1
                                else:
                                    edge.orders[ORDER_STRAHLER] = max_order
                            else:
                                edge.orders[ORDER_STRAHLER] = 1

                        if ORDER_SHREVE in order_types:
                            trib_shreve = [
                                edges[tid].orders.get(ORDER_SHREVE, 1)
                                for tid in tributaries if tid in computed
                            ]
                            edge.orders[ORDER_SHREVE] = sum(trib_shreve) if trib_shreve else 1

                    computed.add(edge_id)
                    processing.discard(edge_id)
                else:
                    # First visit
                    if edge_id in processing:
                        # Cycle detected
                        continue

                    processing.add(edge_id)
                    stack.append((edge_id, True))

                    # Push tributaries to process first
                    for trib_id in tributaries:
                        if trib_id not in computed and trib_id not in processing:
                            stack.append((trib_id, False))

    # Phase 2: Top-down traversal for Hack ordering (from outlet to headwaters)
    if ORDER_HACK in order_types:
        hack_computed: Set[int] = set()

        # BFS from outlet edges, propagating hack_order
        # Queue holds (edge_id, hack_order)
        from collections import deque
        queue: deque = deque()

        for outlet_edge_id in outlet_edge_ids:
            queue.append((outlet_edge_id, 1))

        while queue:
            edge_id, hack_order = queue.popleft()

            if edge_id in hack_computed:
                continue

            hack_computed.add(edge_id)
            edge = edges[edge_id]
            edge.orders[ORDER_HACK] = hack_order

            # Find tributaries
            upstream_node = edge.start_node_id
            tributaries = [
                eid for eid in upstream_edges.get(upstream_node, [])
                if eid != edge_id and eid in component_edge_ids and eid not in hack_computed
            ]

            if not tributaries:
                continue

            # Determine main tributary by longest upstream length
            main_trib_id = tributaries[0]
            max_upstream_len = edges[tributaries[0]].upstream_length

            for trib_id in tributaries[1:]:
                if edges[trib_id].upstream_length > max_upstream_len:
                    max_upstream_len = edges[trib_id].upstream_length
                    main_trib_id = trib_id

            # Queue tributaries with appropriate hack orders
            for trib_id in tributaries:
                if trib_id == main_trib_id:
                    # Main tributary continues with same hack order
                    queue.append((trib_id, hack_order))
                else:
                    # Other tributaries get incremented hack order
                    queue.append((trib_id, hack_order + 1))


# ── Main processing function ──────────────────────────────────────────────────


def process_network(
    features: List[Tuple[int, Tuple[float, float], Tuple[float, float], float]],
    snap_tolerance: float = 1.0,
    order_types: Optional[List[int]] = None,
    recursion_limit: int = 10000,
) -> Tuple[Dict[int, GraphEdge], Dict[int, int], int]:
    """Process a stream network and compute stream orders.

    This is the main entry point for stream order computation.

    Args:
        features: List of tuples (feature_id, start_coord, end_coord, length).
        snap_tolerance: Endpoint snapping tolerance.
        order_types: List of order methods to compute. Defaults to [ORDER_HACK].
        recursion_limit: Python recursion limit for deep networks.

    Returns:
        Tuple of:
            - edges: Dict mapping feature_id -> GraphEdge with computed orders.
            - network_ids: Dict mapping feature_id -> network_id (component index).
            - reversed_count: Total number of edges that were reversed.

    Methodology:
        1. Build network graph from feature endpoints.
        2. Find connected components.
        3. For each component:
           a. Detect outlet node.
           b. Normalize edge directions toward outlet.
           c. Compute requested stream orders.
        4. Return results keyed by feature ID.
    """
    if order_types is None:
        order_types = [ORDER_HACK]

    if not features:
        return {}, {}, 0

    # Build graph
    nodes, edges = build_graph(features, snap_tolerance)

    # Find connected components
    components = find_connected_components(nodes, edges)

    # Process each component
    network_ids: Dict[int, int] = {}
    total_reversed = 0

    for component_idx, component_edge_ids in enumerate(components, start=1):
        # Assign network ID to all edges in component
        for edge_id in component_edge_ids:
            network_ids[edge_id] = component_idx

        # Find outlet
        outlet_node_id = find_outlet_node(nodes, edges, component_edge_ids)
        if outlet_node_id is None:
            continue

        # Normalize directions
        reversed_count = normalize_directions(
            nodes, edges, component_edge_ids, outlet_node_id
        )
        total_reversed += reversed_count

        # Compute orders
        compute_stream_orders(
            nodes, edges, component_edge_ids, outlet_node_id,
            order_types, recursion_limit
        )

    return edges, network_ids, total_reversed


def process_network_from_geometries(
    geometries: List[Tuple[int, Any]],
    snap_tolerance: float = 1.0,
    order_types: Optional[List[int]] = None,
    recursion_limit: int = 10000,
) -> Tuple[Dict[int, int], Dict[int, int], int, Dict[int, List[int]]]:
    """Process a stream network from full line geometries.

    This is the preferred entry point for stream order computation as it
    handles networks where lines meet at points along each other (not just
    at endpoints) by automatically splitting lines at junction points.

    Args:
        geometries: List of (feature_id, shapely_geometry) tuples.
        snap_tolerance: Distance tolerance for snapping endpoints.
        order_types: List of order methods to compute. Defaults to [ORDER_HACK].
        recursion_limit: Python recursion limit for deep networks.

    Returns:
        Tuple of:
            - orders: Dict mapping original_feature_id -> computed Hack order.
            - network_ids: Dict mapping original_feature_id -> network_id.
            - reversed_count: Total number of segments that were reversed.
            - segment_mapping: Dict mapping original_feature_id -> [segment_edge_ids]
              (for cases where a feature was split into multiple segments).

    Methodology:
        1. Find all intersection points between geometries.
        2. Split each geometry at junction points that lie along it.
        3. Build network graph from resulting segments.
        4. Process network to compute stream orders.
        5. Aggregate results back to original feature IDs (for split features,
           use the order of the segment closest to the outlet).
    """
    if order_types is None:
        order_types = [ORDER_HACK]

    if not geometries:
        return {}, {}, 0, {}

    # Split lines at junctions
    split_result = split_lines_at_junctions(geometries, snap_tolerance)
    
    # Build features list from split segments
    # Use a compound ID: (original_fid * 10000 + segment_index) to track origin
    features: List[Tuple[int, Tuple[float, float], Tuple[float, float], float]] = []
    segment_to_original: Dict[int, int] = {}
    original_to_segments: Dict[int, List[int]] = defaultdict(list)
    
    for original_fid, segments in split_result:
        for seg_idx, (start, end, length) in enumerate(segments):
            seg_id = original_fid * 100000 + seg_idx
            features.append((seg_id, start, end, length))
            segment_to_original[seg_id] = original_fid
            original_to_segments[original_fid].append(seg_id)
    
    if not features:
        return {}, {}, 0, {}
    
    # Build and process graph
    nodes, edges = build_graph(features, snap_tolerance)
    components = find_connected_components(nodes, edges)
    
    segment_network_ids: Dict[int, int] = {}
    total_reversed = 0
    
    for component_idx, component_edge_ids in enumerate(components, start=1):
        for edge_id in component_edge_ids:
            segment_network_ids[edge_id] = component_idx
        
        outlet_node_id = find_outlet_node(nodes, edges, component_edge_ids)
        if outlet_node_id is None:
            continue
        
        reversed_count = normalize_directions(
            nodes, edges, component_edge_ids, outlet_node_id
        )
        total_reversed += reversed_count
        
        compute_stream_orders(
            nodes, edges, component_edge_ids, outlet_node_id,
            order_types, recursion_limit
        )
    
    # Aggregate results back to original feature IDs
    # For Hack order: use the MINIMUM order among all segments (closest to main channel)
    orders: Dict[int, Dict[int, int]] = {}
    network_ids: Dict[int, int] = {}
    
    for original_fid in original_to_segments:
        seg_ids = original_to_segments[original_fid]
        
        # Collect orders from all segments
        seg_orders: Dict[int, List[int]] = defaultdict(list)
        seg_networks = []
        
        for seg_id in seg_ids:
            if seg_id in edges:
                edge = edges[seg_id]
                for order_type in order_types:
                    order_val = edge.orders.get(order_type)
                    if order_val is not None:
                        seg_orders[order_type].append(order_val)
            if seg_id in segment_network_ids:
                seg_networks.append(segment_network_ids[seg_id])
        
        # Use minimum order (most important/main channel segments)
        orders[original_fid] = {}
        for order_type in order_types:
            if seg_orders[order_type]:
                orders[original_fid][order_type] = min(seg_orders[order_type])
        
        # Use most common network ID
        if seg_networks:
            network_ids[original_fid] = max(set(seg_networks), key=seg_networks.count)
    
    return orders, network_ids, total_reversed, dict(original_to_segments)
