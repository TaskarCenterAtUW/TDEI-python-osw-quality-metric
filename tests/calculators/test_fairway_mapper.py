import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests
from osmnx import settings
from flagstones.osm import SEED_CUSTOM_FILTER
from shapely import box

from src.calculators.fairway_mapper import INTERPRETER_URL, download_seed_network
from src.calculators.qm_xn_lib_calculator import fetch_seed_graph_with_retry


class TestFairwayMapper(unittest.TestCase):
    def setUp(self):
        self.hull = box(-120.818, 45.835, -120.814, 45.8382175)
        self.cache = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(settings, 'cache_folder', self.cache))
        self.enterContext(patch.object(settings, 'use_cache', True))
        self.enterContext(patch.dict(os.environ, {'FAIRWAY_MAPPER_API_KEY': 'test-secret'}))
        self.post = self.enterContext(patch('src.calculators.fairway_mapper.requests.post'))
        self.post.return_value = Mock(status_code=200)
        self.post.return_value.json.return_value = {'elements': []}

    def download(self):
        return list(download_seed_network(self.hull, SEED_CUSTOM_FILTER))

    def test_authenticated_query_preserves_filter_and_caches_without_key(self):
        before = (settings.overpass_url, settings.requests_kwargs.copy())
        self.assertEqual(self.download(), [{'elements': []}])
        args, kwargs = self.post.call_args
        self.assertEqual(args, (INTERPRETER_URL,))
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer test-secret')
        self.assertFalse(kwargs['allow_redirects'])
        self.assertEqual(kwargs['timeout'], (10, settings.requests_timeout))
        query = kwargs['data']['data']
        self.assertIn(f'way{SEED_CUSTOM_FILTER}(poly:', query)
        self.assertIn(';>;);out;', query)
        self.assertNotIn('test-secret', query)
        self.assertEqual(before, (settings.overpass_url, settings.requests_kwargs))
        self.download()
        self.post.assert_called_once()
        files = list(Path(self.cache).glob('*.json'))
        self.assertEqual(len(files), 1)
        self.assertNotIn('test-secret', files[0].read_text())
        with patch.dict(os.environ, {'FAIRWAY_MAPPER_API_KEY': 'another-key'}):
            self.download()
        self.post.assert_called_once()

    def test_missing_key_fails_without_request(self):
        with patch.dict(os.environ, {'FAIRWAY_MAPPER_API_KEY': ' '}):
            with self.assertRaisesRegex(ValueError, 'FAIRWAY_MAPPER_API_KEY'):
                self.download()
        self.post.assert_not_called()

    def test_each_subdivision_is_requested(self):
        with patch('src.calculators.fairway_mapper._overpass._make_overpass_polygon_coord_strs',
                   return_value=['45 -120 46 -120 46 -121', '46 -120 47 -120 47 -121']):
            self.assertEqual(len(self.download()), 2)
        self.assertEqual(self.post.call_count, 2)

    def test_http_errors_and_redirects_do_not_cache_or_expose_body(self):
        for status in [301, 401, 403, 429, 500, 502, 503, 504]:
            with self.subTest(status=status):
                self.post.return_value.status_code = status
                self.post.return_value.text = 'test-secret'
                with self.assertRaises(requests.HTTPError) as raised:
                    self.download()
                self.assertEqual(raised.exception.response.status_code, status)
                self.assertNotIn('test-secret', str(raised.exception))
        self.assertEqual(list(Path(self.cache).glob('*.json')), [])

    def test_invalid_or_partial_data_fails_without_caching(self):
        for data in [[], {}, {'error': 'unauthorized'}, {'elements': None},
                     {'elements': ['invalid']}, {'elements': [], 'remark': 'query timed out'}]:
            with self.subTest(data=data):
                self.post.return_value.json.return_value = data
                with self.assertRaises(ValueError):
                    self.download()
        self.post.return_value.json.side_effect = ValueError('test-secret')
        with self.assertRaisesRegex(ValueError, '^Fairway Mapper returned invalid JSON$'):
            self.download()
        self.assertEqual(list(Path(self.cache).glob('*.json')), [])

    @patch('src.calculators.qm_xn_lib_calculator.time.sleep')
    @patch('src.calculators.qm_xn_lib_calculator.fetch_seed_graph')
    def test_transient_errors_retry_but_authentication_errors_do_not(self, fetch, sleep):
        for status in [401, 403, 429, 500, 502, 503, 504]:
            with self.subTest(status=status):
                fetch.reset_mock()
                sleep.reset_mock()
                response = requests.Response()
                response.status_code = status
                fetch.side_effect = requests.HTTPError('Provider error', response=response)
                with self.assertRaises(requests.HTTPError):
                    fetch_seed_graph_with_retry(self.hull)
                attempts = 1 if status in {401, 403} else 3
                self.assertEqual(fetch.call_count, attempts)
                self.assertEqual(sleep.call_count, attempts - 1)

    @patch('src.calculators.qm_xn_lib_calculator.time.sleep')
    @patch('src.calculators.qm_xn_lib_calculator.fetch_seed_graph')
    def test_connection_failures_can_recover(self, fetch, sleep):
        expected = object()
        fetch.side_effect = [requests.ConnectionError(), requests.Timeout(), expected]
        self.assertIs(fetch_seed_graph_with_retry(self.hull), expected)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [10, 20])
