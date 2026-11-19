import os
import unittest
from unittest.mock import patch
from src.config import Config
from src.calculators import QMFixedCalculator, QMXNLibCalculator


def _env_without(*names):
    return {k: v for k, v in os.environ.items() if k not in names}


class TestConfig(unittest.TestCase):

    def test_default_values(self):
        config = Config()
        self.assertEqual(config.app_name, 'osw-quality-metric-service-python')
        self.assertEqual(config.incoming_topic_name, '')
        self.assertEqual(config.incoming_topic_subscription, '')
        self.assertEqual(config.outgoing_topic_name, '')
        self.assertEqual(config.storage_container_name, 'osw')
        self.assertEqual(config.max_concurrent_messages, 1)
        self.assertEqual(config.intersection_distance, 50.0)
        self.assertFalse(config.debug_intersection_polygons)

    @patch.dict('os.environ', {'DEFAULT_CPU': '4'})
    def test_partition_count_defaults_to_default_cpu(self):
        with patch.dict('os.environ', _env_without('PARTITION_COUNT'), clear=True):
            self.assertEqual(Config().partition_count, 4)

    def test_partition_count_falls_back_to_the_os_cpu_count(self):
        with patch.dict('os.environ', _env_without('PARTITION_COUNT', 'DEFAULT_CPU'), clear=True), \
                patch('src.calculators.cpus.os.cpu_count', return_value=3):
            self.assertEqual(Config().partition_count, 3)

    @patch.dict('os.environ', {'DEFAULT_CPU': '4', 'PARTITION_COUNT': '16'})
    def test_partition_count_overrides_default_cpu(self):
        self.assertEqual(Config().partition_count, 16)

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
        'PARTITION_COUNT': '10',
        'INTERSECTION_DISTANCE': '35',
        'DEBUG_INTERSECTION_POLYGONS': 'true',
    })
    def test_environment_variable_overrides(self):
        config = Config()
        self.assertEqual(config.incoming_topic_name, '')
        self.assertEqual(config.incoming_topic_subscription, '')
        self.assertEqual(config.outgoing_topic_name, '')
        self.assertEqual(config.storage_container_name, 'osw')
        self.assertEqual(config.max_concurrent_messages, 5)  # Casts to int
        self.assertEqual(config.partition_count, 10)  # Casts to int
        self.assertEqual(config.intersection_distance, 35.0)
        self.assertTrue(config.debug_intersection_polygons)


if __name__ == '__main__':
    unittest.main()
