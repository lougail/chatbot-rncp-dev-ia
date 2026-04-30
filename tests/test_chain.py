"""Tests pour `src.chain` — focus sur `ScoringCrossEncoderReranker`.

On ne teste PAS le pipeline complet (Mistral + Qdrant en intégration)
car coûteux en tokens et fragile (clé API, rate limit). À la place on
teste uniquement la logique métier pure : injection du score dans
metadata, normalisation sigmoid, tri décroissant.

Le `model.score()` du cross-encoder est mocké (interface minimale :
une méthode `score(pairs) -> list[float]`).
"""

from __future__ import annotations

from langchain_community.cross_encoders.base import BaseCrossEncoder
from langchain_core.documents import Document

from src.chain import ScoringCrossEncoderReranker


class _FakeCrossEncoder(BaseCrossEncoder):
    """Mock minimal qui retourne des logits prédéfinis dans l'ordre des paires.

    Hérite de `BaseCrossEncoder` pour passer la validation Pydantic du
    `ScoringCrossEncoderReranker.model`.
    """

    def __init__(self, scores: list[float]) -> None:
        self._scores = scores
        self.last_pairs: list[tuple[str, str]] | None = None

    def score(self, text_pairs: list[tuple[str, str]]) -> list[float]:
        self.last_pairs = text_pairs
        return self._scores


def _make_docs(n: int) -> list[Document]:
    return [Document(page_content=f"chunk {i}", metadata={"page": i}) for i in range(n)]


def test_scoring_reranker_injects_relevance_score_in_metadata():
    """Le bug #22556 est fixé : `metadata['relevance_score']` est présent."""
    fake = _FakeCrossEncoder(scores=[0.5, -1.0, 2.0])
    reranker = ScoringCrossEncoderReranker(model=fake, top_n=3)

    result = reranker.compress_documents(_make_docs(3), "query")

    for doc in result:
        assert "relevance_score" in doc.metadata
        assert isinstance(doc.metadata["relevance_score"], float)


def test_scoring_reranker_score_is_in_unit_interval():
    """Sigmoid normalise les logits bruts en probabilité [0, 1]."""
    # Logits volontairement extrêmes pour vérifier que sigmoid les borne
    fake = _FakeCrossEncoder(scores=[-10.0, 0.0, 10.0])
    reranker = ScoringCrossEncoderReranker(model=fake, top_n=3)

    result = reranker.compress_documents(_make_docs(3), "query")

    for doc in result:
        score = doc.metadata["relevance_score"]
        assert 0.0 <= score <= 1.0


def test_scoring_reranker_returns_top_n_in_descending_order():
    """Les documents sont triés par score décroissant et limités à top_n."""
    # 5 docs avec scores croissants → on attend les 2 plus pertinents en premier
    fake = _FakeCrossEncoder(scores=[0.1, 0.5, 0.9, 0.3, 0.7])
    reranker = ScoringCrossEncoderReranker(model=fake, top_n=2)

    result = reranker.compress_documents(_make_docs(5), "query")

    assert len(result) == 2
    # Le premier doit être l'index 2 (score=0.9), le second l'index 4 (score=0.7)
    assert result[0].metadata["page"] == 2
    assert result[1].metadata["page"] == 4
    # Et le tri par score sigmoid doit rester décroissant
    assert result[0].metadata["relevance_score"] > result[1].metadata["relevance_score"]


def test_scoring_reranker_passes_query_doc_pairs_to_model():
    """Le reranker passe bien (query, page_content) au model.score()."""
    fake = _FakeCrossEncoder(scores=[0.5, 0.5])
    reranker = ScoringCrossEncoderReranker(model=fake, top_n=2)

    docs = [
        Document(page_content="contenu A", metadata={}),
        Document(page_content="contenu B", metadata={}),
    ]
    reranker.compress_documents(docs, "ma question")

    assert fake.last_pairs == [
        ("ma question", "contenu A"),
        ("ma question", "contenu B"),
    ]
