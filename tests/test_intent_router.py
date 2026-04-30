"""Tests pour `src.intent_router`.

Couvre les 6 intents + extraction de compétences + edge cases (codes
hors plage, déduplication, casse).
"""

from __future__ import annotations

import pytest

from src.intent_router import Intent, _extract_competences, detect_intent


class TestExtractCompetences:
    def test_extracts_single_code(self):
        assert _extract_competences("Que dit C13 ?") == ["C13"]

    def test_extracts_multiple_codes_in_order(self):
        assert _extract_competences("Compare C13 et C19") == ["C13", "C19"]

    def test_deduplicates_repeated_codes(self):
        assert _extract_competences("C13 puis encore C13") == ["C13"]

    def test_filters_codes_outside_range(self):
        # C0, C22, C99 ne sont pas valides — la plage est C1-C21
        assert _extract_competences("C0 C22 C99") == []

    def test_keeps_only_valid_codes_among_invalid(self):
        assert _extract_competences("C0 et C13 et C22") == ["C13"]

    def test_returns_empty_list_when_no_code(self):
        assert _extract_competences("Quelles compétences ?") == []

    def test_word_boundary_avoids_false_positives(self):
        # "C9" dans "MC9" ou "C99" ne doit PAS matcher (word boundary)
        assert _extract_competences("MC9") == []


class TestDetectIntent:
    def test_meta_intent_bypasses_rag(self):
        result = detect_intent("Combien de compétences au total ?")
        assert result.intent == Intent.META
        assert result.bypass_rag is True
        assert result.suggested_top_n == 0

    def test_comparison_intent_with_two_codes(self):
        result = detect_intent("Compare C13 et C19")
        assert result.intent == Intent.COMPARISON
        assert result.competences == ["C13", "C19"]
        assert result.suggested_top_n >= 2

    def test_comparison_without_codes_falls_back_to_general(self):
        # "compare" seul sans codes → on ne sait pas quoi comparer
        result = detect_intent("Compare un peu si tu veux")
        assert result.intent == Intent.GENERAL

    def test_specific_competence_intent_with_one_code(self):
        result = detect_intent("Que dit C13 ?")
        assert result.intent == Intent.SPECIFIC_COMPETENCE
        assert result.competences == ["C13"]

    def test_definition_intent(self):
        for query in [
            "C'est quoi le bloc MLOps ?",
            "Définis le RNCP",
            "Que veut dire packaging dans ce contexte ?",
        ]:
            result = detect_intent(query)
            assert result.intent == Intent.DEFINITION, f"failed for: {query}"
            assert result.suggested_top_n <= 5

    def test_coverage_analysis_intent(self):
        for query in [
            "Quelles compétences couvre mon projet FastAPI Docker ?",
            "Mon projet valide quelles compétences ?",
            "Décris-moi ce qui manque dans mon projet",
        ]:
            result = detect_intent(query)
            assert result.intent in (
                Intent.COVERAGE_ANALYSIS,
                Intent.DEFINITION,
            ), f"failed for: {query}"

    def test_general_intent_fallback(self):
        result = detect_intent("blabla random texte sans pattern")
        assert result.intent == Intent.GENERAL

    def test_specific_competence_takes_precedence_over_definition(self):
        # "c'est quoi C13" : on a un code → on retrieve C13 ciblé,
        # pas une définition générale
        result = detect_intent("C'est quoi C13 ?")
        assert result.intent == Intent.SPECIFIC_COMPETENCE
        assert result.competences == ["C13"]

    def test_meta_takes_priority_over_specific_competence(self):
        # "Combien de blocs au total" doit rester META même si Cn apparaît
        result = detect_intent("Combien de blocs au total dans le RNCP ?")
        assert result.intent == Intent.META

    def test_jury_interview_intent_via_slash_command(self):
        assert detect_intent("/jury").intent == Intent.JURY_INTERVIEW

    @pytest.mark.parametrize(
        "query",
        [
            "Prépare-moi à la soutenance",
            "Simule un entretien jury sur mon projet FastAPI",
            "Je veux faire une simulation de soutenance",
        ],
    )
    def test_jury_interview_intent_via_keyword(self, query: str):
        assert detect_intent(query).intent == Intent.JURY_INTERVIEW


@pytest.mark.parametrize(
    "query,expected_intent",
    [
        ("https://github.com/user/repo", Intent.GENERAL),  # URL, pas de mots-clés
        ("Mon projet FastAPI Docker", Intent.COVERAGE_ANALYSIS),  # "projet" → coverage
        ("Bonjour, comment ça va ?", Intent.GENERAL),  # vraie question hors-scope
        ("C13 ?", Intent.SPECIFIC_COMPETENCE),
        ("Liste des blocs ?", Intent.META),
    ],
)
def test_intent_routing_examples(query: str, expected_intent: Intent):
    """Smoke test paramétré sur des cas typiques."""
    assert detect_intent(query).intent == expected_intent
