# Déploiement Hugging Face Spaces

> Documentation du déploiement public du chatbot sur Hugging Face Spaces.
> Bonus du brief Simplon ("URL publique accessible sans installation").

## 🌐 URLs

- **Space (admin)** : https://huggingface.co/spaces/centau/chatbot-rncp-dev-ia
- **App live** : https://centau-chatbot-rncp-dev-ia.hf.space

## 🏗️ Architecture du déploiement

```
GitHub repo (main)                    HF Space (centau/chatbot-rncp-dev-ia)
   │                                       │
   │  branche `hf-deploy` (ne merge pas)   │  Docker SDK + Xet pour binaires
   ├──────────────────────────────────────►│
   │                                       │
   │  + PDF uploadé via huggingface_hub    │  Image Docker construite par HF
   │    (API Xet, hors git)                │  → Container exécuté sur cpu-basic
   │                                       │  → URL publique disponible
```

La branche `hf-deploy` contient des **adaptations spécifiques HF Spaces** qu'on
ne veut pas merger dans `main` (qui reste optimisé pour le dev local avec Qdrant
en sidecar).

## 🔧 Adaptations sur la branche `hf-deploy`

| Fichier | Modification | Pourquoi |
|---------|--------------|----------|
| `Dockerfile` | Port 7860 (au lieu de 8000) | Convention HF Spaces |
| `Dockerfile` | `ENV QDRANT_URL=:memory:` | Pas de service Qdrant externe en HF |
| `Dockerfile` | `RUN python -c "CrossEncoder(...)"` | Pré-télécharge bge-reranker-v2-m3 (1.1 GB) en build pour éviter les 30s du 1er run |
| `src/config.py` | Flag `QDRANT_IN_MEMORY` | Active l'auto-indexation au boot |
| `src/chain.py` | Singleton `get_qdrant_client()` | **Critique** en in-memory : on doit partager le même client entre ingestion et retrieval (sinon vecteurs invisibles) |
| `src/ingest.py` | `ensure_indexed_in_memory()` | Réindexe le PDF au démarrage du container (in-memory = pas de persistence) |
| `app.py` | Pré-warm complet au chargement du module | Appel à `ensure_indexed_in_memory()` + reranker + BM25 avant que Chainlit accepte un message |
| `README.md` | Frontmatter YAML HF Spaces | `sdk: docker`, `app_port: 7860`, `short_description`, etc. |

## 📦 Comment HF gère les binaires (et pourquoi on contourne)

HF Spaces **n'accepte plus** :
- Les fichiers binaires directement dans git
- Git LFS (deprecated chez HF en 2025)

Ils utilisent **Xet** (système propriétaire HF). Le PDF du référentiel
(`data/referentiel-rncp-dev-ia.pdf`, 979 KB) est donc uploadé séparément via
la lib Python `huggingface_hub` :

```python
from huggingface_hub import upload_file

upload_file(
    path_or_fileobj="data/referentiel-rncp-dev-ia.pdf",
    path_in_repo="data/referentiel-rncp-dev-ia.pdf",
    repo_id="centau/chatbot-rncp-dev-ia",
    repo_type="space",
    token=HF_TOKEN,
)
```

L'API `huggingface_hub` gère automatiquement Xet pour ces gros fichiers.
Le PDF apparaît côté HF mais ne peut pas être récupéré via `git clone`.

## 🔐 Secrets (MISTRAL_API_KEY)

Configuré côté HF via l'API REST (pas de CLI nécessaire) :

```bash
curl -X POST "https://huggingface.co/api/spaces/centau/chatbot-rncp-dev-ia/secrets" \
  -H "Authorization: Bearer $HF_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"key\": \"MISTRAL_API_KEY\", \"value\": \"$MISTRAL_API_KEY\"}"
```

Le secret est injecté en variable d'environnement dans le container.
**Jamais commité, jamais visible dans les logs.**

## ⚙️ Caractéristiques du container

| Param | Valeur |
|-------|--------|
| **Hardware** | cpu-basic (gratuit, 16 GB RAM) |
| **Image taille** | ~3.5 GB (Python + venv + reranker pré-téléchargé) |
| **Cold start** | ~10-15s (indexation in-memory du PDF + chargement reranker) |
| **Latence par message** | 10-15s (idem qu'en local) |
| **Persistence** | ⚠️ Aucune (Qdrant in-memory) — l'index se reconstruit à chaque restart |

## 🚀 Comment redéployer (mise à jour du code)

```bash
git checkout hf-deploy
# faire les modifs sur cette branche uniquement
git add ...
git commit -m "..."
git push hf hf-deploy:main
# (le push relance automatiquement le build HF)
```

⚠️ **Si on modifie le PDF**, il faut le re-uploader manuellement via l'API HF
(le push git n'inclut pas le PDF qui est en Xet).

## 🔄 Comment ramener les modifs hf-deploy dans main (déconseillé)

**Surtout pas !** Les modifs hf-deploy cassent le dev local :
- Port 7860 au lieu de 8000
- `QDRANT_URL=:memory:` désactive le Qdrant local Docker
- L'auto-indexation au boot est inutile en local

→ La séparation `main` (dev local) / `hf-deploy` (déploiement HF) est volontaire.

## 🧪 Vérifier l'état du Space

```bash
# Stage du build (BUILDING / RUNNING / SLEEPING / ERROR)
curl -s -H "Authorization: Bearer $HF_TOKEN" \
  https://huggingface.co/api/spaces/centau/chatbot-rncp-dev-ia | \
  jq '.runtime.stage'

# Logs en temps réel : aller sur https://huggingface.co/spaces/centau/chatbot-rncp-dev-ia/logs
```

## 📊 Points soutenance liés au déploiement

À mentionner si questions sur le déploiement :

1. **Pourquoi HF Spaces** : gratuit, pas d'inscription pour l'utilisateur final, intégration Docker simple
2. **Pourquoi pas Cloud Run/Azure** : nécessite carte bancaire, IAM complexe pour un projet d'apprentissage
3. **Limite cpu-basic** : reranker `bge-reranker-v2-m3` (1.1 GB) tient dans 16 GB de RAM mais latence ~3-5s en CPU
4. **Évolution prod** : passer en GPU T4 ou switcher vers `bge-reranker-base` (3-4× plus rapide en CPU)
5. **Pas de persistence Qdrant** : indexation au boot OK pour 21 chunks (1-2s), problématique pour 10000+ chunks → migration Qdrant Cloud nécessaire
