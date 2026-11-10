import os
import unittest
from unittest.mock import patch

from src.calculators.cpus import available_cpus


def _env_without_default_cpu():
    return {k: v for k, v in os.environ.items() if k != "DEFAULT_CPU"}


class TestAvailableCpus(unittest.TestCase):

    def test_default_cpu_sets_the_count(self):
        with patch.dict(os.environ, {"DEFAULT_CPU": "4"}), \
                patch("src.calculators.cpus.os.cpu_count", return_value=16):
            self.assertEqual(available_cpus(), 4)

    def test_fractional_cpus_round_down_but_never_below_one(self):
        for raw, expected in [("1.5", 1), ("2.9", 2), ("0.5", 1), (" 4 ", 4)]:
            with self.subTest(raw=raw), patch.dict(os.environ, {"DEFAULT_CPU": raw}):
                self.assertEqual(available_cpus(), expected)

    def test_unset_or_blank_falls_back_to_the_os_count(self):
        for env in [_env_without_default_cpu(), {**_env_without_default_cpu(), "DEFAULT_CPU": "  "}]:
            with self.subTest(env=env.get("DEFAULT_CPU")), patch.dict(os.environ, env, clear=True), \
                    patch("src.calculators.cpus.os.cpu_count", return_value=3):
                self.assertEqual(available_cpus(), 3)

    def test_unknown_os_count_is_one(self):
        with patch.dict(os.environ, _env_without_default_cpu(), clear=True), \
                patch("src.calculators.cpus.os.cpu_count", return_value=None):
            self.assertEqual(available_cpus(), 1)

    def test_a_value_that_is_not_a_positive_number_raises(self):
        for raw in ["four", "0", "-2", "nan", "inf"]:
            with self.subTest(raw=raw), patch.dict(os.environ, {"DEFAULT_CPU": raw}):
                with self.assertRaises(ValueError) as raised:
                    available_cpus()
                self.assertIn("DEFAULT_CPU", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
