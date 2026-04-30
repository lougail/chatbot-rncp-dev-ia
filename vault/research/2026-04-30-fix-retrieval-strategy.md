# Recherche — Fix de la régression du retrieval (post-PyMuPDF)

> **Date** : 2026-04-30
> **Contexte** : Après le swap pypdf → PyMuPDF, le retrieval ramène des chunks d'annexes (grilles d'évaluation) avec des scores cosinus tous très proches (0.822-0.844). Le LLM rate les bonnes compétences (C5, C13, C18, C19, C20) et fait un faux match sur C6 (veille technique).
> **Sources** : recherche via `context7` (`/websites/langchain`) et `docfork` (`langchain-ai/langchain`, `qdrant/qdrant`)

---

## Diagnostic

Trois pathologies se cumulent :

1. **Fragmentation des compétences** — un libellé C5 (300 caractères) chevauche 2 chunks, perdant l'ancrage `C5.` en début
2. **Pollution sémantique** — les grilles d'évaluation (lexique très proche des compétences) saturent le top-k cosinus
3. **Embedding dense seul** — `mistral-embed` 1024d ne discrimine pas les codes alphanumériques courts (C5 vs C15) → écart 0.022 entre voisins

## Solution : pattern triplet 2026

| Couche | Choix | Pourquoi |
|--------|-------|----------|
| **Chunking** | Splitter regex `C\d+\.` + métadonnée `competence` | Garantit 1 chunk = 1 compétence |
| **Recherche** | `EnsembleRetriever(BM25 0.4, Qdrant 0.6)` | BM25 attrape "C5" littéralement, dense attrape sémantique |
| **Re-ranking** | `CrossEncoderReranker(BAAI/bge-reranker-v2-m3, top_n=5)` | Multilingue FR natif, ref 2025-2026 |

## Code prêt à intégrer

### Splitter (src/ingest.py)

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    separators=[
        r"\nC\d+\.\s",        # frontière de compétence (priorité max)
        r"\n#{1,3}\s",        # titres markdown
        "\n\n", "\n", ". ", " ", "",
    ],
    is_separator_regex=True,
    chunk_size=900,           # plus grand : un libellé tient en 1 chunk
    chunk_overlap=120,
    add_start_index=True,
    keep_separator=True,
)
```

### Hybrid + Rerank (src/chain.py)

```python
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import EnsembleRetriever, ContextualCompressionRetriever
from langchain.retrievers.document_compressors import CrossEncoderReranker
from langchain_community.cross_encoders import HuggingFaceCrossEncoder

# 1. Retriever dense (Qdrant)
qdrant_retriever = vector_store.as_retriever(
    search_type="similarity",
    search_kwargs={"k": 20},
)

# 2. BM25 sur les mêmes Documents
bm25_retriever = BM25Retriever.from_documents(docs, k=20)

# 3. Ensemble RRF pondéré
ensemble = EnsembleRetriever(
    retrievers=[bm25_retriever, qdrant_retriever],
    weights=[0.4, 0.6],
)

# 4. Cross-encoder reranker
cross_encoder = HuggingFaceCrossEncoder(
    model_name="BAAI/bge-reranker-v2-m3",
    model_kwargs={"device": "cpu"},
)
reranker = CrossEncoderReranker(model=cross_encoder, top_n=5)

# 5. Pipeline final
retriever = ContextualCompressionRetriever(
    base_compressor=reranker,
    base_retriever=ensemble,
)
```

## Hyperparamètres à tuner

- **`weights` Ensemble** : 0.4/0.6 par défaut. Si BM25 bruite → 0.3/0.7. Si l'utilisateur tape des codes ("C5") → 0.5/0.5
- **`k` avant rerank** : 20 par retriever → 40 candidats → top 5 final. OK pour 21 compétences
- **`top_n` reranker** : 5 par défaut, 3 si très strict
- **`chunk_size`** : 900 caractères pour qu'une compétence reste atomique

## Vérifications post-implémentation

- Lancer `uv run pytest` après chaque modif
- Mesurer l'écart cosinus sur 10 requêtes de référence : passer de 0.022 à >0.05 entre top-1 et top-2
- Compter les chunks : avec chunk_size=900, viser ~25-35 chunks (vs 267 actuellement)
- Test manuel via dev-browser sur les 3 prompts de référence

## Liens doc

- [RecursiveCharacterTextSplitter avec regex](https://docs.langchain.com/oss/python/integrations/splitters/recursive_text_splitter)
- [BM25Retriever](https://docs.langchain.com/oss/python/integrations/retrievers/bm25)
- [ContextualCompressionRetriever + rerankers](https://docs.langchain.com/oss/python/integrations/retrievers/cohere-reranker)
- [HuggingFace BGE models](https://docs.langchain.com/oss/python/integrations/text_embedding/bge_huggingface)
