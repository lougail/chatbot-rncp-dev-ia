"""Pipeline RAG LangChain — Hybrid Search + Reranking.

Ce module assemble le pipeline complet :

    Question
       │
       ├──► BM25 (lexical, k=20) ──┐
       │                            ├──► EnsembleRetriever (RRF, weights=0.4/0.6)
       └──► Qdrant (dense, k=20) ──┘                │
                                                     ▼
                            CrossEncoderReranker (bge-reranker-v2-m3, top_n=5)
                                                     │
                                                     ▼
                            Prompt → ChatMistralAI (temp=0) → Réponse

On expose :
  - build_chain()         : la chain LCEL complète (Runnable LangChain)
  - retrieve_with_scores(): top-5 chunks AVEC leur score de pertinence (reranker)

Pourquoi cette architecture (vs Qdrant-only) ?
  - mistral-embed seul ne discrimine pas les codes courts (C5 vs C15)
  - BM25 capture les mots-clés littéraux ("FastAPI", "Docker", "C13")
  - Le cross-encoder affine la pertinence finale (vs similarité cosinus brute)
"""

from __future__ import annotations

import json
import logging

from langchain.retrievers import ContextualCompressionRetriever, EnsembleRetriever
from langchain.retrievers.document_compressors import CrossEncoderReranker
from langchain_community.cross_encoders import HuggingFaceCrossEncoder
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_mistralai import ChatMistralAI, MistralAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from src.config import (
    MISTRAL_API_KEY,
    MISTRAL_EMBED_MODEL,
    MISTRAL_LLM_MODEL,
    QDRANT_COLLECTION,
    QDRANT_URL,
)
from src.ingest import BM25_CORPUS_PATH
from src.prompts import SYSTEM_PROMPT

log = logging.getLogger(__name__)


# Hyperparamètres du retriever — figés ici car liés à la stratégie hybride.
# Modifiables si on doit ajuster (cf. vault/decisions/2026-04-30-fix-retrieval-strategy.md).
RETRIEVER_K = 15  # Top-k de chaque retriever AVANT rerank (BM25 et dense)
RERANKER_TOP_N = 10  # Top-n final après rerank (envoyé au LLM) — sur 21 compétences
# totales, top 10 donne au LLM quasi-toutes les candidates pertinentes
ENSEMBLE_WEIGHTS = [0.4, 0.6]  # Pondération [BM25, dense]


# ---------------------------------------------------------------------------
# Singletons : modèle reranker + corpus BM25
# ---------------------------------------------------------------------------
# Le reranker bge-reranker-v2-m3 fait ~1.1 GB et prend ~30s à télécharger
# au premier appel. On le charge UNE seule fois au niveau module pour éviter
# de bloquer le premier message utilisateur.
_RERANKER_MODEL: HuggingFaceCrossEncoder | None = None
_BM25_RETRIEVER: BM25Retriever | None = None


def _detect_best_device() -> str:
    """Détecte le meilleur device disponible pour le reranker.

    Priorité : CUDA (GPU NVIDIA) > CPU.
    On évite explicitement MPS (Apple Silicon Metal) à cause d'un bug PyTorch
    sur les modèles XLM-Roberta (Invalid buffer size 45 GiB) sur les longues
    séquences. Sur Mac sans CUDA, on reste donc en CPU (lent mais stable).
    """
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


def _get_reranker_model() -> HuggingFaceCrossEncoder:
    """Singleton du modèle cross-encoder. Charge le modèle au premier appel."""
    global _RERANKER_MODEL
    if _RERANKER_MODEL is None:
        device = _detect_best_device()
        log.info(
            f"📥 Chargement du reranker BAAI/bge-reranker-v2-m3 sur {device} (~30s la 1ère fois)"
        )
        _RERANKER_MODEL = HuggingFaceCrossEncoder(
            model_name="BAAI/bge-reranker-v2-m3",
            model_kwargs={"device": device},
        )
        log.info(f"✅ Reranker chargé en mémoire (device={device})")
    return _RERANKER_MODEL


def _get_bm25_retriever() -> BM25Retriever:
    """Singleton du BM25 retriever. Reconstruit depuis le corpus JSON sauvé à l'ingestion."""
    global _BM25_RETRIEVER
    if _BM25_RETRIEVER is None:
        if not BM25_CORPUS_PATH.exists():
            raise FileNotFoundError(
                f"Corpus BM25 manquant ({BM25_CORPUS_PATH}). "
                "Lance `uv run python -m src.ingest --recreate` pour le générer."
            )
        log.info(f"📚 Reconstruction de BM25 depuis {BM25_CORPUS_PATH.name}")
        data = json.loads(BM25_CORPUS_PATH.read_text())
        corpus = [Document(page_content=d["page_content"], metadata=d["metadata"]) for d in data]
        _BM25_RETRIEVER = BM25Retriever.from_documents(corpus, k=RETRIEVER_K)
        log.info(f"   → {len(corpus)} documents chargés dans BM25")
    return _BM25_RETRIEVER


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
# Hybrid Retriever : BM25 (lexical) + Qdrant (dense), fusion par RRF pondéré
# ---------------------------------------------------------------------------
def build_hybrid_retriever() -> EnsembleRetriever:
    """Construit le retriever hybride BM25 + Qdrant.

    Pourquoi hybride ?
      - BM25 capture les mots-clés exacts ("FastAPI", "Docker", "C13") que
        l'embedding sémantique manque.
      - L'embedding capture les paraphrases ("API REST" ↔ "endpoint web").
      - L'EnsembleRetriever fusionne les deux résultats via RRF (Reciprocal
        Rank Fusion) avec pondération [0.4, 0.6] (priorité au sémantique).

    Chaque retriever ramène k=20 candidats, soit jusqu'à 40 candidats pour
    le reranker. Suffisant pour 21 compétences.
    """
    qdrant_retriever = _get_vector_store().as_retriever(
        search_type="similarity",
        search_kwargs={"k": RETRIEVER_K},
    )
    bm25_retriever = _get_bm25_retriever()

    return EnsembleRetriever(
        retrievers=[bm25_retriever, qdrant_retriever],
        weights=ENSEMBLE_WEIGHTS,
    )


# ---------------------------------------------------------------------------
# Reranker : cross-encoder bge-reranker-v2-m3 (multilingue, FR-friendly)
# ---------------------------------------------------------------------------
def build_retriever() -> ContextualCompressionRetriever:
    """Pipeline complet : Hybrid → Cross-encoder rerank → top 5.

    Le cross-encoder est plus précis qu'un calcul de similarité cosinus
    car il prend en entrée la PAIRE (question, chunk) et calcule un score
    de pertinence direct. Plus lent mais beaucoup plus précis.

    Modèle utilisé : `BAAI/bge-reranker-v2-m3` (multilingue, FR natif).
    """
    hybrid = build_hybrid_retriever()
    reranker = CrossEncoderReranker(model=_get_reranker_model(), top_n=RERANKER_TOP_N)
    return ContextualCompressionRetriever(
        base_compressor=reranker,
        base_retriever=hybrid,
    )


def retrieve_with_scores(question: str) -> list[tuple[Document, float]]:
    """Récupère les top-N chunks reranked AVEC leur score de pertinence.

    Le score retourné est celui du cross-encoder (`relevance_score` dans la
    metadata du Document), plus précis que le score cosinus brut.
    Plus le score est élevé, plus le chunk est pertinent.

    Returns:
        Liste de tuples (Document, relevance_score) triés par score décroissant.
    """
    retriever = build_retriever()
    docs = retriever.invoke(question)
    # Le CrossEncoderReranker injecte le score dans metadata['relevance_score']
    return [(d, float(d.metadata.get("relevance_score", 0.0))) for d in docs]


# ---------------------------------------------------------------------------
# Helpers pour le prompt
# ---------------------------------------------------------------------------
def format_docs(docs: list[Document]) -> str:
    """Formate la liste de Documents en un seul bloc de texte.

    On préfixe chaque chunk avec sa compétence et sa page (ex: "[C5 — page 4]")
    pour donner au LLM une notion claire du code et l'aider à citer correctement.
    """
    if not docs:
        return "(Aucun extrait pertinent trouvé dans le référentiel.)"

    formatted: list[str] = []
    for i, doc in enumerate(docs, start=1):
        # Avec le splitter par compétence, chaque chunk a metadata.competence et .page
        comp = doc.metadata.get("competence", "?")
        page = doc.metadata.get("page", "?")
        formatted.append(f"[Extrait {i} — compétence {comp}, page {page}]\n{doc.page_content}")

    return "\n\n---\n\n".join(formatted)


# ---------------------------------------------------------------------------
# Chain : assemblage final via LCEL (LangChain Expression Language)
# ---------------------------------------------------------------------------
def build_chain() -> Runnable:
    """Construit la chain RAG : prompt + LLM + parser.

    La chain attend en entrée un dict `{"context": <str>, "question": <str>}`
    (pas la question brute) — le retrieval est délégué à `retrieve_with_scores()`
    appelée AVANT, dans `app.py`.

    Pourquoi cette séparation ?
        Le pipeline hybrid + reranker est lourd (~2-5s en CPU). Si on l'incluait
        dans la chain, chaque message déclencherait DEUX appels au reranker :
          1. dans `retrieve_with_scores()` (pour afficher les sources)
          2. dans `chain.invoke()` (pour générer la réponse)
        En séparant, on récupère les docs UNE SEULE FOIS dans `app.py` puis on
        les passe à la chain pour la génération. Latence divisée par 2.

    Pourquoi temperature=0 ?
        Pour un chatbot d'analyse factuelle, on veut un comportement
        déterministe et anti-hallucination — pas de créativité.
    """
    # Template du prompt avec placeholders {context} et {question}
    prompt = ChatPromptTemplate.from_template(SYSTEM_PROMPT)

    # LLM : on force temperature=0 pour la stabilité des réponses
    llm = ChatMistralAI(
        model=MISTRAL_LLM_MODEL,
        api_key=MISTRAL_API_KEY,
        temperature=0,
    )

    # Composition LCEL minimale : le retrieval est externe
    chain: Runnable = prompt | llm | StrOutputParser()
    return chain
