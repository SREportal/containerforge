"""
DatabaseWirer: Detects database dependencies and injects them into docker-compose.yml.

Scans requirements/package.json/go.mod for DB client packages and env vars
for connection strings. Adds the correct database service, volume, and
network links automatically.
"""

from pathlib import Path
from typing import Optional


# ─── DB service templates ──────────────────────────────────────────────────────

DB_SERVICES = {
    "postgres": {
        "display": "PostgreSQL",
        "image": "postgres:16-alpine",
        "port": 5432,
        "env_vars": {
            "POSTGRES_DB": "${DB_NAME:-appdb}",
            "POSTGRES_USER": "${DB_USER:-appuser}",
            "POSTGRES_PASSWORD": "${DB_PASSWORD:-changeme}",
        },
        "healthcheck": 'pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}',
        "volume": "postgres_data:/var/lib/postgresql/data",
        "app_env": {
            "DATABASE_URL": "postgresql://${DB_USER:-appuser}:${DB_PASSWORD:-changeme}@postgres:5432/${DB_NAME:-appdb}",
        },
    },
    "mysql": {
        "display": "MySQL",
        "image": "mysql:8-oracle",
        "port": 3306,
        "env_vars": {
            "MYSQL_DATABASE": "${DB_NAME:-appdb}",
            "MYSQL_USER": "${DB_USER:-appuser}",
            "MYSQL_PASSWORD": "${DB_PASSWORD:-changeme}",
            "MYSQL_ROOT_PASSWORD": "${DB_ROOT_PASSWORD:-rootpassword}",
        },
        "healthcheck": "mysqladmin ping -h localhost",
        "volume": "mysql_data:/var/lib/mysql",
        "app_env": {
            "DATABASE_URL": "mysql://${DB_USER:-appuser}:${DB_PASSWORD:-changeme}@mysql:3306/${DB_NAME:-appdb}",
        },
    },
    "redis": {
        "display": "Redis",
        "image": "redis:7-alpine",
        "port": 6379,
        "env_vars": {},
        "healthcheck": "redis-cli ping",
        "volume": "redis_data:/data",
        "app_env": {
            "REDIS_URL": "redis://redis:6379/0",
        },
    },
    "mongodb": {
        "display": "MongoDB",
        "image": "mongo:7",
        "port": 27017,
        "env_vars": {
            "MONGO_INITDB_ROOT_USERNAME": "${MONGO_USER:-appuser}",
            "MONGO_INITDB_ROOT_PASSWORD": "${MONGO_PASSWORD:-changeme}",
            "MONGO_INITDB_DATABASE": "${DB_NAME:-appdb}",
        },
        "healthcheck": "mongosh --eval 'db.adminCommand(\"ping\")'",
        "volume": "mongo_data:/data/db",
        "app_env": {
            "MONGODB_URI": "mongodb://${MONGO_USER:-appuser}:${MONGO_PASSWORD:-changeme}@mongodb:27017/${DB_NAME:-appdb}",
        },
    },
    "elasticsearch": {
        "display": "Elasticsearch",
        "image": "elasticsearch:8.13.0",
        "port": 9200,
        "env_vars": {
            "discovery.type": "single-node",
            "ES_JAVA_OPTS": "-Xms512m -Xmx512m",
            "xpack.security.enabled": "false",
        },
        "healthcheck": "curl -sf http://localhost:9200/_cluster/health",
        "volume": "es_data:/usr/share/elasticsearch/data",
        "app_env": {
            "ELASTICSEARCH_URL": "http://elasticsearch:9200",
        },
    },
    "rabbitmq": {
        "display": "RabbitMQ",
        "image": "rabbitmq:3-management-alpine",
        "port": 5672,
        "env_vars": {
            "RABBITMQ_DEFAULT_USER": "${RABBITMQ_USER:-appuser}",
            "RABBITMQ_DEFAULT_PASS": "${RABBITMQ_PASSWORD:-changeme}",
        },
        "healthcheck": "rabbitmq-diagnostics -q ping",
        "volume": "rabbitmq_data:/var/lib/rabbitmq",
        "app_env": {
            "RABBITMQ_URL": "amqp://${RABBITMQ_USER:-appuser}:${RABBITMQ_PASSWORD:-changeme}@rabbitmq:5672/",
        },
    },
    "kafka": {
        "display": "Apache Kafka",
        "image": "confluentinc/cp-kafka:7.6.0",
        "port": 9092,
        "env_vars": {
            "KAFKA_BROKER_ID": "1",
            "KAFKA_ZOOKEEPER_CONNECT": "zookeeper:2181",
            "KAFKA_ADVERTISED_LISTENERS": "PLAINTEXT://kafka:9092",
            "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR": "1",
        },
        "healthcheck": "kafka-broker-api-versions --bootstrap-server localhost:9092",
        "volume": "kafka_data:/var/lib/kafka/data",
        "app_env": {
            "KAFKA_BROKERS": "kafka:9092",
        },
    },
    "sqlite": {
        "display": "SQLite (local file)",
        "image": None,  # No container needed
        "port": None,
        "env_vars": {},
        "healthcheck": None,
        "volume": "sqlite_data:/app/data",
        "app_env": {
            "DATABASE_URL": "sqlite:////app/data/app.db",
        },
    },
}

# ─── Detection signals per DB ─────────────────────────────────────────────────

DB_SIGNALS = {
    "postgres": {
        "python": ["psycopg2", "psycopg", "asyncpg", "databases[postgresql]", "sqlalchemy"],
        "nodejs": ["pg", "pg-native", "postgres", "@prisma/client"],
        "go": ["pq", "pgx", "gorm.io/driver/postgres"],
        "java": ["postgresql", "spring-boot-starter-data-jpa"],
        "ruby": ["pg", "activerecord-postgresql"],
        "rust": ["sqlx", "diesel"],
        "env": ["DATABASE_URL", "POSTGRES_URL", "PG_URL", "DB_HOST"],
    },
    "mysql": {
        "python": ["mysqlclient", "pymysql", "aiomysql", "databases[mysql]"],
        "nodejs": ["mysql", "mysql2", "sequelize"],
        "go": ["gorm.io/driver/mysql", "go-sql-driver/mysql"],
        "java": ["mysql-connector-java", "spring-boot-starter-data-jpa"],
        "ruby": ["mysql2"],
        "env": ["MYSQL_URL", "DATABASE_URL"],
    },
    "redis": {
        "python": ["redis", "aioredis", "hiredis", "celery"],
        "nodejs": ["redis", "ioredis", "bull", "bullmq"],
        "go": ["go-redis", "redigo"],
        "java": ["spring-boot-starter-data-redis", "lettuce"],
        "ruby": ["redis", "sidekiq"],
        "env": ["REDIS_URL", "CACHE_URL", "CELERY_BROKER_URL"],
    },
    "mongodb": {
        "python": ["pymongo", "motor", "mongoengine"],
        "nodejs": ["mongodb", "mongoose"],
        "go": ["mongo-driver"],
        "java": ["spring-boot-starter-data-mongodb"],
        "ruby": ["mongoid", "mongo"],
        "env": ["MONGODB_URI", "MONGO_URL", "MONGO_URI"],
    },
    "elasticsearch": {
        "python": ["elasticsearch", "elasticsearch-async"],
        "nodejs": ["@elastic/elasticsearch"],
        "go": ["elastic/go-elasticsearch"],
        "java": ["spring-boot-starter-data-elasticsearch"],
        "env": ["ELASTICSEARCH_URL", "ES_URL"],
    },
    "rabbitmq": {
        "python": ["pika", "aio-pika", "celery[rabbitmq]"],
        "nodejs": ["amqplib", "amqp-connection-manager"],
        "go": ["streadway/amqp", "rabbitmq/amqp091-go"],
        "java": ["spring-boot-starter-amqp"],
        "env": ["RABBITMQ_URL", "AMQP_URL", "BROKER_URL"],
    },
}


def detect_databases(detection: dict, app_path: Path) -> list:
    """Auto-detect which databases the app needs based on dependencies and env vars."""
    language = detection.get("language", "unknown")
    env_vars = [v.upper() for v in detection.get("env_vars", [])]
    deps_text = _read_deps(app_path, language).lower()
    found = []

    for db, signals in DB_SIGNALS.items():
        # Check language-specific dep signals
        lang_signals = signals.get(language, [])
        if any(s.lower() in deps_text for s in lang_signals):
            found.append(db)
            continue
        # Check env var signals
        env_signals = signals.get("env", [])
        if any(e in env_vars for e in env_signals):
            found.append(db)

    return found


def render_db_services(db_names: list) -> str:
    """Render docker-compose service blocks for all requested databases."""
    blocks = []
    for name in db_names:
        spec = DB_SERVICES.get(name)
        if not spec or spec["image"] is None:
            continue
        blocks.append(_render_service(name, spec))
    return "\n".join(blocks)


def render_db_volumes(db_names: list) -> str:
    """Render docker-compose volume declarations."""
    volumes = []
    for name in db_names:
        spec = DB_SERVICES.get(name)
        if spec and spec.get("volume"):
            vol_name = spec["volume"].split(":")[0]
            volumes.append(f"  {vol_name}:")
    return "\n".join(volumes)


def render_app_env_additions(db_names: list) -> str:
    """Render env vars to add to the app service for DB connections."""
    lines = []
    for name in db_names:
        spec = DB_SERVICES.get(name)
        if spec:
            for k, v in spec.get("app_env", {}).items():
                lines.append(f"      - {k}={v}")
    return "\n".join(lines)


def render_depends_on(db_names: list) -> str:
    """Render depends_on block for healthy DB services."""
    lines = []
    for name in db_names:
        spec = DB_SERVICES.get(name)
        if spec and spec["image"] and spec.get("healthcheck"):
            lines.append(f"      {name}:")
            lines.append(f"        condition: service_healthy")
    return "\n".join(lines)


def _render_service(name: str, spec: dict) -> str:
    lines = [f"  # ── {spec['display']} ──────────────────────────────────────"]
    lines.append(f"  {name}:")
    lines.append(f"    image: {spec['image']}")
    lines.append(f"    restart: unless-stopped")

    if spec["env_vars"]:
        lines.append(f"    environment:")
        for k, v in spec["env_vars"].items():
            lines.append(f"      - {k}={v}")

    if spec["port"]:
        lines.append(f"    ports:")
        lines.append(f"      - \"{spec['port']}:{spec['port']}\"")

    if spec["volume"]:
        lines.append(f"    volumes:")
        lines.append(f"      - {spec['volume']}")

    if spec["healthcheck"]:
        lines.append(f"    healthcheck:")
        lines.append(f"      test: [\"CMD-SHELL\", \"{spec['healthcheck']}\"]")
        lines.append(f"      interval: 10s")
        lines.append(f"      timeout: 5s")
        lines.append(f"      retries: 5")
        lines.append(f"      start_period: 30s")

    lines.append(f"    networks:")
    lines.append(f"      - forge-net")
    lines.append("")

    return "\n".join(lines)


def _read_deps(app_path: Path, language: str) -> str:
    dep_files = {
        "python": ["requirements.txt", "pyproject.toml", "Pipfile"],
        "nodejs": ["package.json"],
        "go": ["go.mod"],
        "java": ["pom.xml", "build.gradle"],
        "ruby": ["Gemfile"],
        "rust": ["Cargo.toml"],
    }
    texts = []
    for fname in dep_files.get(language, []):
        p = app_path / fname
        if p.exists():
            try:
                texts.append(p.read_text(errors="ignore"))
            except Exception:
                pass
    return " ".join(texts)
