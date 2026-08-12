"""
Unit tests for engines/french/capitalization_engine.py — the single
authoritative FR capitalization pass (label/value/sentence/continuation
classification, protected-token preservation, column profiles, QA).

Run with:  python3 -m unittest tests.test_capitalization_engine -v
"""

import unittest

from engines.french.capitalization_engine import (
    FrenchCapitalizationEngine,
    PROTECTED_ACRONYMS,
    PROTECTED_MODEL_NAMES,
    auto_fix_protected_casing,
    is_protected_token,
    protect_tokens,
    restore_tokens,
    validate_french_capitalization,
)


class TestProtectedTokens(unittest.TestCase):
    def test_model_names_round_trip(self):
        for name in ("Vedene", "Boston", "Sonoma", "Hudson"):
            text = f"Applique murale {name} type A"
            protected, tokens = protect_tokens(text)
            self.assertNotIn(name, protected)
            self.assertEqual(restore_tokens(protected, tokens), text)

    def test_acronyms_round_trip(self):
        for acr in ("MDF", "LED", "USB-C", "FSC", "PEFC", "OEKO-TEX", "Home24"):
            text = f"Structure en {acr} massif"
            protected, tokens = protect_tokens(text)
            self.assertNotIn(acr, protected)
            self.assertEqual(restore_tokens(protected, tokens), text)

    def test_roman_numeral_round_trip(self):
        text = "Coussin décoratif Type II"
        protected, tokens = protect_tokens(text)
        self.assertEqual(restore_tokens(protected, tokens), text)

    def test_type_designation_round_trip(self):
        text = "Applique murale Boston type A"
        protected, tokens = protect_tokens(text)
        self.assertEqual(restore_tokens(protected, tokens), text)

    def test_br_and_url_round_trip(self):
        text = "Revêtement : beige<br>Voir https://home24.fr/produit pour détails"
        protected, tokens = protect_tokens(text)
        self.assertNotIn("<br>", protected)
        self.assertEqual(restore_tokens(protected, tokens), text)

    def test_is_protected_token(self):
        self.assertTrue(is_protected_token("MDF"))
        self.assertTrue(is_protected_token("mdf"))
        self.assertTrue(is_protected_token("Vedene."))
        self.assertFalse(is_protected_token("chaise"))
        self.assertFalse(is_protected_token("velours"))


class TestAutoFixProtectedCasing(unittest.TestCase):
    def test_deterministic_acronym_fix(self):
        self.assertEqual(auto_fix_protected_casing("Structure en Mdf"), "Structure en MDF")
        self.assertEqual(auto_fix_protected_casing("led intégrée"), "LED intégrée")
        self.assertEqual(auto_fix_protected_casing("Certifié fsc"), "Certifié FSC")

    def test_model_name_fix(self):
        self.assertEqual(auto_fix_protected_casing("collection vedene"), "collection Vedene")

    def test_untouched_when_already_correct(self):
        text = "Structure en MDF avec pieds Vedene"
        self.assertEqual(auto_fix_protected_casing(text), text)

    def test_does_not_touch_ordinary_words(self):
        text = "velours côtelé gris clair"
        self.assertEqual(auto_fix_protected_casing(text), text)


class TestLabelsAndValues(unittest.TestCase):
    """Spec Part 24 — 'Bezug: Cord<br>Gestell: Massivholz Pappel' ->
    'Revêtement : velours côtelé<br>Structure : peuplier massif'."""

    def setUp(self):
        self.engine = FrenchCapitalizationEngine()

    def test_label_and_value_casing(self):
        text = "Revêtement : Velours côtelé<br>Structure : Métal thermolaqué"
        result = self.engine.capitalize(text, "materialDetail")
        self.assertEqual(
            result.text, "Revêtement : velours côtelé<br>Structure : métal thermolaqué",
        )

    def test_br_preserved(self):
        text = "Revêtement : beige<br>Pieds : noir"
        result = self.engine.capitalize(text, "materialDetail")
        self.assertIn("<br>", result.text)
        self.assertEqual(result.text, "Revêtement : beige<br>Pieds : noir")

    def test_both_labels_uppercase_after_br(self):
        result = self.engine.capitalize("Revêtement : beige<br>Pieds : noirs", "materialDetail")
        self.assertTrue(result.text.startswith("Revêtement"))
        self.assertIn("<br>Pieds :", result.text)


class TestStandaloneSentenceAfterBr(unittest.TestCase):
    """Spec Part 24 — new sentence, new label, continuation, proper name."""

    def setUp(self):
        self.engine = FrenchCapitalizationEngine()

    def test_two_independent_sentences_both_capitalized(self):
        text = "Facile à entretenir<br>Convient à un usage extérieur"
        result = self.engine.capitalize(text, "qualityDetail")
        self.assertEqual(result.text, text)  # already correctly capitalized, no change

    def test_continuation_not_forced_uppercase(self):
        text = "Métal thermolaqué<br>facile à entretenir"
        result = self.engine.capitalize(text, "materialDetail")
        self.assertEqual(result.text, text)

    def test_independent_statement_after_br_stays_uppercase(self):
        text = "Métal thermolaqué<br>Facile à entretenir et résistant"
        result = self.engine.capitalize(text, "materialDetail")
        self.assertEqual(result.text, text)

    def test_new_label_after_br(self):
        text = "revêtement : beige<br>pieds : noir"
        result = self.engine.capitalize(text, "materialDetail")
        self.assertTrue(result.text.startswith("Revêtement"))
        self.assertIn("<br>Pieds :", result.text)


class TestColonHandling(unittest.TestCase):
    def setUp(self):
        self.engine = FrenchCapitalizationEngine()

    def test_ordinary_material_lowercased(self):
        r = self.engine.capitalize("Structure : Métal thermolaqué", "materialDetail")
        self.assertEqual(r.text, "Structure : métal thermolaqué")

    def test_color_lowercased(self):
        r = self.engine.capitalize("Couleur : Gris clair", "colorDetail")
        self.assertEqual(r.text, "Couleur : gris clair")

    def test_acronym_preserved_after_colon(self):
        r = self.engine.capitalize("Matériau : Mdf", "materialDetail")
        self.assertEqual(r.text, "Matériau : MDF")

    def test_proper_model_preserved_after_colon(self):
        r = self.engine.capitalize("Modèle : EVIRA", "materialDetail")
        self.assertEqual(r.text, "Modèle : EVIRA")

    def test_full_sentence_after_colon_stays_capitalized(self):
        r = self.engine.capitalize(
            "Remarque : Convient à un usage extérieur.", "qualityDetail",
        )
        self.assertEqual(r.text, "Remarque : Convient à un usage extérieur.")

    def test_name_column_does_not_lowercase_after_colon(self):
        # name profile disables colon-lowering — product names rarely carry a
        # colon, and if one appears it shouldn't be second-guessed here.
        r = self.engine.capitalize("Lit banquette : Rio", "name")
        self.assertEqual(r.text, "Lit banquette : Rio")


class TestSlashHandling(unittest.TestCase):
    def setUp(self):
        self.engine = FrenchCapitalizationEngine()

    def test_no_forced_title_case(self):
        for text in ("noir/gris", "aluminium/polyester", "bois massif/métal"):
            with self.subTest(text=text):
                r = self.engine.capitalize(text, "colorDetail")
                self.assertEqual(r.text, text)

    def test_over_capitalized_slash_pair_normalized(self):
        r = self.engine.capitalize("Noir/Gris", "colorDetail")
        # Left side is left as authored (ambiguous segment-start), right
        # side — clearly not segment-initial — is normalized to lowercase.
        self.assertEqual(r.text, "Noir/gris")

    def test_slash_not_turned_into_semicolon(self):
        r = self.engine.capitalize("noir/gris", "colorDetail")
        self.assertIn("/", r.text)
        self.assertNotIn(";", r.text)

    def test_order_not_reversed(self):
        r = self.engine.capitalize("aluminium/polyester", "materialDetail")
        self.assertTrue(r.text.startswith("aluminium"))


class TestPercentLowercase(unittest.TestCase):
    def setUp(self):
        self.engine = FrenchCapitalizationEngine()

    def test_lowercased_after_percent(self):
        r = self.engine.capitalize("100 % Polyester", "textileCompositionCover1")
        self.assertEqual(r.text, "100 % polyester")

    def test_already_lowercase_unchanged(self):
        r = self.engine.capitalize("100 % polyester", "textileCompositionCover1")
        self.assertEqual(r.text, "100 % polyester")


class TestAcronyms(unittest.TestCase):
    def setUp(self):
        self.engine = FrenchCapitalizationEngine()

    def test_mdf_led_fsc_normalized(self):
        self.assertEqual(self.engine.capitalize("Mdf", "materialDetail").text, "MDF")
        self.assertEqual(self.engine.capitalize("Led", "materialDetail").text, "LED")
        self.assertEqual(self.engine.capitalize("Fsc", "materialDetail").text, "FSC")


class TestProductNameCapitalization(unittest.TestCase):
    def setUp(self):
        self.engine = FrenchCapitalizationEngine()

    def test_sentence_style_not_title_case(self):
        text = "Chaise à accoudoirs pivotante EVIRA x2"
        r = self.engine.capitalize(text, "name")
        self.assertEqual(r.text, text)

    def test_model_casing_preserved(self):
        r = self.engine.capitalize("applique murale Boston type A", "name")
        self.assertIn("Boston", r.text)
        self.assertIn("type A", r.text)


class TestColumnProfiles(unittest.TestCase):
    """Same bare fragment, different column defaults."""

    def setUp(self):
        self.engine = FrenchCapitalizationEngine()

    def test_value_column_leaves_bare_fragment_lowercase(self):
        r = self.engine.capitalize("noir/gris", "colorDetail")
        self.assertEqual(r.text, "noir/gris")

    def test_narrative_column_capitalizes_bare_sentence(self):
        r = self.engine.capitalize("convient à un usage extérieur", "qualityDetail")
        self.assertEqual(r.text, "Convient à un usage extérieur")

    def test_generic_unknown_column_defaults_like_narrative(self):
        r = self.engine.capitalize("convient à un usage extérieur", "someUnknownColumn")
        self.assertEqual(r.text, "Convient à un usage extérieur")


class TestOtherMeasurements(unittest.TestCase):
    def setUp(self):
        self.engine = FrenchCapitalizationEngine()

    def test_labels_upper_units_lower(self):
        r = self.engine.capitalize("Largeur : 100 cm<br>Hauteur : 75 cm", "otherMeasurements")
        self.assertEqual(r.text, "Largeur : 100 cm<br>Hauteur : 75 cm")


class TestValidateFrenchCapitalization(unittest.TestCase):
    def test_no_issues_on_correct_text(self):
        issues = validate_french_capitalization("Structure : métal thermolaqué", "materialDetail")
        self.assertEqual(issues, [])

    def test_critical_on_protected_token_altered(self):
        issues = validate_french_capitalization("Structure : Mdf", "materialDetail")
        self.assertTrue(any(i["severity"] == "Critical" for i in issues))
        self.assertTrue(any(i["type"] == "cap_protected_token_altered" for i in issues))

    def test_warning_on_missing_label_capitalization(self):
        issues = validate_french_capitalization("structure : métal", "materialDetail")
        self.assertTrue(any(i["severity"] == "Warning" for i in issues))

    def test_warning_on_uppercase_value_after_colon(self):
        issues = validate_french_capitalization("Structure : Métal thermolaqué", "materialDetail")
        self.assertTrue(any(i["type"] == "cap_value_after_colon_upper" for i in issues))

    def test_model_name_wrong_case_is_critical(self):
        issues = validate_french_capitalization("Collection vedene", "materialDetail")
        self.assertTrue(any(i["severity"] == "Critical" for i in issues))


class TestRegressionAgainstOldFunction(unittest.TestCase):
    """Table of (input, canonical, expected) taken from the old
    apply_french_capitalization_rules' own docstring examples — the new
    engine must be equal-or-better, not regress on documented behavior."""

    def setUp(self):
        self.engine = FrenchCapitalizationEngine()

    def test_start_of_text_capitalized(self):
        r = self.engine.capitalize("velours côtelé", "qualityDetail")
        self.assertEqual(r.text, "Velours côtelé")

    def test_percent_composition_lowercased(self):
        r = self.engine.capitalize("60 % Coton", "textileCompositionCover1")
        self.assertEqual(r.text, "60 % coton")

    def test_br_tags_preserved_exactly(self):
        r = self.engine.capitalize("Un<br>Deux<br>Trois", "qualityDetail")
        self.assertEqual(r.text.count("<br>"), 2)

    def test_brand_name_restored_mid_string(self):
        r = self.engine.capitalize("collection sonoma disponible", "materialDetail")
        self.assertIn("Sonoma", r.text)


class TestKnownModelsUnification(unittest.TestCase):
    """Regression guard against the two protected-model-name lists (this
    module's PROTECTED_MODEL_NAMES and french_name_engine.py's KNOWN_MODELS)
    drifting apart again."""

    def test_french_name_engine_shares_the_same_registry(self):
        from engines.french.french_name_engine import KNOWN_MODELS
        self.assertIs(KNOWN_MODELS, PROTECTED_MODEL_NAMES)


if __name__ == "__main__":
    unittest.main()
