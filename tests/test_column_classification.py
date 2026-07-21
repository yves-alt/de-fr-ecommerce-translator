"""
Unit tests for dynamic column detection (pipeline.py).

Run with:  python3 -m unittest tests.test_column_classification -v
"""

import unittest

from pipeline import (
    ColumnHeaderNormalizer,
    ColumnClassifier,
    ColumnType,
    TranslationProfile,
    TranslationPlanBuilder,
    TranslationCoverageValidator,
)


class TestColumnHeaderNormalizer(unittest.TestCase):
    def setUp(self):
        self.norm = ColumnHeaderNormalizer()

    def test_capitalization_and_punctuation_variants_all_match(self):
        variants = ["Jira Key", "jira_key", "JIRA-KEY", "JiraKey", "  jira   key  "]
        normalized = {self.norm.normalize(v) for v in variants}
        self.assertEqual(normalized, {"jira key"})

    def test_camel_case_split(self):
        self.assertEqual(self.norm.normalize("articleNumber"), "article number")
        self.assertEqual(self.norm.normalize("careInstructions"), "care instructions")

    def test_snake_case_split(self):
        self.assertEqual(self.norm.normalize("delivery_scope"), "delivery scope")

    def test_accent_stripping(self):
        self.assertEqual(self.norm.normalize("Übersetzung"), "ubersetzung")

    def test_digit_letter_boundary(self):
        self.assertEqual(self.norm.normalize("Cover1"), "cover 1")

    def test_empty_and_whitespace(self):
        self.assertEqual(self.norm.normalize(""), "")
        self.assertEqual(self.norm.normalize("   "), "")


class TestColumnClassifier(unittest.TestCase):
    def setUp(self):
        self.clf = ColumnClassifier()

    def test_unknown_descriptive_column_is_translatable(self):
        samples = [
            "Bitte das Möbelstück vor der Montage auf Beschädigungen prüfen.",
            "Zwei Personen werden für den Aufbau empfohlen, da das Gewicht hoch ist.",
            "Alle Schrauben und Werkzeuge sind im Lieferumfang enthalten.",
        ]
        result = self.clf.classify("assemblyInformation", samples)
        self.assertEqual(result.column_type, ColumnType.UNKNOWN_CONTENT)
        self.assertTrue(result.translatable)
        self.assertEqual(result.profile, TranslationProfile.GENERIC_HOME24_DESCRIPTION)

    def test_unknown_descriptive_column_with_new_never_hardcoded_header(self):
        # A header that has never existed in the codebase before.
        samples = [
            "Nachhaltig produziert aus recyceltem Polyester und FSC-zertifiziertem Holz.",
            "Die Verpackung besteht zu 90 % aus wiederverwertbaren Materialien.",
        ]
        result = self.clf.classify("sustainabilityDetail", samples)
        self.assertEqual(result.column_type, ColumnType.UNKNOWN_CONTENT)
        self.assertTrue(result.translatable)

    def test_protected_metadata_by_header_and_values(self):
        samples = ["VAR-88213", "VAR-90021", "VAR-11029", "VAR-55010"]
        result = self.clf.classify("variantId", samples)
        self.assertEqual(result.column_type, ColumnType.PROTECTED_METADATA)
        self.assertFalse(result.translatable)

    def test_technical_data_urls(self):
        samples = [
            "https://cdn.home24.com/img/12345.jpg",
            "https://cdn.home24.com/img/67890.jpg",
            "https://cdn.home24.com/img/54321.jpg",
        ]
        result = self.clf.classify("imageUrl", samples)
        self.assertEqual(result.column_type, ColumnType.TECHNICAL_DATA)
        self.assertFalse(result.translatable)

    def test_technical_data_dates(self):
        samples = ["2026-01-15", "2026-02-03", "2026-03-21", "2025-12-31"]
        result = self.clf.classify("createdAt", samples)
        self.assertEqual(result.column_type, ColumnType.TECHNICAL_DATA)
        self.assertFalse(result.translatable)

    def test_technical_data_booleans_and_codes(self):
        samples = ["true", "false", "true", "true", "false"]
        result = self.clf.classify("isActive", samples)
        self.assertEqual(result.column_type, ColumnType.TECHNICAL_DATA)

    def test_empty_column(self):
        result = self.clf.classify("someHeader", ["", None, "   ", ""])
        self.assertEqual(result.column_type, ColumnType.EMPTY)
        self.assertFalse(result.translatable)

    def test_empty_column_no_samples_at_all(self):
        result = self.clf.classify("someHeader", [])
        self.assertEqual(result.column_type, ColumnType.EMPTY)

    def test_ambiguous_mixed_codes_and_text(self):
        samples = [
            "REF-001",
            "Dieser Artikel wurde im letzten Quartal überarbeitet und verbessert.",
            "REF-002",
            "Kommentar vom Support-Team zur Qualität des Produkts nach Rückgabe.",
        ]
        result = self.clf.classify("internalCommentCode", samples)
        self.assertEqual(result.column_type, ColumnType.AMBIGUOUS)
        self.assertFalse(result.translatable)

    def test_ambiguous_too_few_samples(self):
        result = self.clf.classify("mysteryColumn", ["Irgendein Text hier"])
        self.assertEqual(result.column_type, ColumnType.AMBIGUOUS)

    def test_known_style_header_still_routes_through_content_when_prose(self):
        # Sanity: a header the registry *would* have matched isn't normally
        # passed to ColumnClassifier at all, but if it somehow were, prose
        # content should still win over an incidental header token.
        samples = [
            "Hochwertiges Massivholz mit natürlicher Maserung und langer Haltbarkeit.",
            "Pflegeleichtes Material, ideal für den täglichen Gebrauch im Wohnbereich.",
        ]
        result = self.clf.classify("productFeatures", samples)
        self.assertEqual(result.column_type, ColumnType.UNKNOWN_CONTENT)


class TestTranslationPlanBuilder(unittest.TestCase):
    def setUp(self):
        self.builder = TranslationPlanBuilder()

    def _base_classification(self):
        return {
            "to_translate": {"name": (1, "name"), "materialDetail": (4, "materialDetail")},
            "protected": {"Jira Key": 2},
            "ignored": {
                "careInstructions": 5,
                "imageUrl": 6,
                "internalId": 7,
                "internalCommentCode": 8,
                "emptyColumn": 9,
            },
            "normalized_map": {
                "name": "name", "materialDetail": "material detail", "Jira Key": "jira key",
                "careInstructions": "care instructions", "imageUrl": "image url",
                "internalId": "internal id", "internalCommentCode": "internal comment code",
                "emptyColumn": "empty column",
            },
        }

    def test_full_plan_matches_expected_test_case_16(self):
        classification = self._base_classification()
        samples = {
            "careInstructions": [
                "Nur mit einem feuchten Tuch reinigen, keine scharfen Reiniger verwenden.",
                "Nicht direkter Sonneneinstrahlung aussetzen, um Ausbleichen zu vermeiden.",
            ],
            "imageUrl": [
                "https://cdn.home24.com/a.jpg", "https://cdn.home24.com/b.jpg",
            ],
            "internalId": ["INT-001", "INT-002", "INT-003"],
            "internalCommentCode": ["REF-1", "Freitext-Kommentar mit mehreren deutschen Wörtern hier", "REF-2"],
            "emptyColumn": ["", "", ""],
        }
        counts = {
            "name": 100, "materialDetail": 100, "Jira Key": 100,
            "careInstructions": 100, "imageUrl": 100, "internalId": 100,
            "internalCommentCode": 100, "emptyColumn": 0,
        }

        out = self.builder.build(classification, samples, counts)

        # careInstructions -> translated, promoted into to_translate
        self.assertIn("careInstructions", out["to_translate"])
        self.assertEqual(out["to_translate"]["careInstructions"][1], "other")

        # imageUrl / internalId -> preserved (merged into protected)
        self.assertIn("imageUrl", out["protected"])
        self.assertIn("internalId", out["protected"])

        # internalCommentCode -> ambiguous, needs confirmation, NOT auto-translated
        self.assertIn("internalCommentCode", out["needs_confirmation"])
        self.assertNotIn("internalCommentCode", out["to_translate"])

        # emptyColumn -> neither translated nor protected, just noted
        self.assertNotIn("emptyColumn", out["to_translate"])

        # known columns pass through untouched
        self.assertEqual(out["to_translate"]["name"], (1, "name"))
        self.assertEqual(out["to_translate"]["materialDetail"], (4, "materialDetail"))
        self.assertIn("Jira Key", out["protected"])

        summary = out["summary"]
        self.assertEqual(summary["known_translatable_columns"], 2)
        self.assertEqual(summary["additional_content_columns"], 1)
        self.assertIn("careInstructions", summary["newly_detected_content_columns"])
        self.assertEqual(summary["columns_requiring_review"], 1)

    def test_confirmed_ambiguous_column_can_be_merged_in_by_caller(self):
        # The plan itself never auto-translates AMBIGUOUS columns — but the
        # caller (app.py UI) can merge a user-confirmed header into
        # to_translate afterward. Simulate that here.
        classification = self._base_classification()
        samples = {"internalCommentCode": ["REF-1", "Text auf Deutsch hier", "REF-2"]}
        counts = {"internalCommentCode": 50}
        out = self.builder.build(classification, samples, counts)
        self.assertIn("internalCommentCode", out["needs_confirmation"])

        # Caller confirms it should be translated:
        out["to_translate"]["internalCommentCode"] = (8, "other")
        self.assertIn("internalCommentCode", out["to_translate"])


class TestTranslationCoverageValidator(unittest.TestCase):
    def setUp(self):
        self.validator = TranslationCoverageValidator()

    def test_clean_coverage(self):
        from pipeline import TranslationPlanEntry, ColumnType, TranslationProfile
        plan = [TranslationPlanEntry(
            header="name", normalized_header="name", column_type=ColumnType.PRODUCT_NAME,
            action="Translate", profile=TranslationProfile.PRODUCT_NAME, reason="",
            non_empty_cells=2, expected_translations=2,
        )]
        cells_queue = [(1, "name", 1, "name", "Sofa"), (2, "name", 1, "name", "Tisch")]
        results = {(1, 1): "Canapé", (2, 1): "Table"}
        failures = self.validator.validate(plan, cells_queue, results)
        self.assertEqual(failures, [])

    def test_detects_missing_cell(self):
        from pipeline import TranslationPlanEntry, ColumnType, TranslationProfile
        plan = [TranslationPlanEntry(
            header="name", normalized_header="name", column_type=ColumnType.PRODUCT_NAME,
            action="Translate", profile=TranslationProfile.PRODUCT_NAME, reason="",
            non_empty_cells=2, expected_translations=2,
        )]
        cells_queue = [(1, "name", 1, "name", "Sofa"), (2, "name", 1, "name", "Tisch")]
        results = {(1, 1): "Canapé"}  # row 2 missing
        failures = self.validator.validate(plan, cells_queue, results)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["row"], 2)
        self.assertEqual(failures[0]["column"], "name")
        self.assertEqual(failures[0]["source_value"], "Tisch")

    def test_ignores_non_translatable_columns(self):
        from pipeline import TranslationPlanEntry, ColumnType, TranslationProfile
        plan = [TranslationPlanEntry(
            header="Jira Key", normalized_header="jira key", column_type=ColumnType.PROTECTED_METADATA,
            action="Preserve", profile=TranslationProfile.NONE, reason="",
            non_empty_cells=2, expected_translations=0,
        )]
        cells_queue = [(1, "Jira Key", 2, "protected", "ABC-123")]
        results = {}  # nothing translated — expected, it's protected
        failures = self.validator.validate(plan, cells_queue, results)
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
