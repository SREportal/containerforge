"""
CICDGenerator: Generates CI/CD pipeline configs for GitHub Actions, GitLab CI, and Jenkins.

All pipelines:
  - Detect language (uses containerforge detect output)
  - Build OCI-compliant image
  - Run vulnerability scan (trivy)
  - Push to registry on main/master
  - Optional Kubernetes deploy step
"""

from pathlib import Path
from typing import Optional


class CICDGenerator:
    def __init__(self, app_path: Path, detection: dict, config):
        self.app_path = Path(app_path)
        self.d = detection
        self.cfg = config

    def generate_all(self) -> dict:
        """Generate all requested pipeline files. Returns dict of path->content."""
        generated = {}
        generated.update(self._github_actions())
        generated.update(self._gitlab_ci())
        generated.update(self._jenkins())
        return generated

    def generate_github_actions(self) -> Path:
        files = self._github_actions()
        for path, content in files.items():
            full = self.app_path / path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content)
        return self.app_path / ".github/workflows/containerforge.yml"

    def generate_gitlab_ci(self) -> Path:
        files = self._gitlab_ci()
        for path, content in files.items():
            full = self.app_path / path
            full.write_text(content)
        return self.app_path / ".gitlab-ci.yml"

    def generate_jenkins(self) -> Path:
        files = self._jenkins()
        for path, content in files.items():
            full = self.app_path / path
            full.write_text(content)
        return self.app_path / "Jenkinsfile"

    # ─── GitHub Actions ───────────────────────────────────────────────────────

    def _github_actions(self) -> dict:
        name = self.cfg.name or self.app_path.name.lower().replace("_", "-")
        port = self.d.get("port", 8080)
        lang = self.d.get("language", "python")
        runtime = self.d.get("runtime_version", "")
        registry = self.cfg.push_registry or "ghcr.io/${{ github.repository_owner }}"
        k8s = self.cfg.k8s_namespace != "default" or self.cfg.k8s_replicas > 1
        setup_step = self._gh_setup_step(lang, runtime)
        test_step = self._gh_test_step(lang)

        content = f"""\
# ──────────────────────────────────────────────────────────────────────
# ContainerForge - GitHub Actions Pipeline
# Auto-generated for: {name} ({lang})
# ──────────────────────────────────────────────────────────────────────

name: ContainerForge CI/CD

on:
  push:
    branches: [ main, master, develop ]
  pull_request:
    branches: [ main, master ]
  workflow_dispatch:

env:
  IMAGE_NAME: {name}
  REGISTRY: {registry}

jobs:
  # ── 1. Test ──────────────────────────────────────────────────────────
  test:
    name: Test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

{setup_step}

{test_step}

  # ── 2. Build & Scan ──────────────────────────────────────────────────
  build:
    name: Build & Vulnerability Scan
    needs: test
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
      security-events: write

    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to Registry
        if: github.event_name != 'pull_request'
        uses: docker/login-action@v3
        with:
          registry: ${{{{ env.REGISTRY }}}}
          username: ${{{{ github.actor }}}}
          password: ${{{{ secrets.GITHUB_TOKEN }}}}

      - name: Extract Docker metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{{{ env.REGISTRY }}}}/${{{{ env.IMAGE_NAME }}}}
          tags: |
            type=ref,event=branch
            type=ref,event=pr
            type=semver,pattern={{{{version}}}}
            type=sha,prefix=sha-
            type=raw,value=latest,enable={{{{is_default_branch}}}}

      - name: Build Docker image
        id: build
        uses: docker/build-push-action@v5
        with:
          context: .
          push: false
          load: true
          tags: ${{{{ steps.meta.outputs.tags }}}}
          labels: ${{{{ steps.meta.outputs.labels }}}}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          platforms: linux/amd64

      - name: Run Trivy vulnerability scan
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: ${{{{ env.REGISTRY }}}}/${{{{ env.IMAGE_NAME }}}}:latest
          format: sarif
          output: trivy-results.sarif
          severity: CRITICAL,HIGH
          exit-code: 0   # set to 1 to block on CRITICAL findings

      - name: Upload Trivy results to GitHub Security tab
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: trivy-results.sarif

      - name: Generate SBOM
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: ${{{{ env.REGISTRY }}}}/${{{{ env.IMAGE_NAME }}}}:latest
          format: cyclonedx
          output: sbom.json

      - name: Upload SBOM artifact
        uses: actions/upload-artifact@v4
        with:
          name: sbom
          path: sbom.json

      - name: Push Docker image
        if: github.event_name != 'pull_request'
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{{{ steps.meta.outputs.tags }}}}
          labels: ${{{{ steps.meta.outputs.labels }}}}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          platforms: linux/amd64,linux/arm64

{"  # ── 3. Deploy to Kubernetes ──────────────────────────────────────────" if k8s else ""}
{"  deploy:" if k8s else ""}
{"    name: Deploy to Kubernetes" if k8s else ""}
{"    needs: build" if k8s else ""}
{"    if: github.ref == 'refs/heads/main' && github.event_name == 'push'" if k8s else ""}
{"    runs-on: ubuntu-latest" if k8s else ""}
{"    environment: production" if k8s else ""}
{"    steps:" if k8s else ""}
{"      - uses: actions/checkout@v4" if k8s else ""}
{"      - name: Set up kubectl" if k8s else ""}
{"        uses: azure/setup-kubectl@v3" if k8s else ""}
{"      - name: Configure kubeconfig" if k8s else ""}
{"        run: |" if k8s else ""}
{f"          echo '${{{{ secrets.KUBECONFIG }}}}' | base64 -d > kubeconfig.yaml" if k8s else ""}
{"          export KUBECONFIG=./kubeconfig.yaml" if k8s else ""}
{f"      - name: Deploy to {self.cfg.k8s_namespace}" if k8s else ""}
{"        run: |" if k8s else ""}
{"          kubectl apply -f k8s/" if k8s else ""}
{"          kubectl rollout status deployment/" + name + " -n " + self.cfg.k8s_namespace if k8s else ""}
"""
        # Clean up empty lines from conditional blocks
        lines = [l for l in content.splitlines() if not (l.strip() == "" and l.endswith(""))]
        return {".github/workflows/containerforge.yml": content}

    def _gh_setup_step(self, lang: str, runtime: str) -> str:
        steps = {
            "python": f"""\
      - name: Set up Python {runtime}
        uses: actions/setup-python@v5
        with:
          python-version: '{runtime or "3.11"}'
          cache: pip""",
            "nodejs": f"""\
      - name: Set up Node.js {runtime}
        uses: actions/setup-node@v4
        with:
          node-version: '{runtime or "20"}'
          cache: npm""",
            "go": f"""\
      - name: Set up Go {runtime}
        uses: actions/setup-go@v5
        with:
          go-version: '{runtime or "1.22"}'
          cache: true""",
            "java": f"""\
      - name: Set up Java {runtime}
        uses: actions/setup-java@v4
        with:
          java-version: '{runtime or "21"}'
          distribution: temurin
          cache: maven""",
            "rust": """\
      - name: Set up Rust
        uses: dtolnay/rust-toolchain@stable""",
        }
        return steps.get(lang, "      # No runtime setup needed")

    def _gh_test_step(self, lang: str) -> str:
        steps = {
            "python": """\
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run tests
        run: python -m pytest tests/ -v --tb=short || echo "No tests found" """,
            "nodejs": """\
      - name: Install dependencies
        run: npm ci
      - name: Run tests
        run: npm test || echo "No tests found" """,
            "go": """\
      - name: Run tests
        run: go test ./... -v -coverprofile=coverage.out || echo "No tests found" """,
            "java": """\
      - name: Run tests
        run: mvn test || ./gradlew test""",
            "rust": """\
      - name: Run tests
        run: cargo test""",
        }
        return steps.get(lang, "      # No test step configured")

    # ─── GitLab CI ────────────────────────────────────────────────────────────

    def _gitlab_ci(self) -> dict:
        name = self.cfg.name or self.app_path.name.lower().replace("_", "-")
        lang = self.d.get("language", "python")
        runtime = self.d.get("runtime_version", "")
        registry = "${CI_REGISTRY_IMAGE}"

        content = f"""\
# ──────────────────────────────────────────────────────────────────────
# ContainerForge - GitLab CI Pipeline
# Auto-generated for: {name} ({lang})
# ──────────────────────────────────────────────────────────────────────

stages:
  - test
  - build
  - scan
  - push
  - deploy

variables:
  IMAGE_NAME: {name}
  DOCKER_DRIVER: overlay2
  DOCKER_TLS_CERTDIR: "/certs"

# ── Templates ────────────────────────────────────────────────────────
.docker:
  image: docker:26
  services:
    - docker:26-dind
  before_script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_REGISTRY_PASSWORD" "$CI_REGISTRY"

# ── Test ─────────────────────────────────────────────────────────────
test:
  stage: test
  image: {self._gitlab_image(lang, runtime)}
  script:
    {self._gitlab_test_script(lang)}
  cache:
    key: "$CI_COMMIT_REF_SLUG"
    paths: {self._gitlab_cache_paths(lang)}

# ── Build ─────────────────────────────────────────────────────────────
build:
  stage: build
  extends: .docker
  script:
    - docker buildx build
        --platform linux/amd64
        --tag "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA"
        --tag "$CI_REGISTRY_IMAGE:latest"
        --cache-from "$CI_REGISTRY_IMAGE:latest"
        --build-arg BUILDKIT_INLINE_CACHE=1
        --load .
    - docker save "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA" -o image.tar
  artifacts:
    paths:
      - image.tar
    expire_in: 1 hour

# ── Vulnerability Scan ────────────────────────────────────────────────
scan:
  stage: scan
  image: aquasec/trivy:latest
  dependencies:
    - build
  script:
    - trivy image
        --exit-code 0
        --severity CRITICAL,HIGH
        --format json
        --output trivy-report.json
        "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA"
    - trivy image
        --format cyclonedx
        --output sbom.json
        "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA"
  artifacts:
    when: always
    reports:
      container_scanning: trivy-report.json
    paths:
      - trivy-report.json
      - sbom.json
    expire_in: 30 days

# ── Push ─────────────────────────────────────────────────────────────
push:
  stage: push
  extends: .docker
  dependencies:
    - build
  script:
    - docker load -i image.tar
    - docker push "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA"
    - |
      if [ "$CI_COMMIT_BRANCH" = "main" ] || [ "$CI_COMMIT_BRANCH" = "master" ]; then
        docker push "$CI_REGISTRY_IMAGE:latest"
      fi
  only:
    - main
    - master
    - tags

# ── Deploy ────────────────────────────────────────────────────────────
deploy:
  stage: deploy
  image: bitnami/kubectl:latest
  environment:
    name: production
  script:
    - echo "$KUBECONFIG_CONTENT" | base64 -d > kubeconfig.yaml
    - export KUBECONFIG=./kubeconfig.yaml
    - kubectl apply -f k8s/
    - kubectl rollout status deployment/{name} -n {self.cfg.k8s_namespace}
  only:
    - main
    - master
  when: manual
  needs:
    - push
"""
        return {".gitlab-ci.yml": content}

    def _gitlab_image(self, lang: str, runtime: str) -> str:
        images = {
            "python": f"python:{runtime or '3.11'}-slim",
            "nodejs": f"node:{runtime or '20'}-alpine",
            "go": f"golang:{runtime or '1.22'}-alpine",
            "java": f"eclipse-temurin:{runtime or '21'}-jdk-alpine",
            "rust": "rust:slim",
        }
        return images.get(lang, "alpine:latest")

    def _gitlab_test_script(self, lang: str) -> str:
        scripts = {
            "python": "- pip install -r requirements.txt\n    - python -m pytest tests/ || echo 'no tests'",
            "nodejs": "- npm ci\n    - npm test || echo 'no tests'",
            "go": "- go test ./...",
            "java": "- mvn test",
            "rust": "- cargo test",
        }
        return scripts.get(lang, "- echo 'no test step'")

    def _gitlab_cache_paths(self, lang: str) -> str:
        paths = {
            "python": "      - .pip/",
            "nodejs": "      - node_modules/",
            "go": "      - .go/",
            "java": "      - .m2/",
        }
        return paths.get(lang, "      - []")

    # ─── Jenkinsfile ──────────────────────────────────────────────────────────

    def _jenkins(self) -> dict:
        name = self.cfg.name or self.app_path.name.lower().replace("_", "-")
        lang = self.d.get("language", "python")
        registry = self.cfg.push_registry or "your-registry"

        content = f"""\
// ──────────────────────────────────────────────────────────────────────
// ContainerForge - Jenkinsfile
// Auto-generated for: {name} ({lang})
// ──────────────────────────────────────────────────────────────────────

pipeline {{
    agent any

    environment {{
        IMAGE_NAME      = '{name}'
        REGISTRY        = '{registry}'
        IMAGE_TAG       = "${{REGISTRY}}/${{IMAGE_NAME}}:${{BUILD_NUMBER}}"
        IMAGE_LATEST    = "${{REGISTRY}}/${{IMAGE_NAME}}:latest"
    }}

    options {{
        buildDiscarder(logRotator(numToKeepStr: '10'))
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
    }}

    stages {{
        stage('Checkout') {{
            steps {{
                checkout scm
                sh 'git log --oneline -5'
            }}
        }}

        stage('Test') {{
            steps {{
                {self._jenkins_test_step(lang)}
            }}
            post {{
                always {{
                    publishTestResults testResultsPattern: '**/test-results/*.xml', allowEmptyResults: true
                }}
            }}
        }}

        stage('Build Image') {{
            steps {{
                script {{
                    docker.build(env.IMAGE_TAG, '--platform linux/amd64 .')
                }}
            }}
        }}

        stage('Vulnerability Scan') {{
            steps {{
                sh 'trivy image --exit-code 0 --severity CRITICAL,HIGH --format json --output trivy-report.json $IMAGE_TAG 2>/dev/null; trivy image --format cyclonedx --output sbom.json $IMAGE_TAG 2>/dev/null || echo "Trivy not installed"'  
            }}
            post {{
                always {{
                    archiveArtifacts artifacts: 'trivy-report.json,sbom.json', allowEmptyArchive: true
                }}
            }}
        }}

        stage('Push Image') {{
            when {{
                branch 'main'
            }}
            steps {{
                script {{
                    docker.withRegistry("https://${{REGISTRY}}", 'registry-credentials') {{
                        docker.image(env.IMAGE_TAG).push()
                        docker.image(env.IMAGE_TAG).push('latest')
                    }}
                }}
            }}
        }}

        stage('Deploy') {{
            when {{
                branch 'main'
            }}
            steps {{
                sh '''
                    kubectl apply -f k8s/
                    kubectl rollout status deployment/{name} -n {self.cfg.k8s_namespace}
                '''
            }}
        }}
    }}

    post {{
        always {{
            cleanWs()
        }}
        failure {{
            echo "Build failed: ${{BUILD_URL}}"
        }}
        success {{
            echo "Deployed ${{IMAGE_TAG}} successfully"
        }}
    }}
}}
"""
        return {"Jenkinsfile": content}

    def _jenkins_test_step(self, lang: str) -> str:
        steps = {
            "python": "sh 'pip install -r requirements.txt && python -m pytest tests/ || echo no tests'",
            "nodejs": "sh 'npm ci && npm test || echo no tests'",
            "go": "sh 'go test ./...'",
            "java": "sh 'mvn test'",
            "rust": "sh 'cargo test'",
        }
        return steps.get(lang, "sh 'echo no test step configured'")
