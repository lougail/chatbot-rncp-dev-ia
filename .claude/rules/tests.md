# Règles de tests (appliquées aux fichiers test/spec)

- Pattern AAA : Arrange, Act, Assert — un bloc logique par test
- Un concept par test — pas de tests "et aussi"
- Noms de tests descriptifs : `test_split_documents_returns_chunks`, pas `test_1`
- Mock les dépendances externes (Mistral API, Qdrant) mais PAS la logique métier
- Tester les cas limites : entrée vide, texte court, métadonnées absentes
- Tests indépendants et idempotents (pas de dépendance à l'ordre d'exécution)
- Pas de données de test hardcodées — utiliser des factories ou fixtures
- Pour ce projet RAG : on teste les fonctions PURES (split, format) sans Mistral/Qdrant
  → tests d'intégration end-to-end (avec Qdrant + Mistral réels) sont hors scope MVP
