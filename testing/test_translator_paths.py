from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from translate import Translator


class TranslatorPathTest(unittest.TestCase):
    def test_v2_output_path_maps_ko_tree_to_language_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "blog"
            source_path = source_root / "ko" / "devlog" / "ALGO" / "Post.mdx"
            en_root = source_root / "en"

            translator = Translator.__new__(Translator)
            translator.output_dirs = {"en": en_root}
            translator.source_root = source_root

            output_path = translator._output_path(source_path, "en")

            self.assertEqual(output_path, en_root / "devlog" / "ALGO" / "Post.mdx")

    def test_default_output_path_uses_suffix_when_no_output_dir(self):
        source_path = Path("/tmp/Post.mdx")

        translator = Translator.__new__(Translator)
        translator.output_dirs = {}
        translator.source_root = None

        output_path = translator._output_path(source_path, "en")

        self.assertEqual(output_path, Path("/tmp/Post_en.mdx"))


if __name__ == "__main__":
    unittest.main()
