"""Yerellestirme tablolari: tr/en anahtar kumeleri ayni, bicim yer tutuculari uyumlu."""

from __future__ import annotations

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import _support  # noqa: E402,F401

from src.utils.locales import LOCALES  # noqa: E402

_PLACEHOLDER = re.compile(r"\{[^{}]*\}")


class LocaleParityTests(unittest.TestCase):
    def test_every_key_exists_in_every_language(self) -> None:
        tr, en = LOCALES["tr"], LOCALES["en"]
        self.assertEqual(sorted(set(tr) - set(en)), [], "en'de eksik anahtarlar")
        self.assertEqual(sorted(set(en) - set(tr)), [], "tr'de eksik anahtarlar")

    def test_format_placeholders_match_between_languages(self) -> None:
        tr, en = LOCALES["tr"], LOCALES["en"]
        for key in sorted(set(tr) & set(en)):
            self.assertEqual(
                sorted(_PLACEHOLDER.findall(tr[key])), sorted(_PLACEHOLDER.findall(en[key])), key,
            )

    def test_no_empty_strings(self) -> None:
        for lang, table in LOCALES.items():
            for key, value in table.items():
                self.assertTrue(str(value).strip(), f"{lang}.{key} bos")


if __name__ == "__main__":
    unittest.main()
