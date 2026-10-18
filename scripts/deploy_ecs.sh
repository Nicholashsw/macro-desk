#!/usr/bin/env bash
# Build the image, push it to ECR and serve it over HTTPS on ECS Express Mode.
#
#   AWS_REGION=us-east-1 scripts/deploy_ecs.sh          # create or update
#   AWS_REGION=us-east-1 scripts/deploy_ecs.sh --delete # tear down
#
# Needs: aws CLI v2 with credentials, Docker with buildx.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
NAME="${SERVICE_NAME:-macro-desk}"
STATE=".ecs-service-arn"

if [[ "${1:-}" == "--delete" ]]; then
  aws ecs delete-express-gateway-service --service-arn "$(cat "$STATE")" --region "$REGION"
  rm -f "$STATE"
  exit 0
fi

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
IMAGE="$REGISTRY/$NAME:$(git rev-parse --short HEAD)"

aws ecr describe-repositories --repository-names "$NAME" --region "$REGION" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$NAME" --region "$REGION" >/dev/null
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
docker buildx build --platform linux/arm64 -t "$IMAGE" --push .

ensure_role() {
  local role=$1 service=$2 policy=$3
  if ! aws iam get-role --role-name "$role" >/dev/null 2>&1; then
    aws iam create-role --role-name "$role" --assume-role-policy-document "{
      \"Version\": \"2012-10-17\",
      \"Statement\": [{\"Effect\": \"Allow\", \"Principal\": {\"Service\": \"$service\"}, \"Action\": \"sts:AssumeRole\"}]
    }" >/dev/null
    aws iam attach-role-policy --role-name "$role" --policy-arn "$policy"
    sleep 15  # IAM is eventually consistent
  fi
  aws iam get-role --role-name "$role" --query Role.Arn --output text
}

EXEC_ROLE=$(ensure_role ecsTaskExecutionRole ecs-tasks.amazonaws.com \
  arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy)
INFRA_ROLE=$(ensure_role ecsInfrastructureRoleForExpressServices ecs.amazonaws.com \
  arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices)

CONTAINER="{\"image\": \"$IMAGE\", \"containerPort\": 8000}"

if [[ -f "$STATE" ]]; then
  aws ecs update-express-gateway-service --service-arn "$(cat "$STATE")" \
    --primary-container "$CONTAINER" --region "$REGION" --monitor-resources
else
  aws ecs create-express-gateway-service \
    --service-name "$NAME" \
    --execution-role-arn "$EXEC_ROLE" \
    --infrastructure-role-arn "$INFRA_ROLE" \
    --primary-container "$CONTAINER" \
    --cpu-architecture ARM64 \
    --health-check-path /ping \
    --scaling-target '{"minTaskCount": 1, "maxTaskCount": 2}' \
    --region "$REGION" --query service.serviceArn --output text | tee "$STATE"
fi

aws ecs describe-express-gateway-service --service-arn "$(cat "$STATE")" --region "$REGION"
