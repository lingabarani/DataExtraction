"""
OneExtraction — Production Configuration Manager & AWS Secrets Integration
Enterprise-grade configuration management with AWS Secrets Manager support,
environment variable resolution, fail-fast production security gates,
and SEC EDGAR Fair Access User-Agent compliance.
"""

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

logger = logging.getLogger("dataextraction.config")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [CONFIG] %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

# Load local .env files if present (bottom-up: config dir, packages, and repo root)
_CURRENT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _CURRENT_DIR.parent.parent
for env_path in [_CURRENT_DIR / ".env", _CURRENT_DIR.parent / ".env", _REPO_ROOT / ".env"]:
    if env_path.exists():
        load_dotenv(env_path, override=True)


class ConfigurationError(Exception):
    """Raised when critical configuration or production security validations fail."""
    pass


# ── Known Insecure Default Secrets ─────────────────────────────────────────────
INSECURE_JWT_SECRETS = {
    "oneextraction-jwt-secret-change-in-prod",
    "secret",
    "changeme",
    "jwtsecret",
    "admin",
    "default",
}

INSECURE_DB_PASSWORDS = {
    "7903",
    "password",
    "postgres",
    "admin",
    "root",
    "123456",
}

INSECURE_ADMIN_PASSWORDS = {
    "admin123",
    "admin",
    "password",
    "123456",
}

# Regex for SEC EDGAR compliant User-Agent:
# Expected: "Sample Company Name AdminContact@domain.com" or "Company Name <AdminContact@domain.com>"
SEC_USER_AGENT_PATTERN = re.compile(
    r"^[A-Za-z0-9\s\.\-_/]+[\s<]+[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+>?$"
)


class ConfigManager:
    """
    Centralized configuration provider.
    Resolves configuration in priority order:
    1. System environment variables
    2. AWS Secrets Manager (if enabled or running in production)
    3. Local .env file
    4. Default values (with strict production guards)
    """

    _ephemeral_rsa_pair: Optional[Tuple[str, str]] = None

    def __init__(self):
        self._secrets_cache: Optional[Dict[str, Any]] = None
        self._env = os.getenv("ENVIRONMENT", os.getenv("APP_ENV", "development")).lower()

    @property
    def environment(self) -> str:
        return self._env

    @property
    def is_production(self) -> bool:
        return self._env in ("production", "prod")

    def _fetch_aws_secrets(self) -> Dict[str, Any]:
        """Fetch secrets dictionary from AWS Secrets Manager if configured."""
        if self._secrets_cache is not None:
            return self._secrets_cache

        secret_name = os.getenv("AWS_SECRETS_NAME")
        if not secret_name:
            self._secrets_cache = {}
            return self._secrets_cache

        region_name = os.getenv("AWS_DEFAULT_REGION", os.getenv("AWS_REGION", "us-east-1"))
        logger.info("Attempting to fetch production secrets from AWS Secrets Manager: %s (%s)", secret_name, region_name)

        try:
            import boto3
            from botocore.exceptions import ClientError

            client = boto3.client("secretsmanager", region_name=region_name)
            response = client.get_secret_value(SecretId=secret_name)
            if "SecretString" in response:
                secret_str = response["SecretString"]
                self._secrets_cache = json.loads(secret_str)
            elif "SecretBinary" in response:
                self._secrets_cache = json.loads(response["SecretBinary"].decode("utf-8"))
            else:
                self._secrets_cache = {}

            logger.info("Successfully loaded %d secrets from AWS Secrets Manager", len(self._secrets_cache))
            return self._secrets_cache

        except ImportError:
            logger.warning("boto3 not installed; skipping AWS Secrets Manager retrieval.")
            self._secrets_cache = {}
            return self._secrets_cache
        except Exception as e:
            if self.is_production:
                logger.error("CRITICAL: Failed to load required secrets from AWS Secrets Manager: %s", e)
                raise ConfigurationError(f"Production AWS Secrets Manager retrieval failed: {e}") from e
            logger.warning("Could not retrieve AWS Secrets Manager secrets (%s); falling back to environment.", e)
            self._secrets_cache = {}
            return self._secrets_cache

    def get(self, key: str, default: Any = None) -> Any:
        """
        Retrieve configuration value by key.
        In production, AWS Secrets Manager takes priority for managed secrets.
        Otherwise checks OS environment variables, then Secrets Manager, then default.
        """
        if self.is_production:
            secrets = self._fetch_aws_secrets()
            if key in secrets and secrets[key] is not None:
                return str(secrets[key])

        # Environment variable
        val = os.getenv(key)
        if val is not None and str(val).strip() != "":
            return val

        # Non-production AWS Secrets fallback
        secrets = self._fetch_aws_secrets()
        if key in secrets and secrets[key] is not None:
            return str(secrets[key])

        return default

    # ── Security & Authentication Config ──────────────────────────────────────

    def get_jwt_secret(self) -> str:
        """
        Retrieve JWT secret. Enforces production strength and disallows default keys.
        """
        secret = self.get("JWT_SECRET")

        if self.is_production:
            if not secret:
                raise ConfigurationError("FATAL: JWT_SECRET environment variable is missing in production environment!")
            if secret.strip() in INSECURE_JWT_SECRETS:
                raise ConfigurationError("FATAL: Insecure default JWT_SECRET detected in production! Change JWT_SECRET immediately.")
            if len(secret.strip()) < 32:
                raise ConfigurationError("FATAL: JWT_SECRET must be at least 32 characters in production.")

        return secret if secret else "oneextraction-jwt-secret-change-in-prod"

    def get_jwt_algorithm(self) -> str:
        return self.get("JWT_ALGORITHM", "HS256")

    def get_jwt_expiration_hours(self) -> int:
        return int(self.get("JWT_EXPIRATION_HOURS", 24))

    def get_jwt_private_key(self) -> str:
        """
        Retrieves RSA Private Key for RS256 token signing.
        Supports JWT_PRIVATE_KEY or file path via JWT_PRIVATE_KEY_PATH.
        Generates ephemeral 2048-bit RSA keypair in development if not explicitly configured.
        """
        key = self.get("JWT_PRIVATE_KEY")
        if not key:
            key_path = self.get("JWT_PRIVATE_KEY_PATH")
            if key_path and Path(key_path).exists():
                key = Path(key_path).read_text(encoding="utf-8")

        if key and "-----BEGIN" in key:
            return key.strip()

        if self.is_production:
            raise ConfigurationError(
                "FATAL: JWT_PRIVATE_KEY or JWT_PRIVATE_KEY_PATH must be provided for RS256 in production!"
            )

        if ConfigManager._ephemeral_rsa_pair is None:
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives import serialization
            priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            priv_pem = priv.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode("utf-8")
            pub_pem = priv.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("utf-8")
            ConfigManager._ephemeral_rsa_pair = (priv_pem, pub_pem)

        return ConfigManager._ephemeral_rsa_pair[0]

    def get_jwt_public_key(self) -> str:
        """
        Retrieves RSA Public Key for RS256 token verification.
        Supports JWT_PUBLIC_KEY or file path via JWT_PUBLIC_KEY_PATH.
        """
        key = self.get("JWT_PUBLIC_KEY")
        if not key:
            key_path = self.get("JWT_PUBLIC_KEY_PATH")
            if key_path and Path(key_path).exists():
                key = Path(key_path).read_text(encoding="utf-8")

        if key and "-----BEGIN" in key:
            return key.strip()

        if self.is_production:
            raise ConfigurationError(
                "FATAL: JWT_PUBLIC_KEY or JWT_PUBLIC_KEY_PATH must be provided for RS256 in production!"
            )

        if ConfigManager._ephemeral_rsa_pair is not None:
            return ConfigManager._ephemeral_rsa_pair[1]

        self.get_jwt_private_key()
        return ConfigManager._ephemeral_rsa_pair[1]

    def get_admin_credentials(self) -> Dict[str, str]:
        """
        Retrieve administrator credentials with production checks.
        """
        email = self.get("API_ADMIN_EMAIL", "admin@oneextraction.io").strip()
        password = self.get("API_ADMIN_PASSWORD", "admin123").strip()
        name = self.get("API_ADMIN_NAME", "Admin").strip()

        if self.is_production and password in INSECURE_ADMIN_PASSWORDS:
            raise ConfigurationError(
                "FATAL: Insecure default API_ADMIN_PASSWORD detected in production! Must be overridden."
            )

        return {"email": email, "password": password, "name": name}

    # ── Database Config ───────────────────────────────────────────────────────

    def get_database_config(self) -> Dict[str, Any]:
        """
        Retrieve database configuration. Validates production password safety.
        """
        db_type = (self.get("DATABASE_TYPE") or self.get("POSTGRES_TYPE") or "postgresql").lower()
        host = self.get("DATABASE_HOST") or self.get("POSTGRES_HOST") or "localhost"
        port = int(self.get("DATABASE_PORT") or self.get("POSTGRES_PORT") or 5432)
        dbname = self.get("DATABASE_NAME") or self.get("POSTGRES_DB") or "dataextraction"
        user = self.get("DATABASE_USER") or self.get("POSTGRES_USER") or "postgres"
        password = self.get("DATABASE_PASSWORD") or self.get("POSTGRES_PASSWORD") or "7903"
        base_pool = int(self.get("DATABASE_POOL_MIN") or self.get("POSTGRES_POOL_SIZE") or 5)
        max_overflow = int(self.get("DATABASE_POOL_MAX") or self.get("POSTGRES_MAX_OVERFLOW") or 20)
        if self.get("DATABASE_POOL_MIN") and self.get("DATABASE_POOL_MAX"):
            pool_min = int(self.get("DATABASE_POOL_MIN"))
            pool_max = int(self.get("DATABASE_POOL_MAX"))
        else:
            # Base pool + overflow mapping for psycopg2 / pgbouncer
            pool_min = min(base_pool, 5)
            pool_max = base_pool + max_overflow

        if pool_min > pool_max:
            pool_min, pool_max = pool_max, pool_min

        if self.is_production and db_type == "postgresql":
            if not password or password in INSECURE_DB_PASSWORDS:
                raise ConfigurationError(
                    "FATAL: Insecure or default DATABASE_PASSWORD detected in production!"
                )

        return {
            "type": db_type,
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": user,
            "password": password,
            "pool_min": pool_min,
            "pool_max": pool_max,
        }

    def get_database_url(self) -> str:
        """
        Retrieve validated database connection URL.
        Prioritizes explicit DATABASE_URL environment or secret, then constructs
        from verified structured database configuration.
        """
        direct_url = self.get("DATABASE_URL")
        if direct_url and str(direct_url).strip():
            return str(direct_url).strip()

        cfg = self.get_database_config()
        if cfg["type"] == "postgresql":
            user = cfg["user"]
            password = cfg.get("password", "")
            host = cfg["host"]
            port = cfg["port"]
            dbname = cfg["dbname"]
            auth = f"{user}:{password}@" if password else f"{user}@"
            return f"postgresql://{auth}{host}:{port}/{dbname}"
        return f"sqlite:///output/us/api/{cfg['dbname']}.db"

    # ── Lakehouse & Object Storage (MinIO / AWS S3) ───────────────────────────

    def get_lakehouse_config(self) -> Dict[str, Any]:
        """
        Retrieve Lakehouse & Object Storage configuration (MinIO / AWS S3).
        Sourced from AWS Secrets Manager or environment variables.
        """
        endpoint_url = self.get("LAKEHOUSE_ENDPOINT_URL")
        if endpoint_url:
            endpoint_url = str(endpoint_url).strip()
            if not endpoint_url:
                endpoint_url = None

        bucket_name = self.get("LAKEHOUSE_BUCKET_NAME", "dataextraction-lakehouse").strip()
        access_key = self.get("LAKEHOUSE_ACCESS_KEY", "minioadmin").strip()
        secret_key = self.get("LAKEHOUSE_SECRET_KEY", "miniopassword").strip()
        region_name = self.get("LAKEHOUSE_REGION", "us-east-1").strip()
        use_ssl = str(self.get("LAKEHOUSE_USE_SSL", "false")).lower() in ("true", "1", "yes")

        return {
            "endpoint_url": endpoint_url,
            "bucket_name": bucket_name,
            "access_key": access_key,
            "secret_key": secret_key,
            "region_name": region_name,
            "use_ssl": use_ssl,
        }

    # ── OpenSearch 2.x CDC Search Engine ──────────────────────────────────────

    def get_opensearch_config(self) -> Dict[str, Any]:
        """
        Retrieve validated OpenSearch 2.x configuration.
        """
        host = self.get("OPENSEARCH_HOST", "127.0.0.1").strip()
        port = int(self.get("OPENSEARCH_PORT", "9200"))
        user = self.get("OPENSEARCH_USER", "admin").strip()
        password = self.get("OPENSEARCH_PASSWORD", "admin").strip()
        use_ssl = str(self.get("OPENSEARCH_USE_SSL", "false")).lower() in ("true", "1", "yes")
        verify_certs = str(self.get("OPENSEARCH_VERIFY_CERTS", "false")).lower() in ("true", "1", "yes")
        index_companies = self.get("OPENSEARCH_INDEX_COMPANIES", "kg_companies_v1").strip()
        index_people = self.get("OPENSEARCH_INDEX_PEOPLE", "kg_people_v1").strip()
        batch_size = int(self.get("OPENSEARCH_BULK_BATCH_SIZE", "1000"))
        timeout = int(self.get("OPENSEARCH_TIMEOUT_SECONDS", "30"))

        return {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "use_ssl": use_ssl,
            "verify_certs": verify_certs,
            "index_companies": index_companies,
            "index_people": index_people,
            "batch_size": batch_size,
            "timeout": timeout,
            "base_url": f"{'https' if use_ssl else 'http'}://{host}:{port}",
        }

    # ── Temporal Orchestration & Agent Task Queues ────────────────────────────

    QUEUE_REGISTRY = "registry-ingestion-queue"
    QUEUE_GEOSPATIAL = "geospatial-domain-queue"
    QUEUE_IDENTITY = "identity-clustering-queue"
    QUEUE_EXECUTIVE = "executive-contact-queue"
    QUEUE_GOVERNANCE = "governance-quality-queue"
    QUEUE_SEARCH = "search-persistence-queue"

    def get_temporal_queues(self) -> Dict[str, str]:
        """
        Retrieve standardized Temporal Task Queue mapping for all 6 agents.
        Can be overridden via environment variables for custom deployment topologies.
        """
        return {
            "agent_1_registry": self.get("QUEUE_REGISTRY", self.QUEUE_REGISTRY),
            "agent_2_geospatial": self.get("QUEUE_GEOSPATIAL", self.QUEUE_GEOSPATIAL),
            "agent_3_identity": self.get("QUEUE_IDENTITY", self.QUEUE_IDENTITY),
            "agent_4_executive": self.get("QUEUE_EXECUTIVE", self.QUEUE_EXECUTIVE),
            "agent_5_governance": self.get("QUEUE_GOVERNANCE", self.QUEUE_GOVERNANCE),
            "agent_6_search": self.get("QUEUE_SEARCH", self.QUEUE_SEARCH),
        }

    # ── SEC EDGAR Compliance ──────────────────────────────────────────────────

    def validate_sec_user_agent(self, user_agent: Optional[str]) -> bool:
        """
        Validate User-Agent string against SEC EDGAR Fair Access policy.
        Must contain entity name and valid contact email.
        """
        if not user_agent:
            return False
        ua = str(user_agent).strip()
        if len(ua) < 10:
            return False
        # Disallow generic crawler headers
        generic_markers = ["python-requests", "curl/", "wget", "urllib", "oneextraction/1.0"]
        if ua.lower() in generic_markers or any(ua.lower().startswith(m) for m in generic_markers):
            return False

        return bool(SEC_USER_AGENT_PATTERN.match(ua))

    def get_sec_user_agent(self) -> str:
        """
        Retrieve validated SEC EDGAR User-Agent header.
        Raises ConfigurationError in production if invalid or missing.
        """
        ua = self.get("SEC_USER_AGENT")

        if ua and self.validate_sec_user_agent(ua):
            return ua.strip()

        if self.is_production:
            raise ConfigurationError(
                "FATAL: Valid SEC_USER_AGENT is required in production! Format: "
                "'Sample Company Name AdminContact@<sample company domain>.com'"
            )

        # Compliant fallback for development/testing
        default_ua = "OneExtraction Research admin@oneextraction.com"
        logger.debug("SEC_USER_AGENT not configured; using compliant development default: %s", default_ua)
        return default_ua

    def get_cors_origins(self) -> List[str]:
        """
        Retrieve validated list of allowed CORS origins.
        Sourced from CORS_ALLOWED_ORIGINS (comma-separated).
        """
        raw = self.get("CORS_ALLOWED_ORIGINS")
        if raw:
            origins = [o.strip() for o in raw.split(",") if o.strip()]
            if origins:
                return origins
        # Secure default origins for local development
        return [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        ]

    # ── Email Enrichment & SMTP Probe Config ──────────────────────────────────

    def get_email_enrichment_config(self) -> Dict[str, Any]:
        """
        Retrieve settings for asynchronous web crawl, contact page crawler,
        and domain tech stack analysis.
        """
        return {
            "rate_limit_per_second": float(self.get("EMAIL_ENRICHMENT_RATE_LIMIT", 50.0)),
            "per_host_limit": int(self.get("EMAIL_ENRICHMENT_PER_HOST_LIMIT", 2)),
            "total_timeout": float(self.get("EMAIL_ENRICHMENT_TIMEOUT_SECONDS", 10.0)),
            "connect_timeout": float(self.get("EMAIL_ENRICHMENT_CONNECT_TIMEOUT", 3.0)),
            "max_body_size": int(self.get("EMAIL_ENRICHMENT_MAX_BODY_SIZE_MB", 5)) * 1024 * 1024,
            "max_concurrent": int(self.get("EMAIL_ENRICHMENT_MAX_CONCURRENT", 100)),
            "user_agent": self.get("EMAIL_ENRICHMENT_USER_AGENT", "Mozilla/5.0 (compatible; DataExtractionBot/2.0; business-intelligence)"),
        }

    def get_smtp_probe_config(self) -> Dict[str, Any]:
        """
        Retrieve settings for active SMTP RCPT TO mailbox handshake and catch-all probing.
        Includes cloud port-25 bypass, authenticated relay, and DNS fallback options.
        """
        return {
            "probe_from": self.get("SMTP_PROBE_FROM", "verify@oneextraction.com"),
            "probe_ehlo": self.get("SMTP_PROBE_EHLO", "mail.oneextraction.com"),
            "timeout": float(self.get("SMTP_TIMEOUT_SECONDS", 5.0)),
            "rate_limit_delay": float(self.get("SMTP_PROBE_RATE_LIMIT_DELAY", 0.5)),
            "candidate_prefixes": [
                p.strip() for p in self.get("SMTP_CANDIDATE_PREFIXES", "info,contact,hello,office,sales").split(",") if p.strip()
            ],
            "max_mx_hosts_to_try": int(self.get("SMTP_MAX_MX_HOSTS", 3)),
            "relay_host": self.get("SMTP_RELAY_HOST", None),
            "relay_port": int(self.get("SMTP_RELAY_PORT", 587)),
            "relay_user": self.get("SMTP_RELAY_USER", None),
            "relay_password": self.get("SMTP_RELAY_PASSWORD", None),
            "probe_port": int(self.get("SMTP_PROBE_PORT", 25)),
            "fallback_mx_on_blocked_port": str(self.get("SMTP_FALLBACK_MX_ON_BLOCKED_PORT", "true")).lower() == "true",
        }

    # ── Ollama LLM Configuration ──────────────────────────────────────────────

    def get_ollama_config(self) -> Dict[str, Any]:
        """
        Retrieve settings for Ollama local/cluster LLM service integration.
        Controls base URL, target model, request timeouts, keep-alive heartbeat,
        and circuit breaker thresholds.
        """
        return {
            "base_url": self.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
            "model": self.get("OLLAMA_MODEL", "llama3.1:8b"),
            "timeout_seconds": float(self.get("OLLAMA_TIMEOUT_SECONDS", 5.0)),
            "batch_timeout_seconds": float(self.get("OLLAMA_BATCH_TIMEOUT_SECONDS", 30.0)),
            "keep_alive": self.get("OLLAMA_KEEP_ALIVE", "30m"),
            "circuit_breaker_threshold": int(self.get("OLLAMA_CIRCUIT_BREAKER_THRESHOLD", 3)),
            "circuit_breaker_recovery_seconds": float(self.get("OLLAMA_CIRCUIT_BREAKER_RECOVERY_SECONDS", 60.0)),
            "enabled": str(self.get("OLLAMA_ENABLED", "true")).lower() in ("true", "1", "yes"),
        }

    # ── AI Agent & Normalization Capabilities ─────────────────────────────────

    def get_agent_ai_config(self) -> Dict[str, Any]:
        """
        Retrieve settings for AI agent capabilities across Agent 3 (Entity Resolution Adjudicator),
        Agent 4 (Executive Normalizer), and Agent 5 (Industry Classifier).
        """
        return {
            "entity_adjudication_enabled": str(self.get("LLM_ENTITY_ADJUDICATION_ENABLED", "true")).lower() in ("true", "1", "yes"),
            "entity_adjudication_timeout": float(self.get("LLM_ENTITY_ADJUDICATION_TIMEOUT", 10.0)),
            "normalization_enabled": str(self.get("LLM_NORMALIZATION_ENABLED", "true")).lower() in ("true", "1", "yes"),
            "normalization_timeout": float(self.get("LLM_NORMALIZATION_TIMEOUT", 5.0)),
            "batch_concurrency": int(self.get("LLM_BATCH_CONCURRENCY", 5)),
            "quarantine_min_threshold": float(self.get("SPLINK_QUARANTINE_MIN_PROB", 0.70)),
            "quarantine_max_threshold": float(self.get("SPLINK_QUARANTINE_MAX_PROB", 0.95)),
        }

    # ── Promotion Gate & Governance Configuration ─────────────────────────────

    def get_promotion_gate_config(self) -> Dict[str, Any]:
        """
        Configuration for Promotion Gate thresholds, batch chunks, and freshness initialization.
        Eliminates hardcoded governance and certification parameters.
        """
        return {
            "min_quality_score": int(self.get("PROMOTION_MIN_QUALITY_SCORE", 80)),
            "min_trust_score": float(self.get("PROMOTION_MIN_TRUST_SCORE", 0.8500)),
            "batch_chunk_size": int(self.get("PROMOTION_BATCH_CHUNK_SIZE", 5000)),
            "freshness_initial_score": float(self.get("PROMOTION_INITIAL_FRESHNESS", 1.0000)),
            "revalidation_interval_days": int(self.get("PROMOTION_REVALIDATION_INTERVAL_DAYS", 90)),
        }

    # ── Freshness Engine & Revalidation Configuration ──────────────────────────

    def get_freshness_engine_config(self) -> Dict[str, Any]:
        """
        Configuration for continuous freshness scoring decay and SLA thresholds.
        Eliminates hardcoded decay batch sizes, reharvest intervals, and stale score cutoffs.
        """
        return {
            "decay_batch_size": int(self.get("FRESHNESS_DECAY_BATCH_SIZE", 5000)),
            "overdue_fetch_limit": int(self.get("FRESHNESS_OVERDUE_LIMIT", 5000)),
            "stale_threshold": float(self.get("FRESHNESS_STALE_THRESHOLD", 0.70)),
            "reharvest_batch_size": int(self.get("FRESHNESS_REHARVEST_BATCH_SIZE", 1000)),
        }



# Global singleton instance
config_manager = ConfigManager()


def get_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    """Convenience helper to retrieve configuration or secret value."""
    return config_manager.get(key, default)
