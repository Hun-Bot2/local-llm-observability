from __future__ import annotations

import unittest

from translate import Translator


class TranslationNormalizerTest(unittest.TestCase):
    def setUp(self):
        self.translator = Translator.__new__(Translator)

    def test_restores_missing_yaml_code_fence(self):
        source = """```yml
name: 알고리즘 매일 복습 봇

on:
  schedule:
    # 매일 한국시간 오전 9시에 실행
    - cron: '0 0 * * *'
```"""
        model_output = """yml
name: アルゴリズム毎日復習ボット

on:
  schedule:
    # 毎日韓国時間午前9時に実行
    - cron: '0 0 * * *'"""

        normalized = self.translator._normalize_translated_section(source, model_output, "code")

        self.assertTrue(normalized.startswith("```yml\n"))
        self.assertTrue(normalized.endswith("\n```"))
        self.assertNotIn("\n```yml\n```", normalized)
        self.assertIn("name: アルゴリズム毎日復習ボット", normalized)

    def test_preserves_existing_code_fence_but_restores_language_marker(self):
        source = """```python
# 인사
print("hello")
```"""
        model_output = """```
# Greeting
print("hello")
```"""

        normalized = self.translator._normalize_translated_section(source, model_output, "code")

        self.assertTrue(normalized.startswith("```python\n"))
        self.assertTrue(normalized.endswith("\n```"))

    def test_does_not_strip_normal_markdown_code_fence(self):
        source = "코드 예시입니다."
        model_output = """Here is the example:

```python
print("hello")
```"""

        normalized = self.translator._normalize_translated_section(source, model_output, "paragraph")

        self.assertIn("```python", normalized)
        self.assertIn("```", normalized)


if __name__ == "__main__":
    unittest.main()
