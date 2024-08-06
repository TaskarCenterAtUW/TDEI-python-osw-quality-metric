import os
os.environ['USE_PYGEOS'] = '0'
import networkx as nx
import sys
import copy
import traceback
import geopandas as gpd
import osmnx as ox
import dask_geopandas
import geonetworkx as gnx
from shapely import Point, LineString, MultiLineString, Polygon, MultiPolygon
from tqdm import tqdm
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


def calculate_xn_qm(osw_edge_file_path: str, xn_polygon_path: str, qm_file_path: str):
    """
    Calculate and save quality metric for given OSW edge data on intersetion define by the polygon file.

    Parameters:
    osw_edge_file_path (str): Path to the OSW edge file.
    xn_polygon_path (str): Path to the intersection polygon file.
    qm_file_path (str): Path where the output quality metric file will be saved.
    """

    try:
        gdf = gpd.read_file(osw_edge_file_path)
        tile_gdf = gpd.read_file(xn_polygon_path)

        gdf = gdf.to_crs(PROJ)
        tile_gdf = tile_gdf.to_crs(PROJ)

        tile_gdf = tile_gdf[['geometry']]

        # compute local stats
        df_dask = dask_geopandas.from_geopandas(tile_gdf, npartitions=64)

        print('computing stats...')
        output = df_dask.apply(qm_func, axis=1, meta=[
            ('geometry', 'geometry'),
            ('tra_score', 'object'),
            ], gdf=gdf).compute(scheduler='multiprocessing')

        output.to_file(qm_file_path, driver='GeoJSON')
    except Exception as e:
        print(f"Error {e} occurred when calculating qualiity metric for data {osw_edge_file_path} on {xn_polygon_path}")
        #traceback.print_exc()
        stats["tra_score"] = -1
        return -1

    return None


if __name__ == '__main__':
    osw_edge_file_path = sys.argv[1]
    xn_polygon_path = sys.argv[2]
    qm_file_path = sys.argv[3]

    print(calculate_xn_qm(osw_edge_file_path, xn_polygon_path, qm_file_path))
