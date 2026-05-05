# Guide TD2 - Phase 3 + 4 (Cloud Tasks + Firestore)

Ce guide deploie la version complete:
- Redis + Pub/Sub (temps reel)
- Cloud Tasks + Cloud Storage (snapshot async)
- Firestore (rate limiting + analytics)

## 1) Variables cible

- `PROJECT_ID`: `td-cloud-495410`
- `REGION`: `europe-west1`
- `SERVICES`: `instance-1`, `instance-2`
- `TOPIC_NAME`: `game-events`
- `SUB_PREFIX`: `td-redis-sub`
- `TASK_QUEUE`: `game-events-queue`
- `SNAPSHOT_BUCKET`: `game-snapshots-<PROJECT_ID>`

## 2) Provisioning + deploiement via script unique

Depuis `td-cloud/`:

```powershell
.\deploy.ps1 `
  -ProjectId td-cloud-495410 `
  -Region europe-west1 `
  -RedisHost 10.128.148.43 `
  -RedisPort 6379 `
  -VpcConnector vpc-connector `
  -VpcEgress private-ranges-only `
  -RateLimitPerMin 5 `
  -AdminKey td-secret-2026 `
  -ProvisionInfra `
  -AllowUnauthenticated
```

Le script fait:
- activation APIs (`run`, `pubsub`, `cloudtasks`, `storage`, `firestore`, etc.)
- creation topic + subscriptions
- creation queue Cloud Tasks
- creation bucket snapshots
- creation base Firestore Native (si absente)
- IAM sur SA Cloud Run (`pubsub`, `cloudtasks.enqueuer`, `datastore.user`, `storage.objectCreator`)
- deploiement Cloud Run des 2 services

## 3) Tests acceptance

```powershell
$u1 = gcloud run services describe instance-1 --region=europe-west1 --format="value(status.url)"
$u2 = gcloud run services describe instance-2 --region=europe-west1 --format="value(status.url)"
```

### Smoke

```powershell
Invoke-RestMethod "$u1/health"
Invoke-RestMethod "$u2/health"
```

### Phase 3 - Task + snapshot

```powershell
Invoke-RestMethod -Method Post -Uri "$u1/publish" -ContentType "application/json" -Body '{"message":"phase3-check"}'
Start-Sleep -Seconds 5
gcloud storage ls "gs://game-snapshots-td-cloud-495410/snapshots/**"
```

### Phase 4 - Rate limiting

```powershell
1..7 | ForEach-Object {
  try {
    Invoke-RestMethod -Method Post -Uri "$u1/publish" -ContentType "application/json" -Headers @{ "X-Player-ID" = "player-test-42" } -Body "{`"message`":`"hit $_`"}"
  } catch {
    $_.Exception.Response.StatusCode.value__
  }
}
```

Attendu:
- 1..5 OK
- ensuite `429`

### Analytics

```powershell
Invoke-RestMethod -Method Get -Uri "$u1/analytics" -Headers @{ "X-Admin-Key" = "td-secret-2026" }
```

## 4) Debug utile

```powershell
gcloud pubsub subscriptions list --project=td-cloud-495410
gcloud tasks queues describe game-events-queue --location=europe-west1 --project=td-cloud-495410
gcloud firestore databases list --project=td-cloud-495410
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=instance-1 AND textPayload:process" --project=td-cloud-495410 --limit=30 --format="table(timestamp,textPayload)"
```
