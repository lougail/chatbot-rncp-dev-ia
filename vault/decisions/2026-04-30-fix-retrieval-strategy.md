# Décision — Stratégie de fix du retrieval

> **Date** : 2026-04-30
> **Statut** : 🟡 En attente de validation par Louis
> **Contexte** : Régression du retrieval après swap pypdf → PyMuPDF. Le LLM rate les compétences C5/C13/C18/C19/C20 et fait un faux match C6.

---

## Le problème en une phrase

L'embedding `mistral-embed` seul + chunking générique ne discrimine pas les 21 compétences RNCP : tous les chunks ont des scores cosinus dans une fenêtre de 0.022, ce qui les rend indistinguables.

## Options évaluées (synthèse 2 agents de recherche)

### Option 1 — Quick fix : k=4 → k=8
- ✅ 5 secondes d'effort
- ❌ Pas de fond, le LLM se "noie" plus
- ❌ Ne traite pas le vrai problème
- **Verdict** : non, c'est un sparadrap

### Option 2 — Splitter custom seul
- ✅ Élimine la fragmentation des compétences
- ❌ Ne résout pas le manque de discrimination de mistral-embed
- **Verdict** : nécessaire mais pas suffisant

### Option 3 — Hybrid Search (BM25 + Dense) seul
- ✅ BM25 capture les mots-clés littéraux (FastAPI, Docker)
- ✅ Compense la faiblesse de mistral-embed sur les codes
- ⚠️ Sans rerank, les top-k peuvent être bruités
- **Verdict** : nécessaire mais pas suffisant

### Option 4 — Reranker seul
- ✅ Affine la pertinence des top-k
- ❌ Si le retrieval initial est mauvais, le reranker ne peut rien faire
- **Verdict** : nécessaire mais pas suffisant

### Option 5 (RECOMMANDÉE) — Pattern triplet 2026 ⭐
**Splitter custom + Hybrid Search + Reranker** combinés.
- ✅ Couvre les 3 problèmes diagnostiqués
- ✅ Pattern dominant en production 2026 (consensus 2 agents)
- ✅ Argument soutenance fort (3 décisions techniques justifiables avec benchmarks)
- ⚠️ Effort ~1-2h, latence reranker +1.5-3s
- **Verdict** : ✅ on y va

---

## Décisions techniques actées

### 1. Splitter

**Choix** : split manuel via regex `^C\d+\.\s` (Option B agent 2)

**Raison** : garantit 21 chunks identifiables, chacun avec metadata `competence` exploitable pour filtres et citations.

```python
import re
from langchain_core.documents import Document

PATTERN = re.compile(r"(?=^C\d+\.\s)", re.MULTILINE)

def split_competences(full_text: str, source: str) -> list[Document]:
    parts = [p.strip() for p in PATTERN.split(full_text) if p.strip()]
    docs = []
    for part in parts:
        m = re.match(r"^(C\d+)\.", part)
        if not m:
            continue
        docs.append(Document(
            page_content=part,
            metadata={"source": source, "competence": m.group(1)},
        ))
    return docs
```

### 2. Hybrid Retriever

**Choix** : `EnsembleRetriever(BM25 + Qdrant)` avec poids `[0.4, 0.6]`

**Raisons** :
- BM25 capture les mots-clés littéraux ("FastAPI", "Docker", "C5") que mistral-embed rate
- Pondération 0.4/0.6 : consensus des 2 agents et patterns GitHub réels
- `k=20` par retriever pour donner à manger au reranker

**Persistence BM25** : on sérialise le corpus de Documents en **JSON** (pas pickle, pour sécurité + portabilité) pour reconstruction au démarrage.

### 3. Reranker

**Choix** : `CrossEncoderReranker(BAAI/bge-reranker-v2-m3, top_n=5)`

**Raisons** :
- Multilingue avec excellent FR (notre PDF est en FR)
- Standard 2026 pour le rerank multilingue
- Latence acceptable (~2s en CPU pour 20 candidats)
- Open-source = aligné argument souveraineté du projet

**Singleton** : instancié au niveau module (chargé une fois au startup), pas par message.

**Pré-warm Docker** : ajouter une étape `RUN python -c "..."` dans le Dockerfile pour télécharger le modèle en build time.

### 4. Hyperparamètres (figés pour MVP, ajustables ensuite)

| Param | Valeur | Justification |
|-------|--------|---------------|
| `chunk_size` | N/A (split par compétence) | Garantit 1 chunk = 1 compétence |
| `k` (retriever) | 20 | Pool large avant rerank |
| `weights` (Ensemble) | [0.4, 0.6] | Consensus 2 agents |
| `top_n` (reranker) | 5 | Compromis qualité/latence |
| `score_threshold` | Conservé à 0.4 | Anti-hallucination |
| `temperature` (LLM) | 0 | Inchangé |

### 5. Métriques de succès post-implémentation

- ✅ Sur le prompt FastAPI/Docker/CI/CD/Monitoring, identifier au moins **C5, C11, C13, C18, C19, C20** (vs C6+C11 actuel)
- ✅ Écart de score top-1 / top-2 > 0.05 (vs 0.022 actuel)
- ✅ Pas de faux match C6 sur "GitHub Actions = veille technique"
- ✅ Tests pytest passent (3/3)
- ✅ Latence par message < 5s (P95)

## Plan d'implémentation

| Étape | Effort | Modifie |
|-------|--------|---------|
| 1. Refactor `src/ingest.py` : split par regex + corpus BM25 en JSON | 20 min | `src/ingest.py` |
| 2. Refactor `src/chain.py` : Ensemble + Reranker (singleton) | 20 min | `src/chain.py` |
| 3. Vérifier deps : `rank-bm25`, `sentence-transformers` (déjà présents ?) | 1 min | `pyproject.toml` |
| 4. Réindexer Qdrant + générer corpus BM25 | 1 min | runtime |
| 5. Redémarrer Chainlit | 1 min | runtime |
| 6. Re-tester via dev-browser sur 3 prompts | 5 min | runtime |
| **Total** | **~50 min** | |

## Validation requise par Louis

- [ ] OK pour le pattern triplet (Splitter + Hybrid + Rerank) ?
- [ ] OK pour `bge-reranker-v2-m3` malgré la latence (1.5-3s) vs `bge-reranker-base` (~0.5s) ?
- [ ] OK pour les hyperparamètres figés au démarrage (ajustables ensuite) ?
