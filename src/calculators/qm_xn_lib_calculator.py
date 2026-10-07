from src.calculators.qm_calculator import QMCalculator, QualityMetricResult
import geopandas as gpd
import sys
import warnings
import networkx as nx
import traceback
from flagstones import FallbackGrid
from flagstones.clip import repair_reprojected
from flagstones.crs import utm_crs_for
from flagstones.geo import tiles_to_geodataframe
from flagstones.osm import InsufficientResponseError, fetch_seed_graph, tiles_for_polygon
from flagstones.pipeline import TILE_ALGORITHM_VERSION
import dask_geopandas 
from shapely import Point, LineString, MultiLineString, Polygon, MultiPolygon, GeometryCollection
from shapely.geometry.base import BaseGeometry
import itertools
import numpy as np
import pandas as pd
import os


class QMXNLibCalculator(QMCalculator):
    def __init__(self, edges_file_path:str, output_file_path:str, polygon_file_path:str=None, partition_count:int = os.cpu_count()):
        """
        Initializes the QMXNLibCalculator class.

        Args:
            edges_file_path (str): Path to the file containing the OSW edge data.
            output_file_path (str): Path to where the output quality metric file will be saved.
            polygon_file_path (str, optional): Path to the intersection polygon file. If not provided, will use the polygon computed from the convex hull of OSW edge data. Defaults to None.
        """
        self.edges_file_path = edges_file_path
        self.output_file_path = output_file_path
        self.polygon_file_path = polygon_file_path
        warnings.filterwarnings("ignore")
        self.default_projection = None
        self.output_projection = 'epsg:4326'
        self.precision = 1e-5
        self.partition_count = partition_count

    def add_edges_from_linestring(self, graph, linestring, edge_attrs):
        points = list(linestring.coords)
        for start, end in zip(points[:-1], points[1:]):
            graph.add_edge(start, end, **edge_attrs)
    
    def graph_from_gdf(self, gdf):
        G = nx.Graph()
        for index, row in gdf.iterrows():
            geom = row.geometry
            if isinstance(geom, LineString):
                self.add_edges_from_linestring(G, geom, row.to_dict())
            elif isinstance(geom, MultiLineString):
                for linestring in geom.geoms:
                    self.add_edges_from_linestring(G, linestring, row.to_dict())
        return G
    
    def group_G_pts(self, G, poly):
        P = poly
        node_pts = [Point(x) for x in G.nodes()]
        boundary = list(P.exterior.coords)
        segments = [LineString([boundary[i], boundary[i + 1]]) for i in range(len(boundary) - 1)]
        segment_point_map = {index: [] for index in range(len(segments))}
        for point in node_pts:
            for idx, segment in enumerate(segments):
                if segment.distance(point) < self.precision:
                    segment_point_map[idx].append((point.x, point.y))
                    break
        return segment_point_map
    
    def edges_are_connected(self, G, e1_pts, e2_pts):
        for pt1 in e1_pts:
            for pt2 in e2_pts:
                if nx.has_path(G, pt1, pt2):
                    return True
        return False

    def algorithm_name(self):
        return "QMXNLibCalculator"

    def tile_tra_score(self, G, polygon):
        # assign each point to a polygon line
        pts_line_map = self.group_G_pts(G, polygon)
        boundary_nodes = [item for sublist in pts_line_map.values() for item in sublist]

        # find all pair of edges
        edge_pairs = list(itertools.combinations_with_replacement(pts_line_map.keys(), 2))

        n_total = len(edge_pairs)
        n_connected = 0
        connected_pairs = list()
        for pair in edge_pairs:
            is_connected = self.edges_are_connected(G, pts_line_map[pair[0]], pts_line_map[pair[1]])
            if is_connected:
                n_connected += 1
                connected_pairs.append(pair)
        return n_total, n_connected, connected_pairs

    def get_stats(self, polygon, G, gdf):
        stats = {}
        undirected_g = nx.Graph(G)

        try:
            n_total, n_connected, connected_pairs = self.tile_tra_score(G, polygon)
            stats['tra_score'] = n_connected / n_total
        except Exception as e:
            print(f"Unexpected {e}, {type(e)} with polygon {polygon} when getting number of connected edge pairs")
            #traceback.print_exc()
            stats["tra_score"] = -1
        return stats
    
    def get_measures_from_polygon(self, polygon, gdf):
        # A multipart tile scores its largest part: one tile stays one output
        # row, and tile_tra_score walks one exterior ring.
        if isinstance(polygon, MultiPolygon):
            polygon = max(polygon.geoms, key=lambda part: part.area)
        # crop gdf to the polygon
        cropped_gdf = gpd.clip(gdf, polygon)
        
        G = self.graph_from_gdf(cropped_gdf)
        stats = self.get_stats(polygon, G, cropped_gdf)
        return stats
    
    def qm_func(self, feature, gdf):
        poly = feature.geometry
        if (poly.geom_type == 'Polygon' or poly.geom_type == 'MultiPolygon'):
            measures = self.get_measures_from_polygon(poly, gdf)
            # The row of a geometry-only frame has the geometry dtype, which
            # cannot hold a score, and pandas 2 no longer upcasts on enlargement.
            feature = feature.astype(object)
            feature.loc['tra_score'] = measures['tra_score']
            return feature
        else:
            return feature
    
    def work_crs(self, bounding_polygon: BaseGeometry) -> str:
        """The UTM zone of the data's centroid, where tiling and scoring run."""
        centre = bounding_polygon.centroid
        return utm_crs_for(centre.x, centre.y)

    def create_tiles(
        self, bounding_polygon: BaseGeometry, graph: nx.MultiDiGraph | None, crs: str
    ) -> gpd.GeoDataFrame:
        """Tiles covering `bounding_polygon`, geometry only, in `crs`.

        `bounding_polygon` is in EPSG:4326. The rows are the intersection
        tiles over `graph`, then fallback grid cells over the ground they
        leave. `graph` is None when the hull holds no road, and fallback
        cells then cover all of it.
        """
        tile_set = tiles_for_polygon(bounding_polygon, graph, crs=crs, fallback=FallbackGrid())
        return tiles_to_geodataframe(tile_set, to_crs=crs)[["geometry"]]

    def calculate_quality_metric(self):
        try:
            gdf = gpd.read_file(self.edges_file_path)
            edges_lonlat = gdf if gdf.crs is None else gdf.to_crs(self.output_projection)
            # The hull of the edges as given: union_all would node them first.
            bounding_polygon = GeometryCollection(list(edges_lonlat.geometry.dropna())).convex_hull
            self.default_projection = self.work_crs(bounding_polygon)

            if self.polygon_file_path:
                tile_gdf = gpd.read_file(self.polygon_file_path)
            else:
                try:
                    graph = fetch_seed_graph(bounding_polygon)
                except InsufficientResponseError:
                    # No road inside the hull: fallback cells tile all of it.
                    graph = None
                tile_gdf = self.create_tiles(bounding_polygon, graph, self.default_projection)
            
            gdf = gdf.to_crs(self.default_projection)
            tile_gdf = tile_gdf.to_crs(self.default_projection)
            tile_gdf = tile_gdf[['geometry']]
            no_of_cores = min(self.partition_count, os.cpu_count())
            df_dask = dask_geopandas.from_geopandas(tile_gdf, npartitions=no_of_cores)

            output = df_dask.apply(self.qm_func,axis=1, meta=[
                ('geometry', 'geometry'),
                ('tra_score', 'object')
            ], gdf=gdf).compute(scheduler='multiprocessing')
            if not self.polygon_file_path:
                output["tile_algorithm_version"] = TILE_ALGORITHM_VERSION
            output = output.to_crs(self.output_projection) # The output should be in WGS84 (epsg:4326)
            if not self.polygon_file_path:
                # A fallback cell can keep a near-pinched vertex that turns
                # self-intersecting once reprojected to WGS84:
                output = output.set_geometry([repair_reprojected(g) for g in output.geometry], crs=output.crs)
            output.to_file(self.output_file_path, driver='GeoJSON')
            return QualityMetricResult(success=True, message='QMXNLibCalculator', output_file=self.output_file_path)

        except Exception as e:
            print(f"Error {e} occurred when calculating quality metric for data {self.edges_file_path}")
            return QualityMetricResult(success=False, message=f'Error: {e}', output_file="")


if __name__ == '__main__':
    osw_edge_file_path = sys.argv[1]  # First argument: OSW edge file path
    qm_file_path = sys.argv[2]        # Second argument: Quality metric output file path

    # Check if the optional third argument (xn_polygon_path) is provided
    if len(sys.argv) > 3:
        xn_polygon_path = sys.argv[3]  # Third argument: Intersection polygon file path (optional)
        qm_calculator = QMXNLibCalculator(osw_edge_file_path, qm_file_path, xn_polygon_path)
        print(qm_calculator.calculate_quality_metric())
         
    else:
        # If the third argument is not provided, call without xn_polygon_path
        qm_calculator = QMXNLibCalculator(osw_edge_file_path, qm_file_path)
        print(qm_calculator.calculate_quality_metric())
