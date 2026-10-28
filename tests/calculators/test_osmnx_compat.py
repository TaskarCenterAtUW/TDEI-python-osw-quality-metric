import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import geopandas as gpd
import osmnx as ox
from flagstones.osm import InsufficientResponseError, SEED_CUSTOM_FILTER
from shapely import box, from_wkt

from src.calculators import osmnx_compat
from src.calculators.intersection_polygons import create_intersection_polygons
from src.calculators.qm_xn_lib_calculator import (
    QMXNLibCalculator, fetch_seed_graph, seed_graph_for_tiles,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tests/fixtures/osmnx_compat'


class TestOSMnxCompatibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.response = json.loads((FIXTURE / 'response.json').read_text())
        cls.expected = json.loads((FIXTURE / 'expected.json').read_text())
        cls.hull = box(*cls.expected['bounds'])

    def test_installed_version_and_pin_match_reviewed_baseline(self):
        version = self.expected['osmnx_version']
        self.assertEqual(ox.__version__, version,
                         'Review OSMnx private APIs and fixture differences before updating the baseline')
        self.assertIn(f'osmnx=={version}', (ROOT / 'requirements.txt').read_text().splitlines())

    def assert_graph_matches(self, graph, expected):
        self.assertEqual(set(graph.nodes), {row['id'] for row in expected['nodes']})
        self.assertTrue(graph.graph['simplified'])
        for row in expected['nodes']:
            node = graph.nodes[row['id']]
            self.assertEqual(node['street_count'], row['street_count'])
            self.assertAlmostEqual(node['x'], row['x'], places=12)
            self.assertAlmostEqual(node['y'], row['y'], places=12)
        self.assertEqual(set(graph.edges(keys=True)), {
            (row['u'], row['v'], row['key']) for row in expected['edges']
        })
        for row in expected['edges']:
            edge = graph.edges[row['u'], row['v'], row['key']]
            for name in ['osmid', 'highway', 'oneway', 'reversed']:
                self.assertEqual(edge[name], row[name])
            self.assertAlmostEqual(edge['length'], row['length'], places=5)
            if 'geometry' in row:
                self.assertTrue(edge['geometry'].equals_exact(from_wkt(row['geometry']), 1e-12))

    def test_saved_response_preserves_queries_graphs_tiles_and_boundary_polygon(self):
        # Mock only HTTP: execute the actual private helpers, projection,
        # simplification, truncation, tiling, and polygon generation offline.
        with patch.dict(os.environ, {'FAIRWAY_MAPPER_API_KEY': 'fixture-key'}), \
                patch.object(ox.settings, 'use_cache', False), \
                patch.object(ox.settings, 'requests_timeout', 180), \
                patch('src.calculators.fairway_mapper.requests.post') as post:
            post.return_value = Mock(status_code=200)
            post.return_value.json.return_value = self.response
            graph = fetch_seed_graph(self.hull)
        self.assertEqual([call.kwargs['data']['data'] for call in post.call_args_list],
                         self.expected['queries'])
        self.assert_graph_matches(graph, self.expected['scoring_graph'])
        tiles_graph = seed_graph_for_tiles(graph, self.hull)
        self.assert_graph_matches(tiles_graph, self.expected['tile_graph'])
        self.assert_graph_matches(graph, self.expected['scoring_graph'])

        tiles = QMXNLibCalculator('unused', 'unused').create_tiles(self.hull, tiles_graph, 'EPSG:32610')
        self.assertEqual(len(tiles), len(self.expected['tiles_wkt']))
        for actual, expected in zip(tiles.geometry, self.expected['tiles_wkt']):
            self.assertTrue(actual.equals_exact(from_wkt(expected), 1e-6))

        footprint = gpd.GeoSeries([self.hull], crs=4326).to_crs(32610).iloc[0]
        polygons = create_intersection_polygons(graph, 32610, dataset_footprint=footprint)
        self.assertEqual(len(polygons), len(self.expected['polygons']))
        for (_, actual), expected in zip(polygons.iterrows(), self.expected['polygons']):
            for name, value in expected.items():
                if name == 'geometry':
                    self.assertTrue(actual.geometry.equals_exact(from_wkt(value), 1e-6))
                else:
                    self.assertEqual(actual[name], value)

    def test_cache_round_trip_respects_disabled_cache(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(ox.settings, 'cache_folder', folder), \
                patch.object(ox.settings, 'use_cache', True):
            key = 'https://api.fairwaymapper.com/api/interpreter?data=fixture'
            self.assertIsNone(osmnx_compat.cached_response(key))
            osmnx_compat.cache_response(key, self.response)
            self.assertEqual(osmnx_compat.cached_response(key), self.response)
            with patch.object(ox.settings, 'use_cache', False):
                self.assertIsNone(osmnx_compat.cached_response(key))

    def test_large_query_is_subdivided(self):
        with patch.object(ox.settings, 'max_query_area_size', 10000):
            queries = list(osmnx_compat.network_queries(self.hull, SEED_CUSTOM_FILTER))
        self.assertGreater(len(queries), 1)
        self.assertEqual(len(queries), len(set(queries)))
        self.assertTrue(all(f'way{SEED_CUSTOM_FILTER}' in query for query in queries))

    def test_empty_osm_response_preserves_no_data_exception(self):
        with self.assertRaises(InsufficientResponseError):
            osmnx_compat.graph_from_responses(iter([{'elements': []}]))
