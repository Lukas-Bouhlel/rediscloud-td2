param(
  [string]$ProjectId = "redis-demo-cloud",
  [string]$Region = "europe-west1",
  [string]$TopicName = "redis-updates",
  [string]$Service1 = "instance-1",
  [string]$Service2 = "instance-2",
  [string]$RedisHost = "",
  [string]$RedisPort = "",
  [string]$RedisUsername = "",
  [string]$RedisPassword = "",
  [string]$VpcConnector = "",
  [string]$VpcEgress = "",
  [int]$TimeoutSeconds = 3600,
  [int]$MinInstances = 1,
  [int]$MaxInstances = 1,
  [bool]$PubSubAutoCreate = $false,
  [switch]$AllowUnauthenticated
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$envVars1 = @(
  "GCP_PROJECT_ID=$ProjectId",
  "TOPIC_NAME=$TopicName",
  "SERVER_ID=$Service1",
  "PUBSUB_AUTO_CREATE=$($PubSubAutoCreate.ToString().ToLower())",
  "SUBSCRIPTION_NAME=$TopicName-$Service1"
)
$envVars2 = @(
  "GCP_PROJECT_ID=$ProjectId",
  "TOPIC_NAME=$TopicName",
  "SERVER_ID=$Service2",
  "PUBSUB_AUTO_CREATE=$($PubSubAutoCreate.ToString().ToLower())",
  "SUBSCRIPTION_NAME=$TopicName-$Service2"
)

if ($RedisHost) { $envVars1 += "REDIS_HOST=$RedisHost"; $envVars2 += "REDIS_HOST=$RedisHost" }
if ($RedisPort) { $envVars1 += "REDIS_PORT=$RedisPort"; $envVars2 += "REDIS_PORT=$RedisPort" }
if ($RedisUsername) { $envVars1 += "REDIS_USERNAME=$RedisUsername"; $envVars2 += "REDIS_USERNAME=$RedisUsername" }
if ($RedisPassword) { $envVars1 += "REDIS_PASSWORD=$RedisPassword"; $envVars2 += "REDIS_PASSWORD=$RedisPassword" }

$envVars1 = $envVars1 -join ","
$envVars2 = $envVars2 -join ","

$common1 = @(
  "run", "deploy", $Service1,
  "--source", ".",
  "--project", $ProjectId,
  "--region", $Region,
  "--timeout", $TimeoutSeconds,
  "--min-instances", $MinInstances,
  "--max-instances", $MaxInstances,
  "--set-env-vars", $envVars1
)

$common2 = @(
  "run", "deploy", $Service2,
  "--source", ".",
  "--project", $ProjectId,
  "--region", $Region,
  "--timeout", $TimeoutSeconds,
  "--min-instances", $MinInstances,
  "--max-instances", $MaxInstances,
  "--set-env-vars", $envVars2
)

if ($VpcConnector) {
  $common1 += @("--vpc-connector", $VpcConnector)
  $common2 += @("--vpc-connector", $VpcConnector)
}

if ($VpcEgress) {
  $common1 += @("--vpc-egress", $VpcEgress)
  $common2 += @("--vpc-egress", $VpcEgress)
}

if ($AllowUnauthenticated) {
  $common1 += "--allow-unauthenticated"
  $common2 += "--allow-unauthenticated"
}

gcloud @common1
gcloud @common2
