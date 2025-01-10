import unittest
from abc import ABC, abstractmethod
from src.calculators import QMCalculator
from src.calculators.qm_calculator import QualityMetricResult

# A concrete implementation for testing purposes
class MockQMCalculator(QMCalculator):
    def calculate_quality_metric(self) -> QualityMetricResult:
        return QualityMetricResult(success=True, message='Calculation succeeded.', output_file='output.geojson')

    def algorithm_name(self) -> str:
        return 'mock-algorithm'

class TestQualityMetricResult(unittest.TestCase):
    def test_quality_metric_result_initialization(self):
        # Create a QualityMetricResult instance
        result = QualityMetricResult(
            success=True,
            message='Calculation succeeded.',
            output_file='output.geojson'
        )

        # Assertions
        self.assertTrue(result.success)
        self.assertEqual(result.message, 'Calculation succeeded.')
        self.assertEqual(result.output_file, 'output.geojson')

class TestQMCalculator(unittest.TestCase):
    def test_qm_calculator_is_abstract(self):
        # Ensure QMCalculator cannot be instantiated directly
        with self.assertRaises(TypeError):
            QMCalculator()

    def test_concrete_implementation(self):
        # Instantiate the mock implementation
        calculator = MockQMCalculator()

        # Test calculate_quality_metric
        result = calculator.calculate_quality_metric()
        self.assertIsInstance(result, QualityMetricResult)
        self.assertTrue(result.success)
        self.assertEqual(result.message, 'Calculation succeeded.')
        self.assertEqual(result.output_file, 'output.geojson')

        # Test algorithm_name
        self.assertEqual(calculator.algorithm_name(), 'mock-algorithm')

if __name__ == '__main__':
    unittest.main()
