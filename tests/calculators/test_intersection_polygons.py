import unittest
import tempfile
from itertools import combinations
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
from shapely import LineString, Point, Polygon, box

from src.calculators.intersection_polygons import (
    add_closing_cap_directions, average_scores_to_tiles, create_intersection_polygons,
    deduplicate_directions, polygon_from_directions, polygon_side_roles,
    bounded_junction_clusters,
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
    def junction_chain(self, count=7, spacing=20):
        positions = {i: (500000 + spacing * i, 5200000) for i in range(count)}
        positions.update({100+i: (500000 + spacing * i, 5200100) for i in range(count)})
        positions.update({200: (499900, 5200000),
                          201: (500100 + spacing * (count-1), 5200000)})
        pairs = ([(i, i+1) for i in range(count-1)]
                 + [(i, 100+i) for i in range(count)] + [(0, 200), (count-1, 201)])
        return road_graph(positions, pairs), positions, pairs

    def test_long_chain_is_split_without_losing_member_junctions(self):
        graph, positions, _ = self.junction_chain()
        polygons = create_intersection_polygons(graph, 32610)
        self.assertEqual(polygons.intersection_id.tolist(), ['0|1', '2|3', '4|5', '6'])
        assigned = []
        for row in polygons.itertuples():
            members = [int(node) for node in row.intersection_id.split('|')]
            assigned.extend(members)
            diameter = max((Point(positions[a]).distance(Point(positions[b]))
                            for a, b in combinations(members, 2)), default=0)
            self.assertEqual(row.cluster_diameter_m, diameter)
            self.assertLessEqual(diameter, 20)
            self.assertEqual(row.cluster_member_count, len(members))
            self.assertTrue(row.cluster_members_covered)
            self.assertTrue(all(row.geometry.covers(Point(positions[node])) for node in members))
            self.assertEqual(row.degree, 3)  # Split links become real external approaches.
            self.assertEqual(row.side_roles.split(',').count('approach'), 3)
        self.assertEqual(sorted(assigned), list(range(7)))

    def test_cluster_diameter_checks_all_members_not_only_links_or_center(self):
        # All three are within 15 m of the middle, but the endpoints are 30 m apart.
        points = {0: Point(-15, 0), 1: Point(0, 0), 2: Point(15, 0)}
        adjacency = nx.Graph([(0, 1), (1, 2)])
        self.assertEqual(bounded_junction_clusters(adjacency, points, 20), [(0, 1), (2,)])

    def test_cluster_boundary_and_input_order_are_deterministic(self):
        for spacing, expected_count in [(20, 1), (20.0001, 2)]:
            with self.subTest(spacing=spacing):
                graph, _, _ = self.junction_chain(count=2, spacing=spacing)
                self.assertEqual(len(create_intersection_polygons(graph, 32610)), expected_count)
        graph, positions, pairs = self.junction_chain()
        reverse = road_graph(dict(reversed(list(positions.items()))), list(reversed(pairs)))
        expected = create_intersection_polygons(graph, 32610)
        actual = create_intersection_polygons(reverse, 32610)
        self.assertEqual(actual.intersection_id.tolist(), expected.intersection_id.tolist())
        self.assertEqual(actual.side_roles.tolist(), expected.side_roles.tolist())
        self.assertTrue(actual.geom_equals_exact(expected.geometry, tolerance=1e-8).all())

    def test_small_custom_polygons_still_cover_all_cluster_members(self):
        graph, positions, _ = self.junction_chain(count=2, spacing=14)
        polygons = create_intersection_polygons(graph, 32610, distance=5)
        self.assertEqual(polygons.intersection_id.tolist(), ['0', '1'])
        for row in polygons.itertuples():
            self.assertTrue(row.geometry.covers(Point(positions[int(row.intersection_id)])))
            self.assertEqual(row.cluster_diameter_m, 0)
            self.assertTrue(row.cluster_members_covered)

    def test_outside_junction_supplies_an_approach_but_cannot_join_cluster(self):
        graph = road_graph(
            {0: (500000, 5200000), 1: (500000, 5200014),
             2: (499900, 5200000), 3: (500000, 5199900),
             4: (500000, 5200114), 5: (500100, 5200014)},
            [(0, 1), (0, 2), (0, 3), (1, 4), (1, 5)],
        )
        # Node 0 lies exactly on the footprint boundary; node 1 lies outside.
        footprint = box(499800, 5199800, 500200, 5200000)
        polygons = create_intersection_polygons(graph, 32610, dataset_footprint=footprint)
        self.assertEqual(polygons.intersection_id.tolist(), ['0'])
        row = polygons.iloc[0]
        self.assertEqual((row.degree, row.cap_side_count), (3, 1))
        self.assertTrue(row.geometry.equals(box(499950, 5199950, 500050, 5200050)))
        self.assertTrue(row.extends_beyond_dataset)
        self.assertTrue(create_intersection_polygons(
            graph, 32610, dataset_footprint=box(499700, 5199700, 499800, 5199800),
        ).empty)

    def test_interior_polygon_and_score_are_unchanged_by_footprint(self):
        graph = road_graph(
            {0: (500000, 5200000), 1: (500100, 5200000),
             2: (500000, 5200100), 3: (499900, 5200000)},
            [(0, 1), (0, 2), (0, 3)],
        )
        original = create_intersection_polygons(graph, 32610).iloc[0]
        calculator = QMXNLibCalculator('unused', 'unused')
        edges = gpd.GeoDataFrame(geometry=[
            LineString([(499900, 5200010), (500100, 5200010)]),
            LineString([(500000, 5200010), (500000, 5200100)]),
        ], crs=32610)
        expected = calculator.qm_func(original, edges)
        for footprint, extends in [
            (box(499800, 5199800, 500200, 5200200), False),
            (box(499800, 5199800, 500200, 5200001), True),
        ]:
            row = create_intersection_polygons(graph, 32610, dataset_footprint=footprint).iloc[0]
            self.assertEqual(row.extends_beyond_dataset, extends)
            self.assertEqual(row.side_roles, original.side_roles)
            self.assertTrue(row.geometry.equals(original.geometry))
            scored = calculator.qm_func(row, edges)
            self.assertEqual(scored.tra_score, expected.tra_score)
            self.assertEqual(scored.total_edges, 6)

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


class TestApproachScoring(unittest.TestCase):
    def setUp(self):
        self.calculator = QMXNLibCalculator('unused', 'unused', partition_count=1)

    def intersection(self, angles=(0, 90, 180)):
        positions = {0: (500000, 5200000)}
        for index, angle in enumerate(np.deg2rad(angles), start=1):
            positions[index] = (500000 + 100 * np.cos(angle), 5200000 + 100 * np.sin(angle))
        graph = road_graph(positions, [(0, index) for index in range(1, len(positions))])
        return create_intersection_polygons(graph, 'EPSG:32610')

    def pedestrian_edges(self, feature, contacts=2, skip_side=None, caps_only=False):
        coords = list(feature.geometry.exterior.coords)
        center = np.array([500000, 5200000])
        lines = []
        for index, role in enumerate(feature.side_roles.split(',')):
            if (role == 'cap') != caps_only or index == skip_side:
                continue
            for fraction in ([0.5] if contacts == 1 else [0.4, 0.6]):
                boundary = (1 - fraction) * np.array(coords[index]) + fraction * np.array(coords[index + 1])
                # Extend beyond the polygon to exercise clipping, too.
                lines.append(LineString([center, center + 2 * (boundary - center)]))
        return gpd.GeoDataFrame(geometry=lines, crs=32610)

    def test_connected_t_scores_one_under_rotation_and_reflection(self):
        for angles in [(0, 90, 180), (0, -90, 180), (27, 117, 207), (0, 100, 235.001)]:
            with self.subTest(angles=angles):
                feature = self.intersection(angles).iloc[0]
                edges = self.pedestrian_edges(feature)
                scored = self.calculator.qm_func(feature, edges)
                self.assertEqual((scored.total_edges, scored.connect_edges, scored.tra_score), (6, 6, 1))
                self.assertEqual(feature.side_roles.split(',').count('approach'), 3)
                self.assertEqual(feature.side_roles.split(',').count('cap'), feature.cap_side_count)
                self.assertTrue(scored.geometry.equals(feature.geometry))

    def test_uncapped_y_and_four_way_keep_all_sides(self):
        for angles, pairs in [((0, 120, 240), 6), ((0, 90, 180, 270), 10), ((0, 100, 234.999), 6)]:
            with self.subTest(angles=angles):
                feature = self.intersection(angles).iloc[0]
                self.assertEqual(feature.cap_side_count, 0)
                edges = self.pedestrian_edges(feature)
                scored = self.calculator.qm_func(feature, edges)
                self.assertEqual((scored.total_edges, scored.connect_edges, scored.tra_score), (pairs, pairs, 1))
                legacy = self.calculator.get_measures_from_polygon(feature.geometry, edges)
                self.assertEqual(legacy['tra_score'], scored.tra_score)

    def test_single_contact_on_each_approach_does_not_earn_same_side_credit(self):
        feature = self.intersection().iloc[0]
        scored = self.calculator.qm_func(feature, self.pedestrian_edges(feature, contacts=1))
        self.assertEqual((scored.total_edges, scored.connect_edges, scored.tra_score), (6, 3, 0.5))

    def test_missing_approach_stays_in_denominator(self):
        feature = self.intersection().iloc[0]
        missing_side = feature.side_roles.split(',').index('approach')
        scored = self.calculator.qm_func(feature, self.pedestrian_edges(feature, skip_side=missing_side))
        self.assertEqual((scored.total_edges, scored.connect_edges, scored.tra_score), (6, 3, 0.5))

    def test_disconnected_contacts_on_same_approach_do_not_earn_credit(self):
        feature = self.intersection().iloc[0]
        # Each pair of approaches has a path, but each approach's two contacts
        # lie in different components: no same-approach pair is connected.
        edges = gpd.GeoDataFrame(geometry=[
            LineString([(499950, 5200010), (499990, 5200050)]),
            LineString([(500010, 5200050), (500050, 5200010)]),
            LineString([(499950, 5199990), (500050, 5199990)]),
        ], crs=32610)
        scored = self.calculator.qm_func(feature, edges)
        self.assertEqual((scored.total_edges, scored.connect_edges, scored.tra_score), (6, 3, 0.5))

    def test_cap_contacts_never_earn_credit(self):
        feature = self.intersection().iloc[0]
        scored = self.calculator.qm_func(feature, self.pedestrian_edges(feature, caps_only=True))
        self.assertEqual((scored.total_edges, scored.connect_edges, scored.tra_score), (6, 0, 0))

    def test_path_can_use_cap_boundary_nodes_to_connect_actual_approaches(self):
        feature = self.intersection().iloc[0]
        # West and east are linked via a node on the southern cap.
        edges = gpd.GeoDataFrame(geometry=[LineString([
            (499940, 5200000), (499950, 5200000), (500000, 5199950),
            (500050, 5200000), (500060, 5200000),
        ])], crs=32610)
        scored = self.calculator.qm_func(feature, edges)
        self.assertEqual((scored.total_edges, scored.connect_edges), (6, 1))

    def test_cap_corner_contacts_belong_to_the_actual_approach(self):
        feature = self.intersection().iloc[0]
        graph = nx.Graph()
        graph.add_edge((499950, 5199950), (500050, 5199950))
        total, connected, _ = self.calculator.tile_tra_score(graph, feature.geometry, feature.side_roles)
        self.assertEqual((total, connected), (6, 1))

    def test_side_labels_follow_constraints_after_ring_reordering(self):
        center = Point(500000, 5200000)
        directions, _ = add_closing_cap_directions([(1, 0), (0, 1), (-1, 0)])
        polygon = polygon_from_directions(center, directions, 50)
        coords = list(polygon.exterior.coords)[:-1]
        for ring in [coords, coords[::-1], coords[1:] + coords[:1]]:
            reordered = Polygon(ring)
            roles = polygon_side_roles(reordered, center, directions, 3, 50).split(',')
            for index, role in enumerate(roles):
                segment = list(reordered.exterior.coords)[index:index + 2]
                self.assertEqual(role, 'cap' if all(y == 5199950 for x, y in segment) else 'approach')

    def test_invalid_side_labels_fail_instead_of_scoring_caps(self):
        feature = self.intersection().iloc[0]
        edges = self.pedestrian_edges(feature)
        for roles in ['', 'approach', 'approach,approach,approach,unknown', 'cap,cap,cap,cap', 3]:
            with self.subTest(roles=roles):
                scored = self.calculator.get_measures_from_polygon(feature.geometry, edges, roles)
                self.assertEqual(scored['tra_score'], -1)

    def test_parallel_scoring_and_geojson_preserve_side_roles(self):
        intersections = self.intersection()
        edges = self.pedestrian_edges(intersections.iloc[0])
        scored = self.calculator.score_intersections(intersections, edges)
        self.assertEqual(scored.tra_score.tolist(), [1])
        self.assertEqual(scored.total_edges.tolist(), [6])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'scores.geojson'
            scored.to_crs(4326).to_file(path, driver='GeoJSON')
            restored = gpd.read_file(path).to_crs(32610)
        self.assertEqual(restored.side_roles.tolist(), scored.side_roles.tolist())
        # Reprojection and file serialization must preserve the side mapping.
        result = self.calculator.qm_func(restored.iloc[0], edges)
        self.assertEqual((result.total_edges, result.connect_edges, result.tra_score), (6, 6, 1))

    def test_intersection_pipeline_rejects_missing_side_roles(self):
        intersections = self.intersection()
        edges = self.pedestrian_edges(intersections.iloc[0])
        for malformed in [intersections.drop(columns='side_roles'), intersections.assign(side_roles=None)]:
            with self.subTest(columns=malformed.columns.tolist()), self.assertRaises(ValueError):
                self.calculator.score_intersections(malformed, edges)


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
