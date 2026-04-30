"""Pipeline RAG LangChain.

Ce module assemble le pipeline complet :
    Question → Retriever (Qdrant) → Prompt → LLM (Mistral) → Réponse

On expose deux fonctions principales :
  - build_chain()    : retourne la chain LCEL (objet Runnable LangChain)
  - build_retriever(): retourne juste le retriever (utile pour afficher les sources)

Les deux sont séparés volontairement : on a besoin du retriever isolé pour
afficher les chunks utilisés en source dans l'UI Chainlit.
"""

from __future__ import annotations

import logging

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnablePassthrough
from langchain_core.vectorstores import VectorStoreRetriever
from langchain_mistralai import ChatMistralAI, MistralAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from src.config import (
    MISTRAL_API_KEY,
    MISTRAL_EMBED_MODEL,
    MISTRAL_LLM_MODEL,
    QDRANT_COLLECTION,
    QDRANT_URL,
    RETRIEVAL_K,
    SCORE_THRESHOLD,
)
from src.prompts import SYSTEM_PROMPT

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vector store : on charge la collection existante (créée par ingest.py)
# ---------------------------------------------------------------------------
def _get_vector_store() -> QdrantVectorStore:
    """Charge la collection Qdrant existante (sans réindexer).

    Il faut avoir lancé `python -m src.ingest` AVANT que cette fonction marche.
    """
    log.info(f"🔌 Connexion à Qdrant ({QDRANT_URL}, collection={QDRANT_COLLECTION})")

    client = QdrantClient(url=QDRANT_URL)
    embeddings = MistralAIEmbeddings(
        model=MISTRAL_EMBED_MODEL,
        api_key=MISTRAL_API_KEY,
    )

    return QdrantVectorStore(
        client=client,
        collection_name=QDRANT_COLLECTION,
        embedding=embeddings,
    )


# ---------------------------------------------------------------------------
# Retriever : objet qui prend une question et retourne les top-k chunks
# ---------------------------------------------------------------------------
def build_retriever() -> VectorStoreRetriever:
    """Construit le retriever Qdrant avec score threshold.

    Paramètres clés (justifiables en soutenance) :
      - k = RETRIEVAL_K (4 par défaut) : nombre de chunks à retourner
      - score_threshold = SCORE_THRESHOLD (0.4) : sous ce score, chunk rejeté
        → permet au LLM de répondre "je ne sais pas" si la question est hors-sujet
    """
    vector_store = _get_vector_store()

    return vector_store.as_retriever(
        search_type="similarity_score_threshold",
        search_kwargs={
            "k": RETRIEVAL_K,
            "score_threshold": SCORE_THRESHOLD,
        },
    )


# ---------------------------------------------------------------------------
# Helpers pour le prompt
# ---------------------------------------------------------------------------
def format_docs(docs: list[Document]) -> str:
    """Formate la liste de Documents en un seul bloc de texte.

    On préfixe chaque chunk avec sa source (page) pour donner au LLM
    une notion de la provenance et l'aider à citer correctement.
    """
    if not docs:
        return "(Aucun extrait pertinent trouvé dans le référentiel.)"

    formatted: list[str] = []
    for i, doc in enumerate(docs, start=1):
        page = doc.metadata.get("page", "?")
        formatted.append(f"[Extrait {i} — page {page}]\n{doc.page_content}")

    return "\n\n---\n\n".join(formatted)


# ---------------------------------------------------------------------------
# Chain : assemblage final via LCEL (LangChain Expression Language)
# ---------------------------------------------------------------------------
def build_chain() -> Runnable:
    """Construit la chain RAG complète avec LCEL.

    Le flux LCEL avec l'opérateur `|` (façon pipe Unix) :
      question → {context: retriever | format_docs, question: identité}
                → prompt template (remplit {context} et {question})
                → LLM Mistral
                → parser en string

    `RunnablePassthrough()` sert à dupliquer l'input : on l'envoie à la fois
    au retriever (pour chercher) ET au prompt (pour le réinjecter dans le template).

    Pourquoi temperature=0 ?
        Pour un chatbot d'analyse factuelle, on veut un comportement
        déterministe et anti-hallucination — pas de créativité.
    """
    retriever = build_retriever()

    # Template du prompt avec placeholders {context} et {question}
    prompt = ChatPromptTemplate.from_template(SYSTEM_PROMPT)

    # LLM : on force temperature=0 pour la stabilité des réponses
    llm = ChatMistralAI(
        model=MISTRAL_LLM_MODEL,
        api_key=MISTRAL_API_KEY,
        temperature=0,
    )

    # Composition LCEL — le cœur du pipeline RAG
    chain: Runnable = (
        {
            "context": retriever | format_docs,  # retriever puis formattage
            "question": RunnablePassthrough(),  # la question telle quelle
        }
        | prompt  # remplit le template
        | llm  # génère la réponse
        | StrOutputParser()  # extrait juste le texte de l'AIMessage
    )

    return chain
