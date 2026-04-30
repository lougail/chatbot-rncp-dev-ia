"""Tests unitaires du pipeline d'indexation.

On teste les fonctions PURES (sans appel API ni Qdrant) pour rester rapides
et indépendants d'Internet/Docker. Les tests d'intégration end-to-end sont
hors scope d'un MVP.

Pattern AAA (Arrange, Act, Assert) sur chaque test.
"""

from __future__ import annotations

from langchain_core.documents import Document

from src.ingest import split_competences


def test_split_competences_extracts_one_chunk_per_code() -> None:
    """Le splitter doit produire un chunk par compétence présente dans le texte."""
    # Arrange : texte simulant 3 compétences en début de ligne
    text = (
        "Préambule à ignorer.\n"
        "C1. Automatiser l'extraction de données depuis un service web.\n"
        "C2. Développer des requêtes SQL d'extraction des données.\n"
        "C3. Créer une base de données dans le respect du RGPD.\n"
    )
    # page=4 pour que le chunk passe le filtre LIBELLE_PAGES
    docs = [Document(page_content=text, metadata={"source": "test.pdf", "page": 4})]

    # Act
    chunks = split_competences(docs)

    # Assert : 3 chunks, un par code, codes correctement extraits
    codes = sorted(c.metadata["competence"] for c in chunks)
    assert codes == ["C1", "C2", "C3"]


def test_split_competences_ignores_text_before_first_code() -> None:
    """Le préambule (texte avant C1.) ne doit pas devenir un chunk."""
    # Arrange
    text = "Sommaire et introduction sans code.\nPas de compétence ici."
    # page=4 pour que le chunk passe le filtre LIBELLE_PAGES
    docs = [Document(page_content=text, metadata={"source": "test.pdf", "page": 4})]

    # Act
    chunks = split_competences(docs)

    # Assert
    assert chunks == []


def test_split_competences_preserves_source_metadata() -> None:
    """La métadonnée `source` doit être propagée à chaque chunk."""
    # Arrange
    text = "C1. Première compétence.\nC2. Deuxième compétence."
    docs = [Document(page_content=text, metadata={"source": "referentiel.pdf", "page": 4})]

    # Act
    chunks = split_competences(docs)

    # Assert
    assert all(c.metadata["source"] == "referentiel.pdf" for c in chunks)


def test_split_competences_keeps_code_at_start_of_chunk() -> None:
    """Chaque chunk doit commencer par son code de compétence (pas perdu)."""
    # Arrange
    text = "C7. Identifier des services d'intelligence artificielle préexistants."
    # page=4 pour que le chunk passe le filtre LIBELLE_PAGES
    docs = [Document(page_content=text, metadata={"source": "test.pdf", "page": 4})]

    # Act
    chunks = split_competences(docs)

    # Assert
    assert len(chunks) == 1
    assert chunks[0].page_content.startswith("C7.")
    assert chunks[0].metadata["competence"] == "C7"
