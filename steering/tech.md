# Tech — chatbot-rncp-dev-ia

> Dernière mise à jour : 2026-04-30

## Stack

| Couche | Choix | Justification |
|--------|-------|---------------|
| **Langage** | Python 3.13 | Standard ML/RAG, écosystème LangChain mature |
| **Pkg manager** | uv 0.9 (Astral) | 10-100× plus rapide que pip, lockfile reproductible (standard 2026) |
| **Framework RAG** | LangChain v0.3 | Standard de l'écosystème, abstractions universelles |
| **LLM** | Mistral `mistral-small-latest` | Sweet spot perf/coût FR, souveraineté EU |
| **Embeddings** | Mistral `mistral-embed` (1024 dim) | Multilingue (FR), cohérent avec le LLM |
| **Vector store** | Qdrant (Docker) | Hybrid search natif, filtres metadata, persistence auto |
| **PDF parsing** | pypdf 5+ | Léger, pure Python |
| **UI** | Chainlit v2 | Spécialisé chat LLM, streaming natif, step-by-step |
| **Tests** | pytest 8 | Standard Python |
| **Lint/format** | Ruff 0.15 | Tout-en-un (remplace black + isort + flake8 + pylint) |
| **CI/CD** | GitHub Actions | Lint + tests sur push/PR (compétence C18 du référentiel cible) |
| **Conteneurisation** | Docker multistage | Image légère (~150 MB), user non-root |

## Contraintes

- **Souveraineté FR/EU** : pas de dépendance OpenAI/Anthropic (argument soutenance)
- **Coût maîtrisé** : Mistral free tier ou crédit existant (~quelques centimes pour 200 chunks)
- **RGPD** : pas d'envoi de données à OpenAI/Anthropic
- **Démo soutenance** : tourner en local, latence < 5s, pas de blocage réseau
- **Pédagogie** : code défendable ligne par ligne (pas d'abstraction excessive)

## Intégrations externes

| Service | Usage | Authentification |
|---------|-------|-----------------|
| Mistral API | LLM + embeddings | Bearer token via `MISTRAL_API_KEY` (.env) |
| Qdrant | Vector store | URL locale (Docker compose), pas d'auth en dev |

## Conventions

- ES modules-style imports (`from x import y`, jamais `from x import *`)
- `from __future__ import annotations` en haut de chaque module
- Docstrings sur chaque fonction publique (Google style ou simple)
- Variables d'env centralisées dans `src/config.py`
- Commits en français/anglais, focus sur le pourquoi
- Pas de `print()` en prod — utiliser `logging`
- Annotations de types partout (`def foo(x: int) -> str`)

## Architecture

```
PDF → Loader (pypdf) → Splitter → Embeddings (Mistral) → Qdrant
                                                            │
Question utilisateur → Retriever (k=4) → Prompt → Mistral LLM → Réponse
                              │
                              └─ Sources affichées dans Chainlit
```

## Décisions prises

| Date | Décision | Justification |
|------|----------|---------------|
| 2026-04-30 | LLM = `mistral-small-latest` (pas OpenAI) | Crédit Mistral existant, FR natif, souveraineté EU |
| 2026-04-30 | UI = Chainlit (pas Gradio imposé) | Autorisé par formateur, plus moderne pour chat LLM |
| 2026-04-30 | Vector store = Qdrant (pas FAISS du brief) | Filtres metadata + persistence auto + dashboard utile en démo |
| 2026-04-30 | Embeddings = `mistral-embed` (pas bge-m3) | Cohérence stack Mistral, FR natif |
| 2026-04-30 | Pas d'Ollama (pas installé) | Mistral API suffit, +simple en démo |

## MCP Servers recommandés

| Serveur | Usage | Installé ? |
|---------|-------|------------|
| Context7 | Doc officielle libs (LangChain, Chainlit, Qdrant) | oui (global) |
| GitHits | Patterns d'implémentation réels | oui (global) |
| Docfork | Doc libs versionnée | oui (global) |
| GitHub MCP | PRs, issues | oui (gh installé) |

## Environnements

| Env | URL | Notes |
|-----|-----|-------|
| Production (démo soutenance) | localhost:8000 | Chainlit en local |
| Local dev | localhost:8000 + qdrant 6333 | docker compose up qdrant |
| CI | GitHub Actions runners | tests unitaires only (pas d'appel Mistral) |
