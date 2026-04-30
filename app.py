"""Interface Chainlit du chatbot RNCP Dev IA.

Chainlit est un framework moderne 2026 spécialisé pour les apps chat LLM.
Avantages clés vs Gradio :
  - Streaming natif (réponse mot par mot)
  - Affichage step-by-step du raisonnement (montre le retrieval en démo)
  - Persistence des threads par session
  - UX chat plus fluide

Pour lancer :
    chainlit run app.py

L'interface est alors accessible sur http://localhost:8000
"""

from __future__ import annotations

import logging

import chainlit as cl
from langchain_core.runnables.config import RunnableConfig

from src.chain import (
    _get_bm25_retriever,
    _get_reranker_model,
    build_chain,
    format_docs,
    retrieve_with_scores,
)
from src.prompts import ERROR_MESSAGE, WELCOME_MESSAGE

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pré-warm au chargement du module : on force le téléchargement et le chargement
# du reranker bge-reranker-v2-m3 (~30s la 1ère fois) AVANT que Chainlit n'accepte
# des messages utilisateur. Sinon le 1er message bloque pendant 30s, ce qui est
# pénible en démo soutenance.
# ---------------------------------------------------------------------------
log.info("🔥 Pré-warming du retriever (reranker + BM25)…")
_get_reranker_model()  # télécharge + charge bge-reranker-v2-m3 en mémoire
_get_bm25_retriever()  # reconstruit BM25 depuis le corpus JSON
log.info("✅ Retriever prêt — Chainlit peut accepter des messages")


# ---------------------------------------------------------------------------
# Démarrage : on initialise le pipeline et on l'attache à la session
# ---------------------------------------------------------------------------
@cl.on_chat_start
async def on_chat_start() -> None:
    """Hook appelé à chaque nouvelle session de chat.

    On construit la chain RAG une fois par session et on la stocke dans
    `cl.user_session` — c'est l'équivalent Chainlit de `gr.State` en Gradio :
    chaque utilisateur a son propre état, pas de fuite entre sessions.
    """
    try:
        chain = build_chain()
    except Exception:
        # On log l'erreur côté serveur, on affiche un message générique côté user
        log.exception("Erreur lors du build de la chain")
        await cl.Message(
            content=(
                "❌ Impossible de démarrer le chatbot. "
                "Vérifie que :\n"
                "1. Qdrant est démarré (`docker compose up qdrant`)\n"
                "2. L'index existe (`uv run python -m src.ingest`)\n"
                "3. Ta clé MISTRAL_API_KEY est dans le fichier `.env`"
            ),
            author="Système",
        ).send()
        return

    # Stockage en session — accessible depuis on_message via cl.user_session.get(...)
    # On garde uniquement la chain : pour les sources on utilise retrieve_with_scores()
    # qui récupère les scores ET les chunks en une seule passe (plus performant).
    cl.user_session.set("chain", chain)

    # Message d'accueil
    await cl.Message(content=WELCOME_MESSAGE, author="Assistant RNCP").send()


# ---------------------------------------------------------------------------
# Réception d'un message : on lance la chain et on stream la réponse
# ---------------------------------------------------------------------------
@cl.on_message
async def on_message(message: cl.Message) -> None:
    """Hook appelé à chaque message envoyé par l'utilisateur."""
    chain = cl.user_session.get("chain")

    if chain is None:
        await cl.Message(content=ERROR_MESSAGE, author="Système").send()
        return

    # Garde-fou : message trop court = on demande plus de détails
    # (évite de gaspiller un appel API pour rien)
    if len(message.content.strip()) < 20:
        await cl.Message(
            content="⚠️ Décris ton projet en au moins 20 caractères pour que je puisse l'analyser correctement.",
            author="Assistant RNCP",
        ).send()
        return

    # 1. Récupérer les chunks AVEC leurs scores de pertinence (cross-encoder)
    # Pipeline complet : BM25 + Qdrant → EnsembleRetriever → CrossEncoder rerank → top 5
    # IMPORTANT : on appelle ça UNE SEULE FOIS, puis on passe les docs à la chain
    # (sinon le pipeline hybrid+rerank serait exécuté deux fois = +5s de latence)
    try:
        docs_with_scores = retrieve_with_scores(message.content)
    except Exception:
        log.exception("Erreur retrieval")
        await cl.Message(content=ERROR_MESSAGE, author="Système").send()
        return

    if not docs_with_scores:
        # Aucun chunk pertinent — la question est probablement hors-sujet
        await cl.Message(
            content=(
                "🤔 Je n'ai trouvé aucun extrait pertinent dans le référentiel pour cette question. "
                "Reformule ou détaille davantage ton projet."
            ),
            author="Assistant RNCP",
        ).send()
        return

    # 2. Préparer le contexte pour le prompt LLM
    # On extrait les Documents (sans les scores) et on les formatte
    docs = [d for d, _ in docs_with_scores]
    context = format_docs(docs)

    # 3. Stream la réponse du LLM
    # On crée un message vide qu'on va enrichir token par token
    answer_msg = cl.Message(content="", author="Assistant RNCP")

    try:
        # cb permet à Chainlit d'afficher le step-by-step (debug en démo)
        cb = cl.LangchainCallbackHandler()
        config = RunnableConfig(callbacks=[cb])

        # La chain attend un dict {"context": ..., "question": ...}
        chain_input = {"context": context, "question": message.content}
        async for chunk in chain.astream(chain_input, config=config):
            await answer_msg.stream_token(chunk)

        await answer_msg.send()
    except Exception:
        log.exception("Erreur génération LLM")
        await cl.Message(content=ERROR_MESSAGE, author="Système").send()
        return

    # 3. Afficher les sources utilisées (extraits du référentiel + scores)
    sources_md = _format_sources_for_display(docs_with_scores)
    await cl.Message(
        content=sources_md,
        author="📚 Sources du référentiel",
    ).send()


# ---------------------------------------------------------------------------
# Helpers d'affichage
# ---------------------------------------------------------------------------
def _format_sources_for_display(docs_with_scores: list) -> str:
    """Formate les chunks récupérés (avec scores) pour affichage utilisateur.

    Le score affiché est la pertinence sigmoidée [0,1] retournée par le
    cross-encoder bge-reranker-v2-m3 (cf. `ScoringCrossEncoderReranker`).
    On l'affiche en pourcentage pour plus de lisibilité — un score brut
    comme 0.5197 est moins parlant que "52% pertinent".
    """
    lines = ["### Extraits utilisés pour cette analyse\n"]
    for i, (doc, score) in enumerate(docs_with_scores, start=1):
        page = doc.metadata.get("page", "?")
        snippet = doc.page_content.strip()
        if len(snippet) > 400:
            snippet = snippet[:400] + "…"
        lines.append(
            f"**Source {i}** — page {page} · *pertinence : {score * 100:.1f}%*\n\n> {snippet}\n"
        )

    return "\n---\n\n".join(lines)
