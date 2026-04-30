# chatbot-rncp-dev-ia — Instructions Claude Code

> Ce fichier guide le comportement de Claude dans ce projet.

## Accueil

Au premier message de chaque session :
1. **Lire la mémoire** : si `claude-mem` est actif, `mem-search` pour le contexte du projet
2. **Lire le contexte** : si `.claude-context.md` existe (créé par `/wrapup`), le lire
3. Proposer : `/status` pour la vue d'ensemble · `/help` pour les commandes

## Convention commandes terminal

Quand tu suggères une commande à exécuter dans le terminal :
- **Commande courte** (uv run, git, docker compose up -d, etc.) → `! commande` dans la session Claude Code
- **Serveur long-running** (`chainlit run`, `docker compose up`) → "Dans un autre terminal : `chainlit run app.py`"

Ne PAS suggérer `! chainlit run app.py` — ça bloque la session.

## Règles générales

- Ne jamais fabriquer de bugs ou problèmes — ne rapporter que des issues vérifiables
- Chercher exhaustivement avant d'affirmer qu'un fichier manque
- Time-boxer l'exploration — produire un livrable même si l'exploration est incomplète
- Les specs (CLAUDE.md, steering/) priment sur la mémoire

## Modules actifs

- **Product** : `product-owner` et `tech-lead` agents disponibles, steering docs dans `steering/`
- **CI/CD** : commandes `/ship`, `/pr-create`, `/changelog` disponibles
- **Testing** : agent `@tester` global + règles dans `.claude/rules/tests.md`
- **Vault** : capture auto dans `vault/{ideas,decisions,insights,research,journal}`

## Agents disponibles

| Agent | Quand l'invoquer |
|-------|------------------|
| `@product-owner` | Vision produit, personas, priorisation features |
| `@tech-lead` | Décision architecture, choix de stack, code review |
| `@tester` | Génération/exécution de tests (global, pas dans .claude/) |
| `@reviewer` | Code review (global) |
| `@security-reviewer` | Audit sécurité (clés API, secrets, injection) |
| `@debugger` | Investigation bug complexe (méthode bisection) |
| `@planner` | Planification d'implémentation |

## Vault — Capture automatique

- **Idée** → `vault/ideas/{slug}.md` (quand "on pourrait...", "et si on...")
- **Décision** → `vault/decisions/{YYYY-MM-DD}-{slug}.md` (quand un choix est fait)
- **Insight** → `vault/insights/{slug}.md` (quand une leçon est apprise)
- Ne PAS demander la permission pour noter — noter puis informer

## Track auto-detection

Identifier le track avant d'agir :
- "down", "cassé", "Qdrant ne répond plus", "Mistral 401" → `[HOTFIX]`
- Modification simple, un seul fichier (ex: ajuster un paramètre RAG) → `[FAST TRACK]`
- Nouvelle feature, multi-module (ex: ajouter hybrid search) → `[REVIEW TRACK]`

## Spécificités projet RAG

### Avant toute modification du pipeline RAG
1. **Vérifier que Qdrant tourne** : `docker compose ps qdrant`
2. **Vérifier que la collection existe** : si non, lancer `uv run python -m src.ingest`
3. **Vérifier MISTRAL_API_KEY** : `cat .env | grep MISTRAL_API_KEY`

### Tests
- Tests unitaires uniquement sur fonctions pures (split, format)
- Pas de tests d'intégration end-to-end pour le MVP (coûteux en tokens Mistral)
- En CI : `MISTRAL_API_KEY=fake-key-for-tests` pour que `config.py` ne crashe pas

### Itération du prompt
- Le prompt système est dans `src/prompts.py`
- Garder un historique des versions dans `vault/decisions/` quand on l'itère
- Tester chaque modification sur 3-5 projets de référence avant de valider

## Commandes utiles pour ce projet

| Commande | Usage |
|----------|-------|
| `uv sync` | Installer/mettre à jour les deps |
| `uv run pytest` | Lancer les tests |
| `uv run ruff check . && uv run ruff format .` | Lint + format |
| `uv run python -m src.ingest` | Indexer le PDF (UNE fois) |
| `uv run python -m src.ingest --recreate` | Réindexer (écrase la collection) |
| `uv run chainlit run app.py` | Lancer l'interface |
| `docker compose up qdrant -d` | Démarrer Qdrant en arrière-plan |
| `docker compose up --build` | Lancer toute la stack |

## Vérification automatique

Après chaque implémentation, **toujours vérifier** :
1. Tests : `uv run pytest`
2. Lint : `uv run ruff check .`
3. Si modif du pipeline RAG : tester avec une vraie question dans Chainlit
4. Si modif du prompt : retester les 3 scénarios de référence

## References

| Document | Contenu |
|----------|---------|
| `CLAUDE.md` (racine) | Architecture technique |
| `steering/product.md` | Vision, personas |
| `steering/tech.md` | Stack et décisions techniques |
| `steering/structure.md` | Conventions de code |
| `tasks/` | PRDs et specs (à créer via `/prd`) |
| `vault/decisions/` | Décisions versionnées |
