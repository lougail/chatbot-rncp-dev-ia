"""Tests unitaires du pipeline d'indexation.

On teste les fonctions PURES (sans appel API ni Qdrant) pour rester rapides
et indépendants d'Internet/Docker. Les tests d'intégration end-to-end sont
hors scope d'un MVP.
"""

from __future__ import annotations

from langchain_core.documents import Document

from src.ingest import split_documents


def test_split_documents_returns_chunks() -> None:
    """split_documents découpe bien un long texte en plusieurs chunks."""
    long_text = "Phrase de test. " * 200  # ~3200 caractères → plusieurs chunks attendus
    docs = [Document(page_content=long_text, metadata={"page": 1})]

    chunks = split_documents(docs)

    assert len(chunks) > 1, "Un texte long doit être découpé en plusieurs chunks"
    assert all(isinstance(c, Document) for c in chunks)
    # Tous les chunks doivent garder la métadonnée page d'origine
    assert all(c.metadata.get("page") == 1 for c in chunks)


def test_split_documents_short_text() -> None:
    """Un texte court doit rester en un seul chunk."""
    docs = [Document(page_content="Texte court.", metadata={"page": 1})]

    chunks = split_documents(docs)

    assert len(chunks) == 1
    assert chunks[0].page_content == "Texte court."


def test_split_documents_preserves_metadata() -> None:
    """Les métadonnées doivent être propagées à chaque chunk."""
    docs = [
        Document(page_content="X" * 1000, metadata={"page": 5, "source": "test.pdf"}),
    ]

    chunks = split_documents(docs)

    for chunk in chunks:
        assert chunk.metadata["page"] == 5
        assert chunk.metadata["source"] == "test.pdf"
