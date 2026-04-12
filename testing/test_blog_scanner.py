from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from src.blog_scanner import scan_blog_posts


class BlogScannerTest(unittest.TestCase):
    def test_mirror_layout_detects_only_korean_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ko_post = root / "ko" / "devlog" / "Post.mdx"
            en_post = root / "en" / "devlog" / "Post.mdx"
            jp_sample = root / "jp" / "sample.mdx"
            ko_model_output = root / "ko" / "devlog" / "Post_en_gemma4.mdx"

            ko_post.parent.mkdir(parents=True)
            en_post.parent.mkdir(parents=True)
            jp_sample.parent.mkdir(parents=True)
            ko_post.write_text("안녕하세요", encoding="utf-8")
            en_post.write_text("Hello", encoding="utf-8")
            jp_sample.write_text("sample", encoding="utf-8")
            ko_model_output.write_text("Hello with model suffix", encoding="utf-8")

            summary = scan_blog_posts(
                source_dir=root,
                langs=["en", "jp"],
                layout="mirror",
                en_dir=root / "en",
                jp_dir=root / "jp",
            )

            self.assertEqual(summary.total_sources, 1)
            self.assertEqual(summary.posts[0].relative_path, "ko/devlog/Post.mdx")

            target_status = {target.lang: target.status for target in summary.posts[0].targets}
            self.assertEqual(target_status["en"], "ok")
            self.assertEqual(target_status["jp"], "missing")

    def test_stale_when_source_is_newer_than_translation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ko_post = root / "ko" / "Post.mdx"
            en_post = root / "en" / "Post.mdx"
            ko_post.parent.mkdir(parents=True)
            en_post.parent.mkdir(parents=True)

            en_post.write_text("Old", encoding="utf-8")
            time.sleep(0.01)
            ko_post.write_text("새 글", encoding="utf-8")

            summary = scan_blog_posts(
                source_dir=root,
                langs=["en"],
                layout="mirror",
                en_dir=root / "en",
            )

            self.assertEqual(summary.total_sources, 1)
            self.assertEqual(summary.needs_translation, 1)
            self.assertEqual(summary.posts[0].targets[0].status, "stale")


if __name__ == "__main__":
    unittest.main()
