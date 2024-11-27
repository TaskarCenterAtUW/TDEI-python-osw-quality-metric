import unittest
from src.models.quality_response import ResponseData, QualityMetricResponse


class TestResponseData(unittest.TestCase):
    def test_response_data_initialization(self):
        # Test initialization with all fields
        response_data = ResponseData(
            status='success',
            message='Metrics calculated successfully.',
            success=True,
            dataset_url='https://example.com/dataset.zip',
            qm_dataset_url='https://example.com/qm-dataset.zip'
        )
        self.assertEqual(response_data.status, 'success')
        self.assertEqual(response_data.message, 'Metrics calculated successfully.')
        self.assertTrue(response_data.success)
        self.assertEqual(response_data.dataset_url, 'https://example.com/dataset.zip')
        self.assertEqual(response_data.qm_dataset_url, 'https://example.com/qm-dataset.zip')


class TestQualityMetricResponse(unittest.TestCase):
    def test_quality_metric_response_initialization(self):
        # Valid data dictionary for ResponseData
        data_dict = {
            'status': 'success',
            'message': 'Metrics calculated successfully.',
            'success': True,
            'dataset_url': 'https://example.com/dataset.zip',
            'qm_dataset_url': 'https://example.com/qm-dataset.zip'
        }

        # Initialize QualityMetricResponse
        response = QualityMetricResponse(
            messageType='test-message-type',
            messageId='test-message-id',
            data=data_dict
        )

        # Assertions
        self.assertEqual(response.messageType, 'test-message-type')
        self.assertEqual(response.messageId, 'test-message-id')
        self.assertIsInstance(response.data, ResponseData)
        self.assertEqual(response.data.status, 'success')
        self.assertEqual(response.data.message, 'Metrics calculated successfully.')
        self.assertTrue(response.data.success)
        self.assertEqual(response.data.dataset_url, 'https://example.com/dataset.zip')
        self.assertEqual(response.data.qm_dataset_url, 'https://example.com/qm-dataset.zip')

    def test_quality_metric_response_with_invalid_data(self):
        # Test with missing required fields in the data dictionary
        invalid_data = {
            'status': 'success',
            'message': 'Metrics calculated successfully.',
            'success': True,
            'dataset_url': 'https://example.com/dataset.zip'
            # Missing qm_dataset_url
        }

        with self.assertRaises(TypeError) as context:
            QualityMetricResponse(
                messageType='test-message-type',
                messageId='test-message-id',
                data=invalid_data
            )
        self.assertIn("__init__() missing 1 required positional argument: 'qm_dataset_url'", str(context.exception))


if __name__ == '__main__':
    unittest.main()
