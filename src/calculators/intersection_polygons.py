"""Local intersection scoring polygons and aggregation onto existing tiles."""

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
from shapely import LineString, MultiLineString, MultiPoint, Point


DEFAULT_INTERSECTION_DISTANCE = 50.0
CLUSTER_DISTANCE = 20.0
DIRECTION_TOLERANCE_DEGREES = 10.0
MAX_DIRECTION_GAP_DEGREES = 135.0
POLYGON_COLUMNS = [
    "intersection_id", "degree", "side_count", "cap_side_count", "polygon_distance_m",
]
DIAGNOSTIC_PROPERTY_NAMES = {
    column: f"ext:{column}"
    for column in POLYGON_COLUMNS + ["intersection_count", "total_edges", "connect_edges"]
}


def normalize_vector(dx, dy):
    length = float(np.hypot(dx, dy))
    return (dx / length, dy / length) if length else None


def direction_from_edge(edge, nodes, node_id):
    center = nodes.loc[node_id].geometry
    geometry = edge.get("geometry")
    if isinstance(geometry, MultiLineString):
        lines = [line for line in geometry.geoms if len(line.coords) >= 2]
        geometry = min(lines, key=lambda line: min(
            Point(line.coords[0]).distance(center), Point(line.coords[-1]).distance(center)
        )) if lines else None
    if isinstance(geometry, LineString) and not geometry.is_empty:
        coords = list(geometry.coords)
        if Point(coords[0]).distance(center) <= Point(coords[-1]).distance(center):
            targets = coords[1:]
        else:
            targets = coords[-2::-1]
        for x, y in targets:
            direction = normalize_vector(x - center.x, y - center.y)
            if direction is not None:
                return direction

    other_id = edge["v"] if edge["u"] == node_id else edge["u"]
    if other_id in nodes.index:
        other = nodes.loc[other_id].geometry
        return normalize_vector(other.x - center.x, other.y - center.y)
    return None


def deduplicate_directions(directions):
    tolerance = np.deg2rad(DIRECTION_TOLERANCE_DEGREES)
    groups = []
    for dx, dy in directions:
        angle = np.arctan2(dy, dx)
        for group in groups:
            group_angle = np.arctan2(group[1], group[0])
            difference = abs(np.arctan2(np.sin(angle - group_angle), np.cos(angle - group_angle)))
            if difference <= tolerance:
                group[0] += dx
                group[1] += dy
                break
        else:
            groups.append([dx, dy])
    return [normalize_vector(dx, dy) for dx, dy in groups]


def add_closing_cap_directions(directions):
    if len(directions) < 3:
        return list(directions), 0
    augmented = list(directions)
    cap_count = 0
    max_gap = np.deg2rad(MAX_DIRECTION_GAP_DEGREES)
    while True:
        angles = sorted(np.arctan2(dy, dx) % (2 * np.pi) for dx, dy in augmented)
        gaps = np.diff(angles + [angles[0] + 2 * np.pi])
        index = int(np.argmax(gaps))
        if gaps[index] <= max_gap + 1e-9:
            return augmented, cap_count
        angle = angles[index] + gaps[index] / 2
        augmented.append((float(np.cos(angle)), float(np.sin(angle))))
        cap_count += 1


def polygon_from_directions(center, directions, distance):
    vertices = []
    tolerance = max(1e-7, distance * 1e-9)
    for index, first in enumerate(directions):
        for second in directions[index + 1:]:
            matrix = np.array([first, second], dtype=float)
            if abs(np.linalg.det(matrix)) <= 1e-10:
                continue
            offset = np.linalg.solve(matrix, np.array([distance, distance]))
            if all(np.dot(direction, offset) <= distance + tolerance for direction in directions):
                vertices.append((center.x + offset[0], center.y + offset[1]))
    if len(vertices) < 3:
        return None
    polygon = MultiPoint(vertices).convex_hull
    if polygon.geom_type != "Polygon" or polygon.is_empty or polygon.area == 0 or not polygon.is_valid:
        return None
    return polygon


def create_intersection_polygons(graph, crs, distance=DEFAULT_INTERSECTION_DISTANCE):
    """Use the original tile seed graph, measuring all distances in its work CRS."""
    if not np.isfinite(distance) or distance <= 0:
        raise ValueError("intersection_distance must be a positive finite number")
    empty = gpd.GeoDataFrame(columns=POLYGON_COLUMNS + ["geometry"], geometry="geometry", crs=crs)
    if graph is None or graph.number_of_edges() == 0:
        return empty

    projected = ox.projection.project_graph(graph, to_crs=crs)
    nodes, edges = ox.graph_to_gdfs(projected)
    incident = {node_id: [] for node_id in nodes.index}
    seen = set()
    # Index undirected physical edges once rather than scanning all edges for each node.
    for _, edge in edges.reset_index().iterrows():
        u, v = edge["u"], edge["v"]
        pair = frozenset((u, v))
        if u == v or pair in seen:
            continue
        seen.add(pair)
        incident[u].append(edge)
        incident[v].append(edge)

    candidates = set()
    for node_id, node_edges in incident.items():
        directions = [direction_from_edge(edge, nodes, node_id) for edge in node_edges]
        if len(deduplicate_directions([d for d in directions if d is not None])) >= 3:
            candidates.add(node_id)
    clusters = nx.Graph()
    clusters.add_nodes_from(sorted(candidates, key=str))
    for u in candidates:
        for edge in incident[u]:
            v = edge["v"] if edge["u"] == u else edge["u"]
            if v in candidates and nodes.loc[u].geometry.distance(nodes.loc[v].geometry) <= CLUSTER_DISTANCE:
                clusters.add_edge(u, v)

    records = []
    for members in nx.connected_components(clusters):
        directions = []
        seen = set()
        for node_id in sorted(members, key=str):
            for edge in incident[node_id]:
                u, v = edge["u"], edge["v"]
                pair = frozenset((u, v))
                if (u in members and v in members) or pair in seen:
                    continue
                seen.add(pair)
                direction = direction_from_edge(edge, nodes, node_id)
                if direction is not None:
                    directions.append(direction)
        directions = deduplicate_directions(directions)
        if len(directions) < 3:
            continue
        center = MultiPoint([nodes.loc[node_id].geometry for node_id in members]).centroid
        polygon_directions, cap_count = add_closing_cap_directions(directions)
        polygon = polygon_from_directions(center, polygon_directions, distance)
        if polygon is not None:
            records.append({
                "intersection_id": "|".join(str(node_id) for node_id in sorted(members, key=str)),
                "degree": len(directions),
                "side_count": len(polygon.exterior.coords) - 1,
                "cap_side_count": cap_count,
                "polygon_distance_m": float(distance),
                "geometry": polygon,
            })
    return gpd.GeoDataFrame(records, geometry="geometry", crs=crs) if records else empty


def average_scores_to_tiles(intersections, tiles):
    """Average valid scores; otherwise-unassigned tiles use polygon overlaps."""
    output = tiles.copy().reset_index(drop=True)
    output["tra_score"] = -1.0
    output["intersection_count"] = 0
    if intersections.empty or output.empty:
        return output

    intersections = intersections.to_crs(output.crs).reset_index(drop=True)
    points = intersections[["geometry", "tra_score"]].copy()
    points["geometry"] = points.geometry.representative_point()
    joined = gpd.sjoin(points, output[["geometry"]], how="inner", predicate="intersects")
    missing = output.index.difference(joined["index_right"].unique())
    if len(missing):
        overlaps = gpd.sjoin(
            intersections[["geometry", "tra_score"]], output.loc[missing, ["geometry"]],
            how="inner", predicate="intersects",
        )
        joined = pd.concat([joined, overlaps])
    if joined.empty:
        return output

    counts = joined.groupby("index_right").size()
    output.loc[counts.index, "intersection_count"] = counts
    values = pd.to_numeric(joined["tra_score"], errors="coerce")
    valid = joined.loc[values.between(0, 1)].copy()
    valid["tra_score"] = values.loc[values.between(0, 1)]
    averages = valid.groupby("index_right")["tra_score"].mean()
    output.loc[averages.index, "tra_score"] = averages
    return output
