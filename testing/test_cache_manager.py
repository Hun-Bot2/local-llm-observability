from __future__ import annotations

import unittest

from src.cache_manager import CacheManager


class CacheManagerTest(unittest.TestCase):
    def setUp(self):
        self.cache = CacheManager.__new__(CacheManager)

    def test_rejects_cached_code_translation_without_fences(self):
        section = {
            "type": "code",
            "text": "```yml\nname: 테스트\n```",
        }
        translated = "yml\nname: Test"

        self.assertFalse(self.cache._valid_cached_translation(section, translated))

    def test_accepts_cached_code_translation_with_fences(self):
        section = {
            "type": "code",
            "text": "```yml\nname: 테스트\n```",
        }
        translated = "```yml\nname: Test\n```"

        self.assertTrue(self.cache._valid_cached_translation(section, translated))

    def test_accepts_non_code_translation(self):
        section = {
            "type": "paragraph",
            "text": "안녕하세요",
        }

        self.assertTrue(self.cache._valid_cached_translation(section, "Hello"))


if __name__ == "__main__":
    unittest.main()
