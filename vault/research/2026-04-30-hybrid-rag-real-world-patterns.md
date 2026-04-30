# Recherche complémentaire — Patterns RAG hybride réels (2026)

> **Date** : 2026-04-30
> **Sources** : recherche via `mcp__github__search_code` (repos open-source 2025-2026) + `mcp__docfork__search_docs` (LangChain v0.3)
> **Complément à** : `2026-04-30-fix-retrieval-strategy.md` (recherche context7 / docfork)

---

## Différences clés vs rapport 1

### 1. Splitter : Option B > Option A (split manuel par regex)

L'agent 2 recommande **NE PAS** utiliser `RecursiveCharacterTextSplitter(is_separator_regex=True)` :

> "Garantit exactement 21 chunks (audit/test trivial : `assert len(docs) == 21`)"

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
            continue  # texte avant C1 (préambule) ignoré
        code = m.group(1)
        docs.append(Document(
            page_content=part,
            metadata={"source": source, "competence": code},
        ))
    return docs
```

**Avantage** : metadata `competence: "C5"` injectée → filtrage Qdrant possible (`filter={"competence": "C7"}`).

### 2. BM25 persistence : sérialiser le CORPUS en JSON, pas le retriever

```python
import json

# À l'ingestion : sauvegarder uniquement les Documents (JSON safe, pas pickle)
data = [{"page_content": d.page_content, "metadata": d.metadata} for d in documents]
BM25_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))

# Au démarrage de l'app : reconstruire BM25 from scratch (~50ms)
data = json.loads(BM25_PATH.read_text())
corpus = [Document(page_content=d["page_content"], metadata=d["metadata"]) for d in data]
bm25 = BM25Retriever.from_documents(corpus, k=20)
```

> "Ne **jamais** sérialiser le `BM25Retriever` lui-même, seulement le corpus."

JSON > pickle pour 3 raisons : (1) lisible (debug facile), (2) portable entre versions Python, (3) pas de risque d'exécution de code arbitraire.

### 3. Reranker : bge-reranker-v2-m3 vs bge-reranker-base

| Modèle | Taille | Latence CPU 20 candidats | Multilingue FR |
|--------|--------|--------------------------|----------------|
| `bge-reranker-v2-m3` | 1.1 GB | **1.5-3s** | ✅ excellent |
| `bge-reranker-base` | 280 MB | ~0.5-1s | ⚠️ moins bon |

→ **Pour notre cas (FR)** : on garde `v2-m3` car l'écart de qualité FR justifie la latence.

### 4. Singleton du modèle (perf)

> "Sur Chainlit, lance le download avant `cl.on_chat_start` (sinon le premier message bloque 30s). Mets l'instanciation `HuggingFaceCrossEncoder()` au niveau module (singleton)."

→ Critique pour la démo soutenance.

### 5. HF cache pour Docker

```dockerfile
# Pré-télécharge le reranker dans l'image (évite 30s au 1er run)
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('BAAI/bge-reranker-v2-m3')"
```

## TL;DR — synthèse des 2 rapports

```
INGESTION (1 fois)
  PDF
   → split_competences() regex (~21 chunks)
   → metadata.competence = "C5"
   → QdrantVectorStore.add_documents()
   → JSON dump du corpus pour BM25

APP STARTUP (cl.on_chat_start)
  → load JSON → BM25Retriever.from_documents(k=20)
  → qdrant.as_retriever(k=20)
  → EnsembleRetriever(weights=[0.4, 0.6])
  → wrap dans ContextualCompressionRetriever(
        compressor=CrossEncoderReranker(bge-reranker-v2-m3, top_n=5)
    )
  → Singleton du modèle reranker au niveau module

USAGE (chaque message)
  retriever.invoke(question)
   → BM25 (lexical, codes "C5") + Qdrant (sémantique) → 40 candidats
   → cross-encoder rerank → top 5
   → LLM Mistral
```

## Risques identifiés

1. **Cache HF** : 30s au premier démarrage si modèle non prébake
2. **Latence reranker CPU** : 1.5-3s par requête → effet "lent" en démo
3. **Sérialisation** : JSON only, jamais pickle (sécurité + portabilité)

## Sources GitHub

- [advanced-rag-system/bm25_retriever.py](https://github.com/AMINAATTAOUI/advanced-rag-system/blob/main/src/retrieval/bm25_retriever.py) — pattern persistence BM25
- [AI-Tour-Guide/retriever_service.py](https://github.com/heshamebaid/AI-Tour-Guide/blob/main/Agentic_RAG/src/services/retriever_service.py) — EnsembleRetriever 0.4/0.6
- [dacon-financial-information/reranker.py](https://github.com/whybe-choi/dacon-financial-information-ai-search/blob/main/src/reranker.py) — CrossEncoderReranker minimal
- [No.1-RAG/chunk_util.py](https://github.com/engchina/No.1-RAG/blob/main/utils/chunk_util.py) — split par section + metadata
