import unittest
from unittest.mock import patch, MagicMock
from src.services.servicebus_service import ServiceBusService
from src.models.quality_request import RequestData, QualityRequest
from src.models.quality_response import QualityMetricResponse
from python_ms_core.core.queue.models.queue_message import QueueMessage


class TestServiceBusService(unittest.TestCase):
    @patch('src.services.servicebus_service.Config')
    @patch('src.services.servicebus_service.Core')
    def setUp(self, mock_core, mock_config):
        # Mock Config
        mock_config.return_value.connection_string = 'mock-connection-string'
        mock_config.return_value.incoming_topic_name = 'mock-incoming-topic'
        mock_config.return_value.outgoing_topic_name = 'mock-outgoing-topic'
        mock_config.return_value.max_concurrent_messages = 5
        mock_config.return_value.incoming_topic_subscription = 'mock-subscription'

        # Mock Core
        mock_core.return_value.get_topic.return_value = MagicMock()
        mock_core.return_value.get_storage_client.return_value = MagicMock()

        # Initialize the service
        self.service = ServiceBusService()
        self.service.storage_service = MagicMock()
        self.test_message = QueueMessage(
            messageType='mettric-calculation',
            messageId='message-id-from-msg',
            data={
                'jobId': '0b41ebc5-350c-42d3-90af-3af4ad3628fb',
                'data_file': 'https://tdeisamplestorage.blob.core.windows.net/abc.zip',
                'algorithm': 'fixed',
                'sub_regions_file': None
            }
        )

        self.success_message = QualityMetricResponse(
            messageType=self.test_message.messageType,
            messageId=self.test_message.messageId,
            data={
                'status': 'success',
                'message': 'Quality metrics calculated successfully',
                'success': True,
                'dataset_url': self.test_message.data['data_file'],
                'qm_dataset_url': self.test_message.data['data_file']
            }
        )

    def test_initialization(self):
        self.assertIsInstance(self.service.core, MagicMock)
        self.assertIsInstance(self.service.config, MagicMock)
        self.assertIsInstance(self.service.storage_service, MagicMock)

    @patch('src.services.servicebus_service.OswQmCalculator')
    @patch('src.services.servicebus_service.shutil.rmtree')
    def test_process_message_success_without_sub_region(self, mock_rmtree, mock_calculator):
        # Mock message and dependencies

        self.service.storage_service.download_remote_file = MagicMock()
        self.service.storage_service.upload_local_file = MagicMock(return_value='https://example.com/qm-output.zip')
        mock_calculator_instance = MagicMock()
        mock_calculator.return_value = mock_calculator_instance

        self.service.process_message(self.test_message)

        # Assertions
        self.service.storage_service.download_remote_file.assert_called_once()
        mock_calculator_instance.calculate_quality_metric.assert_called_once()
        self.service.storage_service.upload_local_file.assert_called_once()
        mock_rmtree.assert_called_once()

    @patch('src.services.servicebus_service.OswQmCalculator')
    @patch('src.services.servicebus_service.shutil.rmtree')
    def test_process_message_success_with_sub_region(self, mock_rmtree, mock_calculator):
        # Mock message and dependencies


        self.test_message.data['sub_regions_file'] = self.test_message.data['data_file']

        self.service.storage_service.download_remote_file = MagicMock()
        self.service.storage_service.upload_local_file = MagicMock(return_value='https://example.com/qm-output.zip')
        mock_calculator_instance = MagicMock()
        mock_calculator.return_value = mock_calculator_instance

        self.service.process_message(self.test_message)

        # Assertions
        self.service.storage_service.download_remote_file.assert_called()
        mock_calculator_instance.calculate_quality_metric.assert_called_once()
        self.service.storage_service.upload_local_file.assert_called_once()
        mock_rmtree.assert_called_once()

    @patch('src.services.servicebus_service.logger')
    def test_process_message_failure(self, mock_logger):
        self.test_message.data['data_file'] = 'invalid_file_path'

        # Simulate a download failure
        self.service.storage_service.download_remote_file.side_effect = Exception('Download failed')

        self.service.process_message(self.test_message)

        # Assertions
        mock_logger.error.assert_called_with('Error processing message message-id-from-msg : Download failed')

    @patch('src.services.servicebus_service.QueueMessage')
    @patch('src.services.servicebus_service.logger')
    def test_send_response_success(self, mock_logger, mock_queue_message):
        self.service.send_response(self.success_message)

        # Assertions
        mock_queue_message.data_from.assert_called_once()
        mock_logger.info.assert_called_with('Publishing response for message message-id-from-msg')

    @patch('src.services.servicebus_service.logger')
    def test_send_response_failure(self, mock_logger):
        self.service.send_response(self.test_message)

        # Assertions
        mock_logger.error.assert_called_with('Failed to send response for message message-id-from-msg with error asdict() should be called on dataclass instances')

    def test_get_directory_path(self):
        url = 'https://example.com/osw/test_upload/df/fff/500mb_file.zip'
        expected_path = 'test_upload/df/fff'
        result = self.service.get_directory_path(url)
        self.assertEqual(result, expected_path)

    @patch('src.services.servicebus_service.threading.Thread.join')
    def test_stop(self, mock_join):
        self.service.stop()
        mock_join.assert_called_once_with(timeout=0)


if __name__ == '__main__':
    unittest.main()
