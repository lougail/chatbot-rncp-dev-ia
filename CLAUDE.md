# chatbot-rncp-dev-ia — Architecture

> Auto-généré par /init le 2026-04-30. Mettre à jour quand l'architecture change.

## Description

Chatbot RAG analysant la couverture du référentiel RNCP "Développeur en intelligence artificielle" (titre 2023, Simplon) par un projet décrit en langage naturel. L'utilisateur décrit son projet en français, le système identifie les compétences couvertes parmi les 21 du référentiel (C1-C21), avec citations textuelles.

## Stack

| Couche | Techno | Justification |
|--------|--------|---------------|
| **Langage** | Python 3.13 | Standard ML/RAG |
| **Pkg manager** | uv 0.9 (Astral) | 10-100× plus rapide que pip, lockfile reproductible |
| **Pipeline RAG** | LangChain v0.3 | Standard de l'écosystème, abstractions universelles |
| **LLM** | Mistral `mistral-small-latest` | FR natif, souveraineté EU, coût maîtrisé |
| **Embeddings** | Mistral `mistral-embed` (1024 dim) | Multilingue (FR), cohérent avec le LLM |
| **Vector store** | Qdrant (Docker) | Hybrid search natif, filtres metadata, persistence auto |
| **PDF parsing** | pypdf | Léger, pure Python |
| **UI** | Chainlit v2 | Spécialisé chat LLM, streaming natif |
| **Tests** | pytest | Standard Python |
| **Lint/format** | Ruff | Tout-en-un (remplace black + isort + flake8) |
| **CI** | GitHub Actions | Lint + tests sur push/PR (compétence C18) |
| **Conteneurisation** | Docker multistage | Image légère, user non-root |

## Structure

```
chatbot-referentiel-formation/
├── pyproject.toml          # Deps + config Ruff + pytest
├── uv.lock                 # Lockfile
├── .python-version         # 3.13
├── .env.example            # Template config (MISTRAL_API_KEY, QDRANT_URL, etc.)
├── data/                   # PDF du référentiel (à fournir)
├── src/
│   ├── config.py           # Chargement .env + constantes RAG
│   ├── prompts.py          # Prompt système (analyse + accueil + erreur)
│   ├── ingest.py           # Pipeline indexation : Load → Split → Embed → Store
│   └── chain.py            # Pipeline RAG LangChain : Retriever → Prompt → LLM
├── app.py                  # Interface Chainlit
├── tests/test_ingest.py    # Tests unitaires (split, métadonnées)
├── .github/workflows/ci.yml # Lint + tests
├── Dockerfile              # Multistage (builder + runtime, user non-root)
└── docker-compose.yml      # App + Qdrant orchestrés
```

## Communication entre modules

```
PDF → ingest.py (1×) → Qdrant (collection "referentiel_rncp")
                         │
                         │ chargé par
                         ▼
            chain.py.build_chain() ── LCEL ──┬── retriever (Qdrant)
                         │                    │
                         │                    └── ChatMistralAI (mistral-small-latest)
                         │
                         │ utilisé par
                         ▼
                       app.py (Chainlit)
                         │
                         │ stream + sources
                         ▼
                    Browser localhost:8000
```

## Conventions

- ES modules-style imports (Python `from x import y`, jamais `import *`)
- Docstrings sur chaque fonction publique (style Google ou simple)
- `from __future__ import annotations` en haut de chaque module Python
- Variables d'env via `src.config` (jamais `os.getenv()` éparpillés)
- Commits en français/anglais, focus sur le pourquoi
- Tests unitaires sur fonctions pures uniquement (mocks pour Mistral/Qdrant)

## Flux critiques

### Indexation (faite UNE fois)

```
data/*.pdf
  → load_pdf()           # pypdf : un Document par page
  → split_documents()    # RecursiveCharacterTextSplitter (chunk=512, overlap=80)
  → build_vector_store() # MistralAIEmbeddings + QdrantVectorStore.add_documents
```

### Requête utilisateur

```
question utilisateur
  → retriever (similarity_score_threshold, k=4, threshold=0.4)
  → format_docs (concat avec page numbers)
  → ChatPromptTemplate (SYSTEM_PROMPT + context + question)
  → ChatMistralAI (temperature=0)
  → StrOutputParser
  → réponse markdown structurée
  + affichage des sources dans Chainlit
```

## Paramètres RAG (justifiables en soutenance)

| Param | Valeur | Pourquoi |
|-------|--------|----------|
| `chunk_size` | 512 | Sweet spot 2026 |
| `chunk_overlap` | 80 (~15%) | Préserve contexte aux frontières |
| `k` | 4 | Compromis pertinence/dilution |
| `score_threshold` | 0.4 | Anti-hallucination (questions hors-sujet → réponse vide) |
| `temperature` | 0 | Déterminisme, anti-hallucination créative |
