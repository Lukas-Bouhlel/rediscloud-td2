# Rapport bref - TD2 Cloud (Cloud Tasks + Firestore)

Date de validation: 2026-05-05  
Projet GCP: `td-cloud-495410`  
Services Cloud Run: `instance-1`, `instance-2`

## 1. Ce qui a été implémenté

- Phase 3:
  - `POST /publish` conserve Redis + Pub/Sub et ajoute la création d'une Cloud Task.
  - `POST /process` traite la clé Redis reçue et sauvegarde un snapshot JSON dans Cloud Storage.
  - Bucket snapshots: `gs://game-snapshots-td-cloud-495410`.
  - Queue Cloud Tasks: `game-events-queue`.

- Phase 4:
  - Middleware rate limit sur `POST /publish` via Firestore (fenêtre 60s, limite configurable).
  - Mode `fail-open` si Firestore indisponible.
  - `GET /analytics` protégé par `X-Admin-Key`.
  - Collections Firestore utilisées: `rate_limits`, `analytics`.

- Déploiement:
  - Script unique `deploy.ps1` pour provisioning + IAM + deploy.
  - Script de test global `test-td2.ps1`.

## 2. Résultats des tests

Dernier test exécuté avec `test-td2.ps1`:

- Health instances: OK
- Publish: OK
- Snapshot GCS: OK
- Rate limiting: `200 x5`, puis `429 x2` (attendu)
- Analytics protégé: `401` sans clé, OK avec clé
- Résultat global: `GLOBAL PASS: True`

## 3. Comment ça fonctionne (résumé)

1. Client envoie `POST /publish`.
2. Backend écrit l'événement dans Redis + publie la clé sur Pub/Sub.
3. Backend crée une Cloud Task avec `{redis_key}` vers `POST /process` (instance-1).
4. `/process` relit Redis, reconstruit l'état, écrit un snapshot dans GCS.
5. Le middleware Firestore limite le spam par `X-Player-ID`.
6. Les compteurs analytics sont mis à jour dans Firestore.

## 4. Plan de démo vidéo (étape par étape)

## Vidéo 1 - Smoke + temps réel

1. Montrer les 2 URLs Cloud Run ouvertes (`instance-1` et `instance-2`).
2. Publier un message depuis `instance-1`.
3. Montrer la réception en direct sur les 2 pages.
4. Montrer rapidement `/health` des 2 instances en terminal.

## Vidéo 2 - Cloud Tasks + Snapshot

1. Lancer un `POST /publish` en terminal.
2. Attendre 5 secondes.
3. Montrer `gcloud storage ls gs://game-snapshots-td-cloud-495410/snapshots/**`.
4. Ouvrir un snapshot JSON et montrer `trigger_key`, `event_count`.

## Vidéo 3 - Rate limiting + Analytics

1. Envoyer 7 requêtes avec le même `X-Player-ID`.
2. Montrer `200` sur 1..5 puis `429` sur 6..7.
3. Appeler `/analytics` sans clé (montrer `401`).
4. Appeler `/analytics` avec `X-Admin-Key` et montrer les docs.

## 5. Commandes utiles pour la démo

```powershell
cd .\td-cloud
.\test-td2.ps1 -OpenBrowsers
```

```powershell
$u1 = gcloud run services describe instance-1 --region=europe-west1 --format="value(status.url)"
Invoke-RestMethod -Method Post -Uri "$u1/publish" -ContentType "application/json" -Headers @{ "X-Player-ID"="demo-video" } -Body '{"message":"demo"}'
gcloud storage ls "gs://game-snapshots-td-cloud-495410/snapshots/**"
```

