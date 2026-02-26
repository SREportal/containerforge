"""
K8sGenerator: Generates production-grade Kubernetes manifests.

Outputs k8s/ directory with:
  - Namespace
  - Deployment (with health probes, resource limits, rolling update)
  - Service (ClusterIP)
  - Ingress (optional)
  - HorizontalPodAutoscaler (optional)
  - ConfigMap (env vars)
  - Secret template (sensitive values)
  - ServiceAccount
  - NetworkPolicy
  - PodDisruptionBudget
"""

from pathlib import Path


class K8sGenerator:
    def __init__(self, app_path: Path, detection: dict, config, image_tag: str):
        self.app_path = Path(app_path)
        self.d = detection
        self.cfg = config
        self.image = image_tag
        self.name = config.name or app_path.name.lower().replace("_", "-")
        self.ns = config.k8s_namespace
        self.port = detection.get("port", 8080)
        self.k8s_dir = app_path / "k8s"

    def generate(self) -> Path:
        self.k8s_dir.mkdir(exist_ok=True)
        files = {
            "00-namespace.yaml":    self._namespace(),
            "01-serviceaccount.yaml": self._service_account(),
            "02-configmap.yaml":    self._configmap(),
            "03-secret.yaml":       self._secret(),
            "04-deployment.yaml":   self._deployment(),
            "05-service.yaml":      self._service(),
            "06-networkpolicy.yaml":self._network_policy(),
            "07-pdb.yaml":          self._pdb(),
        }
        if self.cfg.k8s_ingress:
            files["08-ingress.yaml"] = self._ingress()
        if self.cfg.k8s_hpa:
            files["09-hpa.yaml"] = self._hpa()

        files["kustomization.yaml"] = self._kustomization(list(files.keys()))

        for fname, content in files.items():
            (self.k8s_dir / fname).write_text(content)

        return self.k8s_dir

    # ── Namespace ─────────────────────────────────────────────────────────────

    def _namespace(self) -> str:
        return f"""\
# ContainerForge - Namespace
apiVersion: v1
kind: Namespace
metadata:
  name: {self.ns}
  labels:
    app.kubernetes.io/managed-by: containerforge
    dev.containerforge/app: {self.name}
"""

    # ── ServiceAccount ────────────────────────────────────────────────────────

    def _service_account(self) -> str:
        return f"""\
# ContainerForge - ServiceAccount
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {self.name}
  namespace: {self.ns}
  labels:
    app.kubernetes.io/name: {self.name}
    app.kubernetes.io/managed-by: containerforge
automountServiceAccountToken: false
"""

    # ── ConfigMap ─────────────────────────────────────────────────────────────

    def _configmap(self) -> str:
        env_vars = self.d.get("env_vars", [])
        # Only non-secret env vars go in ConfigMap
        safe_vars = [v for v in env_vars if not self._is_secret(v)]
        data_lines = "\n".join(f'  {v}: ""  # set actual value' for v in safe_vars) or '  # No env vars detected'
        return f"""\
# ContainerForge - ConfigMap (non-sensitive config)
apiVersion: v1
kind: ConfigMap
metadata:
  name: {self.name}-config
  namespace: {self.ns}
  labels:
    app.kubernetes.io/name: {self.name}
    app.kubernetes.io/managed-by: containerforge
data:
  PORT: "{self.port}"
  LOG_LEVEL: "info"
{data_lines}
"""

    # ── Secret ────────────────────────────────────────────────────────────────

    def _secret(self) -> str:
        secret_vars = self.cfg.env_secrets or []
        if not secret_vars:
            secret_vars = [v for v in self.d.get("env_vars", []) if self._is_secret(v)]

        data_lines = "\n".join(
            f'  {v}: ""  # base64 encoded — use: echo -n "value" | base64'
            for v in secret_vars
        ) or '  # No secrets detected — add manually'

        return f"""\
# ContainerForge - Secret template
# ⚠  DO NOT commit real values. Use Sealed Secrets, External Secrets, or Vault.
apiVersion: v1
kind: Secret
metadata:
  name: {self.name}-secrets
  namespace: {self.ns}
  labels:
    app.kubernetes.io/name: {self.name}
    app.kubernetes.io/managed-by: containerforge
  annotations:
    # Use External Secrets Operator in production
    # externalsecrets.io/backend: vault
type: Opaque
data:
{data_lines}
"""

    # ── Deployment ────────────────────────────────────────────────────────────

    def _deployment(self) -> str:
        replicas = self.cfg.k8s_replicas
        lang = self.d.get("language", "python")
        # Resource presets by language
        resource_presets = {
            "python":  ("100m", "256Mi", "500m",  "512Mi"),
            "nodejs":  ("100m", "128Mi", "500m",  "256Mi"),
            "go":      ("50m",  "64Mi",  "200m",  "128Mi"),
            "java":    ("200m", "512Mi", "1000m", "1Gi"),
            "rust":    ("10m",  "32Mi",  "100m",  "64Mi"),
            "dotnet":  ("100m", "256Mi", "500m",  "512Mi"),
        }
        req_cpu, req_mem, lim_cpu, lim_mem = resource_presets.get(lang, ("100m", "256Mi", "500m", "512Mi"))

        secret_vars = self.cfg.env_secrets or [v for v in self.d.get("env_vars", []) if self._is_secret(v)]
        config_vars = [v for v in self.d.get("env_vars", []) if not self._is_secret(v)]

        secret_env = "\n".join(
            f"""\
        - name: {v}
          valueFrom:
            secretKeyRef:
              name: {self.name}-secrets
              key: {v}
              optional: true"""
            for v in secret_vars
        )

        config_env = "\n".join(
            f"""\
        - name: {v}
          valueFrom:
            configMapKeyRef:
              name: {self.name}-config
              key: {v}
              optional: true"""
            for v in config_vars
        )

        return f"""\
# ContainerForge - Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {self.name}
  namespace: {self.ns}
  labels:
    app.kubernetes.io/name: {self.name}
    app.kubernetes.io/version: "latest"
    app.kubernetes.io/managed-by: containerforge
    dev.containerforge/language: {lang}
  annotations:
    dev.containerforge/generated: "true"
spec:
  replicas: {replicas}
  selector:
    matchLabels:
      app.kubernetes.io/name: {self.name}
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0      # zero-downtime deployments
  template:
    metadata:
      labels:
        app.kubernetes.io/name: {self.name}
        app.kubernetes.io/version: "latest"
    spec:
      serviceAccountName: {self.name}
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 1001
        runAsGroup: 1001
        fsGroup: 1001
        seccompProfile:
          type: RuntimeDefault
      terminationGracePeriodSeconds: 30
      containers:
        - name: {self.name}
          image: {self.image}
          imagePullPolicy: Always
          ports:
            - name: http
              containerPort: {self.port}
              protocol: TCP
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          resources:
            requests:
              cpu: {req_cpu}
              memory: {req_mem}
            limits:
              cpu: {lim_cpu}
              memory: {lim_mem}
          # Liveness: restart if app is stuck
          livenessProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 20
            periodSeconds: 15
            failureThreshold: 3
            timeoutSeconds: 5
          # Readiness: only send traffic when ready
          readinessProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 10
            periodSeconds: 10
            failureThreshold: 3
            timeoutSeconds: 3
          # Startup: give slow apps more time to boot
          startupProbe:
            httpGet:
              path: /health
              port: http
            failureThreshold: 30
            periodSeconds: 5
          env:
            - name: PORT
              value: "{self.port}"
{secret_env}
{config_env}
          volumeMounts:
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir: {{}}
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app.kubernetes.io/name: {self.name}
                topologyKey: kubernetes.io/hostname
"""

    # ── Service ───────────────────────────────────────────────────────────────

    def _service(self) -> str:
        return f"""\
# ContainerForge - Service
apiVersion: v1
kind: Service
metadata:
  name: {self.name}
  namespace: {self.ns}
  labels:
    app.kubernetes.io/name: {self.name}
    app.kubernetes.io/managed-by: containerforge
spec:
  selector:
    app.kubernetes.io/name: {self.name}
  ports:
    - name: http
      port: 80
      targetPort: http
      protocol: TCP
  type: ClusterIP
"""

    # ── Ingress ───────────────────────────────────────────────────────────────

    def _ingress(self) -> str:
        host = self.cfg.k8s_ingress_host or f"{self.name}.example.com"
        return f"""\
# ContainerForge - Ingress
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {self.name}
  namespace: {self.ns}
  labels:
    app.kubernetes.io/name: {self.name}
    app.kubernetes.io/managed-by: containerforge
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - {host}
      secretName: {self.name}-tls
  rules:
    - host: {host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {self.name}
                port:
                  name: http
"""

    # ── HPA ───────────────────────────────────────────────────────────────────

    def _hpa(self) -> str:
        return f"""\
# ContainerForge - HorizontalPodAutoscaler
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {self.name}
  namespace: {self.ns}
  labels:
    app.kubernetes.io/name: {self.name}
    app.kubernetes.io/managed-by: containerforge
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {self.name}
  minReplicas: {self.cfg.k8s_min_replicas}
  maxReplicas: {self.cfg.k8s_max_replicas}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
"""

    # ── NetworkPolicy ─────────────────────────────────────────────────────────

    def _network_policy(self) -> str:
        return f"""\
# ContainerForge - NetworkPolicy (deny all, allow ingress on port + egress DNS)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {self.name}
  namespace: {self.ns}
  labels:
    app.kubernetes.io/name: {self.name}
    app.kubernetes.io/managed-by: containerforge
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: {self.name}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - ports:
        - port: {self.port}
          protocol: TCP
  egress:
    - ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
    - ports:
        - port: 443
          protocol: TCP
        - port: 80
          protocol: TCP
"""

    # ── PodDisruptionBudget ───────────────────────────────────────────────────

    def _pdb(self) -> str:
        return f"""\
# ContainerForge - PodDisruptionBudget
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {self.name}
  namespace: {self.ns}
  labels:
    app.kubernetes.io/name: {self.name}
    app.kubernetes.io/managed-by: containerforge
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: {self.name}
"""

    # ── Kustomization ─────────────────────────────────────────────────────────

    def _kustomization(self, resource_files: list) -> str:
        resources = "\n".join(f"  - {f}" for f in resource_files)
        return f"""\
# ContainerForge - Kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: {self.ns}

resources:
{resources}

commonLabels:
  app.kubernetes.io/managed-by: containerforge
  dev.containerforge/app: {self.name}
"""

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_secret(self, var_name: str) -> bool:
        secret_patterns = [
            "SECRET", "PASSWORD", "PASSWD", "TOKEN", "KEY", "PRIVATE",
            "CREDENTIAL", "AUTH", "API_KEY", "APIKEY", "DATABASE_URL",
            "CONNECTION_STRING", "CERT", "SIGNING",
        ]
        upper = var_name.upper()
        return any(p in upper for p in secret_patterns)
