# TD Cloud Run - Redis, Pub/Sub, Cloud Tasks, Firestore

Projet Flask deploye sur Cloud Run avec:
- synchro temps reel via Redis + Pub/Sub
- traitement asynchrone via Cloud Tasks + snapshots Cloud Storage
- rate limiting et analytics via Firestore

## Stack

- Python 3.12
- Flask + Flask-SocketIO
- Redis Memorystore
- Pub/Sub
- Cloud Tasks
- Cloud Storage
- Firestore
- Cloud Run

## Routes

- `POST /publish`: publie un evenement, ecrit dans Redis, envoie Pub/Sub, enqueue une Cloud Task
- `POST /process`: appelee par Cloud Tasks pour sauvegarder un snapshot JSON dans GCS
- `GET /data`: etat Redis courant
- `GET /analytics`: lecture analytics + quotas (header `X-Admin-Key`)
- `GET /health`: health check Redis

## Deploiement recommande

Depuis `td-cloud/`:

```powershell
.\deploy.ps1 `
  -ProjectId td-cloud-495410 `
  -Region europe-west1 `
  -RedisHost 10.128.148.43 `
  -RedisPort 6379 `
  -VpcConnector vpc-connector `
  -VpcEgress private-ranges-only `
  -ProvisionInfra `
  -AllowUnauthenticated
```

Noms ressources utilises (template TD2):
- Topic Pub/Sub: `game-events`
- Subscriptions: `td-redis-sub-instance-1`, `td-redis-sub-instance-2`
- Queue Cloud Tasks: `game-events-queue`
- Bucket snapshots: `game-snapshots-<PROJECT_ID>`

## Tests rapides

```powershell
$u1 = gcloud run services describe instance-1 --region=europe-west1 --format="value(status.url)"
$u2 = gcloud run services describe instance-2 --region=europe-west1 --format="value(status.url)"

Invoke-RestMethod "$u1/health"
Invoke-RestMethod "$u2/health"

Invoke-RestMethod -Method Post -Uri "$u1/publish" -ContentType "application/json" -Body '{"message":"hello"}'
Invoke-RestMethod -Method Get -Uri "$u1/analytics" -Headers @{ "X-Admin-Key" = "td-secret-2026" }
```

Test complet automatique (health + snapshot + rate limit + analytics auth):

```powershell
cd .\td-cloud
.\test-td2.ps1 -OpenBrowsers
```

Si tout est bon, le script affiche `GLOBAL PASS: True`.

## Note /analytics

- `/analytics` est protege par le header `X-Admin-Key`.
- Sans header, la route retourne `401 Unauthorized`.
- En navigateur direct (barre URL), c'est donc normal de ne pas voir la route sans erreur.

## Rate limit

- Header joueur: `X-Player-ID`
- Limite par defaut: `5` requetes / `60s` (`RATE_LIMIT_PER_MIN`)
- Comportement si Firestore indisponible: fail-open (requete autorisee)



By VERNIER Matthieu, BOUGHEL Lukas, GILRCHRIST Steven
