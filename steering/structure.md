# Structure — chatbot-rncp-dev-ia

> Dernière mise à jour : 2026-04-30

## Arborescence

```
chatbot-referentiel-formation/
├── pyproject.toml          # Deps + config Ruff + pytest
├── uv.lock                 # Lockfile reproductible
├── .python-version         # Pin Python 3.13
├── .gitignore              # Exclut .env, qdrant_storage, etc.
├── .dockerignore           # Exclut secrets et caches de l'image
├── .env.example            # Template config
├── README.md               # Doc utilisateur
├── CLAUDE.md               # Architecture technique (pour Claude Code)
├── data/                   # Référentiel PDF (à fournir, ignoré par git)
├── src/                    # Code applicatif
│   ├── __init__.py
│   ├── config.py           # Chargement .env + constantes RAG
│   ├── prompts.py          # Prompts système (analyse + accueil + erreur)
│   ├── ingest.py           # Pipeline indexation (Load → Split → Embed → Store)
│   └── chain.py            # Pipeline RAG LangChain (Retriever → Prompt → LLM)
├── app.py                  # Interface Chainlit (à la racine, convention Chainlit)
├── tests/                  # Tests unitaires
│   ├── __init__.py
│   └── test_ingest.py      # Tests sur les fonctions pures (split, métadonnées)
├── .github/workflows/ci.yml # Lint Ruff + tests pytest
├── .claude/                # Config Claude Code (spécifique à ce projet)
│   ├── CLAUDE.md           # Instructions Claude
│   ├── agents/             # product-owner, tech-lead
│   └── rules/              # tests.md
├── steering/               # Documents de cadrage
│   ├── product.md          # Vision, personas
│   ├── tech.md             # Stack, contraintes, décisions
│   └── structure.md        # Ce fichier
├── tasks/                  # PRDs et specs (à créer via /prd)
├── vault/                  # Capture auto (idées, décisions, insights)
│   ├── ideas/
│   ├── decisions/
│   ├── insights/
│   ├── research/
│   ├── journal/
│   ├── questions/
│   └── inbox/
├── Dockerfile              # Multistage (builder + runtime)
└── docker-compose.yml      # App + Qdrant orchestrés
```

## Conventions de nommage

| Élément | Convention | Exemple |
|---------|-----------|---------|
| Fichiers Python | snake_case | `test_ingest.py`, `chain.py` |
| Fonctions / variables | snake_case | `build_chain`, `chunk_size` |
| Classes | PascalCase | `MistralAIEmbeddings` |
| Constantes | UPPER_SNAKE_CASE | `CHUNK_SIZE`, `MISTRAL_API_KEY` |
| Modules privés | `_underscore` | `_get_vector_store`, `_required_env` |
| Branches git | `type/description` | `feat/hybrid-search`, `fix/qdrant-connection` |
| Commits | description claire | `Initial scaffold — RAG pipeline` |

## Patterns

### Configuration centralisée
Toutes les variables d'environnement sont chargées dans `src/config.py` au démarrage. Le code applicatif importe les constantes typées (pas `os.getenv()` direct).

### Fail-fast au démarrage
`config.py` lève une `RuntimeError` claire si une variable obligatoire manque (ex: `MISTRAL_API_KEY`). Plutôt qu'un crash bizarre au premier appel API.

### Séparation pipeline / UI
- `src/chain.py` : tout le RAG, testable indépendamment
- `app.py` : juste la couche Chainlit, pas de logique métier
- → Permet de swap Chainlit pour Gradio ou FastAPI sans toucher au RAG

### Pipeline LCEL (LangChain Expression Language)
Composer les composants avec l'opérateur `|` à la Unix pipe :
```python
chain = retriever | format_docs | prompt | llm | parser
```

### Tests sur fonctions pures uniquement (MVP)
Tester `split_documents` : oui (pas d'appel externe).
Tester `build_chain` : non (nécessite Mistral + Qdrant). Hors scope MVP — à faire en Phase 3 avec RAGAS.

## Points d'attention

- **Le PDF n'est jamais commité** (`.gitignore` exclut `data/*.pdf`) — droits d'auteur Simplon
- **Le `.env` n'est jamais commité** ni inclus dans l'image Docker — sécurité
- **L'index Qdrant n'est jamais commité** (`qdrant_storage/`) — peut être volumineux + reconstructible
- **Lancer `uv run python -m src.ingest` UNE fois** avant le premier `chainlit run`
- **Qdrant doit tourner** avant de lancer Chainlit (`docker compose up qdrant -d`)
- **Le prompt système est UN levier critique** — itérer dessus en testant 3-5 projets de référence
