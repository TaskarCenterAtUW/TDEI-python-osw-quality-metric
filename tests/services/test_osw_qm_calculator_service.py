import tempfile
import os
import zipfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import geopandas as gpd
import osmnx as ox
from shapely.geometry import box
from src.calculators import QMXNLibCalculator, QMFixedCalculator
from src.calculators.qm_calculator import QualityMetricResult
from src.services.osw_qm_calculator_service import OswQmCalculator



class TestOswQmCalculator(unittest.TestCase):
    def setUp(self):
        self.calculator = OswQmCalculator(cores_to_use=4)

    def test_initialization(self):
        self.assertEqual(self.calculator.cores_to_use, 4)

    def make_input_zip(self, folder):
        path = os.path.join(folder, 'input.zip')
        edges = os.path.join(os.path.dirname(__file__), '..', 'xnqm', 'inputs', 'p13_edges.geojson')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.write(edges, 'test.edges.geojson')
        return path

    def test_calculate_quality_metric(self):
        with tempfile.TemporaryDirectory() as folder:
            input_path = self.make_input_zip(folder)
            output_path = os.path.join(folder, 'output.zip')
            self.calculator.calculate_quality_metric(input_path, ['fixed'], output_path)
            with zipfile.ZipFile(output_path) as archive:
                self.assertEqual(archive.namelist(), ['fixed_qm.geojson'])
                output = json.loads(archive.read('fixed_qm.geojson'))
                self.assertGreater(len(output['features']), 0)
                self.assertIn('fixed_score', output['features'][0]['properties'])

    def test_failed_calculator_prevents_packaging_partial_results(self):
        with tempfile.TemporaryDirectory() as folder:
            input_path = self.make_input_zip(folder)
            output_path = os.path.join(folder, 'output.zip')
            original_factory = self.calculator.get_osw_qm_calculator
            failed = MagicMock()
            failed.calculate_quality_metric.return_value = QualityMetricResult(
                success=False, message='Fairway Mapper unavailable', output_file='',
            )

            def factory(algorithm, *args):
                return failed if algorithm == 'ixn' else original_factory(algorithm, *args)

            with patch.object(self.calculator, 'get_osw_qm_calculator', side_effect=factory), \
                    patch.object(self.calculator, 'zip_folder') as package:
                with self.assertRaisesRegex(RuntimeError, "Quality metric 'ixn' failed: Fairway Mapper unavailable"):
                    self.calculator.calculate_quality_metric(input_path, ['fixed', 'ixn'], output_path)
            package.assert_not_called()
            self.assertFalse(os.path.exists(output_path))

    def test_success_without_output_prevents_packaging(self):
        for empty_file in [False, True]:
            with self.subTest(empty_file=empty_file), tempfile.TemporaryDirectory() as folder:
                input_path = self.make_input_zip(folder)
                output_path = os.path.join(folder, 'output.zip')

                def factory(algorithm, ixn_file, edges_file, expected_output):
                    if empty_file:
                        with open(expected_output, 'w'):
                            pass
                    calculator = MagicMock()
                    calculator.calculate_quality_metric.return_value = QualityMetricResult(
                        success=True, message='success', output_file=expected_output,
                    )
                    return calculator

                with patch.object(self.calculator, 'get_osw_qm_calculator', side_effect=factory), \
                        patch.object(self.calculator, 'zip_folder') as package:
                    with self.assertRaisesRegex(RuntimeError, 'output file is missing or empty'):
                        self.calculator.calculate_quality_metric(input_path, ['ixn'], output_path)
                package.assert_not_called()
                self.assertFalse(os.path.exists(output_path))

    @patch('src.services.osw_qm_calculator_service.zipfile.ZipFile')
    @patch('src.services.osw_qm_calculator_service.OswQmCalculator.extract_zip')
    def test_calculate_quality_metric_no_edges_file(self, mock_extract_zip, mock_zipfile):
        mock_extract_zip.return_value = []

        with tempfile.NamedTemporaryFile() as temp_input, tempfile.NamedTemporaryFile() as temp_output:
            with self.assertRaises(Exception) as context:
                self.calculator.calculate_quality_metric(temp_input.name, ['fixed'], temp_output.name)
            self.assertEqual(str(context.exception), 'Edges file not found in input files.')

    def test_get_osw_qm_calculator(self):
        calculator = self.calculator.get_osw_qm_calculator('fixed', None, 'edges.geojson', 'output.geojson')
        self.assertIsInstance(calculator, QMFixedCalculator)

        calculator = self.calculator.get_osw_qm_calculator('ixn', 'ixn_file', 'edges.geojson', 'output.geojson')
        self.assertIsInstance(calculator, QMXNLibCalculator)
        self.assertFalse(calculator.debug_intersection_polygons)

    def test_intersection_options_are_passed_to_the_library(self):
        service = OswQmCalculator(
            cores_to_use=2, intersection_distance=35.0, debug_intersection_polygons=True,
        )
        calculator = service.get_osw_qm_calculator('ixn', None, 'edges.geojson', 'ixn_qm.geojson')
        self.assertTrue(calculator.debug_intersection_polygons)
        self.assertEqual(calculator.intersection_distance, 35.0)

    @patch('src.calculators.qm_xn_lib_calculator.fetch_seed_graph', return_value=None)
    def test_output_zip_contains_polygon_debug_scores_only_when_enabled(self, fetch):
        edges = os.path.join(os.path.dirname(__file__), '..', 'xnqm', 'inputs', 'p13_edges.geojson')
        with tempfile.TemporaryDirectory() as tmp:
            input_path = os.path.join(tmp, 'input.zip')
            output_path = os.path.join(tmp, 'output.zip')
            with zipfile.ZipFile(input_path, 'w') as archive:
                archive.write(edges, 'test.edges.geojson')
            for enabled in [False, True]:
                with self.subTest(debug=enabled):
                    service = OswQmCalculator(cores_to_use=1, debug_intersection_polygons=enabled)
                    service.calculate_quality_metric(input_path, ['ixn'], output_path)
                    with zipfile.ZipFile(output_path) as archive:
                        self.assertIn('ixn_qm.geojson', archive.namelist())
                        self.assertEqual('ixn_qm_intersection_scores.geojson' in archive.namelist(), enabled)

    @patch('src.services.osw_qm_calculator_service.zipfile.ZipFile')
    def test_zip_folder(self, mock_zipfile):
        with tempfile.TemporaryDirectory() as temp_folder:
            with tempfile.NamedTemporaryFile(dir=temp_folder) as temp_file:
                output_zip = tempfile.NamedTemporaryFile().name
                self.calculator.zip_folder(temp_folder, output_zip)
                mock_zipfile.assert_called_once_with(output_zip, 'w')

    def test_serialized_zip_matches_downstream_score_contract(self):
        tests_dir = Path(__file__).resolve().parents[1]
        example_path = tests_dir / 'fixtures' / 'consumer_contract' / 'ixn_qm.geojson'
        example = json.loads(example_path.read_text())
        tiles = gpd.read_file(example_path)
        # Control the polygon scores to cover edge cases deterministically;
        # aggregation, GeoJSON writing, and service packaging remain real.
        polygons = []
        for tile_index, count in [(0, 1), (1, 1), (2, 3), (3, 1)]:
            x, y, _, _ = tiles.geometry.iloc[tile_index].bounds
            for offset in range(count):
                polygons.append(box(x + .001 + offset * .002, y + .002,
                                    x + .002 + offset * .002, y + .003))
        scores = gpd.GeoDataFrame({
            'tra_score': [0., 1., 0., 1., -1., -1.],
            'total_edges': [6, 6, 6, 10, -1, -1],
            'connect_edges': [0, 6, 0, 10, -1, -1],
        }, geometry=polygons, crs=4326)
        graph = ox.load_graphml(tests_dir / 'xnqm' / 'inputs' / 'p13_seed.graphml')
        with tempfile.TemporaryDirectory() as folder:
            input_path = self.make_input_zip(folder)
            tile_path = os.path.join(folder, 'supplied_tiles.geojson')
            tiles[['geometry']].to_file(tile_path, driver='GeoJSON')
            output_path = os.path.join(folder, 'output.zip')
            for debug in [False, True]:
                with self.subTest(debug=debug), \
                        patch('src.calculators.qm_xn_lib_calculator.fetch_seed_graph', return_value=graph), \
                        patch.object(QMXNLibCalculator, 'score_intersections', return_value=scores):
                    service = OswQmCalculator(cores_to_use=1, debug_intersection_polygons=debug)
                    service.calculate_quality_metric(input_path, ['ixn'], output_path, ixn_file=tile_path)
                    with zipfile.ZipFile(output_path) as archive:
                        expected_files = {'ixn_qm.geojson'}
                        if debug:
                            expected_files.add('ixn_qm_intersection_scores.geojson')
                            diagnostics = json.loads(archive.read('ixn_qm_intersection_scores.geojson'))
                            self.assertEqual(len(diagnostics['features']), 6)
                            for feature in diagnostics['features']:
                                self.assertEqual(feature['properties']['ext:scoring_algorithm_version'],
                                                 'intersection-approaches-v1')
                        self.assertEqual(set(archive.namelist()), expected_files)
                        output = json.loads(archive.read('ixn_qm.geojson'))
                self.assertEqual(output['type'], 'FeatureCollection')
                self.assertEqual([f['properties'] for f in output['features']],
                                 [f['properties'] for f in example['features']])
                restored = gpd.GeoDataFrame.from_features(output, crs=4326)
                self.assertTrue(restored.geom_equals_exact(tiles.geometry, tolerance=1e-10).all())

    @patch('src.services.osw_qm_calculator_service.zipfile.ZipFile')
    @patch('os.walk')
    def test_extract_zip(self, mock_walk, mock_zipfile):
        mock_zip = MagicMock()
        mock_zipfile.return_value = mock_zip
        mock_walk.return_value = [('/mock', [], ['file1.geojson', 'file2.geojson'])]
        with tempfile.TemporaryDirectory() as temp_folder:
            extracted_files = self.calculator.extract_zip(mock_zip, temp_folder)
        self.assertEqual(extracted_files, ['/mock/file1.geojson', '/mock/file2.geojson'])
        mock_zip.extractall.assert_called_once_with(temp_folder)

    @patch('builtins.open', new_callable=mock_open, read_data='{"features": [{"id": 1}]}')
    @patch('src.services.osw_qm_calculator_service.Config')
    @patch('src.services.osw_qm_calculator_service.QMFixedCalculator')
    def test_parse_and_calculate_quality_metric_with_fixed(self, mock_qm_calculator, mock_config, mock_open):
        # Mock the algorithm dictionary to return the mocked calculator
        mock_instance = MagicMock()
        mock_instance.qm_metric_tag.return_value = 'fixed'
        mock_instance.calculate_quality_metric.return_value = 42  # Example metric value
        mock_qm_calculator.return_value = mock_instance

        mock_config.return_value.algorithm_dictionary = {'fixed': mock_qm_calculator}

        # Call the method under test
        result = self.calculator.parse_and_calculate_quality_metric('input.json', ['fixed'])

        # Verify results
        self.assertEqual(result, {"features": [{"id": 1, "fixed": 42}]})  # Expected modified JSON
        mock_qm_calculator.assert_called_once()  # Ensure the calculator is instantiated
        mock_instance.qm_metric_tag.assert_called_once()  # Ensure qm_metric_tag was called
        mock_instance.calculate_quality_metric.assert_called_once()  # Ensure calculation was performed

    @patch('builtins.open', new_callable=mock_open, read_data='{"features": [{"id": 1}]}')
    @patch('src.services.osw_qm_calculator_service.Config')
    @patch('src.services.osw_qm_calculator_service.logger')
    def test_parse_and_calculate_quality_metric_with_unknown_algorithm(self, mock_logger, mock_config, mock_open):
        # Mock algorithm dictionary to have no matching algorithm
        mock_config.return_value.algorithm_dictionary = {'fixed': MagicMock()}

        # Call the method with an unknown algorithm
        result = self.calculator.parse_and_calculate_quality_metric('input.json', ['unknown_algorithm'])

        # Verify results
        self.assertEqual(result, {"features": [{"id": 1}]})  # No change to features
        mock_logger.warning.assert_called_once_with('Algorithm not found : unknown_algorithm')  # Warning logged


if __name__ == '__main__':
    unittest.main()
