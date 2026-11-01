"""Medya Sıkıştırıcı: Windows ile başlama varsayılan KAPALI, tema varsayılan Sistem."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DefaultsTest(unittest.TestCase):
    def test_defaults(self) -> None:
        from src.utils.config import DEFAULTS

        self.assertIs(DEFAULTS["start_with_windows"], False)
        self.assertEqual(DEFAULTS["theme"], "system")


if __name__ == "__main__":
    unittest.main()
