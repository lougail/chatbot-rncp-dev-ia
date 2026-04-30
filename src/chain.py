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
import math
import operator
from collections.abc import Sequence

from langchain.retrievers import ContextualCompressionRetriever, EnsembleRetriever
from langchain.retrievers.document_compressors import CrossEncoderReranker
from langchain_community.cross_encoders import HuggingFaceCrossEncoder
from langchain_community.retrievers import BM25Retriever
from langchain_core.callbacks import Callbacks
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
from src.prompts import JURY_PROMPT, SYSTEM_PROMPT

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
class ScoringCrossEncoderReranker(CrossEncoderReranker):
    """Variante du CrossEncoderReranker qui injecte le score dans metadata.

    Le `CrossEncoderReranker` upstream (LangChain v0.3) calcule bien les scores
    cross-encoder pour le tri, mais les jette avant de retourner les documents.
    Conséquence : impossible d'afficher le vrai score à l'utilisateur — c'est
    un bug connu (langchain-ai/langchain#22556).

    Ici on override `compress_documents` pour stocker le score dans
    `metadata['relevance_score']` AVANT le slicing top_n, sans changer la
    logique de tri.

    On applique aussi une sigmoid pour convertir le logit brut du cross-encoder
    en probabilité [0,1] — beaucoup plus interprétable côté UI (par ex. 0.62
    plutôt que 0.5 brut). La sigmoid est strictement monotone donc le tri est
    identique avant/après transformation.
    """

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Callbacks | None = None,
    ) -> Sequence[Document]:
        scores = self.model.score([(query, doc.page_content) for doc in documents])
        docs_with_scores = list(zip(documents, scores, strict=True))
        ranked = sorted(docs_with_scores, key=operator.itemgetter(1), reverse=True)
        result = []
        for doc, score in ranked[: self.top_n]:
            doc.metadata["relevance_score"] = 1.0 / (1.0 + math.exp(-float(score)))
            result.append(doc)
        return result


def build_retriever() -> ContextualCompressionRetriever:
    """Pipeline complet : Hybrid → Cross-encoder rerank → top 5.

    Le cross-encoder est plus précis qu'un calcul de similarité cosinus
    car il prend en entrée la PAIRE (question, chunk) et calcule un score
    de pertinence direct. Plus lent mais beaucoup plus précis.

    Modèle utilisé : `BAAI/bge-reranker-v2-m3` (multilingue, FR natif).
    """
    hybrid = build_hybrid_retriever()
    reranker = ScoringCrossEncoderReranker(model=_get_reranker_model(), top_n=RERANKER_TOP_N)
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


def get_chunks_by_competence(codes: list[str]) -> list[tuple[Document, float]]:
    """Récupère directement les chunks correspondant à des codes compétence.

    Court-circuit du retrieval hybride pour les questions très ciblées
    (ex: "C13 ?" → on a déjà la compétence en clair, pas besoin d'embeddings).

    Avantages :
      - Latence instantanée (pas d'appel Mistral embed, pas de rerank)
      - Pertinence parfaite (on récupère exactement la compétence demandée)
      - Coût zéro (0 token Mistral)

    Args:
        codes: Liste de codes type ["C13", "C19"]. Insensible à la casse.

    Returns:
        Liste (Document, score=1.0) — score à 1.0 car match exact.
        Liste vide si aucune compétence ne matche.
    """
    bm25 = _get_bm25_retriever()
    # Le BM25Retriever LangChain stocke les Documents dans `docs` après .from_documents
    all_docs: list[Document] = getattr(bm25, "docs", [])
    upper_codes = {c.upper() for c in codes}
    matches = [d for d in all_docs if str(d.metadata.get("competence", "")).upper() in upper_codes]
    return [(d, 1.0) for d in matches]


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
def build_chain(prompt_template: str = SYSTEM_PROMPT, temperature: float = 0.0) -> Runnable:
    """Construit la chain RAG : prompt + LLM + parser.

    La chain attend en entrée un dict `{"context": <str>, "question": <str>}`
    (pas la question brute) — le retrieval est délégué à `retrieve_with_scores()`
    appelée AVANT, dans `app.py`.

    Args:
        prompt_template: Template du prompt avec placeholders {context} et {question}.
            Par défaut SYSTEM_PROMPT (analyse de couverture). Pour le mode entretien
            jury, passer JURY_PROMPT — le LLM bascule alors en POSEUR de questions
            au lieu de répondeur.
        temperature: 0 pour analyse factuelle (déterminisme), 0.3-0.5 pour le mode
            jury (un peu de variété dans les questions générées).

    Pourquoi séparer retrieval / chain ?
        Le pipeline hybrid + reranker est lourd (~2-5s en CPU). Si on l'incluait
        dans la chain, chaque message déclencherait DEUX appels au reranker.
        En séparant, on récupère les docs UNE SEULE FOIS dans `app.py` puis on
        les passe à la chain pour la génération. Latence divisée par 2.
    """
    prompt = ChatPromptTemplate.from_template(prompt_template)

    llm = ChatMistralAI(
        model=MISTRAL_LLM_MODEL,
        api_key=MISTRAL_API_KEY,
        temperature=temperature,
    )

    chain: Runnable = prompt | llm | StrOutputParser()
    return chain


def build_jury_chain() -> Runnable:
    """Variante du build_chain() pour le mode entretien jury.

    Utilise JURY_PROMPT (poseur de questions) avec temperature=0.4 pour
    diversifier les questions tout en restant pertinentes.
    """
    return build_chain(prompt_template=JURY_PROMPT, temperature=0.4)
