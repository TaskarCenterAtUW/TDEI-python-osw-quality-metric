import json
import tempfile
import unittest
import geopandas as gpd
from subprocess import run, PIPE
from unittest.mock import patch, MagicMock
from src.calculators.qm_fixed_calculator import QMFixedCalculator
from src.calculators.qm_calculator import QualityMetricResult


class TestQMFixedCalculator(unittest.TestCase):

    def setUp(self):
        self.edges_file_path = 'test_edges.geojson'
        self.output_file_path = 'test_output.geojson'
        self.polygon_file_path = 'test_polygon.geojson'
        self.calculator = QMFixedCalculator(
            self.edges_file_path,
            self.output_file_path,
            self.polygon_file_path
        )

    def test_initialization(self):
        self.assertEqual(self.calculator.edges_file_path, self.edges_file_path)
        self.assertEqual(self.calculator.output_file_path, self.output_file_path)
        self.assertEqual(self.calculator.polygon_file_path, self.polygon_file_path)

    @patch('src.calculators.qm_fixed_calculator.gpd.read_file')
    @patch('src.calculators.qm_fixed_calculator.gpd.GeoDataFrame.to_file', autospec=True)
    @patch('src.calculators.qm_fixed_calculator.random.randint')
    def test_calculate_quality_metric(self, mock_randint, mock_to_file, mock_read_file):
        # Setup mocks
        mock_randint.return_value = 42
        mock_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_read_file.return_value = mock_gdf

        # Call the method under test
        result = self.calculator.calculate_quality_metric()

        # Assertions
        mock_read_file.assert_called_once_with(self.edges_file_path)
        mock_gdf.__setitem__.assert_called_once_with('fixed_score', 42)
        mock_gdf.to_file.assert_called_once_with(self.output_file_path)
        self.assertIsInstance(result, QualityMetricResult)
        self.assertTrue(result.success)
        self.assertEqual(result.message, 'QMFixedCalculator')
        self.assertEqual(result.output_file, self.output_file_path)

    def test_algorithm_name(self):
        self.assertEqual(self.calculator.algorithm_name(), 'QMFixedCalculator')

    def test_main_with_polygon(self):
        # Create temporary files for edges and polygon
        with tempfile.NamedTemporaryFile(suffix='.geojson') as edges_file, \
                tempfile.NamedTemporaryFile(suffix='.geojson') as output_file, \
                tempfile.NamedTemporaryFile(suffix='.geojson') as polygon_file:
            # Write dummy GeoJSON data to edges and polygon files
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

            edges_file.write(json.dumps(dummy_geojson).encode())
            edges_file.flush()

            polygon_file.write(json.dumps(dummy_geojson).encode())
            polygon_file.flush()

            # Simulate running the script as a standalone process
            result = run(
                [
                    'python',
                    'src/calculators/qm_fixed_calculator.py',
                    edges_file.name,
                    output_file.name,
                    polygon_file.name,
                ],
                stdout=PIPE,
                stderr=PIPE,
                text=True,
            )

            # Debugging: Print stderr if test fails
            if result.returncode != 0:
                print('Error:', result.stderr)

            # Assertions
            self.assertEqual(result.returncode, 0)
            self.assertIn('QMFixedCalculator', result.stdout)

    def test_main_without_polygon(self):
        # Create temporary files for edges
        with tempfile.NamedTemporaryFile(suffix='.geojson') as edges_file, \
                tempfile.NamedTemporaryFile(suffix='.geojson') as output_file:
            # Write dummy GeoJSON data to edges file
            dummy_geojson = {
                'type': 'FeatureCollection',
                'features': []
            }

            edges_file.write(json.dumps(dummy_geojson).encode())
            edges_file.flush()

            # Simulate running the script as a standalone process
            result = run(
                [
                    'python',
                    'src/calculators/qm_fixed_calculator.py',
                    edges_file.name,
                    output_file.name,
                ],
                stdout=PIPE,
                stderr=PIPE,
                text=True,
            )

            # Assertions
            self.assertEqual(result.returncode, 0)
            self.assertIn('QMFixedCalculator', result.stdout)



if __name__ == '__main__':
    unittest.main()
