"""Tests for HumanCorrectionPropagationEngine (spec Part X)."""

import pytest

from engines.french.propagation_engine import (
    HumanCorrectionPropagationEngine,
    build_variable_template,
    apply_variable_template,
    extract_term_change,
    suggest_glossary_update,
    is_exact_source_match,
    CONF_SAFE,
    CONF_HIGH,
    CONF_MEDIUM,
)


def row(id, column, source, target_old):
    return {"id": id, "column": column, "source": source, "target_old": target_old}


# =============================================================================
# 1. Exact source propagation
# =============================================================================

class TestExactSourcePropagation:
    def test_identical_source_propagates_automatically(self):
        engine = HumanCorrectionPropagationEngine()
        corrected = {
            "id": "r1", "column": "name",
            "source": "Armlehnenstuhl ohne Dekoration",
            "target_old": "Fauteuil sans décoration",
            "target_new": "Chaise à accoudoirs sans décoration",
        }
        others = [
            row("r2", "name", "Armlehnenstuhl ohne Dekoration", "Fauteuil sans décoration"),
            row("r3", "name", "Armlehnenstuhl ohne Dekoration", "Fauteuil sans décoration"),
            row("r4", "name", "Table basse", "Table basse"),  # unrelated — must not match
        ]
        analysis = engine.analyze(corrected, others)
        assert {m.row_id for m in analysis.safe} == {"r2", "r3"}
        assert all(m.confidence == CONF_SAFE for m in analysis.safe)
        assert all(m.proposed_target == "Chaise à accoudoirs sans décoration" for m in analysis.safe)

    def test_seven_identical_occurrences(self):
        engine = HumanCorrectionPropagationEngine()
        corrected = {
            "id": "r0", "column": "materialDetail",
            "source": "Bezug: Samt",
            "target_old": "Revêtement : velours",
            "target_new": "Revêtement : velours côtelé",
        }
        others = [row(f"r{i}", "materialDetail", "Bezug: Samt", "Revêtement : velours") for i in range(1, 8)]
        analysis = engine.analyze(corrected, others)
        assert len(analysis.safe) == 7

    def test_different_column_profile_does_not_propagate(self):
        assert not is_exact_source_match("", "")

    def test_confirmed_row_never_overwritten(self):
        engine = HumanCorrectionPropagationEngine()
        corrected = {
            "id": "r1", "column": "name", "source": "Armlehnenstuhl",
            "target_old": "Fauteuil", "target_new": "Chaise à accoudoirs",
        }
        others = [{**row("r2", "name", "Armlehnenstuhl", "Fauteuil"), "confirmed": True}]
        analysis = engine.analyze(corrected, others)
        assert analysis.safe == []


# =============================================================================
# 2. Model-safe pattern propagation
# =============================================================================

class TestModelSafePatternPropagation:
    def test_evira_nova_preserved(self):
        engine = HumanCorrectionPropagationEngine()
        corrected = {
            "id": "r1", "column": "name",
            "source": "Drehbarer Armlehnenstuhl EVIRA 2er-Set",
            "target_old": "Fauteuil pivotant EVIRA 2er-Set",
            "target_new": "Chaise à accoudoirs pivotante EVIRA 2er-Set",
        }
        others = [row("r2", "name", "Drehbarer Armlehnenstuhl NOVA 2er-Set", "Fauteuil pivotant NOVA 2er-Set")]
        analysis = engine.analyze(corrected, others)
        assert len(analysis.high) == 1
        match = analysis.high[0]
        assert match.row_id == "r2"
        assert "NOVA" in match.proposed_target
        assert "EVIRA" not in match.proposed_target
        assert "Chaise à accoudoirs pivotante" in match.proposed_target

    def test_template_extraction_direct(self):
        template = build_variable_template(
            "Drehbarer Armlehnenstuhl EVIRA 2er-Set",
            "Drehbarer Armlehnenstuhl NOVA 2er-Set",
        )
        assert template == [("MODEL", "EVIRA", "NOVA")]

    def test_apply_template_swaps_only_the_model(self):
        template = [("MODEL", "EVIRA", "NOVA")]
        result = apply_variable_template("Chaise à accoudoirs pivotante EVIRA 2er-Set", template)
        assert result == "Chaise à accoudoirs pivotante NOVA 2er-Set"

    def test_apply_template_matches_even_when_correction_also_fixed_casing(self):
        """Regression: a human correction that both fixes wording and
        title-cases an all-caps German model spelling (e.g. "PAKU" ->
        "Paku", which the capitalization engine itself can require) must
        still propagate — a case-sensitive search for the source's literal
        "PAKU" spelling would find nothing in "...Paku..." and silently
        skip the row."""
        template = [("MODEL", "PAKU", "LEDO")]
        result = apply_variable_template("Chaise Paku 2er-Set opt. reglage", template)
        assert result == "Chaise Ledo 2er-Set opt. reglage"

    def test_engine_end_to_end_propagates_corrected_casing(self):
        engine = HumanCorrectionPropagationEngine()
        corrected = {
            "id": "r1", "column": "name",
            "source": "Drehbarer Armlehnenstuhl PAKU 2er-Set opt. Sitzhoehenverstellung",
            "target_old": "Chaise pivotante PAKU 2er-Set opt. reglage",
            "target_new": "Chaise Paku 2er-Set opt. reglage",
        }
        others = [row(
            "r2", "name",
            "Drehbarer Armlehnenstuhl LEDO 2er-Set opt. Sitzhoehenverstellung",
            "Chaise pivotante LEDO 2er-Set opt. reglage",
        )]
        analysis = engine.analyze(corrected, others)
        assert len(analysis.high) == 1
        assert analysis.high[0].proposed_target == "Chaise Ledo 2er-Set opt. reglage"


# =============================================================================
# 3. Quantity safety
# =============================================================================

class TestQuantitySafety:
    def test_2er_set_never_becomes_4er_set(self):
        template = build_variable_template(
            "Drehbarer Armlehnenstuhl EVIRA 2er-Set",
            "Drehbarer Armlehnenstuhl EVIRA 4er-Set",
        )
        assert template == [("QTY", "2er-Set", "4er-Set")]
        result = apply_variable_template("Chaise à accoudoirs pivotante EVIRA 2er-Set", template)
        assert result == "Chaise à accoudoirs pivotante EVIRA 4er-Set"
        assert "2er-Set" not in result

    def test_engine_end_to_end_quantity_propagation(self):
        engine = HumanCorrectionPropagationEngine()
        corrected = {
            "id": "r1", "column": "name",
            "source": "Kissenbezug 2er-Set",
            "target_old": "Housse de coussin 2er-Set",
            "target_new": "Taie d'oreiller 2er-Set",
        }
        others = [row("r2", "name", "Kissenbezug 4er-Set", "Housse de coussin 4er-Set")]
        analysis = engine.analyze(corrected, others)
        assert len(analysis.high) == 1
        assert analysis.high[0].proposed_target == "Taie d'oreiller 4er-Set"


# =============================================================================
# 4. Capitalization propagation
# =============================================================================

class TestCapitalizationPropagation:
    def test_propagated_text_runs_through_capitalization_engine(self):
        engine = HumanCorrectionPropagationEngine()
        corrected = {
            "id": "r1", "column": "colorDetail",
            "source": "Bezug: Samt",
            "target_old": "Revêtement : Velours",
            "target_new": "Revêtement : Velours côtelé",
        }
        others = [row("r2", "colorDetail", "Bezug: Samt", "Revêtement : Velours")]
        analysis = engine.analyze(corrected, others)
        # colorDetail profile lowercases the value after ':' unless it's a
        # proper name/full sentence — capitalization pass must still run on
        # the propagated text, not just copy it verbatim.
        assert analysis.safe[0].proposed_target == "Revêtement : velours côtelé"

    def test_term_level_propagation_uses_correct_case_per_position(self):
        engine = HumanCorrectionPropagationEngine()
        corrected = {
            "id": "r1", "column": "materialDetail",
            "source": "Bezug: Samt",
            "target_old": "Revêtement : velours",
            "target_new": "Revêtement : velours côtelé",
        }
        others = [
            row("r2", "materialDetail", "Bezug: andere", "Farbe hell<br>velours vorhanden"),
        ]
        # target_old on r2 contains lowercase "velours" mid-sentence — the
        # propagated replacement must not force it uppercase.
        analysis = engine.analyze(corrected, others)
        matches = [m for m in analysis.medium if m.row_id == "r2"]
        if matches:
            assert "Velours côtelé" not in matches[0].proposed_target


# =============================================================================
# 5. Glossary learning
# =============================================================================

class TestGlossaryLearning:
    def test_clean_term_correction_is_proposed(self):
        suggestion = suggest_glossary_update(
            "Armlehnenstuhl", "Fauteuil avec accoudoirs", "Chaise à accoudoirs",
        )
        assert suggestion is not None
        assert suggestion["source_term"] == "Armlehnenstuhl"
        assert suggestion["new_target_term"] == "Chaise à accoudoirs"

    def test_full_sentence_correction_is_never_proposed(self):
        suggestion = suggest_glossary_update(
            "Dieser Armlehnenstuhl ist aus massivem Holz gefertigt und sehr bequem.",
            "Ce fauteuil est fabriqué en bois massif et très confortable.",
            "Cette chaise à accoudoirs est fabriquée en bois massif et très confortable.",
        )
        assert suggestion is None

    def test_engine_surfaces_glossary_suggestion(self):
        engine = HumanCorrectionPropagationEngine()
        corrected = {
            "id": "r1", "column": "name",
            "source": "Armlehnenstuhl",
            "target_old": "Fauteuil avec accoudoirs",
            "target_new": "Chaise à accoudoirs",
        }
        analysis = engine.analyze(corrected, [])
        assert analysis.glossary_suggestion is not None
        assert analysis.glossary_suggestion["source_term"] == "Armlehnenstuhl"


# =============================================================================
# 6. Protected-data safeguard (Part R)
# =============================================================================

class TestProtectedDataSafeguard:
    def test_paku_never_becomes_ledo(self):
        engine = HumanCorrectionPropagationEngine()
        corrected = {
            "id": "r1", "column": "name",
            "source": "Tischleuchte Paku",
            "target_old": "Lampe de table Paku",
            "target_new": "Lampe de chevet Paku",
        }
        others = [row("r2", "name", "Tischleuchte Ledo", "Lampe de table Ledo")]
        analysis = engine.analyze(corrected, others)
        assert len(analysis.high) == 1
        assert "Ledo" in analysis.high[0].proposed_target
        assert "Paku" not in analysis.high[0].proposed_target

    def test_color_mismatch_is_vetoed_not_even_suggested(self):
        engine = HumanCorrectionPropagationEngine()
        corrected = {
            "id": "r1", "column": "colorDetail",
            "source": "Farbe: Schwarz",
            "target_old": "Couleur : Noir",
            "target_new": "Couleur : noir mat",
        }
        others = [row("r2", "colorDetail", "Farbe: Grau", "Couleur : gris")]
        analysis = engine.analyze(corrected, others)
        all_ids = {m.row_id for m in analysis.safe + analysis.high + analysis.medium + analysis.low}
        assert "r2" not in all_ids

    def test_dimension_token_only_swaps_the_dimension(self):
        template = build_variable_template("Tisch 120cm", "Tisch 150cm")
        assert template == [("DIM", "120cm", "150cm")]
        result = apply_variable_template("Table 120cm", template)
        assert result == "Table 150cm"


# =============================================================================
# 7. Term-level / similar-segment propagation (Part F/G)
# =============================================================================

class TestTermLevelPropagation:
    def test_recurring_mistranslated_term_detected(self):
        old_phrase, new_phrase = extract_term_change("Revêtement : velours", "Revêtement : velours côtelé")
        assert new_phrase == "velours côtelé"

    def test_multi_word_full_sentence_change_is_not_a_term_change(self):
        result = extract_term_change(
            "Ce produit est fabriqué en bois et convient pour toutes les pièces de la maison",
            "Cet article est conçu en métal et convient pour toutes les pièces du salon",
        )
        assert result is None

    def test_engine_finds_similar_segments_with_different_sources(self):
        engine = HumanCorrectionPropagationEngine()
        corrected = {
            "id": "r1", "column": "materialDetail",
            "source": "Bezug: Cord",
            "target_old": "Revêtement : velours côtelé",
            "target_new": "Revêtement : velours côtelé beige",
        }
        others = [
            row("r2", "materialDetail", "Bezug: Cord grau", "Revêtement : velours côtelé gris"),
        ]
        analysis = engine.analyze(corrected, others)
        assert any(m.row_id == "r2" for m in analysis.medium)


# =============================================================================
# 8. Undo safety — engine never mutates inputs (caller owns undo stack)
# =============================================================================

class TestUndoSafety:
    def test_analyze_does_not_mutate_inputs(self):
        engine = HumanCorrectionPropagationEngine()
        corrected = {
            "id": "r1", "column": "name",
            "source": "Armlehnenstuhl", "target_old": "Fauteuil", "target_new": "Chaise à accoudoirs",
        }
        others = [row("r2", "name", "Armlehnenstuhl", "Fauteuil")]
        snapshot = [dict(r) for r in others]
        engine.analyze(corrected, others)
        assert others == snapshot


# =============================================================================
# 9. Confidence classification sanity
# =============================================================================

class TestConfidenceClassification:
    def test_safe_high_medium_never_overlap_same_row(self):
        engine = HumanCorrectionPropagationEngine()
        corrected = {
            "id": "r1", "column": "name",
            "source": "Armlehnenstuhl EVIRA",
            "target_old": "Fauteuil EVIRA", "target_new": "Chaise à accoudoirs EVIRA",
        }
        others = [
            row("r2", "name", "Armlehnenstuhl EVIRA", "Fauteuil EVIRA"),        # exact -> SAFE
            row("r3", "name", "Armlehnenstuhl NOVA", "Fauteuil NOVA"),          # pattern -> HIGH
        ]
        analysis = engine.analyze(corrected, others)
        safe_ids = {m.row_id for m in analysis.safe}
        high_ids = {m.row_id for m in analysis.high}
        assert safe_ids == {"r2"}
        assert high_ids == {"r3"}
        assert not (safe_ids & high_ids)
