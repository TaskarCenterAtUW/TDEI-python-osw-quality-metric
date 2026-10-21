import unittest

import geopandas as gpd
import networkx as nx
import numpy as np
from shapely import LineString, Point, box

from src.calculators.intersection_polygons import (
    add_closing_cap_directions, average_scores_to_tiles, create_intersection_polygons,
    deduplicate_directions, polygon_from_directions,
)
from src.calculators.qm_xn_lib_calculator import QMXNLibCalculator


def road_graph(positions, pairs, crs="EPSG:32610"):
    graph = nx.MultiDiGraph(crs=crs, simplified=True)
    for node_id, (x, y) in positions.items():
        graph.add_node(node_id, x=x, y=y)
    for u, v in pairs:
        for start, end in [(u, v), (v, u)]:
            graph.add_edge(start, end, geometry=LineString([positions[start], positions[end]]))
    return graph


class TestIntersectionPolygons(unittest.TestCase):
    def test_split_and_rejoin_roads_preserve_both_three_way_junctions(self):
        positions = {
            0: (500000, 5200000), 1: (500200, 5200000),
            2: (499900, 5200000), 3: (500300, 5200000),
        }
        graph = road_graph(positions, [(0, 2), (1, 3)])
        for offset in [100, -100]:
            coords = [
                positions[0], (500000, 5200000 + offset),
                (500200, 5200000 + offset), positions[1],
            ]
            graph.add_edge(0, 1, geometry=LineString(coords))
            graph.add_edge(1, 0, geometry=LineString(coords[::-1]))

        polygons = create_intersection_polygons(graph, 'EPSG:32610')
        self.assertEqual(set(polygons.intersection_id), {'0', '1'})
        self.assertEqual(polygons.degree.tolist(), [3, 3])
        self.assertTrue(polygons.is_valid.all())
        self.assertTrue(polygons.set_index('intersection_id').loc['0'].geometry.equals(
            box(499950, 5199950, 500050, 5200050),
        ))
        self.assertEqual(graph.number_of_edges(), 8)

    def test_cluster_keeps_distinct_external_roads_with_shared_endpoints(self):
        positions = {
            0: (500000, 5200000), 1: (500014, 5200000),
            2: (500150, 5200000), 3: (500014, 5200100),
            4: (500114, 5200000), 5: (499900, 5200000),
        }
        graph = road_graph(positions, [(0, 1), (0, 5), (1, 3), (1, 4)])
        for offset in [100, -100]:
            coords = [
                positions[0], (500000, 5200000 + offset),
                (500150, 5200000 + offset), positions[2],
            ]
            graph.add_edge(0, 2, geometry=LineString(coords))
            graph.add_edge(2, 0, geometry=LineString(coords[::-1]))

        polygons = create_intersection_polygons(graph, 'EPSG:32610')
        self.assertEqual(len(polygons), 1)
        row = polygons.iloc[0]
        self.assertEqual(row.intersection_id, '0|1')
        self.assertEqual((row.degree, row.side_count, row.cap_side_count), (4, 4, 0))
        self.assertTrue(row.geometry.equals(box(499957, 5199950, 500057, 5200050)))

    def test_reverse_copies_do_not_bias_merged_approach_direction(self):
        angle = np.deg2rad(5)
        graph = road_graph(
            {0: (500000, 5200000), 1: (500000, 5200100),
             2: (500100, 5200000), 3: (499900, 5200000),
             4: (500000, 5199900),
             5: (500000 + 100 * np.sin(angle), 5200000 + 100 * np.cos(angle))},
            [(0, 1), (0, 2), (0, 3), (0, 4), (0, 5)],
        )
        expected = create_intersection_polygons(graph, 'EPSG:32610').iloc[0]
        # Distinct roads within 10 degrees still merge to one approach.
        self.assertEqual(expected.degree, 4)
        for _ in range(3):
            graph.add_edge(1, 0, geometry=LineString([(500000, 5200100), (500000, 5200000)]))
        actual = create_intersection_polygons(graph, 'EPSG:32610').iloc[0]
        self.assertEqual(actual.degree, expected.degree)
        self.assertTrue(actual.geometry.equals_exact(expected.geometry, 1e-8))

    def test_four_way_intersection_has_four_perpendicular_sides(self):
        graph = road_graph(
            {0: (500000, 5200000), 1: (500100, 5200000), 2: (500000, 5200100),
             3: (499900, 5200000), 4: (500000, 5199900)},
            [(0, 1), (0, 2), (0, 3), (0, 4)],
        )
        original_crs = graph.graph['crs']
        polygons = create_intersection_polygons(graph, 'EPSG:32610')
        self.assertEqual(len(polygons), 1)
        row = polygons.iloc[0]
        self.assertEqual((row.degree, row.side_count, row.cap_side_count), (4, 4, 0))
        self.assertTrue(row.geometry.equals(box(499950, 5199950, 500050, 5200050)))
        self.assertEqual(graph.graph['crs'], original_crs)

    def test_short_internal_edge_merges_two_intersections_into_one_trapezoid(self):
        graph = road_graph(
            {0: (500000, 5200000), 1: (500000, 5200014),
             2: (500100, 5200000), 3: (500000, 5199900),
             4: (500000, 5200114), 5: (499920, 5200074)},
            [(0, 1), (0, 2), (0, 3), (1, 4), (1, 5)],
        )
        polygons = create_intersection_polygons(graph, 'EPSG:32610')
        self.assertEqual(len(polygons), 1)
        row = polygons.iloc[0]
        self.assertEqual(row.intersection_id, '0|1')
        self.assertEqual((row.degree, row.side_count, row.cap_side_count), (4, 4, 0))
        self.assertTrue(row.geometry.is_valid)
        self.assertTrue(row.geometry.contains(Point(500000, 5200007)))

    def test_nearby_disconnected_intersections_are_not_merged(self):
        positions = {
            0: (500000, 5200000), 1: (500010, 5200000),
            2: (499900, 5200000), 3: (500000, 5200100), 4: (500000, 5199900),
            5: (500110, 5200000), 6: (500010, 5200100), 7: (500010, 5199900),
        }
        graph = road_graph(positions, [(0, 2), (0, 3), (0, 4), (1, 5), (1, 6), (1, 7)])
        self.assertEqual(len(create_intersection_polygons(graph, 'EPSG:32610')), 2)

    def test_almost_opposite_directions_cannot_create_spikes(self):
        angles = np.deg2rad([0, 90, 179.9999])
        directions = [(float(np.cos(a)), float(np.sin(a))) for a in angles]
        capped, count = add_closing_cap_directions(directions)
        polygon = polygon_from_directions(Point(500000, 5200000), capped, 50.0)
        self.assertEqual(count, 1)
        self.assertEqual(len(polygon.exterior.coords) - 1, 4)
        self.assertTrue(polygon.is_valid)
        radius_limit = 50.0 / np.cos(np.deg2rad(135 / 2))
        self.assertTrue(all(Point(x, y).distance(Point(500000, 5200000)) <= radius_limit + 1e-6
                            for x, y in polygon.exterior.coords))

    def test_direction_deduplication_handles_angle_wraparound(self):
        directions = [(float(np.cos(a)), float(np.sin(a))) for a in np.deg2rad([359, 1, 90, 270])]
        self.assertEqual(len(deduplicate_directions(directions)), 3)

    def test_no_candidates_or_no_graph_returns_a_typed_empty_layer(self):
        graphs = [None, nx.MultiDiGraph(), road_graph(
            {0: (500000, 5200000), 1: (500100, 5200000)}, [(0, 1)],
        )]
        for graph in graphs:
            with self.subTest(graph=graph):
                polygons = create_intersection_polygons(graph, 'EPSG:32610')
                self.assertTrue(polygons.empty)
                self.assertIn('intersection_id', polygons)
                self.assertEqual(polygons.crs.to_epsg(), 32610)

    def test_invalid_distance_is_rejected_even_without_intersections(self):
        for distance in [0, -1, np.nan, np.inf]:
            with self.subTest(distance=distance), self.assertRaises(ValueError):
                create_intersection_polygons(None, 'EPSG:32610', distance)

    def test_single_boundary_contact_does_not_connect_a_side_to_itself(self):
        calculator = QMXNLibCalculator('unused', 'unused')
        graph = nx.Graph()
        graph.add_edge((0, 50), (100, 50))
        total, connected, pairs = calculator.tile_tra_score(graph, box(0, 0, 100, 100))
        self.assertEqual((total, connected), (10, 1))
        self.assertTrue(all(a != b for a, b in pairs))
        self.assertFalse(calculator.edges_are_connected(graph, [(0, 50)], [(0, 50)]))


class TestTileAveraging(unittest.TestCase):
    def test_arithmetic_mean_excludes_failed_scores_and_keeps_all_tiles(self):
        tiles = gpd.GeoDataFrame(
            geometry=[box(500000, 5200000, 500100, 5200100), box(500200, 5200000, 500300, 5200100)],
            index=[8, 13], crs=32610,
        )
        intersections = gpd.GeoDataFrame(
            {'tra_score': [0.2, 0.8, -1.0, np.nan], 'total_edges': [6, 15, 10, 10]},
            geometry=[box(500010+i, 5200010, 500020+i, 5200020) for i in range(4)], crs=32610,
        )
        scored = average_scores_to_tiles(intersections, tiles)
        self.assertEqual(scored.tra_score.tolist(), [0.5, -1])
        self.assertEqual(scored.intersection_count.tolist(), [4, 0])
        self.assertTrue(scored.geometry.equals(tiles.geometry.reset_index(drop=True)))

    def test_overlap_fallback_applies_only_to_tiles_without_point_assignments(self):
        tiles = gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10), box(10, 0, 20, 10)], crs=32610)
        polygons = gpd.GeoDataFrame(
            {'tra_score': [0.2, 0.8]}, geometry=[box(1, 1, 14, 9), box(2, 2, 4, 4)], crs=32610,
        )
        scored = average_scores_to_tiles(polygons, tiles)
        self.assertEqual(scored.tra_score.tolist(), [0.5, 0.2])
        self.assertEqual(scored.intersection_count.tolist(), [2, 1])

    def test_tiles_with_only_failed_intersections_have_no_valid_score(self):
        tiles = gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10)], crs=32610)
        polygons = gpd.GeoDataFrame({'tra_score': [-1]}, geometry=[box(2, 2, 4, 4)], crs=32610)
        scored = average_scores_to_tiles(polygons, tiles)
        self.assertEqual(scored.tra_score.tolist(), [-1])
        self.assertEqual(scored.intersection_count.tolist(), [1])

    def test_different_crs_is_reprojected_before_assignment(self):
        tiles = gpd.GeoDataFrame(geometry=[box(500000, 5200000, 500100, 5200100)], crs=32611)
        polygons = gpd.GeoDataFrame(
            {'tra_score': [0.7]}, geometry=[box(500020, 5200020, 500080, 5200080)], crs=32611,
        ).to_crs(4326)
        scored = average_scores_to_tiles(polygons, tiles)
        self.assertEqual(scored.crs.to_epsg(), 32611)
        self.assertEqual(scored.tra_score.tolist(), [0.7])
        self.assertEqual(scored.intersection_count.tolist(), [1])
