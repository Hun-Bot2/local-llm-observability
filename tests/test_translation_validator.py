from __future__ import annotations

import unittest

from local_llm_observability.translation_validator import validate_translation


class TranslationValidatorTest(unittest.TestCase):
    def test_rejects_added_heading(self):
        source = "기존 봇은 성공적이었습니다."
        translated = "既存のボットは成功していました。\n\n# AIエンジニアリングの学習戦略"

        failures = validate_translation(source, translated, "jp", "paragraph")

        self.assertTrue(any("heading count changed" in failure for failure in failures))

    def test_rejects_added_placeholder_link(self):
        source = "참고 자료를 공유하겠습니다."
        translated = "参考資料を共有します。\n\n[関連記事](https://example.com)"

        failures = validate_translation(source, translated, "jp", "paragraph")

        self.assertTrue(any("example.com" in failure for failure in failures))

    def test_rejects_leftover_korean_in_japanese_output(self):
        source = "알고리즘 문제에서 제가 매칭해야 할 데이터는 다음과 같습니다."
        translated = "アルゴリズム問題で、제가 매칭해야 할 데이터는 다음과 같습니다."

        failures = validate_translation(source, translated, "jp", "paragraph")

        self.assertTrue(any("too much Korean" in failure for failure in failures))

    def test_rejects_large_expansion(self):
        source = "왜 만들려고 하는가?"
        translated = "なぜ作ろうとしているのか？\n\n" + ("追加の説明です。" * 20)

        failures = validate_translation(source, translated, "jp", "paragraph")

        self.assertTrue(any("expanded too much" in failure for failure in failures))

    def test_accepts_reasonable_japanese_translation(self):
        source = "## 왜 만들려고 하는가?"
        translated = "## なぜ作ろうとしているのか？"

        failures = validate_translation(source, translated, "jp", "paragraph")

        self.assertEqual([], failures)


if __name__ == "__main__":
    unittest.main()
