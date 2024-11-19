import os
import unittest
from unittest.mock import patch, MagicMock, call
from src.calculators.qm_xn_lib_calculator import QMXNLibCalculator
from src.calculators.qm_calculator import QualityMetricResult
import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Polygon, Point, MultiPolygon
import tempfile
import json
from subprocess import run, PIPE
import networkx as nx


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
        self.default_projection = 'epsg:26910'

    def test_initialization(self):
        self.assertEqual(self.calculator.edges_file_path, self.edges_file_path)
        self.assertEqual(self.calculator.output_file_path, self.output_file_path)
        self.assertEqual(self.calculator.polygon_file_path, self.polygon_file_path)
        self.assertIsNotNone(self.calculator.default_projection)
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

    @patch('src.calculators.qm_xn_lib_calculator.gpd.read_file')
    @patch('src.calculators.qm_xn_lib_calculator.dask_geopandas.from_geopandas')
    def test_calculate_quality_metric_with_polygon(self, mock_from_geopandas, mock_read_file):
        # Mock GeoDataFrames
        mock_edges_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_polygon_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_result_gdf = MagicMock(spec=gpd.GeoDataFrame)

        # Setup mock behaviors
        mock_read_file.side_effect = [mock_edges_gdf, mock_polygon_gdf]
        mock_edges_gdf.to_crs.return_value = mock_edges_gdf
        mock_polygon_gdf.to_crs.return_value = mock_polygon_gdf
        mock_polygon_subset = MagicMock(spec=gpd.GeoDataFrame)  # Mock for tile_gdf[['geometry']]
        mock_polygon_gdf.__getitem__.return_value = mock_polygon_subset  # Mock subset behavior

        mock_result_gdf.to_crs.return_value = mock_result_gdf
        mock_result_gdf.to_file = MagicMock()
        mock_from_geopandas.return_value.apply.return_value.compute.return_value = mock_result_gdf

        # Execute the method
        result = self.calculator.calculate_quality_metric()

        # Assertions
        mock_read_file.assert_any_call(self.edges_file_path)
        mock_read_file.assert_any_call(self.polygon_file_path)
        mock_edges_gdf.to_crs.assert_called_once_with(self.default_projection)
        mock_polygon_gdf.to_crs.assert_called_once_with(self.default_projection)
        mock_polygon_gdf.__getitem__.assert_called_once_with(['geometry'])  # Ensure subset call
        mock_from_geopandas.assert_called_once_with(mock_polygon_subset, npartitions=os.cpu_count())
        mock_result_gdf.to_file.assert_called_once_with(self.output_file_path, driver='GeoJSON')

        # Verify the result
        self.assertIsInstance(result, QualityMetricResult)
        self.assertTrue(result.success)
        self.assertEqual(result.message, 'QMXNLibCalculator')
        self.assertEqual(result.output_file, self.output_file_path)

    @patch('src.calculators.qm_xn_lib_calculator.gpd.read_file')
    @patch('src.calculators.qm_xn_lib_calculator.ox.graph.graph_from_polygon')
    @patch('src.calculators.qm_xn_lib_calculator.QMXNLibCalculator.create_voronoi_diagram')
    @patch('src.calculators.qm_xn_lib_calculator.dask_geopandas.from_geopandas')
    def test_calculate_quality_metric_without_polygon(
            self, mock_from_geopandas, mock_create_voronoi_diagram, mock_graph_from_polygon, mock_read_file
    ):
        # Remove the polygon file path
        self.calculator.polygon_file_path = None

        # Mock input GeoDataFrame
        mock_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_read_file.return_value = mock_gdf
        mock_gdf.to_crs.return_value = mock_gdf

        # Mock the convex hull behavior
        mock_convex_hull = MagicMock(spec=Polygon)
        mock_gdf.unary_union.convex_hull = mock_convex_hull

        # Mock the graph and Voronoi diagram creation
        mock_graph = MagicMock()
        mock_graph_from_polygon.return_value = mock_graph
        mock_voronoi_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_create_voronoi_diagram.return_value = mock_voronoi_gdf
        mock_voronoi_gdf.to_crs.return_value = mock_voronoi_gdf

        # Mock subset for geometry column and from_geopandas behavior
        mock_polygon_subset = MagicMock(spec=gpd.GeoDataFrame)
        mock_voronoi_gdf.__getitem__.return_value = mock_polygon_subset
        mock_from_geopandas.return_value.apply.return_value.compute.return_value = mock_voronoi_gdf

        # Execute the method
        result = self.calculator.calculate_quality_metric()

        # Assertions
        mock_read_file.assert_called_once_with(self.edges_file_path)
        mock_gdf.to_crs.assert_called_once_with(self.calculator.default_projection)
        mock_graph_from_polygon.assert_called_once_with(
            mock_convex_hull, network_type='drive', simplify=True, retain_all=True
        )
        mock_create_voronoi_diagram.assert_called_once_with(mock_graph, mock_convex_hull)

        # Check both `to_crs` calls
        mock_voronoi_gdf.to_crs.assert_has_calls([
            call(self.calculator.default_projection),  # First call for default projection
            call(self.calculator.output_projection)  # Second call for output projection
        ])
        self.assertEqual(mock_voronoi_gdf.to_crs.call_count, 2)  # Ensure exactly 2 calls occurred

        mock_voronoi_gdf.__getitem__.assert_called_once_with(['geometry'])
        mock_from_geopandas.assert_called_once_with(mock_polygon_subset, npartitions=os.cpu_count())
        mock_voronoi_gdf.to_file.assert_called_once_with(self.output_file_path, driver='GeoJSON')

        # Verify the result
        self.assertIsInstance(result, QualityMetricResult)
        self.assertTrue(result.success)  # Should pass if everything is mocked correctly
        self.assertEqual(result.message, 'QMXNLibCalculator')
        self.assertEqual(result.output_file, self.output_file_path)

    @patch('src.calculators.qm_xn_lib_calculator.dask_geopandas.from_geopandas')
    @patch('src.calculators.qm_xn_lib_calculator.gpd.read_file')
    def test_main_with_polygon(self, mock_read_file, mock_from_geopandas):
        with tempfile.NamedTemporaryFile(suffix='.geojson') as edges_file, \
                tempfile.NamedTemporaryFile(suffix='.geojson') as output_file, \
                tempfile.NamedTemporaryFile(suffix='.geojson') as polygon_file:
            # Create dummy GeoJSON data for edges and polygon files
            dummy_geojson = {
                'type': 'FeatureCollection',
                'features': [
                    {
                        'type': 'Feature',
                        'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [1, 1]]},
                        'properties': {}
                    }
                ]
            }

            # Write dummy data to temporary files
            edges_file.write(json.dumps(dummy_geojson).encode())
            edges_file.flush()

            polygon_file.write(json.dumps(dummy_geojson).encode())
            polygon_file.flush()

            # Mock the input GeoDataFrames
            mock_edges_gdf = MagicMock(spec=gpd.GeoDataFrame)
            mock_polygon_gdf = MagicMock(spec=gpd.GeoDataFrame)
            mock_result_gdf = MagicMock(spec=gpd.GeoDataFrame)

            # Mock behaviors for projections
            mock_edges_gdf.to_crs.return_value = mock_edges_gdf
            mock_polygon_gdf.to_crs.return_value = mock_polygon_gdf
            mock_result_gdf.to_crs.return_value = mock_result_gdf

            # Mock the subset behavior for `tile_gdf[['geometry']]`
            mock_polygon_subset = MagicMock(spec=gpd.GeoDataFrame)
            mock_polygon_gdf.__getitem__.return_value = mock_polygon_subset

            # Mock the final result
            mock_result_gdf.columns = ['geometry', 'tra_score']
            mock_result_gdf['geometry'] = [LineString([(0, 0), (1, 1)])]
            mock_result_gdf['tra_score'] = [1.0]
            mock_result_gdf.to_file = MagicMock()

            # Mock dask_geopandas behavior
            mock_from_geopandas.return_value.apply.return_value.compute.return_value = mock_result_gdf

            # Simulate running the script
            result = run(
                [
                    'python',
                    'src/calculators/qm_xn_lib_calculator.py',
                    edges_file.name,
                    output_file.name,
                    polygon_file.name,
                ],
                stdout=PIPE,
                stderr=PIPE,
                text=True,
            )

            # Debugging: Print stderr if the test fails
            if result.returncode != 0:
                print('Error:', result.stderr)

            # Assertions
            self.assertEqual(result.returncode, 0)

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
                    'python',
                    'src/calculators/qm_xn_lib_calculator.py',
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
        mock_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_get_measures_from_polygon.return_value = {'tra_score': 0.8}

        result = self.calculator.qm_func(mock_feature, mock_gdf)
        self.assertEqual(result.loc['tra_score'], 0.8)

    @patch('src.calculators.qm_xn_lib_calculator.gpd.GeoDataFrame')
    @patch('src.calculators.qm_xn_lib_calculator.voronoi_diagram')
    @patch('src.calculators.qm_xn_lib_calculator.gnx.graph_edges_to_gdf')
    def test_create_voronoi_diagram(self, mock_graph_edges_to_gdf, mock_voronoi_diagram, mock_geo_dataframe):
        # Mock graph and bounds
        mock_graph = MagicMock()
        mock_bounds = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])

        # Mock the GeoDataFrame created from graph edges
        mock_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_gdf.crs = 'epsg:4326'  # Mock the CRS attribute
        mock_graph_edges_to_gdf.return_value = mock_gdf

        # Mock the boundary and unary_union attributes of the GeoDataFrame
        mock_boundary = MagicMock()
        mock_unary_union = MagicMock()
        mock_gdf.boundary = mock_boundary
        mock_boundary.unary_union = mock_unary_union

        # Mock the voronoi_diagram output
        mock_voronoi = MagicMock()
        mock_voronoi_diagram.return_value = mock_voronoi

        # Mock the clipped Voronoi GeoDataFrame
        mock_voronoi_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_voronoi_gdf.set_crs = MagicMock(return_value=mock_voronoi_gdf)
        mock_voronoi_gdf_clipped = MagicMock(spec=gpd.GeoDataFrame)
        mock_voronoi_gdf_clipped.to_crs = MagicMock(return_value=mock_voronoi_gdf_clipped)

        # Mock GeoDataFrame creation and clipping
        mock_geo_dataframe.return_value = mock_voronoi_gdf
        gpd.clip = MagicMock(return_value=mock_voronoi_gdf_clipped)

        # Call the function
        result = self.calculator.create_voronoi_diagram(mock_graph, mock_bounds)

        # Assertions
        mock_graph_edges_to_gdf.assert_called_once_with(mock_graph)
        mock_voronoi_diagram.assert_called_once_with(mock_unary_union, envelope=mock_bounds)
        mock_voronoi_gdf.set_crs.assert_called_once_with(mock_gdf.crs)
        gpd.clip.assert_called_once_with(mock_voronoi_gdf, mock_bounds)
        mock_voronoi_gdf_clipped.to_crs.assert_called_once_with(self.calculator.default_projection)
        self.assertEqual(result, mock_voronoi_gdf_clipped)

    @patch('src.calculators.qm_xn_lib_calculator.gpd.read_file')
    def test_calculate_quality_metric_exception(self, mock_read_file):
        mock_read_file.side_effect = Exception('Mocked exception')

        result = self.calculator.calculate_quality_metric()
        self.assertIsInstance(result, QualityMetricResult)
        self.assertFalse(result.success)
        self.assertIn('Mocked exception', result.message)


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
        mock_tile_tra_score.assert_called_once_with(dummy_graph, dummy_polygon)
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
        mock_get_stats.assert_called_once_with(single_polygon, mock_graph, mock_clipped_gdf)
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



if __name__ == '__main__':
    unittest.main()
