import tempfile
import unittest
from unittest.mock import patch, MagicMock, mock_open
from src.calculators import QMXNLibCalculator, QMFixedCalculator
from src.services.osw_qm_calculator_service import OswQmCalculator



class TestOswQmCalculator(unittest.TestCase):
    def setUp(self):
        self.calculator = OswQmCalculator(cores_to_use=4)

    def test_initialization(self):
        self.assertEqual(self.calculator.cores_to_use, 4)

    @patch('src.services.osw_qm_calculator_service.zipfile.ZipFile')
    @patch('src.services.osw_qm_calculator_service.OswQmCalculator.extract_zip')
    @patch('src.services.osw_qm_calculator_service.OswQmCalculator.get_osw_qm_calculator')
    @patch('src.services.osw_qm_calculator_service.OswQmCalculator.zip_folder')
    def test_calculate_quality_metric(self, mock_zip_folder, mock_get_calculator, mock_extract_zip, mock_zipfile):
        mock_extract_zip.return_value = ['mock_path/edges_file.geojson']
        mock_calculator = MagicMock()
        mock_get_calculator.return_value = mock_calculator

        with tempfile.NamedTemporaryFile() as temp_input, tempfile.NamedTemporaryFile() as temp_output:
            self.calculator.calculate_quality_metric(temp_input.name, ['fixed'], temp_output.name)

        mock_zipfile.assert_called_once()
        mock_extract_zip.assert_called_once()
        mock_get_calculator.assert_called_once_with('fixed', None, 'mock_path/edges_file.geojson', unittest.mock.ANY)
        mock_calculator.calculate_quality_metric.assert_called_once()
        mock_zip_folder.assert_called_once()

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

    @patch('src.services.osw_qm_calculator_service.zipfile.ZipFile')
    def test_zip_folder(self, mock_zipfile):
        with tempfile.TemporaryDirectory() as temp_folder:
            with tempfile.NamedTemporaryFile(dir=temp_folder) as temp_file:
                output_zip = tempfile.NamedTemporaryFile().name
                self.calculator.zip_folder(temp_folder, output_zip)
                mock_zipfile.assert_called_once_with(output_zip, 'w')

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
