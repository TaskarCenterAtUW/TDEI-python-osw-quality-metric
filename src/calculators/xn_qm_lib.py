import os
os.environ['USE_PYGEOS'] = '0' # Got to move it somewhere else
import networkx as nx
import sys
import traceback
import geopandas as gpd
import geonetworkx as gnx
import osmnx as ox
import dask_geopandas
from shapely import Point, LineString, MultiLineString, Polygon, MultiPolygon
from shapely.ops import voronoi_diagram
import itertools
import numpy as np
import pandas as pd

import warnings
warnings.filterwarnings("ignore")

PROJ = 'epsg:26910'
PRES = 1e-5


def add_edges_from_linestring(graph, linestring, edge_attrs):
    points = list(linestring.coords)
    #points = [(round(x, 0), round(y, 0)) for x, y in points] #round to meter
    for start, end in zip(points[:-1], points[1:]):
        graph.add_edge(start, end, **edge_attrs)


def graph_from_gdf(gdf):
    # Initialize an empty graph
    G = nx.Graph()

    # Iterate through each row in the GeoDataFrame
    for index, row in gdf.iterrows():
        geom = row.geometry
        if isinstance(geom, LineString):
            add_edges_from_linestring(G, geom, row.to_dict())
        elif isinstance(geom, MultiLineString):
            for linestring in geom.geoms:
                add_edges_from_linestring(G, linestring, row.to_dict())
    return G


def group_G_pts(G, poly):
    P = poly
    
    node_pts = [Point(x) for x in G.nodes()]
    # Get polygon boundary as a list of line segments
    boundary = list(P.boundary.coords)
    segments = [LineString([boundary[i], boundary[i + 1]]) for i in range(len(boundary) - 1)]

    # Dictionary to hold points grouped by line segments
    segment_point_map = {index: [] for index in range(len(segments))}

    # Group points by which line segment they fall on
    for point in node_pts:
        for idx, segment in enumerate(segments):
            if segment.distance(point) < PRES:  # Small threshold for precision issues
                segment_point_map[idx].append((point.x, point.y))
                break
    return segment_point_map


def edges_are_connected(G, e1_pts, e2_pts):
    for pt1 in e1_pts:
        for pt2 in e2_pts: 
            # node self to self should be count at connected
            if pt1 != pt2:
                if nx.has_path(G, pt1, pt2):
                    return True
    return False 


def tile_tra_score(G, polygon):
    # assign each point to an polygon line
    pts_line_map = group_G_pts(G, polygon) 
    boundary_nodes = [item for sublist in pts_line_map.values() for item in sublist]

    # find all pair of edges
    edge_pairs = list(itertools.combinations_with_replacement(pts_line_map.keys(), 2))

    n_total = len(edge_pairs)
    n_connected = 0
    connected_pairs = list()
    for pair in edge_pairs:
        is_connected = edges_are_connected(G, pts_line_map[pair[0]], pts_line_map[pair[1]])
        if is_connected:
            connected_pairs.append(pair)
            n_connected += 1

    return n_total, n_connected, connected_pairs 


def get_stats(polygon, G, gdf):
    stats = {}
    undirected_g = nx.Graph(G)
    
    # edge-to-edge connected paths
    try:
        n_total, n_connected, connected_pairs = tile_tra_score(undirected_g, polygon)
        stats["tra_score"] = n_connected/n_total
        
    except Exception as e:
        print(f"Unexpected {e}, {type(e)} with polygon {polygon} when getting number of connected edge pairs")
        #traceback.print_exc()
        stats["tra_score"] = -1

    return stats


def get_measures_from_polygon(polygon, gdf):
    if isinstance(polygon, MultiPolygon) and len(polygon.geoms)==1:
        polygon = polygon.geoms[0]

    # crop gdf to the polygon
    cropped_gdf = gpd.clip(gdf, polygon)

    G = graph_from_gdf(cropped_gdf) 
    stats = get_stats(polygon, G, cropped_gdf)
    
    return stats


def qm_func(feature, gdf):
    poly = feature.geometry
    if (poly.geom_type == "Polygon" or poly.geom_type == "MultiPolygon"):
        measures = get_measures_from_polygon(poly, gdf)
        feature.loc['tra_score'] = measures["tra_score"]
        return feature


def create_voronoi_diagram(G_roads_simplified, bounds):
    # first thin the nodes 
    gdf_roads_simplified = gnx.graph_edges_to_gdf(G_roads_simplified)
    voronoi = voronoi_diagram(gdf_roads_simplified.boundary.unary_union, envelope = bounds)
    voronoi_gdf = gpd.GeoDataFrame({"geometry": voronoi.geoms})
    voronoi_gdf = voronoi_gdf.set_crs(gdf_roads_simplified.crs)
    voronoi_gdf_clipped = gpd.clip(voronoi_gdf, bounds)
    voronoi_gdf_clipped = voronoi_gdf_clipped.to_crs(PROJ)
    
    return voronoi_gdf_clipped


def calculate_xn_qm(osw_edge_file_path: str, qm_file_path: str, xn_polygon_path: str = None):
    """
    Calculate and save quality metric for given OSW edge data on an intersection polygons.

    Parameters:
    osw_edge_file_path (str): Path to the OSW edge file.
    qm_file_path (str): Path where the output quality metric file will be saved.
    xn_polygon_path (str, optional): Path to the intersection polygon file. If not provided, will use the polygon files computed from the convex hull of OSW edge data.
    """
    try:
        gdf = gpd.read_file(osw_edge_file_path)

        if xn_polygon_path:
            # Use the provided polygon file
            tile_gdf = gpd.read_file(xn_polygon_path)
        else:
            # Calculate bounding polygon from OSW edge data
            unified_geom = gdf.unary_union
            bounding_polygon = unified_geom.convex_hull
            g_roads_simplified = ox.graph.graph_from_polygon(bounding_polygon, network_type='drive', simplify=True, retain_all=True)
            tile_gdf = create_voronoi_diagram(g_roads_simplified, bounding_polygon)

        # Ensure CRS consistency
        gdf = gdf.to_crs(PROJ)
        tile_gdf = tile_gdf.to_crs(PROJ)
        tile_gdf = tile_gdf[['geometry']]

        # Compute local stats using dask-geopandas
        no_of_cores = os.cpu_count()
        df_dask = dask_geopandas.from_geopandas(tile_gdf, npartitions=no_of_cores)

        # print('computing stats...')
        output = df_dask.apply(qm_func, axis=1, meta=[
            ('geometry', 'geometry'),
            ('tra_score', 'object'),
        ], gdf=gdf).compute(scheduler='multiprocessing')

        output.to_file(qm_file_path, driver='GeoJSON')

    except Exception as e:
        print(f"Error {e} occurred when calculating quality metric for data {osw_edge_file_path}")
        return -1

    return None


if __name__ == '__main__':
    osw_edge_file_path = sys.argv[1]  # First argument: OSW edge file path
    qm_file_path = sys.argv[2]        # Second argument: Quality metric output file path

    # Check if the optional third argument (xn_polygon_path) is provided
    if len(sys.argv) > 3:
        xn_polygon_path = sys.argv[3]  # Third argument: Intersection polygon file path (optional)
        print(calculate_xn_qm(osw_edge_file_path, qm_file_path, xn_polygon_path=xn_polygon_path))
    else:
        # If the third argument is not provided, call without xn_polygon_path
        print(calculate_xn_qm(osw_edge_file_path, qm_file_path))
