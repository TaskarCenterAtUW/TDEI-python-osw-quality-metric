from src.calculators.qm_calculator import QMCalculator, QualityMetricResult
from src.calculators.intersection_polygons import (
    DEFAULT_INTERSECTION_DISTANCE, DIAGNOSTIC_PROPERTY_NAMES,
    create_intersection_polygons, average_scores_to_tiles,
)
import argparse
import geopandas as gpd
import warnings
import networkx as nx
import logging
from pathlib import Path
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

logger = logging.getLogger(__name__)
SCORING_ALGORITHM_VERSION = "intersection-approaches-v1"


class QMXNLibCalculator(QMCalculator):
    def __init__(
        self, edges_file_path: str, output_file_path: str, polygon_file_path: str = None,
        partition_count: int = os.cpu_count(), *,
        intersection_distance: float = DEFAULT_INTERSECTION_DISTANCE,
        debug_intersection_polygons: bool = False,
    ):
        """
        Initializes the QMXNLibCalculator class.

        Args:
            edges_file_path (str): Path to the file containing the OSW edge data.
            output_file_path (str): Path to where the output quality metric file will be saved.
            polygon_file_path (str, optional): Existing output tiles. Otherwise,
                tiles are generated over the convex hull of the OSW edges.
            intersection_distance (float): Polygon side distance in meters.
            debug_intersection_polygons (bool): Save intermediate polygon scores
                beside the final output. Disabled by default for production.
        """
        self.edges_file_path = edges_file_path
        self.output_file_path = output_file_path
        self.polygon_file_path = polygon_file_path
        warnings.filterwarnings("ignore")
        self.default_projection = None
        self.output_projection = 'epsg:4326'
        self.precision = 1e-5
        self.partition_count = partition_count
        self.intersection_distance = intersection_distance
        self.debug_intersection_polygons = debug_intersection_polygons

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
    
    def group_G_pts(self, G, poly, side_roles=None):
        P = poly
        node_pts = [Point(x) for x in G.nodes()]
        boundary = list(P.exterior.coords)
        segments = [LineString([boundary[i], boundary[i + 1]]) for i in range(len(boundary) - 1)]
        if side_roles is None:
            # Direct callers with a bare polygon retain all-side scoring.
            roles = ["approach"] * len(segments)
        else:
            if not isinstance(side_roles, str):
                raise ValueError("Polygon side roles must be a comma-separated string")
            roles = side_roles.split(",")
            if (len(roles) != len(segments) or "approach" not in roles
                    or any(role not in {"approach", "cap"} for role in roles)):
                raise ValueError("Polygon side roles do not match its exterior segments")
        segment_point_map = {index: [] for index, role in enumerate(roles) if role == "approach"}
        for point in node_pts:
            # A corner shared with a cap belongs to the actual approach.
            for idx in segment_point_map:
                if segments[idx].distance(point) < self.precision:
                    segment_point_map[idx].append((point.x, point.y))
                    break
        return segment_point_map
    
    def edges_are_connected(self, G, e1_pts, e2_pts):
        for pt1 in e1_pts:
            for pt2 in e2_pts:
                if pt1 != pt2 and nx.has_path(G, pt1, pt2):
                    return True
        return False

    def algorithm_name(self):
        return "QMXNLibCalculator"

    def tile_tra_score(self, G, polygon, side_roles=None):
        # assign each point to a polygon line
        pts_line_map = self.group_G_pts(G, polygon, side_roles)
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

    def get_stats(self, polygon, G, gdf, side_roles=None):
        stats = {}
        try:
            n_total, n_connected, connected_pairs = self.tile_tra_score(G, polygon, side_roles)
            stats['tra_score'] = n_connected / n_total
            stats['total_edges'] = n_total
            stats['connect_edges'] = n_connected
        except Exception as e:
            print(f"Unexpected {e}, {type(e)} with polygon {polygon} when getting number of connected edge pairs")
            #traceback.print_exc()
            stats["tra_score"] = -1
            stats["total_edges"] = -1
            stats["connect_edges"] = -1
        return stats
    
    def get_measures_from_polygon(self, polygon, gdf, side_roles=None):
        # A multipart tile scores its largest part: one tile stays one output
        # row, and tile_tra_score walks one exterior ring.
        if isinstance(polygon, MultiPolygon):
            polygon = max(polygon.geoms, key=lambda part: part.area)
        # crop gdf to the polygon
        cropped_gdf = gpd.clip(gdf, polygon)
        
        G = self.graph_from_gdf(cropped_gdf)
        stats = self.get_stats(polygon, G, cropped_gdf, side_roles)
        return stats
    
    def qm_func(self, feature, gdf):
        poly = feature.geometry
        if (poly.geom_type == 'Polygon' or poly.geom_type == 'MultiPolygon'):
            measures = self.get_measures_from_polygon(poly, gdf, feature.get('side_roles'))
            # The row of a geometry-only frame has the geometry dtype, which
            # cannot hold a score, and pandas 2 no longer upcasts on enlargement.
            feature = feature.astype(object)
            feature.loc['tra_score'] = measures['tra_score']
            feature.loc['total_edges'] = measures.get('total_edges', -1)
            feature.loc['connect_edges'] = measures.get('connect_edges', -1)
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

    def score_intersections(self, intersection_gdf, edges_gdf):
        meta = intersection_gdf.iloc[:0].copy()
        for column in ["tra_score", "total_edges", "connect_edges"]:
            meta[column] = pd.Series(dtype="object")
        if intersection_gdf.empty:
            return meta
        if 'side_roles' not in intersection_gdf or intersection_gdf.side_roles.isna().any():
            raise ValueError("Intersection scoring requires explicit polygon side roles")
        partitions = max(1, min(self.partition_count, os.cpu_count() or 1, len(intersection_gdf)))
        df_dask = dask_geopandas.from_geopandas(intersection_gdf, npartitions=partitions)
        return df_dask.apply(self.qm_func, axis=1, meta=meta, gdf=edges_gdf).compute(
            scheduler='multiprocessing'
        )

    def debug_output_path(self):
        output = Path(self.output_file_path)
        return output.with_name(f"{output.stem}_intersection_scores.geojson")

    def calculate_quality_metric(self):
        try:
            gdf = gpd.read_file(self.edges_file_path)
            edges_lonlat = gdf if gdf.crs is None else gdf.to_crs(self.output_projection)
            # The hull of the edges as given: union_all would node them first.
            bounding_polygon = GeometryCollection(list(edges_lonlat.geometry.dropna())).convex_hull
            self.default_projection = self.work_crs(bounding_polygon)

            try:
                graph = fetch_seed_graph(bounding_polygon)
            except InsufficientResponseError:
                graph = None

            if self.polygon_file_path:
                tile_gdf = gpd.read_file(self.polygon_file_path)
            else:
                tile_gdf = self.create_tiles(bounding_polygon, graph, self.default_projection)

            if gdf.crs is None:
                gdf = gdf.set_crs(self.output_projection)
            gdf = gdf.to_crs(self.default_projection)
            tile_gdf = tile_gdf.to_crs(self.default_projection)
            tile_gdf = tile_gdf[['geometry']]
            # Reuse the graph that seeded the tiles; never fetch a second OSM state.
            intersection_gdf = create_intersection_polygons(
                graph, self.default_projection, self.intersection_distance,
            )
            intersection_scores = self.score_intersections(intersection_gdf, gdf)
            output = average_scores_to_tiles(intersection_scores, tile_gdf)
            if self.debug_intersection_polygons:
                debug_output = intersection_scores.rename(columns=DIAGNOSTIC_PROPERTY_NAMES)
                debug_output['ext:scoring_algorithm_version'] = SCORING_ALGORITHM_VERSION
                debug_output.to_crs(self.output_projection).to_file(
                    self.debug_output_path(), driver='GeoJSON',
                )
            logger.info(
                "Scored %d intersection polygons; %d/%d tiles have assigned intersections",
                len(intersection_scores), int((output['intersection_count'] > 0).sum()), len(output),
            )
            if not self.polygon_file_path:
                output["tile_algorithm_version"] = TILE_ALGORITHM_VERSION
            output = output.rename(columns=DIAGNOSTIC_PROPERTY_NAMES)
            output['ext:scoring_algorithm_version'] = SCORING_ALGORITHM_VERSION
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
    parser = argparse.ArgumentParser(description='Average intersection polygon quality scores onto tiles.')
    parser.add_argument('edges_file')
    parser.add_argument('output_file')
    parser.add_argument('tile_file', nargs='?', help='Optional precomputed intersection tiles.')
    parser.add_argument('--intersection-distance', type=float, default=DEFAULT_INTERSECTION_DISTANCE)
    parser.add_argument('--debug-intersection-polygons', action='store_true')
    args = parser.parse_args()
    calculator = QMXNLibCalculator(
        args.edges_file, args.output_file, args.tile_file,
        intersection_distance=args.intersection_distance,
        debug_intersection_polygons=args.debug_intersection_polygons,
    )
    print(calculator.calculate_quality_metric())
