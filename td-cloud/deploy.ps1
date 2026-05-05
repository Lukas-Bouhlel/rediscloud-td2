param(
  [string]$ProjectId = "td-cloud-495410",
  [string]$Region = "europe-west1",
  [string]$TopicName = "game-events",
  [string]$SubscriptionPrefix = "td-redis-sub",
  [string]$Service1 = "instance-1",
  [string]$Service2 = "instance-2",
  [string]$ProcessorService = "instance-1",
  [string]$TaskQueue = "game-events-queue",
  [string]$SnapshotBucket = "",
  [string]$AdminKey = "td-secret-2026",
  [int]$RateLimitPerMin = 5,
  [string]$RedisHost = "",
  [string]$RedisPort = "",
  [string]$RedisUsername = "",
  [string]$RedisPassword = "",
  [string]$VpcConnector = "",
  [string]$VpcEgress = "private-ranges-only",
  [int]$TimeoutSeconds = 3600,
  [int]$MinInstances = 1,
  [int]$MaxInstances = 1,
  [bool]$PubSubAutoCreate = $false,
  [switch]$AllowUnauthenticated,
  [switch]$ProvisionInfra,
  [switch]$SkipDeploy
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

if (-not $SnapshotBucket) {
  $SnapshotBucket = "game-snapshots-$ProjectId"
}

function Invoke-Gcloud {
  param([string[]]$CommandArgs)
  Write-Host "gcloud $($CommandArgs -join ' ')" -ForegroundColor Cyan
  $result = & gcloud.cmd @CommandArgs
  if ($LASTEXITCODE -ne 0) {
    throw "gcloud command failed with exit code $LASTEXITCODE"
  }
  return $result
}

function Ensure-Topic {
  param([string]$Name)
  try {
    Invoke-Gcloud @("pubsub", "topics", "describe", $Name, "--project", $ProjectId) | Out-Null
  }
  catch {
    Invoke-Gcloud @("pubsub", "topics", "create", $Name, "--project", $ProjectId) | Out-Null
  }
}

function Ensure-Subscription {
  param([string]$Name, [string]$Topic)
  try {
    Invoke-Gcloud @("pubsub", "subscriptions", "describe", $Name, "--project", $ProjectId) | Out-Null
  }
  catch {
    Invoke-Gcloud @("pubsub", "subscriptions", "create", $Name, "--topic", $Topic, "--project", $ProjectId) | Out-Null
  }
}

function Ensure-TaskQueue {
  param([string]$Name)
  try {
    Invoke-Gcloud @("tasks", "queues", "describe", $Name, "--location", $Region, "--project", $ProjectId) | Out-Null
  }
  catch {
    Invoke-Gcloud @(
      "tasks", "queues", "create", $Name,
      "--location", $Region,
      "--project", $ProjectId,
      "--max-dispatches-per-second", "50",
      "--max-concurrent-dispatches", "20",
      "--max-attempts", "3",
      "--min-backoff", "5s",
      "--max-backoff", "60s"
    ) | Out-Null
  }
}

function Ensure-Bucket {
  param([string]$BucketName)
  try {
    Invoke-Gcloud @("storage", "buckets", "describe", "gs://$BucketName", "--project", $ProjectId) | Out-Null
  }
  catch {
    Invoke-Gcloud @(
      "storage", "buckets", "create", "gs://$BucketName",
      "--project", $ProjectId,
      "--location", $Region,
      "--default-storage-class", "STANDARD",
      "--uniform-bucket-level-access"
    ) | Out-Null
  }
}

function Ensure-Firestore {
  $databases = Invoke-Gcloud @("firestore", "databases", "list", "--project", $ProjectId, "--format", "value(name)")
  if (-not ($databases -match "\(default\)")) {
    Invoke-Gcloud @(
      "firestore", "databases", "create",
      "--location", $Region,
      "--type", "firestore-native",
      "--project", $ProjectId
    ) | Out-Null
  }
}

function Deploy-Service {
  param(
    [string]$ServiceName,
    [string]$SubscriptionName,
    [string]$ProcessorUrl
  )

  $envVars = @(
    "GCP_PROJECT_ID=$ProjectId",
    "REGION=$Region",
    "TOPIC_NAME=$TopicName",
    "SERVER_ID=$ServiceName",
    "PUBSUB_AUTO_CREATE=$($PubSubAutoCreate.ToString().ToLower())",
    "SUBSCRIPTION_NAME=$SubscriptionName",
    "TASK_QUEUE=$TaskQueue",
    "SNAPSHOT_BUCKET=$SnapshotBucket",
    "RATE_LIMIT_PER_MIN=$RateLimitPerMin",
    "ADMIN_KEY=$AdminKey",
    "PROCESSOR_URL=$ProcessorUrl"
  )

  if ($RedisHost) { $envVars += "REDIS_HOST=$RedisHost" }
  if ($RedisPort) { $envVars += "REDIS_PORT=$RedisPort" }
  if ($RedisUsername) { $envVars += "REDIS_USERNAME=$RedisUsername" }
  if ($RedisPassword) { $envVars += "REDIS_PASSWORD=$RedisPassword" }

  $args = @(
    "run", "deploy", $ServiceName,
    "--source", ".",
    "--project", $ProjectId,
    "--region", $Region,
    "--timeout", $TimeoutSeconds,
    "--min-instances", $MinInstances,
    "--max-instances", $MaxInstances,
    "--set-env-vars", ($envVars -join ",")
  )

  if ($VpcConnector) { $args += @("--vpc-connector", $VpcConnector) }
  if ($VpcEgress) { $args += @("--vpc-egress", $VpcEgress) }
  if ($AllowUnauthenticated) { $args += "--allow-unauthenticated" }

  Invoke-Gcloud -CommandArgs $args
}

Invoke-Gcloud @("config", "set", "project", $ProjectId) | Out-Null

$sub1 = "$SubscriptionPrefix-$Service1"
$sub2 = "$SubscriptionPrefix-$Service2"

if ($ProvisionInfra) {
  Invoke-Gcloud @(
    "services", "enable",
    "run.googleapis.com",
    "pubsub.googleapis.com",
    "redis.googleapis.com",
    "vpcaccess.googleapis.com",
    "cloudtasks.googleapis.com",
    "storage.googleapis.com",
    "firestore.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "--project", $ProjectId
  ) | Out-Null

  Ensure-Topic -Name $TopicName
  Ensure-Subscription -Name $sub1 -Topic $TopicName
  Ensure-Subscription -Name $sub2 -Topic $TopicName
  Ensure-TaskQueue -Name $TaskQueue
  Ensure-Bucket -BucketName $SnapshotBucket
  Ensure-Firestore

  $projectNumber = Invoke-Gcloud @("projects", "describe", $ProjectId, "--format", "value(projectNumber)")
  $serviceAccount = "$projectNumber-compute@developer.gserviceaccount.com"

  Invoke-Gcloud @(
    "projects", "add-iam-policy-binding", $ProjectId,
    "--member", "serviceAccount:$serviceAccount",
    "--role", "roles/pubsub.publisher"
  ) | Out-Null

  Invoke-Gcloud @(
    "projects", "add-iam-policy-binding", $ProjectId,
    "--member", "serviceAccount:$serviceAccount",
    "--role", "roles/pubsub.subscriber"
  ) | Out-Null

  Invoke-Gcloud @(
    "projects", "add-iam-policy-binding", $ProjectId,
    "--member", "serviceAccount:$serviceAccount",
    "--role", "roles/cloudtasks.enqueuer"
  ) | Out-Null

  Invoke-Gcloud @(
    "projects", "add-iam-policy-binding", $ProjectId,
    "--member", "serviceAccount:$serviceAccount",
    "--role", "roles/datastore.user"
  ) | Out-Null

  Invoke-Gcloud @(
    "storage", "buckets", "add-iam-policy-binding", "gs://$SnapshotBucket",
    "--member", "serviceAccount:$serviceAccount",
    "--role", "roles/storage.objectCreator",
    "--project", $ProjectId
  ) | Out-Null
}

if ($SkipDeploy) {
  Write-Host "Provisioning finished. Deploy skipped by -SkipDeploy." -ForegroundColor Yellow
  exit 0
}

# 1) deploy processor service once (processor URL may not exist yet)
$processorSub = "$SubscriptionPrefix-$ProcessorService"
Deploy-Service -ServiceName $ProcessorService -SubscriptionName $processorSub -ProcessorUrl ""

# 2) retrieve processor URL from deployed service
$processorUrl = Invoke-Gcloud @("run", "services", "describe", $ProcessorService, "--project", $ProjectId, "--region", $Region, "--format", "value(status.url)")

# 3) deploy instance-1 and instance-2 with final processor URL
Deploy-Service -ServiceName $Service1 -SubscriptionName $sub1 -ProcessorUrl $processorUrl
if ($Service2 -ne $Service1) {
  Deploy-Service -ServiceName $Service2 -SubscriptionName $sub2 -ProcessorUrl $processorUrl
}
