import unittest
from unittest.mock import patch
from src.config import Config
from src.calculators import QMFixedCalculator, QMXNLibCalculator


class TestConfig(unittest.TestCase):

    def test_default_values(self):
        config = Config()
        self.assertEqual(config.app_name, 'osw-quality-metric-service-python')
        self.assertEqual(config.incoming_topic_name, '')
        self.assertEqual(config.incoming_topic_subscription, '')
        self.assertEqual(config.outgoing_topic_name, '')
        self.assertEqual(config.storage_container_name, 'osw')
        self.assertEqual(config.max_concurrent_messages, 1)
        self.assertEqual(config.partition_count, 2)

    def test_algorithm_dictionary(self):
        config = Config()
        self.assertIn('fixed', config.algorithm_dictionary)
        self.assertIn('ixn', config.algorithm_dictionary)
        self.assertIs(config.algorithm_dictionary['fixed'], QMFixedCalculator)
        self.assertIs(config.algorithm_dictionary['ixn'], QMXNLibCalculator)

    @patch('src.config.os.path.dirname')
    def test_get_download_folder(self, mock_dirname):
        mock_dirname.side_effect = lambda path: '/mock/root'
        config = Config()
        download_folder = config.get_download_folder()
        self.assertEqual(download_folder, '/mock/root/downloads')

    @patch('src.config.os.path.dirname')
    def test_get_assets_folder(self, mock_dirname):
        mock_dirname.side_effect = lambda path: '/mock/root/src'
        config = Config()
        assets_folder = config.get_assets_folder()
        self.assertEqual(assets_folder, '/mock/root/src/assets')

    @patch.dict('os.environ', {
        'QUALITY_REQ_TOPIC': 'test_topic',
        'QUALITY_REQ_SUB': 'test_subscription',
        'QUALITY_RES_TOPIC': 'test_outgoing_topic',
        'CONTAINER_NAME': 'test_container',
        'MAX_CONCURRENT_MESSAGES': '5',
        'PARTITION_COUNT': '10'
    })
    def test_environment_variable_overrides(self):
        config = Config()
        self.assertEqual(config.incoming_topic_name, '')
        self.assertEqual(config.incoming_topic_subscription, '')
        self.assertEqual(config.outgoing_topic_name, '')
        self.assertEqual(config.storage_container_name, 'osw')
        self.assertEqual(config.max_concurrent_messages, 5)  # Casts to int
        self.assertEqual(config.partition_count, 10)  # Casts to int


if __name__ == '__main__':
    unittest.main()
