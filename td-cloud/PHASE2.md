# Phase 2 - Deploiement Cloud Run + Pub/Sub

Ce document resume les etapes pour la phase 2.

## 1. Variables a ajuster

- PROJECT_ID: redis-demo-cloud
- PROJECT_NUMBER: 516582424495
- REGION: europe-west1
- TOPIC_NAME: redis-updates
- SERVICES: instance-1, instance-2
- REDIS_HOST / REDIS_PORT (Memorystore)
- VPC_CONNECTOR: vpc-connector

## 2. IAM (une seule fois)

```powershell
gcloud projects add-iam-policy-binding redis-demo-cloud --member="serviceAccount:516582424495-compute@developer.gserviceaccount.com" --role="roles/pubsub.publisher"
gcloud projects add-iam-policy-binding redis-demo-cloud --member="serviceAccount:516582424495-compute@developer.gserviceaccount.com" --role="roles/pubsub.subscriber"
```

Si tu veux que le code cree topic + subscriptions automatiquement :

```powershell
gcloud projects add-iam-policy-binding redis-demo-cloud --member="serviceAccount:516582424495-compute@developer.gserviceaccount.com" --role="roles/pubsub.admin"
```

## 3. Topic Pub/Sub

```powershell
gcloud pubsub topics describe redis-updates --project=redis-demo-cloud
```

Si le topic n'existe pas :

```powershell
gcloud pubsub topics create redis-updates --project=redis-demo-cloud
```

## 4. Deployer les 2 services

Option simple (commande directe) :

```powershell
cd "C:\Users\lukas\OneDrive\Bureau\Projet\dev cloud\rediscloud-demo\td-cloud"

gcloud run deploy instance-1 --source . --project=redis-demo-cloud --region=europe-west1 --vpc-connector=vpc-connector --vpc-egress=private-ranges-only --set-env-vars GCP_PROJECT_ID=redis-demo-cloud,TOPIC_NAME=redis-updates,SUBSCRIPTION_NAME=redis-updates-instance-1,REDIS_HOST=10.55.48.211,REDIS_PORT=6379

gcloud run deploy instance-2 --source . --project=redis-demo-cloud --region=europe-west1 --vpc-connector=vpc-connector --vpc-egress=private-ranges-only --set-env-vars GCP_PROJECT_ID=redis-demo-cloud,TOPIC_NAME=redis-updates,SUBSCRIPTION_NAME=redis-updates-instance-2,REDIS_HOST=10.55.48.211,REDIS_PORT=6379
```

Option script (recommande) :

```powershell
cd "C:\Users\lukas\OneDrive\Bureau\Projet\dev cloud\rediscloud-demo\td-cloud"
./deploy.ps1 -RedisHost 10.55.48.211 -RedisPort 6379 -VpcConnector vpc-connector -VpcEgress private-ranges-only -TimeoutSeconds 3600
```

Pour rendre les URLs publiques :

```powershell
./deploy.ps1 -RedisHost 10.55.48.211 -RedisPort 6379 -VpcConnector vpc-connector -VpcEgress private-ranges-only -TimeoutSeconds 3600 -AllowUnauthenticated
```

Note : si tu veux une subscription par instance Cloud Run (pas par service), ne fournis pas SUBSCRIPTION_NAME.

## 5. Test

- Ouvre les 2 URLs Cloud Run.
- Publie un message dans une des deux pages.
- Les deux pages doivent recevoir un `update` en temps reel.

## Local

Voir `LOCAL_DEV.md` pour l'emulateur Pub/Sub ou le mode sans Pub/Sub.
