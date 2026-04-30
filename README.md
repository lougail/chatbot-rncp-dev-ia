# 🎓 Chatbot RNCP Dev IA — Analyse de couverture de compétences

> Chatbot RAG analysant la couverture du référentiel RNCP "Développeur en intelligence artificielle" (titre 2023, Simplon) par un projet décrit en langage naturel.

[![CI](https://github.com/lougail/chatbot-rncp-dev-ia/actions/workflows/ci.yml/badge.svg)](https://github.com/lougail/chatbot-rncp-dev-ia/actions/workflows/ci.yml)
![Python 3.13](https://img.shields.io/badge/python-3.13-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)

---

## 📋 Table des matières

- [Le problème](#-le-problème)
- [Architecture RAG](#️-architecture-rag)
- [Stack technique](#-stack-technique)
- [Installation](#-installation)
- [Utilisation](#-utilisation)
- [Exemples de questions](#-exemples-de-questions)
- [Structure du projet](#-structure-du-projet)
- [Justifications techniques (soutenance)](#-justifications-techniques-soutenance)
- [Auteur](#-auteur)

---

## ❓ Le problème

Chez Simplon, formateurs et apprenants se posent régulièrement la même question :

> *"Mon projet couvre-t-il bien les compétences du référentiel RNCP Dev IA ?"*

Aujourd'hui, répondre demande de relire manuellement **62 pages de référentiel**, retrouver les critères d'évaluation par compétence, et les comparer avec ce que le projet implémente. C'est long, subjectif, et souvent fait à la dernière minute.

**Solution** : un assistant conversationnel qui analyse un projet décrit en langage naturel et identifie précisément les compétences couvertes, à approfondir, ou manquantes — avec citations textuelles du référentiel.

---

## 🏗️ Architecture RAG

Le système repose sur une architecture **RAG** (Retrieval Augmented Generation) classique :

```
┌────────────────────────────────────────────────────────────────┐
│  PHASE D'INDEXATION (faite UNE fois — script src/ingest.py)    │
└────────────────────────────────────────────────────────────────┘

   Référentiel PDF (62 pages)
            │
            ▼
   ┌──────────────────┐
   │  1. LOAD         │  pypdf — extraction texte page par page
   └──────────────────┘
            │
            ▼
   ┌──────────────────┐
   │  2. SPLIT        │  RecursiveCharacterTextSplitter
   │                  │  chunk_size=512, overlap=80
   └──────────────────┘
            │
            ▼
   ┌──────────────────┐
   │  3. EMBED        │  Mistral embed (1024 dim, multilingue FR)
   └──────────────────┘
            │
            ▼
   ┌──────────────────┐
   │  4. STORE        │  Qdrant — vector store persistant
   └──────────────────┘


┌────────────────────────────────────────────────────────────────┐
│  PHASE DE REQUÊTE (à chaque question utilisateur)              │
└────────────────────────────────────────────────────────────────┘

   Question utilisateur
            │
            ▼
   ┌──────────────────┐
   │  5. RETRIEVE     │  similarité cosinus, k=4, threshold=0.4
   └──────────────────┘
            │
            ▼
   ┌──────────────────┐
   │  6. AUGMENT      │  Prompt système + 4 chunks injectés
   └──────────────────┘
            │
            ▼
   ┌──────────────────┐
   │  7. GENERATE     │  Mistral Small (temperature=0)
   └──────────────────┘
            │
            ▼
   Réponse structurée + sources affichées dans Chainlit
```

---

## 🛠️ Stack technique

| Composant | Choix | Justification |
|-----------|-------|---------------|
| **Langage** | Python 3.13 | Standard ML/RAG |
| **Pkg manager** | `uv` 0.9 (Astral) | 10-100× plus rapide que pip, lockfile reproductible (standard 2026) |
| **Pipeline RAG** | LangChain v0.3 | Standard de l'écosystème RAG, abstractions universelles |
| **LLM** | Mistral `mistral-small-latest` | Excellent en français, souveraineté européenne, coût maîtrisé |
| **Embeddings** | Mistral `mistral-embed` | Multilingue (FR), 1024 dim, cohérent avec le LLM |
| **Vector store** | Qdrant (Docker) | Hybrid search natif, filtres metadata, alternative pro à FAISS |
| **PDF parsing** | pypdf | Léger, pure Python, suffisant pour PDF textuel |
| **UI** | Chainlit v2 | Framework moderne 2026 spécialisé chat LLM, streaming natif |
| **Tests** | pytest | Standard Python |
| **Lint/format** | Ruff | Tout-en-un (remplace black + isort + flake8 + pylint) |
| **CI** | GitHub Actions | Lint + tests sur chaque push/PR (compétence C18 du référentiel) |
| **Conteneurisation** | Docker multistage | Image légère (~150 MB), user non-root |

---

## 🚀 Installation

### Pré-requis

- Python 3.13 (`python --version`)
- [uv](https://docs.astral.sh/uv/) 0.9+ (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Docker 24+ (`docker --version`)
- Une clé API Mistral ([console.mistral.ai](https://console.mistral.ai/api-keys))
- Le PDF du référentiel RNCP Dev IA placé dans `data/`

### Étape 1 — Cloner et installer les deps

```bash
git clone https://github.com/lougail/chatbot-rncp-dev-ia.git
cd chatbot-rncp-dev-ia
uv sync
```

### Étape 2 — Configurer les secrets

```bash
cp .env.example .env
# Édite .env et renseigne MISTRAL_API_KEY
```

### Étape 3 — Démarrer Qdrant

```bash
docker compose up qdrant -d
```

Le dashboard Qdrant est accessible sur http://localhost:6333/dashboard.

### Étape 4 — Indexer le référentiel

Place le PDF du référentiel dans `data/` (n'importe quel nom finissant par `.pdf`), puis :

```bash
uv run python -m src.ingest
```

Cette opération prend ~30 secondes. Elle ne doit être faite **qu'une fois** (sauf si le référentiel change, ajouter `--recreate`).

### Étape 5 — Lancer l'app

```bash
uv run chainlit run app.py
```

L'interface est accessible sur **http://localhost:8000**.

### Alternative : tout-en-un avec Docker Compose

```bash
docker compose up --build
```

---

## 💬 Utilisation

Décris ton projet en langage naturel dans le chat. L'assistant :

1. Récupère les **extraits pertinents** du référentiel (top-4 par similarité)
2. Analyse la **couverture** des 21 compétences
3. Retourne une réponse **structurée** :
   - ✅ Compétences validées (avec extrait justificatif)
   - ⚠️ Compétences à approfondir
   - ❌ Compétences non couvertes
   - Synthèse par bloc (Données / Modèles IA / Application)
4. Affiche les **sources** utilisées sous la réponse

---

## 🎯 Exemples de questions

```
Mon projet déploie une API FastAPI avec Docker et un pipeline GitHub Actions.
Quelles compétences RNCP couvre-t-il ?
```

```
La compétence C13 est-elle validée si j'ai seulement un Dockerfile sans CI/CD ?
```

```
J'ai entraîné un modèle de classification avec MLflow et mis en place du
monitoring Prometheus. Quelles compétences me manquent pour valider le bloc 2 ?
```

> 📋 **3 scénarios de test détaillés** (avec compétences attendues et plan B en cas de souci)
> sont documentés dans [`docs/scenarios-demo.md`](docs/scenarios-demo.md) — utilisés pour la
> démonstration live en soutenance.

---

## 📁 Structure du projet

```
chatbot-referentiel-formation/
├── pyproject.toml              # Deps + config Ruff + pytest
├── uv.lock                     # Lockfile reproductible
├── .python-version             # Pin Python 3.13
├── .gitignore                  # Inclut .env, qdrant_storage, etc.
├── .dockerignore               # Exclut secrets et caches de l'image
├── .env.example                # Template de configuration
├── ruff.toml                   # (config dans pyproject.toml)
├── README.md                   # Ce fichier
├── data/                       # Référentiel PDF (à fournir)
├── src/
│   ├── __init__.py
│   ├── config.py               # Chargement .env + constantes RAG
│   ├── prompts.py              # Prompts système (analyse + accueil)
│   ├── ingest.py               # Pipeline d'indexation Load → Split → Embed → Store
│   └── chain.py                # Pipeline RAG LangChain (Retriever → Prompt → LLM)
├── app.py                      # Interface Chainlit
├── tests/
│   ├── __init__.py
│   └── test_ingest.py          # Tests unitaires du splitter
├── .github/workflows/
│   └── ci.yml                  # Lint Ruff + tests pytest
├── Dockerfile                  # Multistage (builder + runtime, user non-root)
└── docker-compose.yml          # App + Qdrant orchestrés
```

---

## 🎓 Justifications techniques (soutenance)

### Pourquoi RAG plutôt que long context ou agentic search ?

- **Long context** (Gemini 2M tokens) : ~20s de latence, ~1250× plus cher que RAG, recall multi-fact plafonne à ~60% sur RULER. Pour 62 pages consultées 100 fois, RAG est imbattable en coût/latence.
- **Agentic search** (style Claude Code) : pertinent pour du code structuré accessible via grep, pas pour un PDF narratif privé.
- **Pour ce cas** : RAG offre des **citations exactes** (exigées par le brief), une latence sub-seconde, et une indépendance totale vis-à-vis d'un LLM cloud à grand contexte.

### Paramètres RAG

| Paramètre | Valeur | Justification |
|-----------|--------|---------------|
| `chunk_size` | 512 | Sweet spot 2026 — assez de contexte, pas de dilution |
| `chunk_overlap` | 80 (~15%) | Préserve le contexte aux frontières des chunks |
| `k` | 4 | Compromis pertinence/dilution |
| `score_threshold` | 0.4 | Garde-fou anti-hallucination — questions hors-sujet → réponse vide |
| `temperature` | 0 | Déterminisme + zéro hallucination créative |

### Pourquoi Qdrant et pas FAISS ?

- ✅ Filtres metadata riches (utile si on étend à plusieurs référentiels)
- ✅ Persistence native (pas de save/load manuel)
- ✅ Hybrid search natif (préparé pour Phase 2 : BM25 + dense)
- ✅ Dashboard intégré (utile en démo : montrer les vecteurs stockés)
- vs FAISS : meilleur pour très grande échelle (millions+) mais pauvre fonctionnellement

### Pourquoi Chainlit et pas Gradio ?

- Streaming natif (réponse mot par mot)
- Step-by-step du raisonnement (montre le retrieval en démo live)
- Persistence des threads par session
- UX chat plus moderne

### Évolutions possibles (Phase 2-3)

- **Hybrid search** BM25 + dense via `EnsembleRetriever`
- **Reranker** `bge-reranker-v2-m3` pour Recall@5 0.70 → 0.82
- **Contextual Retrieval** (Anthropic 2024) : réduit les échecs de retrieval de -49%
- **RAGAS** sur golden set de 30 Q/R pour mesurer chaque upgrade
- **Mini-graphe LangGraph** routant entre tools structurés (codes C13) et RAG sémantique

---

## 🧪 Tests

```bash
# Lancer les tests unitaires
uv run pytest

# Lint + format check (CI)
uv run ruff check .
uv run ruff format --check .
```

---

## 👤 Auteur

**Louis Gaillard** — Apprenant Simplon Dev IA (titre 2023)

- 📧 louis.gaillard94@gmail.com
- Formation : [Développeur en intelligence artificielle, Simplon](https://simplon.co)

---

## 📄 Licence

MIT — voir `LICENSE` (à ajouter)
