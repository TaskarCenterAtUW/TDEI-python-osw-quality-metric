import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from src.calculators.qm_xn_lib_calculator import (
    QMXNLibCalculator, SCORING_ALGORITHM_VERSION, fetch_seed_graph, seed_graph_for_tiles,
)
from src.calculators.intersection_polygons import create_intersection_polygons
from src.calculators.qm_calculator import QualityMetricResult
import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Polygon, Point, MultiPolygon
import tempfile
import json
from subprocess import run, PIPE
import networkx as nx
import osmnx as ox
from shapely.geometry import box
from shapely import wkt

from flagstones import FallbackGrid
from flagstones.osm import InsufficientResponseError, SEED_CUSTOM_FILTER, tiles_for_polygon

INPUTS = os.path.join(os.path.dirname(__file__), "..", "xnqm", "inputs")

# A fallback cell from tiling ped_21's extent: valid in EPSG:32611, with a
# vertex 3e-11 m from an edge that crosses it once reprojected to EPSG:4326.
PINCHED_CELL = wkt.loads(
    "POLYGON ((488950.42345695634 5236250, 488950.55460116745 5236320, "
    "488950.84827411344 5236476.751914875, 488947.8474348803 5236478.550548692, "
    "488935.4286845336 5236499.269981905, 488934.88726621453 5236500, "
    "488920.81389479863 5236518.975744691, 488904.3379767546 5236537.154118947, "
    "488886.15960249887 5236553.63003699, 488866.45383971283 5236568.244826726, "
    "488845.41046566446 5236580.857739736, 488823.2321395492 5236591.347306778, "
    "488800.1324507716 5236599.612507583, 488776.33386196196 5236605.57374375, "
    "488752.06556654035 5236609.173605317, 488750 5236609.275080094, "
    "488750 5236750, 488951.36020132154 5236750, 488950.891829139 5236500, "
    "488950.42345695634 5236250))"
)


class TestBoundarySeedGraph(unittest.TestCase):
    @patch('src.calculators.qm_xn_lib_calculator.download_seed_network')
    @patch('osmnx._overpass._download_overpass_network')
    def test_boundary_t_keeps_three_approaches_and_original_tile_geometries(self, original_download, download):
        # Goldendale's failure pattern: a junction just inside the northern
        # boundary, with the north and west road endpoints outside the hull.
        positions = {
            48719999: (-120.8160817, 45.8382062),
            1: (-120.8160817, 45.8392),
            2: (-120.819, 45.8382062),
            3: (-120.8160817, 45.8362),
            # Beyond even OSMnx's download buffer: trimming this before
            # simplification must leave node 3 as the original road endpoint.
            4: (-120.8160817, 45.82),
        }
        response = {'elements': [
            {'type': 'node', 'id': node, 'lon': lon, 'lat': lat}
            for node, (lon, lat) in positions.items()
        ] + [
            {'type': 'way', 'id': node, 'nodes': [48719999, node],
             'tags': {'highway': 'residential'}}
            for node in [1, 2, 3]
        ] + [
            {'type': 'way', 'id': 4, 'nodes': [3, 4], 'tags': {'highway': 'residential'}},
        ]}
        download.return_value = [response]
        original_download.return_value = [response]
        hull = box(-120.818, 45.835, -120.814, 45.8382175)
        old_graph = ox.graph_from_polygon(
            hull, custom_filter=SEED_CUSTOM_FILTER, simplify=True, retain_all=True,
        )
        download.reset_mock()
        graph = fetch_seed_graph(hull)
        download.assert_called_once()
        self.assertEqual(download.call_args.args[1:], (SEED_CUSTOM_FILTER,))
        self.assertEqual(set(old_graph.neighbors(48719999)), {3})
        self.assertEqual(set(graph.neighbors(48719999)), {1, 2, 3})
        footprint = gpd.GeoSeries([hull], crs=4326).to_crs(32610).iloc[0]
        self.assertTrue(create_intersection_polygons(old_graph, 32610).empty)
        polygons = create_intersection_polygons(graph, 32610, dataset_footprint=footprint)
        self.assertEqual(polygons.intersection_id.tolist(), ['48719999'])
        row = polygons.iloc[0]
        self.assertEqual((row.degree, row.side_count, row.cap_side_count), (3, 4, 1))
        self.assertTrue(row.extends_beyond_dataset)
        crossing = gpd.GeoSeries([LineString([
            (-120.8161667, 45.8381421), (-120.8160267, 45.8381398),
        ])], crs=4326).to_crs(32610).iloc[0]
        self.assertTrue(row.geometry.covers(crossing))
        tile_graph = seed_graph_for_tiles(graph, hull)
        self.assertEqual(dict(tile_graph.nodes(data=True)), dict(old_graph.nodes(data=True)))
        self.assertEqual(
            {(u, v, key): data for u, v, key, data in tile_graph.edges(keys=True, data=True)},
            {(u, v, key): data for u, v, key, data in old_graph.edges(keys=True, data=True)},
        )
        # Trimming tiles must not remove the approaches used by polygons.
        self.assertEqual(set(graph.neighbors(48719999)), {1, 2, 3})
        calculator = QMXNLibCalculator('unused', 'unused')
        tiles = calculator.create_tiles(hull, tile_graph, 'EPSG:32610')
        original_tiles = calculator.create_tiles(hull, old_graph, 'EPSG:32610')
        self.assertEqual(len(tiles), len(original_tiles))
        self.assertTrue(tiles.geom_equals_exact(original_tiles.geometry, tolerance=0).all())
        self.assertTrue(all(footprint.buffer(1e-6).covers(tile) for tile in tiles.geometry))
        self.assertAlmostEqual(tiles.union_all().area / footprint.area, 1.0, places=6)
        self.assertAlmostEqual(tiles.area.sum() / footprint.area, 1.0, places=6)

        # Check routing through the production calculator, including serialization.
        with tempfile.TemporaryDirectory() as tmp:
            input_path = os.path.join(tmp, 'edges.geojson')
            gpd.GeoDataFrame(geometry=[LineString(hull.exterior.coords)], crs=4326).to_file(input_path)
            calculator = QMXNLibCalculator(
                input_path, os.path.join(tmp, 'scores.geojson'),
                partition_count=1, debug_intersection_polygons=True,
            )
            with patch('src.calculators.qm_xn_lib_calculator.fetch_seed_graph', return_value=graph) as fetch:
                result = calculator.calculate_quality_metric()
            self.assertTrue(result.success, result.message)
            fetch.assert_called_once()
            output = gpd.read_file(calculator.output_file_path)
            self.assertTrue(output.geom_equals_exact(original_tiles.to_crs(4326).geometry, tolerance=1e-12).all())
            debug = gpd.read_file(calculator.debug_output_path())
            self.assertEqual(debug['ext:intersection_id'].tolist(), ['48719999'])
            self.assertEqual(debug['ext:degree'].tolist(), [3])

    @patch('src.calculators.qm_xn_lib_calculator.download_seed_network')
    def test_fetch_preserves_empty_network_handling_and_propagates_other_errors(self, fetch):
        for error in [
            InsufficientResponseError('No matching roads'),
            ValueError('Found no graph nodes within the requested polygon'),
        ]:
            with self.subTest(error=error):
                fetch.side_effect = error
                with self.assertRaises(InsufficientResponseError):
                    fetch_seed_graph(box(-121, 45, -120, 46))
        error = ValueError('Invalid polygon')
        fetch.side_effect = error
        with self.assertRaises(ValueError) as raised:
            fetch_seed_graph(box(-121, 45, -120, 46))
        self.assertIs(raised.exception, error)


class TestQMXNLibCalculator(unittest.TestCase):

    def setUp(self):
        self.edges_file_path = 'test_edges.geojson'
        self.output_file_path = 'test_output.geojson'
        self.polygon_file_path = 'test_polygon.geojson'
        self.calculator = QMXNLibCalculator(
            self.edges_file_path,
            self.output_file_path,
            self.polygon_file_path
        )
        self.default_projection = 'EPSG:32610'

    def test_initialization(self):
        self.assertEqual(self.calculator.edges_file_path, self.edges_file_path)
        self.assertEqual(self.calculator.output_file_path, self.output_file_path)
        self.assertEqual(self.calculator.polygon_file_path, self.polygon_file_path)
        self.assertIsNone(self.calculator.default_projection)
        self.assertIsNotNone(self.calculator.output_projection)

    @patch('src.calculators.qm_xn_lib_calculator.gpd.read_file')
    @patch('src.calculators.qm_xn_lib_calculator.nx.Graph')
    def test_graph_from_gdf(self, mock_graph, mock_read_file):
        mock_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_read_file.return_value = mock_gdf
        mock_graph_instance = MagicMock()
        mock_graph.return_value = mock_graph_instance

        # Create mock geometries
        mock_gdf.iterrows.return_value = iter([
            (0, MagicMock(geometry=LineString([(0, 0), (1, 1)]))),
            (1, MagicMock(geometry=LineString([(1, 1), (2, 2)]))),
        ])

        G = self.calculator.graph_from_gdf(mock_gdf)
        mock_graph.assert_called_once()
        self.assertEqual(G, mock_graph_instance)

    @patch('src.calculators.qm_xn_lib_calculator.QMXNLibCalculator.work_crs', return_value='EPSG:32610')
    @patch('src.calculators.qm_xn_lib_calculator.fetch_seed_graph', return_value=nx.MultiDiGraph())
    @patch('src.calculators.qm_xn_lib_calculator.create_intersection_polygons')
    @patch('src.calculators.qm_xn_lib_calculator.gpd.read_file')
    @patch('src.calculators.qm_xn_lib_calculator.dask_geopandas.from_geopandas')
    def test_calculate_quality_metric_with_polygon(
        self, mock_from_geopandas, mock_read_file, mock_polygons, mock_fetch, mock_work_crs,
    ):
        edges = gpd.GeoDataFrame(
            geometry=[LineString([(500000, 5200000), (500100, 5200100)])], crs=32610,
        )
        tiles = gpd.GeoDataFrame(geometry=[box(500000, 5200000, 500100, 5200100)], crs=32610)
        polygons = gpd.GeoDataFrame(
            {'side_roles': ['approach,approach,approach,approach']},
            geometry=[box(500020, 5200020, 500080, 5200080)], crs=32610,
        )
        mock_read_file.side_effect = [edges, tiles]
        mock_polygons.return_value = polygons
        mock_from_geopandas.return_value.apply.return_value.compute.return_value = polygons.assign(
            tra_score=0.75, total_edges=10, connect_edges=7,
        )
        with patch.object(gpd.GeoDataFrame, 'to_file', autospec=True) as write:
            result = self.calculator.calculate_quality_metric()
        self.assertTrue(result.success, result.message)
        mock_read_file.assert_any_call(self.edges_file_path)
        mock_read_file.assert_any_call(self.polygon_file_path)
        mock_fetch.assert_called_once()
        self.assertIs(mock_polygons.call_args.args[0], mock_fetch.return_value)
        self.assertIs(mock_from_geopandas.call_args.args[0], polygons)
        written = write.call_args.args[0]
        self.assertEqual(written.crs.to_epsg(), 4326)
        self.assertEqual(written.tra_score.tolist(), [0.75])
        self.assertEqual(written['ext:intersection_count'].tolist(), [1])
        self.assertNotIn('intersection_count', written)
        self.assertTrue(written.to_crs(32610).geom_equals_exact(tiles.geometry, tolerance=1e-6).all())
        self.assertIsInstance(result, QualityMetricResult)
        self.assertEqual(result.message, 'QMXNLibCalculator')
        self.assertEqual(result.output_file, self.output_file_path)

    def test_cli_exposes_debug_and_distance_without_modes(self):
        result = run(
            [sys.executable, '-m', 'src.calculators.qm_xn_lib_calculator', '--help'],
            stdout=PIPE, stderr=PIPE, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--debug-intersection-polygons', result.stdout)
        self.assertIn('--intersection-distance', result.stdout)
        self.assertNotIn('--mode', result.stdout)

    def test_main_without_polygon(self):
        with tempfile.NamedTemporaryFile(suffix='.geojson') as edges_file, \
                tempfile.NamedTemporaryFile(suffix='.geojson') as output_file:
            dummy_geojson = {
                'type': 'FeatureCollection',
                'features': []
            }

            edges_file.write(json.dumps(dummy_geojson).encode())
            edges_file.flush()

            result = run(
                [
                    sys.executable,
                    '-m',
                    'src.calculators.qm_xn_lib_calculator',
                    edges_file.name,
                    output_file.name,
                ],
                stdout=PIPE,
                stderr=PIPE,
                text=True,
            )

            if result.returncode != 0:
                print('Error:', result.stderr)

            self.assertEqual(result.returncode, 0)

    @patch('src.calculators.qm_xn_lib_calculator.nx.Graph')
    def test_graph_from_gdf_multilinestring(self, mock_graph):
        mock_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_graph_instance = mock_graph.return_value

        # Mock a MultiLineString geometry
        mock_gdf.iterrows.return_value = iter([
            (0, MagicMock(geometry=MultiLineString([LineString([(0, 0), (1, 1)]), LineString([(1, 1), (2, 2)])]))),
        ])

        G = self.calculator.graph_from_gdf(mock_gdf)
        self.assertEqual(G, mock_graph_instance)
        self.assertEqual(mock_graph_instance.add_edge.call_count, 2)

    def test_group_G_pts(self):
        mock_graph = nx.Graph()
        mock_graph.add_nodes_from([(0, 0), (1, 1), (2, 2)])
        mock_polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])

        result = self.calculator.group_G_pts(mock_graph, mock_polygon)
        self.assertTrue(isinstance(result, dict))
        self.assertTrue(all(isinstance(v, list) for v in result.values()))

    def test_edges_are_connected(self):
        mock_graph = nx.Graph()
        mock_graph.add_edge((0, 0), (1, 1))
        mock_graph.add_edge((1, 1), (2, 2))

        result = self.calculator.edges_are_connected(mock_graph, [(0, 0)], [(2, 2)])
        self.assertTrue(result)

    def test_tile_tra_score(self):
        mock_graph = nx.Graph()
        mock_graph.add_edge((0, 0), (1, 1))
        mock_graph.add_edge((1, 1), (2, 2))
        mock_polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])

        result = self.calculator.tile_tra_score(mock_graph, mock_polygon)
        self.assertTrue(isinstance(result, tuple))
        self.assertEqual(len(result), 3)

    @patch('src.calculators.qm_xn_lib_calculator.gpd.clip')
    def test_get_measures_from_polygon(self, mock_clip):
        mock_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
        mock_clipped_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_clip.return_value = mock_clipped_gdf

        mock_clipped_gdf.geometry = MagicMock()
        result = self.calculator.get_measures_from_polygon(mock_polygon, mock_gdf)
        self.assertTrue(isinstance(result, dict))
        self.assertIn('tra_score', result)

    @patch('src.calculators.qm_xn_lib_calculator.QMXNLibCalculator.get_measures_from_polygon')
    def test_qm_func(self, mock_get_measures_from_polygon):
        mock_feature = MagicMock()
        mock_feature.geometry = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
        mock_feature.loc = {}
        mock_feature.astype.return_value = mock_feature
        mock_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_get_measures_from_polygon.return_value = {'tra_score': 0.8}

        result = self.calculator.qm_func(mock_feature, mock_gdf)
        self.assertEqual(result.loc['tra_score'], 0.8)

    @patch('src.calculators.qm_xn_lib_calculator.QMXNLibCalculator.get_measures_from_polygon')
    def test_qm_func_scores_a_row_of_a_geometry_only_frame(self, mock_get_measures_from_polygon):
        mock_get_measures_from_polygon.return_value = {'tra_score': 0.5}
        tiles = gpd.GeoDataFrame(geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])])

        result = self.calculator.qm_func(tiles.iloc[0], MagicMock())
        self.assertEqual(result['tra_score'], 0.5)

    @patch('src.calculators.qm_xn_lib_calculator.gpd.read_file')
    def test_calculate_quality_metric_exception(self, mock_read_file):
        mock_read_file.side_effect = Exception('Mocked exception')

        result = self.calculator.calculate_quality_metric()
        self.assertIsInstance(result, QualityMetricResult)
        self.assertFalse(result.success)
        self.assertIn('Mocked exception', result.message)


    @patch('src.calculators.qm_xn_lib_calculator.dask_geopandas.from_geopandas')
    @patch('src.calculators.qm_xn_lib_calculator.QMXNLibCalculator.create_tiles')
    @patch('src.calculators.qm_xn_lib_calculator.fetch_seed_graph', return_value=None)
    @patch('src.calculators.qm_xn_lib_calculator.QMXNLibCalculator.work_crs', return_value='EPSG:32611')
    @patch('src.calculators.qm_xn_lib_calculator.gpd.read_file')
    def test_tiles_that_reprojection_pinches_are_written_valid(
        self, mock_read_file, mock_work_crs, mock_fetch, mock_create_tiles, mock_from_geopandas
    ):
        self.assertFalse(
            gpd.GeoSeries([PINCHED_CELL], crs='EPSG:32611').to_crs('EPSG:4326').is_valid.iloc[0]
        )
        mock_read_file.return_value = gpd.GeoDataFrame(
            geometry=[LineString([(-117.15, 47.27), (-117.14, 47.28)])], crs='EPSG:4326'
        )
        tiles = gpd.GeoDataFrame(geometry=[PINCHED_CELL], crs='EPSG:32611')
        mock_create_tiles.return_value = tiles
        written = []

        def capture(frame, *args, **kwargs):
            written.append(frame)

        calculator = QMXNLibCalculator(self.edges_file_path, self.output_file_path)
        with patch.object(gpd.GeoDataFrame, 'to_file', autospec=True, side_effect=capture):
            result = calculator.calculate_quality_metric()

        self.assertTrue(result.success, result.message)
        (output,) = written
        self.assertEqual(output.crs.to_epsg(), 4326)
        self.assertTrue(output.is_valid.all())
        self.assertEqual(output.tra_score.tolist(), [-1])
        self.assertAlmostEqual(
            output.to_crs('EPSG:32611').area.iloc[0], PINCHED_CELL.area, delta=1e-6 * PINCHED_CELL.area
        )

    def test_algorithm_name(self):
        result = self.calculator.algorithm_name()
        self.assertEqual(result, 'QMXNLibCalculator')

    @patch('src.calculators.qm_xn_lib_calculator.QMXNLibCalculator.tile_tra_score')
    def test_get_stats_exception(self, mock_tile_tra_score):
        # Setup mock to raise an exception
        mock_tile_tra_score.side_effect = Exception('Mocked tile_tra_score exception')

        # Create a dummy polygon and graph
        dummy_polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        dummy_graph = nx.Graph()
        dummy_gdf = MagicMock()  # Mocked GeoDataFrame

        # Call the function
        result = self.calculator.get_stats(dummy_polygon, dummy_graph, dummy_gdf)

        # Assertions
        mock_tile_tra_score.assert_called_once_with(dummy_graph, dummy_polygon, None)
        self.assertIn('tra_score', result)
        self.assertEqual(result['tra_score'], -1)

    @patch('src.calculators.qm_xn_lib_calculator.gpd.clip')
    @patch('src.calculators.qm_xn_lib_calculator.QMXNLibCalculator.graph_from_gdf')
    @patch('src.calculators.qm_xn_lib_calculator.QMXNLibCalculator.get_stats')
    def test_get_measures_from_polygon_single_geometry_multipolygon(self, mock_get_stats, mock_graph_from_gdf,
                                                                    mock_clip):
        # Create a MultiPolygon with a single geometry
        single_polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        multipolygon = MultiPolygon([single_polygon])

        # Mock GeoDataFrame and graph
        mock_gdf = MagicMock()
        mock_clipped_gdf = MagicMock()
        mock_clip.return_value = mock_clipped_gdf
        mock_graph = MagicMock()
        mock_graph_from_gdf.return_value = mock_graph

        # Mock the stats returned
        mock_stats = {'tra_score': 0.85}
        mock_get_stats.return_value = mock_stats

        # Call the function
        result = self.calculator.get_measures_from_polygon(multipolygon, mock_gdf)

        # Assertions
        mock_clip.assert_called_once_with(mock_gdf, single_polygon)  # Ensure the single polygon was used
        mock_graph_from_gdf.assert_called_once_with(mock_clipped_gdf)
        mock_get_stats.assert_called_once_with(single_polygon, mock_graph, mock_clipped_gdf, None)
        self.assertEqual(result, mock_stats)

    @patch('src.calculators.qm_xn_lib_calculator.QMXNLibCalculator.get_measures_from_polygon')
    def test_qm_func_else(self, mock_get_measures_from_polygon):
        # Mock feature with a non-Polygon/MultiPolygon geometry (e.g., Point)
        mock_feature = MagicMock()
        mock_feature.geometry = Point(0, 0)  # Point geometry

        # Mock GeoDataFrame (not actually used in this test case)
        mock_gdf = MagicMock()

        # Call the function
        result = self.calculator.qm_func(mock_feature, mock_gdf)

        # Assertions
        mock_get_measures_from_polygon.assert_not_called()  # Ensure get_measures_from_polygon is not called
        self.assertEqual(result, mock_feature)


class TestIntersectionTiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = ox.load_graphml(os.path.join(INPUTS, "p13_seed.graphml"))
        cls.edges = os.path.join(INPUTS, "p13_edges.geojson")
        cls.hull = gpd.read_file(cls.edges).to_crs(4326).union_all().convex_hull

    @patch("src.calculators.qm_xn_lib_calculator.fetch_seed_graph")
    def test_without_a_polygon_file_the_service_averages_onto_library_tiles(self, fetch):
        fetch.return_value = self.graph
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "ixn_qm.geojson")
            result = QMXNLibCalculator(self.edges, out, partition_count=1).calculate_quality_metric()
            self.assertTrue(result.success, result.message)
            scored = gpd.read_file(out)
        fetch.assert_called_once()
        self.assertGreater(len(scored), 0)
        self.assertEqual(scored.crs.to_epsg(), 4326)
        self.assertEqual(sorted(scored.columns), [
            "ext:intersection_count", "ext:scoring_algorithm_version", "geometry", "tile_algorithm_version", "tra_score",
        ])
        self.assertTrue((scored.tra_score.between(0, 1) | (scored.tra_score == -1)).all())
        self.assertTrue((scored['ext:intersection_count'] > 0).any())
        self.assertTrue((scored.loc[scored['ext:intersection_count'] == 0, 'tra_score'] == -1).all())

    @patch("src.calculators.qm_xn_lib_calculator.fetch_seed_graph")
    def test_the_work_crs_is_the_utm_zone_of_the_data(self, fetch):
        fetch.return_value = self.graph
        with tempfile.TemporaryDirectory() as tmp:
            calculator = QMXNLibCalculator(self.edges, os.path.join(tmp, "o.geojson"), partition_count=1)
            calculator.calculate_quality_metric()
        self.assertEqual(calculator.default_projection, "EPSG:32610")

    def test_create_tiles_stays_inside_the_hull_in_the_tiling_crs(self):
        calculator = QMXNLibCalculator(self.edges, "unused.geojson")
        tiles = calculator.create_tiles(self.hull, self.graph, "EPSG:32610")
        bound = gpd.GeoSeries([self.hull], crs=4326).to_crs(32610).iloc[0].buffer(1e-3)
        self.assertEqual(list(tiles.columns), ["geometry"])
        self.assertEqual(tiles.crs.to_epsg(), 32610)
        self.assertTrue(all(bound.covers(g) for g in tiles.geometry))

    @patch("src.calculators.qm_xn_lib_calculator.fetch_seed_graph")
    def test_a_hull_with_no_road_network_has_unavailable_scores_on_fallback_cells(self, fetch):
        fetch.side_effect = InsufficientResponseError("Found no graph nodes within the requested polygon")
        cells = tiles_for_polygon(self.hull, None, crs="EPSG:32610", fallback=FallbackGrid()).fallback
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "ixn_qm.geojson")
            with self.assertLogs('src.calculators.qm_xn_lib_calculator', level='WARNING') as logs:
                result = QMXNLibCalculator(self.edges, out, partition_count=1).calculate_quality_metric()
            self.assertTrue(result.success, result.message)
            scored = gpd.read_file(out)
        self.assertEqual(len(scored), len(cells))
        self.assertTrue((scored.tra_score == -1).all())
        self.assertTrue((scored['ext:intersection_count'] == 0).all())
        self.assertIn('generated fallback tiles', logs.output[0])
        self.assertIn(self.edges, logs.output[0])
        self.assertIn('tra_score=-1 (unavailable)', logs.output[0])

    @patch('src.calculators.qm_xn_lib_calculator.fetch_seed_graph')
    def test_missing_roads_warn_and_preserve_supplied_tiles(self, fetch):
        for no_roads in [InsufficientResponseError('No matching roads'), None, nx.MultiDiGraph()]:
            with self.subTest(no_roads=no_roads), tempfile.TemporaryDirectory() as tmp:
                fetch.side_effect = no_roads if isinstance(no_roads, Exception) else None
                fetch.return_value = no_roads
                tile_path = os.path.join(tmp, 'supplied.geojson')
                tiles = gpd.GeoDataFrame(geometry=[self.hull], crs=4326)
                tiles.to_file(tile_path, driver='GeoJSON')
                output_path = os.path.join(tmp, 'scores.geojson')
                calculator = QMXNLibCalculator(self.edges, output_path, tile_path, partition_count=1)
                with self.assertLogs('src.calculators.qm_xn_lib_calculator', level='WARNING') as logs:
                    result = calculator.calculate_quality_metric()
                self.assertTrue(result.success, result.message)
                scored = gpd.read_file(output_path)
                self.assertEqual(scored.tra_score.tolist(), [-1])
                self.assertEqual(scored['ext:intersection_count'].tolist(), [0])
                self.assertTrue(scored.geom_equals_exact(tiles.geometry, tolerance=1e-12).all())
                self.assertEqual(len(logs.output), 1)
                self.assertIn('No qualifying OSM roads', logs.output[0])
                self.assertIn('all supplied tiles', logs.output[0])
                self.assertIn(self.edges, logs.output[0])

    @patch('src.calculators.qm_xn_lib_calculator.fetch_seed_graph_with_retry')
    def test_fetch_errors_with_supplied_tiles_are_not_reported_as_missing_roads(self, fetch):
        from requests.exceptions import HTTPError, Timeout
        for error in [HTTPError('Authentication failed'), Timeout('Retries exhausted'),
                      ValueError('Fairway Mapper returned an invalid OSM response')]:
            with self.subTest(error=error), tempfile.TemporaryDirectory() as tmp:
                fetch.side_effect = error
                tile_path = os.path.join(tmp, 'supplied.geojson')
                gpd.GeoDataFrame(geometry=[self.hull], crs=4326).to_file(tile_path, driver='GeoJSON')
                output_path = os.path.join(tmp, 'scores.geojson')
                calculator = QMXNLibCalculator(self.edges, output_path, tile_path, partition_count=1)
                with self.assertNoLogs('src.calculators.qm_xn_lib_calculator', level='WARNING'):
                    result = calculator.calculate_quality_metric()
                self.assertFalse(result.success)
                self.assertIn(str(error), result.message)
                self.assertFalse(os.path.exists(output_path))

    def test_a_hull_with_no_road_gets_only_fallback_cells(self):
        calculator = QMXNLibCalculator(self.edges, "unused.geojson")
        tiles = calculator.create_tiles(self.hull, None, "EPSG:32610")
        tile_set = tiles_for_polygon(self.hull, None, crs="EPSG:32610", fallback=FallbackGrid())
        self.assertEqual(tile_set.tiles, ())
        self.assertEqual(len(tiles), len(tile_set.fallback))
        bound = gpd.GeoSeries([self.hull], crs=4326).to_crs(32610).iloc[0]
        self.assertAlmostEqual(tiles.area.sum() / bound.area, 1.0, places=6)

    def test_a_tile_with_a_hole_is_scored_on_its_outer_ring(self):
        calculator = QMXNLibCalculator("unused.geojson", "unused.geojson")
        tile = Polygon(
            [(0, 0), (100, 0), (100, 100), (0, 100)],
            [[(40, 40), (60, 40), (60, 60), (40, 60)]],
        )
        edges = gpd.GeoDataFrame(geometry=[LineString([(-10, 50), (110, 50)])], crs="EPSG:32610")
        self.assertEqual(calculator.get_measures_from_polygon(tile, edges)["tra_score"], 0.0)

    def test_a_multipart_tile_is_scored_on_its_largest_part(self):
        calculator = QMXNLibCalculator("unused.geojson", "unused.geojson")
        tile = MultiPolygon([box(200, 0, 210, 10), box(0, 0, 100, 100)])
        edges = gpd.GeoDataFrame(geometry=[LineString([(-10, 50), (110, 50)])], crs="EPSG:32610")
        self.assertEqual(calculator.get_measures_from_polygon(tile, edges)["tra_score"], 0.1)

    @patch("src.calculators.qm_xn_lib_calculator.fetch_seed_graph")
    def test_debug_polygon_scores_are_optional_and_average_back_to_output(self, fetch):
        from src.calculators.intersection_polygons import average_scores_to_tiles
        fetch.return_value = self.graph
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "ixn_qm.geojson")
            calculator = QMXNLibCalculator(
                self.edges, out, partition_count=1, debug_intersection_polygons=True,
            )
            result = calculator.calculate_quality_metric()
            self.assertTrue(result.success, result.message)
            debug = gpd.read_file(calculator.debug_output_path())
            scored = gpd.read_file(out)
            self.assertEqual(debug.crs.to_epsg(), 4326)
            self.assertGreater(len(debug), 0)
            self.assertTrue(debug.is_valid.all())
            self.assertTrue((
                debug['ext:side_count'] == debug['ext:degree'] + debug['ext:cap_side_count']
            ).all())
            self.assertTrue((debug['ext:connect_edges'] <= debug['ext:total_edges']).all())
            self.assertTrue((debug['ext:total_edges'] == debug['ext:degree'] * (debug['ext:degree'] + 1) / 2).all())
            self.assertTrue((debug['ext:scoring_algorithm_version'] == SCORING_ALGORITHM_VERSION).all())
            self.assertTrue((scored['ext:scoring_algorithm_version'] == SCORING_ALGORITHM_VERSION).all())
            for _, row in debug.iterrows():
                roles = row['ext:side_roles'].split(',')
                self.assertEqual(len(roles), row['ext:side_count'])
                self.assertEqual(roles.count('approach'), row['ext:degree'])
                self.assertEqual(roles.count('cap'), row['ext:cap_side_count'])
            self.assertTrue(debug.tra_score.between(0, 1).all())
            self.assertEqual(set(debug.columns), {
                'geometry', 'tra_score', 'ext:intersection_id', 'ext:degree',
                'ext:side_count', 'ext:cap_side_count', 'ext:polygon_distance_m',
                'ext:total_edges', 'ext:connect_edges',
                'ext:side_roles', 'ext:scoring_algorithm_version', 'ext:extends_beyond_dataset',
            })
            tiles = calculator.create_tiles(self.hull, self.graph, calculator.default_projection)
            expected = average_scores_to_tiles(debug.to_crs(tiles.crs), tiles)
            self.assertEqual(scored['ext:intersection_count'].tolist(), expected.intersection_count.tolist())
            for actual, mean in zip(scored.tra_score, expected.tra_score):
                self.assertAlmostEqual(actual, mean)
        fetch.assert_called_once()

    @patch("src.calculators.qm_xn_lib_calculator.fetch_seed_graph", return_value=None)
    def test_debug_disabled_does_not_write_polygon_output(self, fetch):
        with tempfile.TemporaryDirectory() as tmp:
            calculator = QMXNLibCalculator(self.edges, os.path.join(tmp, "ixn_qm.geojson"))
            result = calculator.calculate_quality_metric()
            self.assertTrue(result.success, result.message)
            self.assertFalse(os.path.exists(calculator.debug_output_path()))

    @patch("src.calculators.qm_xn_lib_calculator.fetch_seed_graph", return_value=None)
    def test_debug_can_write_an_empty_intersection_layer(self, fetch):
        with tempfile.TemporaryDirectory() as tmp:
            calculator = QMXNLibCalculator(
                self.edges, os.path.join(tmp, "ixn_qm.geojson"), debug_intersection_polygons=True,
            )
            result = calculator.calculate_quality_metric()
            self.assertTrue(result.success, result.message)
            self.assertTrue(gpd.read_file(calculator.debug_output_path()).empty)

    def test_the_tiles_and_the_fallback_cells_cover_the_hull_without_overlap(self):
        """Compared in the tiling CRS against the projected hull."""
        calculator = QMXNLibCalculator(self.edges, "unused.geojson")
        tiles = calculator.create_tiles(self.hull, self.graph, "EPSG:32610")
        tile_set = tiles_for_polygon(self.hull, self.graph, crs="EPSG:32610", fallback=FallbackGrid())
        self.assertEqual(len(tiles), len(tile_set.tiles) + len(tile_set.fallback))
        bound = gpd.GeoSeries([self.hull], crs=4326).to_crs(32610).iloc[0]
        self.assertAlmostEqual(tiles.union_all().area / bound.area, 1.0, places=6)
        self.assertAlmostEqual(tiles.area.sum(), tiles.union_all().area, delta=1e-6 * bound.area)


if __name__ == '__main__':
    unittest.main()
