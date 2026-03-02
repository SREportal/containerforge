"""
CloudDeployer: Deploys containerized apps to cloud providers.

Supported targets:
  - AWS ECS Fargate (via ECR + ECS)
  - GCP Cloud Run (via Artifact Registry)
  - Azure Container Apps (via ACR)
  - Fly.io (via fly CLI)

Each provider generates its IaC config AND optionally runs the deploy.
"""

import json
import shutil
import subprocess
from pathlib import Path

PROVIDERS = ["aws", "gcp", "azure", "fly"]


class CloudDeployer:
    def __init__(self, app_path: Path, detection: dict, config, image_tag: str):
        self.app_path = Path(app_path)
        self.d = detection
        self.cfg = config
        self.image = image_tag
        self.name = config.name or app_path.name.lower().replace("_", "-")
        self.port = detection.get("port", 8080)
        self.provider = (config.cloud_provider or "").lower()
        self.region = config.cloud_region or self._default_region()
        self.out_dir = app_path / ".containerforge" / "cloud"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def generate_iac(self) -> dict:
        """Generate IaC files for the configured provider. Returns {filename: content}."""
        generators = {
            "aws":   self._aws_ecs,
            "gcp":   self._gcp_cloudrun,
            "azure": self._azure_container_apps,
            "fly":   self._fly_io,
        }
        gen = generators.get(self.provider)
        if not gen:
            return {}

        files = gen()
        for fname, content in files.items():
            path = self.out_dir / fname
            path.write_text(content)

        return files

    def deploy(self, dry_run: bool = False) -> bool:
        """Run the deployment. Returns True on success."""
        deployers = {
            "aws":   self._deploy_aws,
            "gcp":   self._deploy_gcp,
            "azure": self._deploy_azure,
            "fly":   self._deploy_fly,
        }
        fn = deployers.get(self.provider)
        if not fn:
            return False
        return fn(dry_run)

    # ─── AWS ECS Fargate ──────────────────────────────────────────────────────

    def _aws_ecs(self) -> dict:
        name = self.name
        region = self.region
        port = self.port
        registry = self.cfg.push_registry or f"<AWS_ACCOUNT_ID>.dkr.ecr.{region}.amazonaws.com"

        task_def = {
            "family": name,
            "networkMode": "awsvpc",
            "requiresCompatibilities": ["FARGATE"],
            "cpu": "256",
            "memory": "512",
            "executionRoleArn": "arn:aws:iam::<AWS_ACCOUNT_ID>:role/ecsTaskExecutionRole",
            "taskRoleArn": f"arn:aws:iam::<AWS_ACCOUNT_ID>:role/{name}-task-role",
            "containerDefinitions": [
                {
                    "name": name,
                    "image": f"{registry}/{name}:latest",
                    "portMappings": [{"containerPort": port, "protocol": "tcp"}],
                    "essential": True,
                    "healthCheck": {
                        "command": ["CMD-SHELL", f"curl -sf http://localhost:{port}/health || exit 1"],
                        "interval": 30,
                        "timeout": 10,
                        "retries": 3,
                        "startPeriod": 20,
                    },
                    "logConfiguration": {
                        "logDriver": "awslogs",
                        "options": {
                            "awslogs-group": f"/ecs/{name}",
                            "awslogs-region": region,
                            "awslogs-stream-prefix": "ecs",
                        },
                    },
                    "environment": [{"name": "PORT", "value": str(port)}],
                    "secrets": [
                        # {"name": "DATABASE_URL", "valueFrom": "arn:aws:secretsmanager:..."}
                    ],
                    "readonlyRootFilesystem": True,
                    "user": "1001:1001",
                }
            ],
        }

        deploy_script = f"""\
#!/usr/bin/env bash
# ContainerForge — AWS ECS Fargate Deploy Script
# Usage: bash deploy-aws.sh [--dry-run]
set -euo pipefail

REGION="{region}"
APP_NAME="{name}"
PORT={port}
ECR_REGISTRY="{registry}"
IMAGE="$ECR_REGISTRY/$APP_NAME:latest"
CLUSTER="$APP_NAME-cluster"
SERVICE="$APP_NAME-service"

echo "🔐 Authenticating with ECR..."
aws ecr get-login-password --region "$REGION" | \\
  docker login --username AWS --password-stdin "$ECR_REGISTRY"

echo "📦 Pushing image: $IMAGE"
docker tag "{name}:latest" "$IMAGE"
docker push "$IMAGE"

echo "📋 Registering task definition..."
TASK_DEF_ARN=$(aws ecs register-task-definition \\
  --cli-input-json file://.containerforge/cloud/ecs-task-definition.json \\
  --region "$REGION" \\
  --query 'taskDefinition.taskDefinitionArn' \\
  --output text)

echo "🚀 Updating ECS service..."
aws ecs update-service \\
  --cluster "$CLUSTER" \\
  --service "$SERVICE" \\
  --task-definition "$TASK_DEF_ARN" \\
  --region "$REGION" \\
  --force-new-deployment

echo "⏳ Waiting for deployment to stabilize..."
aws ecs wait services-stable \\
  --cluster "$CLUSTER" \\
  --services "$SERVICE" \\
  --region "$REGION"

echo "✅ Deployed $APP_NAME to ECS Fargate ($REGION)"
"""

        cloudformation = f"""\
# ContainerForge — AWS CloudFormation stack for ECS Fargate
# Deploy: aws cloudformation deploy --template-file cf-stack.yaml --stack-name {name} --capabilities CAPABILITY_IAM
AWSTemplateFormatVersion: '2010-09-09'
Description: ContainerForge ECS Fargate stack for {name}

Parameters:
  AppName:
    Type: String
    Default: {name}
  ContainerPort:
    Type: Number
    Default: {port}
  DesiredCount:
    Type: Number
    Default: {self.cfg.k8s_replicas}

Resources:
  ECRRepository:
    Type: AWS::ECR::Repository
    Properties:
      RepositoryName: !Ref AppName
      ImageScanningConfiguration:
        ScanOnPush: true
      LifecyclePolicy:
        LifecyclePolicyText: |
          {{"rules":[{{"rulePriority":1,"description":"Keep 10 images","selection":{{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":10}},"action":{{"type":"expire"}}}}]}}

  ECSCluster:
    Type: AWS::ECS::Cluster
    Properties:
      ClusterName: !Sub "${{AppName}}-cluster"
      CapacityProviders: [FARGATE, FARGATE_SPOT]

  TaskExecutionRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Statement:
          - Effect: Allow
            Principal: {{Service: ecs-tasks.amazonaws.com}}
            Action: sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

  LogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: !Sub "/ecs/${{AppName}}"
      RetentionInDays: 30

  ECSService:
    Type: AWS::ECS::Service
    Properties:
      Cluster: !Ref ECSCluster
      ServiceName: !Sub "${{AppName}}-service"
      DesiredCount: !Ref DesiredCount
      LaunchType: FARGATE
      NetworkConfiguration:
        AwsvpcConfiguration:
          AssignPublicIp: ENABLED
          Subnets: !Split [",", !ImportValue PublicSubnets]
          SecurityGroups: [!Ref AppSecurityGroup]

  AppSecurityGroup:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: !Sub "${{AppName}} container security group"
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: !Ref ContainerPort
          ToPort: !Ref ContainerPort
          CidrIp: 0.0.0.0/0
"""
        return {
            "ecs-task-definition.json": json.dumps(task_def, indent=2),
            "deploy-aws.sh":            deploy_script,
            "cf-stack.yaml":            cloudformation,
        }

    # ─── GCP Cloud Run ────────────────────────────────────────────────────────

    def _gcp_cloudrun(self) -> dict:
        name = self.name
        region = self.region or "us-central1"
        port = self.port
        project = "${GCP_PROJECT_ID}"
        registry = f"gcr.io/{project}/{name}"

        service_yaml = f"""\
# ContainerForge — GCP Cloud Run service definition
# Deploy: gcloud run services replace .containerforge/cloud/cloudrun-service.yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: {name}
  labels:
    managed-by: containerforge
  annotations:
    run.googleapis.com/ingress: all
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/minScale: "1"
        autoscaling.knative.dev/maxScale: "{self.cfg.k8s_max_replicas}"
        run.googleapis.com/cpu-throttling: "false"
    spec:
      containerConcurrency: 80
      timeoutSeconds: 300
      serviceAccountName: {name}-sa@{project}.iam.gserviceaccount.com
      containers:
        - image: {registry}:latest
          ports:
            - containerPort: {port}
          resources:
            limits:
              cpu: "1"
              memory: 512Mi
          env:
            - name: PORT
              value: "{port}"
          startupProbe:
            httpGet:
              path: /health
              port: {port}
            failureThreshold: 30
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /health
              port: {port}
            periodSeconds: 15
"""

        deploy_script = f"""\
#!/usr/bin/env bash
# ContainerForge — GCP Cloud Run Deploy Script
set -euo pipefail

PROJECT="${{GCP_PROJECT_ID:?Set GCP_PROJECT_ID}}"
REGION="{region}"
APP_NAME="{name}"
IMAGE="gcr.io/$PROJECT/$APP_NAME:latest"

echo "🔐 Configuring Docker for GCR..."
gcloud auth configure-docker --quiet

echo "📦 Pushing image: $IMAGE"
docker tag "{name}:latest" "$IMAGE"
docker push "$IMAGE"

echo "🚀 Deploying to Cloud Run..."
gcloud run deploy "$APP_NAME" \\
  --image "$IMAGE" \\
  --region "$REGION" \\
  --platform managed \\
  --allow-unauthenticated \\
  --port {port} \\
  --min-instances 1 \\
  --max-instances {self.cfg.k8s_max_replicas} \\
  --memory 512Mi \\
  --cpu 1 \\
  --project "$PROJECT"

URL=$(gcloud run services describe "$APP_NAME" \\
  --region "$REGION" --format "value(status.url)" --project "$PROJECT")
echo "✅ Live at: $URL"
"""
        return {
            "cloudrun-service.yaml": service_yaml,
            "deploy-gcp.sh":         deploy_script,
        }

    # ─── Azure Container Apps ─────────────────────────────────────────────────

    def _azure_container_apps(self) -> dict:
        name = self.name
        port = self.port
        rg = f"{name}-rg"
        env = f"{name}-env"
        acr = f"{name}acr"
        region = self.region or "eastus"

        bicep = f"""\
// ContainerForge — Azure Container Apps Bicep template
// Deploy: az deployment group create --resource-group {rg} --template-file main.bicep
param location string = '{region}'
param appName string = '{name}'
param containerPort int = {port}
param minReplicas int = 1
param maxReplicas int = {self.cfg.k8s_max_replicas}

resource acr 'Microsoft.ContainerRegistry/registries@2023-01-01-preview' = {{
  name: '{acr}'
  location: location
  sku: {{ name: 'Basic' }}
  properties: {{ adminUserEnabled: true }}
}}

resource env 'Microsoft.App/managedEnvironments@2023-04-01-preview' = {{
  name: '{env}'
  location: location
  properties: {{
    appLogsConfiguration: {{
      destination: 'azure-monitor'
    }}
  }}
}}

resource app 'Microsoft.App/containerApps@2023-04-01-preview' = {{
  name: appName
  location: location
  properties: {{
    managedEnvironmentId: env.id
    configuration: {{
      ingress: {{
        external: true
        targetPort: containerPort
        transport: 'http'
      }}
      registries: [{{
        server: acr.properties.loginServer
        username: acr.listCredentials().username
        passwordSecretRef: 'acr-password'
      }}]
      secrets: [{{
        name: 'acr-password'
        value: acr.listCredentials().passwords[0].value
      }}]
    }}
    template: {{
      containers: [{{
        name: appName
        image: '${{acr.properties.loginServer}}/{name}:latest'
        resources: {{ cpu: json('0.5'), memory: '1Gi' }}
        env: [{{ name: 'PORT', value: string(containerPort) }}]
        probes: [{{
          type: 'Liveness'
          httpGet: {{ path: '/health', port: containerPort }}
          periodSeconds: 15
        }}]
      }}]
      scale: {{
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [{{
          name: 'http-rule'
          http: {{ metadata: {{ concurrentRequests: '100' }} }}
        }}]
      }}
    }}
  }}
}}

output appUrl string = 'https://${{app.properties.configuration.ingress.fqdn}}'
"""

        deploy_script = f"""\
#!/usr/bin/env bash
# ContainerForge — Azure Container Apps Deploy Script
set -euo pipefail

RG="{rg}"
ACR="{acr}"
APP_NAME="{name}"
REGION="{region}"
IMAGE="$ACR.azurecr.io/$APP_NAME:latest"

echo "🔐 Logging in to ACR..."
az acr login --name "$ACR"

echo "📦 Pushing image..."
docker tag "{name}:latest" "$IMAGE"
docker push "$IMAGE"

echo "🚀 Deploying to Azure Container Apps..."
az containerapp update \\
  --name "$APP_NAME" \\
  --resource-group "$RG" \\
  --image "$IMAGE"

URL=$(az containerapp show --name "$APP_NAME" --resource-group "$RG" \\
  --query "properties.configuration.ingress.fqdn" -o tsv)
echo "✅ Live at: https://$URL"
"""
        return {
            "main.bicep":      bicep,
            "deploy-azure.sh": deploy_script,
        }

    # ─── Fly.io ───────────────────────────────────────────────────────────────

    def _fly_io(self) -> dict:
        name = self.name
        port = self.port
        region = self.region or "iad"

        fly_toml = f"""\
# ContainerForge — fly.toml
# Deploy: fly deploy
app = "{name}"
primary_region = "{region}"

[build]
  dockerfile = "Dockerfile"

[env]
  PORT = "{port}"

[http_service]
  internal_port = {port}
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true
  min_machines_running = 1
  processes = ["app"]

  [[http_service.checks]]
    grace_period = "20s"
    interval = "15s"
    method = "GET"
    path = "/health"
    timeout = "10s"

[[vm]]
  cpu_kind = "shared"
  cpus = 1
  memory_mb = 512
"""

        deploy_script = f"""\
#!/usr/bin/env bash
# ContainerForge — Fly.io Deploy Script
set -euo pipefail

APP_NAME="{name}"
REGION="{region}"

# Create app if it doesn't exist
if ! fly status --app "$APP_NAME" &>/dev/null; then
  echo "🆕 Creating Fly app: $APP_NAME"
  fly launch --name "$APP_NAME" --region "$REGION" --no-deploy --copy-config
fi

echo "🚀 Deploying to Fly.io..."
fly deploy --remote-only

echo "✅ Deployed: $(fly status --app "$APP_NAME" | grep Hostname)"
"""
        return {
            "fly.toml":      fly_toml,
            "deploy-fly.sh": deploy_script,
        }

    # ─── Deployment runners ───────────────────────────────────────────────────

    def _deploy_aws(self, dry_run: bool) -> bool:
        script = self.out_dir / "deploy-aws.sh"
        if not script.exists():
            self._aws_ecs()
        if dry_run:
            return True
        rc = subprocess.run(["bash", str(script)]).returncode
        return rc == 0

    def _deploy_gcp(self, dry_run: bool) -> bool:
        script = self.out_dir / "deploy-gcp.sh"
        if not script.exists():
            self._gcp_cloudrun()
        if dry_run:
            return True
        rc = subprocess.run(["bash", str(script)]).returncode
        return rc == 0

    def _deploy_azure(self, dry_run: bool) -> bool:
        script = self.out_dir / "deploy-azure.sh"
        if not script.exists():
            self._azure_container_apps()
        if dry_run:
            return True
        rc = subprocess.run(["bash", str(script)]).returncode
        return rc == 0

    def _deploy_fly(self, dry_run: bool) -> bool:
        toml = self.out_dir / "fly.toml"
        if not toml.exists():
            self._fly_io()
        shutil.copy(toml, self.app_path / "fly.toml")
        if dry_run:
            return True
        rc = subprocess.run(["fly", "deploy", "--remote-only"], cwd=self.app_path).returncode
        return rc == 0

    def _default_region(self) -> str:
        defaults = {"aws": "us-east-1", "gcp": "us-central1", "azure": "eastus", "fly": "iad"}
        return defaults.get(self.provider, "us-east-1")
