import re
from dataclasses import dataclass

from local_llm_observability.db.db_manager import DBManager


@dataclass
class QualityScore:
    structural: float
    hallucination: float
    glossary: float
    length: float
    composite: float
    passed: bool
    details: dict


# Weights for composite score
WEIGHTS = {
    "structural": 0.30,
    "hallucination": 0.30,
    "glossary": 0.20,
    "length": 0.20,
}

PASS_THRESHOLD = 0.70


class QualityScorer:
    def __init__(self, db: DBManager):
        self.db = db
        self._glossary_cache = {}

    def score(self, ko_text: str, translated_text: str, target_lang: str) -> QualityScore:
        """Score a single translated paragraph against its Korean source."""
        structural = self._structural_score(ko_text, translated_text)
        hallucination = self._hallucination_score(ko_text, translated_text)
        glossary = self._glossary_score(ko_text, translated_text, target_lang)
        length = self._length_score(ko_text, translated_text, target_lang)

        composite = (
            WEIGHTS["structural"] * structural
            + WEIGHTS["hallucination"] * hallucination
            + WEIGHTS["glossary"] * glossary
            + WEIGHTS["length"] * length
        )

        return QualityScore(
            structural=round(structural, 3),
            hallucination=round(hallucination, 3),
            glossary=round(glossary, 3),
            length=round(length, 3),
            composite=round(composite, 3),
            passed=composite >= PASS_THRESHOLD,
            details={},
        )

    def score_file(self, ko_sections: list, translated_sections: list,
                   target_lang: str, filename: str = None, run_id: int = None) -> list[QualityScore]:
        """Score all paragraph sections of a translated file. Returns list of QualityScore."""
        scores = []
        for ko_sec, tr_sec in zip(ko_sections, translated_sections):
            if ko_sec["type"] == "code":
                # Code blocks pass automatically
                scores.append(QualityScore(
                    structural=1.0, hallucination=1.0, glossary=1.0,
                    length=1.0, composite=1.0, passed=True, details={"type": "code"},
                ))
                continue

            qs = self.score(ko_sec["text"], tr_sec["text"], target_lang)
            scores.append(qs)

        # Store aggregate score in DB if filename provided
        if filename and scores:
            paragraph_scores = [s for s in scores if s.details.get("type") != "code"]
            if paragraph_scores:
                avg = lambda attr: sum(getattr(s, attr) for s in paragraph_scores) / len(paragraph_scores)
                self.db.insert_quality_score(
                    filename=filename,
                    target_lang=target_lang,
                    structural_score=avg("structural"),
                    length_score=avg("length"),
                    semantic_score=avg("hallucination"),
                    glossary_score=avg("glossary"),
                    composite_score=avg("composite"),
                    passed=all(s.passed for s in paragraph_scores),
                    run_id=run_id,
                )

        return scores

    # ── Scoring dimensions ──

    def _structural_score(self, ko: str, translated: str) -> float:
        """Check that structural elements survive translation."""
        checks = []

        # Heading count
        ko_headings = len(re.findall(r"^#{1,6}\s", ko, re.MULTILINE))
        tr_headings = len(re.findall(r"^#{1,6}\s", translated, re.MULTILINE))
        if ko_headings > 0:
            checks.append(1.0 if ko_headings == tr_headings else 0.0)

        # Inline code spans
        ko_code = re.findall(r"`[^`]+`", ko)
        tr_code = re.findall(r"`[^`]+`", translated)
        if ko_code:
            preserved = sum(1 for c in ko_code if c in translated)
            checks.append(preserved / len(ko_code))

        # URLs
        ko_urls = re.findall(r"https?://\S+", ko)
        if ko_urls:
            preserved = sum(1 for u in ko_urls if u in translated)
            checks.append(preserved / len(ko_urls))

        # Image links
        ko_images = re.findall(r"!\[.*?\]\(.*?\)", ko)
        if ko_images:
            preserved = sum(1 for img in ko_images if img in translated)
            checks.append(preserved / len(ko_images))

        return sum(checks) / len(checks) if checks else 1.0

    def _hallucination_score(self, ko: str, translated: str) -> float:
        """Detect signs of hallucinated content."""
        score = 1.0

        # Meta-commentary patterns (JP)
        jp_meta = [
            r"この翻訳では",
            r"翻訳にあたり",
            r"以上の翻訳",
            r"翻訳についての",
            r"注：翻訳",
        ]
        # Meta-commentary patterns (EN)
        en_meta = [
            r"(?i)in this translation",
            r"(?i)note:?\s*(?:the|this) translation",
            r"(?i)translator'?s?\s+note",
            r"(?i)I have translated",
        ]
        for pattern in jp_meta + en_meta:
            if re.search(pattern, translated):
                score -= 0.5
                break

        # Paragraph count anomaly — translated should not add paragraphs
        ko_paras = len([p for p in ko.split("\n\n") if p.strip()])
        tr_paras = len([p for p in translated.split("\n\n") if p.strip()])
        if tr_paras > ko_paras + 1:
            score -= 0.3

        return max(score, 0.0)

    def _glossary_score(self, ko: str, translated: str, target_lang: str) -> float:
        """Check that glossary terms are used correctly."""
        glossary = self._get_glossary(target_lang)
        if not glossary:
            return 1.0

        expected = 0
        found = 0
        for ko_term, target_term in glossary.items():
            if ko_term in ko:
                expected += 1
                if target_term in translated:
                    found += 1

        return found / expected if expected > 0 else 1.0

    def _length_score(self, ko: str, translated: str, target_lang: str) -> float:
        """Check that translation length is within expected ratio."""
        ko_len = len(ko)
        tr_len = len(translated)
        if ko_len == 0:
            return 1.0

        ratio = tr_len / ko_len

        # Expected ratios: EN ~1.2-2.5x (Korean is compact), JP ~0.8-1.5x (similar density)
        if target_lang == "en":
            ideal_min, ideal_max = 0.8, 3.0
        else:
            ideal_min, ideal_max = 0.5, 2.0

        if ideal_min <= ratio <= ideal_max:
            return 1.0

        # Score drops linearly outside the range
        if ratio < ideal_min:
            return max(ratio / ideal_min, 0.0)
        else:
            return max(1.0 - (ratio - ideal_max) / ideal_max, 0.0)

    def _get_glossary(self, target_lang: str) -> dict:
        """Load glossary from DB with caching."""
        if target_lang not in self._glossary_cache:
            self._glossary_cache[target_lang] = self.db.get_glossary(target_lang)
        return self._glossary_cache[target_lang]
