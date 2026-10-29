import os
import unittest
from email.utils import formatdate
from unittest.mock import patch

import requests
from shapely import box

from src.calculators.fetch_timing import FetchBudget, FetchBudgetExceeded, FetchPolicy
from src.calculators.qm_xn_lib_calculator import fetch_seed_graph_with_retry, retry_after_seconds


class TestFetchTiming(unittest.TestCase):
    def test_environment_settings_are_loaded_and_validated(self):
        with patch.dict(os.environ, {
            'FAIRWAY_CONNECT_TIMEOUT_SECONDS': '4', 'FAIRWAY_READ_TIMEOUT_SECONDS': '30',
            'FAIRWAY_FETCH_BUDGET_SECONDS': '90', 'FAIRWAY_MAX_ATTEMPTS': '2',
            'FAIRWAY_RETRY_BACKOFF_SECONDS': '3',
        }):
            self.assertEqual(FetchPolicy.from_environment(), FetchPolicy(4, 30, 90, 2, 3))
        for values in [{'connect_timeout': 0}, {'read_timeout': 0.5},
                       {'read_timeout': float('nan')}, {'budget_seconds': float('inf')},
                       {'max_attempts': 0}, {'max_attempts': 1.5}, {'retry_backoff': -1}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                FetchPolicy(**values)

    @patch('src.calculators.fetch_timing.time.monotonic', return_value=0)
    def test_timeouts_shrink_and_independent_budgets_do_not_reset_each_other(self, clock):
        first = FetchBudget(FetchPolicy(budget_seconds=30))
        self.assertEqual(first.request_timeouts(), (10, 20))
        clock.return_value = 20
        second = FetchBudget(FetchPolicy(budget_seconds=30))
        self.assertEqual(first.request_timeouts(), (5, 5))
        self.assertEqual(second.remaining(), 30)
        clock.return_value = 30
        with self.assertRaises(FetchBudgetExceeded):
            first.remaining()
        self.assertEqual(second.remaining(), 20)

    @patch('src.calculators.qm_xn_lib_calculator.time.time', return_value=1000)
    def test_retry_after_accepts_seconds_and_dates(self, clock):
        response = requests.Response()
        for header, expected in [('25', 25), (formatdate(1025, usegmt=True), 25),
                                 ('-5', 0), ('invalid', 0), ('nan', 0), ('inf', 0)]:
            with self.subTest(header=header):
                response.headers['Retry-After'] = header
                self.assertEqual(retry_after_seconds(response), expected)
        self.assertEqual(retry_after_seconds(None), 0)

    @patch('src.calculators.qm_xn_lib_calculator.time.sleep')
    @patch('src.calculators.qm_xn_lib_calculator.fetch_seed_graph')
    def test_retry_after_is_respected_or_fails_without_sleeping_past_budget(self, fetch, sleep):
        response = requests.Response()
        response.status_code = 429
        error = requests.HTTPError('Rate limited', response=response)
        expected = object()
        for delay, should_fail in [('25', False), ('600', True)]:
            with self.subTest(delay=delay):
                fetch.reset_mock()
                sleep.reset_mock()
                response.headers['Retry-After'] = delay
                fetch.side_effect = [error, expected]
                if should_fail:
                    with self.assertRaises(FetchBudgetExceeded):
                        fetch_seed_graph_with_retry(box(0, 0, 1, 1))
                    fetch.assert_called_once()
                    sleep.assert_not_called()
                else:
                    self.assertIs(fetch_seed_graph_with_retry(box(0, 0, 1, 1)), expected)
                    sleep.assert_called_once_with(25)

    @patch('src.calculators.fetch_timing.time.monotonic', return_value=0)
    @patch('src.calculators.qm_xn_lib_calculator.time.sleep')
    @patch('src.calculators.qm_xn_lib_calculator.fetch_seed_graph')
    def test_retry_shares_deadline_and_discards_late_success(self, fetch, sleep, clock):
        budgets = []

        def attempt(polygon, *, budget):
            budgets.append(budget)
            clock.return_value += 8
            if len(budgets) == 1:
                raise requests.Timeout()
            return object()

        sleep.side_effect = lambda delay: setattr(clock, 'return_value', clock.return_value + delay)
        fetch.side_effect = attempt
        with patch.dict(os.environ, {'FAIRWAY_FETCH_BUDGET_SECONDS': '20',
                                     'FAIRWAY_RETRY_BACKOFF_SECONDS': '5'}):
            with self.assertRaises(FetchBudgetExceeded):
                fetch_seed_graph_with_retry(box(0, 0, 1, 1))
        self.assertEqual(fetch.call_count, 2)
        self.assertIs(budgets[0], budgets[1])
        sleep.assert_called_once_with(5)

    @patch('src.calculators.qm_xn_lib_calculator.time.sleep')
    @patch('src.calculators.qm_xn_lib_calculator.fetch_seed_graph', side_effect=requests.Timeout())
    def test_attempt_count_can_disable_retries(self, fetch, sleep):
        with patch.dict(os.environ, {'FAIRWAY_MAX_ATTEMPTS': '1'}):
            with self.assertRaises(requests.Timeout):
                fetch_seed_graph_with_retry(box(0, 0, 1, 1))
        fetch.assert_called_once()
        sleep.assert_not_called()
