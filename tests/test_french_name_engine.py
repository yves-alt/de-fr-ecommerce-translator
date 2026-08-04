"""
Unit tests for engines/french/french_name_engine.py — the consolidated
FR product-name engine (terminology, 40-char compression, opt./type
designation preservation, ending validation).

Run with:  python3 -m unittest tests.test_french_name_engine -v
"""

import unittest

from engines.french.french_name_engine import (
    FrenchProductNameEngine,
    validate_french_name_ending,
)


class TestTypDesignationPreservation(unittest.TestCase):
    """Spec Part 2 / Case 1 — 'Typ A' must never silently disappear."""

    def setUp(self):
        self.engine = FrenchProductNameEngine()

    def test_boston_typ_a_word_and_letter_dropped(self):
        # GPT dropped "Typ" entirely, keeping only the model — the reported bug.
        result = self.engine.process(
            "Wandleuchte Boston Typ A", "Applique murale Boston", limit=40,
        )
        self.assertEqual(result.text, "Applique murale Boston type A")
        self.assertLessEqual(len(result.text), 40)
        self.assertEqual(len(result.text), 29)
        self.assertFalse(result.review_recommended)

    def test_boston_typ_a_word_dropped_letter_kept(self):
        # GPT kept the bare letter but dropped the word "Typ"/"type".
        result = self.engine.process(
            "Wandleuchte Boston Typ A", "Applique murale Boston A", limit=40,
        )
        self.assertEqual(result.text, "Applique murale Boston type A")

    def test_pollerleuchte_ossy_typ_b(self):
        result = self.engine.process(
            "Pollerleuchte Ossy Typ B", "Borne lumineuse Ossy", limit=40,
        )
        self.assertIn("type B", result.text)
        self.assertLessEqual(len(result.text), 40)

    def test_already_correct_is_left_alone(self):
        result = self.engine.process(
            "Wandleuchte Boston Typ A", "Applique murale Boston type A", limit=40,
        )
        self.assertEqual(result.text, "Applique murale Boston type A")
        self.assertEqual(result.strategy, "none")


class TestOptHandling(unittest.TestCase):
    """Spec Part 3 / Case 2 — 'opt.' preservation, dedup, never dangling."""

    def setUp(self):
        self.engine = FrenchProductNameEngine()

    def test_opt_mit_sensor_typ_b_end_to_end(self):
        result = self.engine.process(
            "Pollerleuchte Ossy opt. mit Sensor Typ B",
            "Borne lumineuse Ossy opt. avec capteur type B",
            limit=40,
        )
        self.assertLessEqual(len(result.text), 40)
        self.assertEqual(result.text.lower().count("opt."), 1)
        self.assertNotIn("option opt.", result.text.lower())
        self.assertFalse(result.text.rstrip().lower().endswith("opt."))
        self.assertIn("capteur", result.text.lower())
        self.assertIn("b", result.text.lower().split()[-1].lower())

    def test_duplicate_option_opt_normalized(self):
        result = self.engine.process(
            "x opt. y", "Borne lumineuse Ossy option opt. capteur", limit=40,
        )
        self.assertEqual(result.text.lower().count("opt."), 1)
        self.assertNotIn("option opt.", result.text.lower())

    def test_duplicate_opt_opt_normalized(self):
        result = self.engine.process(
            "x opt. y", "Borne lumineuse Ossy opt. opt. capteur", limit=40,
        )
        self.assertEqual(result.text.lower().count("opt."), 1)

    def test_double_dot_normalized(self):
        result = self.engine.process(
            "x opt. y", "Borne lumineuse Ossy opt.. capteur", limit=40,
        )
        self.assertNotIn("opt..", result.text.lower())
        self.assertEqual(result.text.lower().count("opt."), 1)

    def test_opt_expanded_to_avec_is_restored(self):
        # source only ever said the bare "opt." — GPT swapped it for "avec".
        result = self.engine.process(
            "Ossy opt. mit Sensor", "Borne lumineuse Ossy avec capteur", limit=40,
        )
        self.assertEqual(result.text.lower().count("opt."), 1)

    def test_opt_never_left_dangling_when_object_available(self):
        result = self.engine.process(
            "Pollerleuchte Ossy opt. mit Sensor Typ B sehr sehr sehr langer Zusatztext",
            "Borne lumineuse Ossy opt. avec capteur type B accessoire supplémentaire vraiment très long",
            limit=40,
        )
        self.assertLessEqual(len(result.text), 40)
        ok, reason = validate_french_name_ending(result.text)
        self.assertTrue(ok, reason)


class TestCompressionCandidates(unittest.TestCase):
    """Spec Parts 4-9 / Cases 3-4 — scored candidates, not blind truncation."""

    def setUp(self):
        self.engine = FrenchProductNameEngine()

    def test_ossy_candidate_under_40_chars(self):
        full = "Borne lumineuse Ossy opt. avec capteur type B"
        self.assertEqual(len(full), 45)
        result = self.engine.process(
            "Pollerleuchte Ossy opt. mit Sensor Typ B", full, limit=40,
        )
        self.assertLessEqual(len(result.text), 40)
        self.assertEqual(result.text.lower().count("opt."), 1)
        self.assertIn("capteur", result.text.lower())
        self.assertTrue(result.text.rstrip().endswith("B"))
        ok, reason = validate_french_name_ending(result.text)
        self.assertTrue(ok, reason)

    def test_hudson_keeps_recamiere_over_avec(self):
        full = "Canapé d'angle HUDSON 3 places avec récamière"
        self.assertEqual(len(full), 45)
        result = self.engine.process(
            "Ecksofa HUDSON 3-Sitzer mit Récamière", full, limit=40,
        )
        self.assertLessEqual(len(result.text), 40)
        self.assertIn("HUDSON", result.text)
        self.assertIn("récamière", result.text.lower())
        # "avec" should be the thing compressed away, not the accessory.
        self.assertNotIn(" avec ", result.text.lower())

    def test_scoring_prefers_information_over_shortest(self):
        # A trivially short but info-poor candidate must not beat a longer,
        # still-valid, more-informative one.
        full = "Borne lumineuse Ossy opt. avec capteur type B"
        result = self.engine.process(
            "Pollerleuchte Ossy opt. mit Sensor Typ B", full, limit=40,
        )
        self.assertGreater(len(result.text), 20)  # not collapsed to near-nothing


class TestEndingValidation(unittest.TestCase):
    """Spec Part 8 / Case 6 — dangling / incomplete endings rejected."""

    def test_invalid_endings(self):
        bad_endings = [
            "Borne lumineuse Ossy opt.",
            "Canapé HUDSON avec",
            "Canapé HUDSON type",
            "Canapé HUDSON -",
            "Canapé HUDSON +",
            "Canapé HUDSON &",
            "Table basse Sam option opt.",
            "Table basse Sam opt. opt.",
            "Table basse Sam opt..",
            "Table basse Sam (incomplet",
        ]
        for name in bad_endings:
            with self.subTest(name=name):
                ok, _reason = validate_french_name_ending(name)
                self.assertFalse(ok, f"expected invalid: {name!r}")

    def test_valid_endings(self):
        good_endings = [
            "Applique murale Boston type A",
            "Borne lumineuse Ossy opt. capteur B",
            "Table basse Sam",
            "Canapé d'angle HUDSON 3 places récamière",
        ]
        for name in good_endings:
            with self.subTest(name=name):
                ok, reason = validate_french_name_ending(name)
                self.assertTrue(ok, f"expected valid: {name!r} ({reason})")


class TestGeneralRegression(unittest.TestCase):
    """Names that don't involve opt./Typ at all must still compress sanely."""

    def setUp(self):
        self.engine = FrenchProductNameEngine()

    def test_short_name_untouched(self):
        result = self.engine.process("Tisch klein", "Table basse Sam", limit=40)
        self.assertEqual(result.text, "Table basse Sam")
        self.assertEqual(result.strategy, "none")

    def test_empty_name_returns_empty(self):
        result = self.engine.process("x", "", limit=40)
        self.assertEqual(result.text, "")

    def test_never_exceeds_limit_even_in_worst_case(self):
        long_name = (
            "Ensemble de jardin Paku table extensible chaises coussins "
            "parasol housse de protection supplémentaire très détaillée"
        )
        result = self.engine.process("quelle source", long_name, limit=40)
        self.assertLessEqual(len(result.text), 40)
        self.assertTrue(result.text)

    def test_parens_stripped_even_when_short(self):
        result = self.engine.process("x", "Table basse Sam (nouvelle édition)", limit=40)
        self.assertNotIn("(", result.text)
        self.assertNotIn(")", result.text)


if __name__ == "__main__":
    unittest.main()
