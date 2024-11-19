import unittest
from src.models.quality_request import RequestData, QualityRequest


class TestRequestData(unittest.TestCase):
    def test_request_data_initialization(self):
        # Test initialization with all fields
        request_data = RequestData(
            jobId='test-job',
            data_file='https://example.com/data-file.zip',
            algorithm='fixed',
            sub_regions_file='https://example.com/sub-region-file.zip'
        )
        self.assertEqual(request_data.jobId, 'test-job')
        self.assertEqual(request_data.data_file, 'https://example.com/data-file.zip')
        self.assertEqual(request_data.algorithm, 'fixed')
        self.assertEqual(request_data.sub_regions_file, 'https://example.com/sub-region-file.zip')

        # Test initialization without optional field
        request_data = RequestData(
            jobId='test-job',
            data_file='https://example.com/data-file.zip',
            algorithm='fixed'
        )
        self.assertEqual(request_data.jobId, 'test-job')
        self.assertEqual(request_data.data_file, 'https://example.com/data-file.zip')
        self.assertEqual(request_data.algorithm, 'fixed')
        self.assertIsNone(request_data.sub_regions_file)


class TestQualityRequest(unittest.TestCase):
    def test_quality_request_initialization(self):
        # Test initialization with valid data
        data_dict = {
            'jobId': 'test-job',
            'data_file': 'https://example.com/data-file.zip',
            'algorithm': 'fixed',
            'sub_regions_file': 'https://example.com/sub-region-file.zip'
        }

        quality_request = QualityRequest(
            messageType='test-message-type',
            messageId='test-message-id',
            data=data_dict
        )

        self.assertEqual(quality_request.messageType, 'test-message-type')
        self.assertEqual(quality_request.messageId, 'test-message-id')
        self.assertIsInstance(quality_request.data, RequestData)
        self.assertEqual(quality_request.data.jobId, 'test-job')
        self.assertEqual(quality_request.data.data_file, 'https://example.com/data-file.zip')
        self.assertEqual(quality_request.data.algorithm, 'fixed')
        self.assertEqual(quality_request.data.sub_regions_file, 'https://example.com/sub-region-file.zip')

    def test_quality_request_initialization_with_missing_optional(self):
        # Test initialization with missing optional field
        data_dict = {
            'jobId': 'test-job',
            'data_file': 'https://example.com/data-file.zip',
            'algorithm': 'fixed'
        }

        quality_request = QualityRequest(
            messageType='test-message-type',
            messageId='test-message-id',
            data=data_dict
        )

        self.assertEqual(quality_request.messageType, 'test-message-type')
        self.assertEqual(quality_request.messageId, 'test-message-id')
        self.assertIsInstance(quality_request.data, RequestData)
        self.assertEqual(quality_request.data.jobId, 'test-job')
        self.assertEqual(quality_request.data.data_file, 'https://example.com/data-file.zip')
        self.assertEqual(quality_request.data.algorithm, 'fixed')
        self.assertIsNone(quality_request.data.sub_regions_file)

    def test_quality_request_initialization_with_invalid_data(self):
        # Test initialization with invalid data (missing required fields)
        invalid_data = {
            'jobId': 'test-job',
            'data_file': 'https://example.com/data-file.zip',
        }  # Missing 'algorithm'

        with self.assertRaises(TypeError) as context:
            QualityRequest(
                messageType='test-message-type',
                messageId='test-message-id',
                data=invalid_data
            )
        self.assertIn("__init__() missing 1 required positional argument: 'algorithm'", str(context.exception))


if __name__ == '__main__':
    unittest.main()
