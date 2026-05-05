# Redis Pub/Sub Demo (Cloud Run + WebSocket)

Projet de demo temps reel avec 2 services Cloud Run (`instance-1`, `instance-2`), Redis (Memorystore), Pub/Sub et Socket.IO.

## Objectif

Quand un client publie un message:

1. le serveur ecrit le message dans Redis (`SETEX`)
2. le serveur publie la cle Redis dans Pub/Sub
3. chaque instance Cloud Run recoit le message via sa subscription dediee
4. chaque instance pousse `update` a ses clients WebSocket

Resultat: les 2 pages recoivent la mise a jour sans reload.

## Stack

- Python 3.12
- Flask + Flask-SocketIO
- Gunicorn (`gthread`)
- Redis (google Memorystore)
- Google Pub/Sub
- Cloud Run

## Arborescence utile

- `main.py`: API Flask + listener Pub/Sub + Socket.IO
- `static/index.html`: page web
- `static/app.js`: client Socket.IO + publish + debug live
- `static/styles.css`: style frontend
- `deploy.ps1`: deploiement des 2 services Cloud Run
- `PHASE2.md`: notes phase 2
- `LOCAL_DEV.md`: notes rapide dev local
- `DOCUMENTATION.md` / `DOCUMENTATION.pdf`: doc detaillee

## Prerequis

- `gcloud` installe et configure
- projet GCP actif (ex: `redis-demo-cloud`)
- topic Pub/Sub cree (`redis-updates`)
- 2 subscriptions creees:
  - `redis-updates-instance-1`
  - `redis-updates-instance-2`
- Redis Memorystore disponible
- VPC connector Cloud Run vers le VPC Redis

## IAM (compte de service Cloud Run)

Le compte de service Cloud Run doit avoir:

- `roles/pubsub.publisher`
- `roles/pubsub.subscriber`

Optionnel si creation auto topic/sub par le code:

- `roles/pubsub.admin`

## Variables d'environnement backend

Variables principales:

- `GCP_PROJECT_ID`
- `TOPIC_NAME`
- `SUBSCRIPTION_NAME`
- `SERVER_ID`
- `REDIS_HOST`
- `REDIS_PORT`
- `PUBSUB_AUTO_CREATE` (recommande `false`)

## Deploiement (recommande)

Depuis `td-cloud/`:

```powershell
.\deploy.ps1 `
  -ProjectId redis-demo-cloud `
  -Region europe-west1 `
  -RedisHost 10.55.48.211 `
  -RedisPort 6379 `
  -VpcConnector vpc-connector `
  -VpcEgress private-ranges-only `
  -TimeoutSeconds 3600 `
  -MinInstances 1 `
  -MaxInstances 1 `
  -AllowUnauthenticated
```

Notes:

- `MinInstances=1` garde le listener Pub/Sub actif (meilleure stabilite temps reel).
- `MaxInstances=1` evite les effets de repartition multi-container pour cette demo.

## Test end-to-end

1. Ouvre les 2 URLs Cloud Run dans 2 onglets:
   - `https://instance-1-...run.app`
   - `https://instance-2-...run.app`
2. Fais `Ctrl+F5` sur les deux pages.
3. Publie un message depuis un onglet.
4. Verifie reception sur les deux onglets (sans reload).

## Commandes de debug utiles

Verifier subscriptions:

```powershell
gcloud pubsub subscriptions list --project=redis-demo-cloud
```

Logs Pub/Sub instance-1:

```powershell
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=instance-1 AND textPayload:Pub/Sub" --project=redis-demo-cloud --limit=30 --format="table(timestamp,textPayload)"
```

Logs Pub/Sub instance-2:

```powershell
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=instance-2 AND textPayload:Pub/Sub" --project=redis-demo-cloud --limit=30 --format="table(timestamp,textPayload)"
```

## Dev local

Voir `LOCAL_DEV.md`:

- Option A: emulateur Pub/Sub
- Option B: desactiver Pub/Sub (`DISABLE_PUBSUB=1`)

## Cout

Pour economiser la nuit:

- redeployer avec `-MinInstances 0`

Avant demo/tests:

- remettre `-MinInstances 1`
