import unittest
import os
import tempfile
import zipfile
from unittest.mock import patch, MagicMock
from src.services.servicebus_service import ServiceBusService
from src.models.quality_request import RequestData, QualityRequest
from src.models.quality_response import QualityMetricResponse
from python_ms_core.core.queue.models.queue_message import QueueMessage
from python_ms_core.core.topic.azure_topic import AzureTopic


class TestServiceBusService(unittest.TestCase):
    @patch('src.services.servicebus_service.Config')
    @patch('src.services.servicebus_service.Core')
    def setUp(self, mock_core, mock_config):
        # Listener behavior is invoked explicitly in these unit tests. Avoid
        # background threads observing a later test's reinitialized singleton.
        self.enterContext(patch.object(ServiceBusService, '_instance', None))
        self.enterContext(patch('src.services.servicebus_service.threading.Thread.start'))
        # Mock Config
        mock_config.return_value.connection_string = 'mock-connection-string'
        mock_config.return_value.incoming_topic_name = 'mock-incoming-topic'
        mock_config.return_value.outgoing_topic_name = 'mock-outgoing-topic'
        mock_config.return_value.max_concurrent_messages = 5
        mock_config.return_value.incoming_topic_subscription = 'mock-subscription'
        mock_config.return_value.max_receivable_messages = -1

        # Mock Core
        mock_core.return_value.get_topic.return_value = MagicMock()
        mock_core.return_value.get_storage_client.return_value = MagicMock()

        # Initialize the service
        self.service = ServiceBusService()
        self.service.storage_service = MagicMock()
        self.download_root = self.enterContext(tempfile.TemporaryDirectory())
        self.service.config.get_download_folder.return_value = self.download_root
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

    @patch('src.services.servicebus_service.threading.Thread.start')
    @patch.object(ServiceBusService, '_stop_server_and_container')
    @patch('src.services.servicebus_service.Config')
    @patch('src.services.servicebus_service.Core')
    def test_start_listening_stops_container_after_subscribe_returns(
        self,
        mock_core,
        mock_config,
        mock_stop_server_and_container,
        mock_thread_start,
    ):
        mock_config.return_value.connection_string = 'mock-connection-string'
        mock_config.return_value.incoming_topic_name = 'mock-incoming-topic'
        mock_config.return_value.outgoing_topic_name = 'mock-outgoing-topic'
        mock_config.return_value.max_concurrent_messages = 5
        mock_config.return_value.incoming_topic_subscription = 'mock-subscription'
        mock_config.return_value.max_receivable_messages = 1

        mock_incoming_topic = MagicMock()
        mock_outgoing_topic = MagicMock()
        mock_core.return_value.get_topic.side_effect = [mock_incoming_topic, mock_outgoing_topic]
        mock_core.return_value.get_storage_client.return_value = MagicMock()

        service = ServiceBusService()

        service.start_listening()

        mock_incoming_topic.subscribe.assert_called_once_with(
            'mock-subscription',
            service.process_message,
            1,
        )
        mock_stop_server_and_container.assert_called_once_with(delay_seconds=5)

    @patch('src.services.servicebus_service.OswQmCalculator')
    def test_process_message_success_without_sub_region(self, mock_calculator):
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

    @patch('src.services.servicebus_service.OswQmCalculator')
    def test_process_message_success_with_sub_region(self, mock_calculator):
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

    @patch('src.services.servicebus_service.logger')
    def test_process_message_failure(self, mock_logger):
        self.test_message.data['data_file'] = 'invalid_file_path'

        # Simulate a download failure
        self.service.storage_service.download_remote_file.side_effect = Exception('Download failed')

        self.service.process_message(self.test_message)

        # Assertions
        mock_logger.error.assert_called_with('Error processing message message-id-from-msg : Download failed')

    @patch('src.services.servicebus_service.OswQmCalculator')
    def test_processing_duration_is_logged_on_success_and_failure(self, calculator):
        for error in [None, RuntimeError('Calculation failed')]:
            with self.subTest(error=error):
                calculator.return_value.calculate_quality_metric.side_effect = error
                with patch('src.services.servicebus_service.time.monotonic', side_effect=[10, 14]), \
                        patch('src.services.servicebus_service.logger') as logger, \
                        patch.object(self.service, 'send_response'):
                    self.service.process_message(self.test_message)
                logger.info.assert_any_call(
                    'Message processing finished: message_id=%s status=%s elapsed_seconds=%.3f',
                    self.test_message.messageId, 'failed' if error else 'success', 4,
                )

    def test_listener_logs_reported_lock_renewal_and_concurrency(self):
        self.service.incoming_topic.max_renewal_duration = 86400
        self.service.config.partition_count = 2
        with patch('src.services.servicebus_service.logger') as logger:
            self.service.start_listening()
        logger.info.assert_any_call(
            'Queue worker timing: python_ms_core=%s max_concurrent_messages=%s '
            'partition_count=%s reported_lock_renewal_limit_seconds=%s',
            unittest.mock.ANY, 5, 2, 86400,
        )

    @patch('src.calculators.qm_xn_lib_calculator.fetch_seed_graph',
           side_effect=RuntimeError('Fairway Mapper unavailable'))
    def test_calculator_failure_sends_failed_response_without_upload(self, fetch):
        self.test_message.data['algorithm'] = 'ixn'
        self.service.config.partition_count = 1
        self.service.config.intersection_distance = 50.0
        self.service.config.debug_intersection_polygons = False
        edges = os.path.join(os.path.dirname(__file__), '..', 'xnqm', 'inputs', 'p13_edges.geojson')

        def download(url, path):
            with zipfile.ZipFile(path, 'w') as archive:
                archive.write(edges, 'test.edges.geojson')

        self.service.storage_service.download_remote_file.side_effect = download
        with tempfile.TemporaryDirectory() as folder:
            self.service.config.get_download_folder.return_value = folder
            with patch.object(self.service, 'send_response') as send:
                # Exercise the real calculator and packaging wrapper; mock only
                # the network failure and external storage/message transport.
                self.service.process_message(self.test_message)
            fetch.assert_called_once()
            self.service.storage_service.upload_local_file.assert_not_called()
            send.assert_called_once()
            response = send.call_args.args[0]
            self.assertEqual(response.data.status, 'failed')
            self.assertFalse(response.data.success)
            self.assertIsNone(response.data.qm_dataset_url)
            self.assertIn('Fairway Mapper unavailable', response.data.message)
            self.assertEqual(response.messageId, self.test_message.messageId)
            self.assertFalse(os.path.exists(os.path.join(
                folder, self.test_message.messageId, 'qm', 'qm-output.zip',
            )))

    @patch('src.services.servicebus_service.QueueMessage')
    @patch('src.services.servicebus_service.logger')
    def test_send_response_success(self, mock_logger, mock_queue_message):
        self.service.send_response(self.success_message)

        # Assertions
        mock_queue_message.data_from.assert_called_once()
        mock_logger.info.assert_called_with('Publishing response for message message-id-from-msg')

    @patch('src.services.servicebus_service.logger')
    def test_send_response_failure(self, mock_logger):
        with self.assertRaisesRegex(TypeError, 'asdict'):
            self.service.send_response(self.test_message)

        # Assertions
        mock_logger.error.assert_called_with('Failed to send response for message message-id-from-msg with error asdict() should be called on dataclass instances')

    @patch('src.services.servicebus_service.OswQmCalculator')
    def test_response_delivery_failure_reaches_queue_without_false_failure_response(self, calculator):
        publisher = self.service.core.get_topic.return_value.publish
        publisher.side_effect = RuntimeError('Response transport unavailable')
        self.service.storage_service.upload_local_file.return_value = 'https://example.com/output.zip'
        # Use the installed worker's real callback adapter, with only external
        # calculation/storage/publishing mocked. Failure must trigger redelivery.
        worker = object.__new__(AzureTopic)
        for calculation_error in [None, RuntimeError('Calculation failed')]:
            with self.subTest(calculation_error=calculation_error):
                publisher.reset_mock()
                calculator.return_value.calculate_quality_metric.side_effect = calculation_error
                with self.assertLogs('QualityMetricService', level='INFO') as logs:
                    result = worker.internal_callback(self.test_message.__dict__, self.service.process_message)
                self.assertFalse(result['success'])
                self.assertIn('Response transport unavailable', result['error'])
                publisher.assert_called_once()
                response = publisher.call_args.kwargs['data']
                self.assertEqual(response.messageId, self.test_message.messageId)
                self.assertEqual(response.data['success'], calculation_error is None)
                self.assertTrue(any('status=response_delivery_failed' in line for line in logs.output))

    @patch('src.services.servicebus_service.OswQmCalculator')
    def test_redelivery_uses_isolated_files_and_outputs_with_stable_message_id(self, calculator):
        publisher = self.service.core.get_topic.return_value.publish
        publisher.side_effect = [RuntimeError('Response transport unavailable'), None]
        uploads = {}

        def upload(local_path, remote_path):
            self.assertNotIn(remote_path, uploads, 'A retry must not collide with an existing blob')
            uploads[remote_path] = local_path
            return 'https://example.com/' + remote_path.lstrip('/')

        self.service.storage_service.upload_local_file.side_effect = upload
        with self.assertRaisesRegex(RuntimeError, 'Response transport unavailable'):
            self.service.process_message(self.test_message)
        self.service.process_message(self.test_message)
        self.assertEqual(len(uploads), 2)
        self.assertEqual(len(set(uploads.values())), 2)
        downloads = self.service.storage_service.download_remote_file.call_args_list
        self.assertNotEqual(downloads[0].args[1], downloads[1].args[1])
        responses = [call.kwargs['data'] for call in publisher.call_args_list]
        self.assertEqual([response.messageId for response in responses], [self.test_message.messageId] * 2)
        self.assertTrue(all(response.data['success'] for response in responses))
        self.assertNotEqual(responses[0].data['qm_dataset_url'], responses[1].data['qm_dataset_url'])

    @patch('src.services.servicebus_service.OswQmCalculator')
    def test_reported_calculation_failure_is_a_completed_queue_callback(self, calculator):
        calculator.return_value.calculate_quality_metric.side_effect = RuntimeError('Calculation failed')
        worker = object.__new__(AzureTopic)
        result = worker.internal_callback(self.test_message.__dict__, self.service.process_message)
        self.assertTrue(result['success'])
        publisher = self.service.core.get_topic.return_value.publish
        publisher.assert_called_once()
        self.assertFalse(publisher.call_args.kwargs['data'].data['success'])
        self.service.storage_service.upload_local_file.assert_not_called()

    def test_get_directory_path(self):
        url = 'https://example.com/osw/test_upload/df/fff/500mb_file.zip'
        expected_path = 'test_upload/df/fff'
        result = self.service.get_directory_path(url)
        self.assertEqual(result, expected_path)

    @patch.object(ServiceBusService, '_stop_server_and_container')
    @patch('src.services.servicebus_service.threading.Thread.join')
    def test_stop(self, mock_join, mock_stop_server_and_container):
        self.service.stop()
        mock_stop_server_and_container.assert_called_once_with()
        mock_join.assert_called_once_with(timeout=0)


if __name__ == '__main__':
    unittest.main()
