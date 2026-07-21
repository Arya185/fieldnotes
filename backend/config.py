"""Configuration and startup validation for Fieldnotes backend."""

from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.sandbox.environment import build_sandbox_environment


ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"
DEMO_COURSE_DIR = ROOT_DIR / "demo_course"
RELEASE_ARTIFACTS_DIR = ROOT_DIR / "scripts" / "release_artifacts"
FIELDNOTES_VERSION = "1.0.0-beta.1"

WORKSPACE_REGISTRY_DIR = ROOT_DIR / ".fieldnotes_registry"
WORKSPACE_REGISTRY_PATH = WORKSPACE_REGISTRY_DIR / "workspaces.json"

VALID_RETRIEVAL_PROVIDERS = {"bm25", "hybrid", "vector"}
VALID_EMBEDDINGS_PROVIDERS = {"deterministic", "fastembed"}


def load_project_dotenv(env_path: Path | None = None) -> bool:
    """Load project-root .env values without overriding existing shell variables."""

    target = env_path or (ROOT_DIR / ".env")
    if not target.exists():
        return False

    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)
    return True


load_project_dotenv()

DEFAULT_RETRIEVAL_PROVIDER = "hybrid"
DEFAULT_EMBEDDINGS_PROVIDER = "deterministic"
DEFAULT_EMBEDDING_MODEL = "hash-v1"
DEFAULT_BM25_WEIGHT = "0.5"
DEFAULT_VECTOR_WEIGHT = "0.5"
DEFAULT_MAX_RETRIEVAL_CANDIDATES = "12"
DEFAULT_MAX_CONTEXT_CHUNKS = "5"
DEFAULT_MAX_CONTEXT_TOKENS = "1200"
DEFAULT_ENABLE_TRACING = "0"
DEFAULT_ENABLE_METRICS = "1"
DEFAULT_VERBOSE_TRACING = "0"
DEFAULT_USE_FAKE_LLM = "0"
DEFAULT_OPENAI_MODEL = "gpt-5"
DEFAULT_OPENAI_API_KEY = ""
DEFAULT_OPENAI_BASE_URL = ""
DEFAULT_TRUSTED_ORIGINS = (
    "http://localhost:5173,"
    "http://127.0.0.1:5173,"
    "http://localhost:3000,"
    "http://127.0.0.1:3000"
)

logger = logging.getLogger("fieldnotes.startup")

RETRIEVAL_PROVIDER = os.environ.get("FIELDNOTES_RETRIEVAL_PROVIDER", DEFAULT_RETRIEVAL_PROVIDER)
EMBEDDINGS_PROVIDER = os.environ.get("FIELDNOTES_EMBEDDINGS_PROVIDER", DEFAULT_EMBEDDINGS_PROVIDER)
EMBEDDING_MODEL = os.environ.get("FIELDNOTES_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
BM25_WEIGHT = os.environ.get("FIELDNOTES_BM25_WEIGHT", DEFAULT_BM25_WEIGHT)
VECTOR_WEIGHT = os.environ.get("FIELDNOTES_VECTOR_WEIGHT", DEFAULT_VECTOR_WEIGHT)
MAX_RETRIEVAL_CANDIDATES = os.environ.get("FIELDNOTES_MAX_RETRIEVAL_CANDIDATES", DEFAULT_MAX_RETRIEVAL_CANDIDATES)
MAX_CONTEXT_CHUNKS = os.environ.get("FIELDNOTES_MAX_CONTEXT_CHUNKS", DEFAULT_MAX_CONTEXT_CHUNKS)
MAX_CONTEXT_TOKENS = os.environ.get("FIELDNOTES_MAX_CONTEXT_TOKENS", DEFAULT_MAX_CONTEXT_TOKENS)
ENABLE_TRACING = os.environ.get("FIELDNOTES_ENABLE_TRACING", DEFAULT_ENABLE_TRACING)
ENABLE_METRICS = os.environ.get("FIELDNOTES_ENABLE_METRICS", DEFAULT_ENABLE_METRICS)
VERBOSE_TRACING = os.environ.get("FIELDNOTES_VERBOSE_TRACING", DEFAULT_VERBOSE_TRACING)
USE_FAKE_LLM = os.environ.get("FIELDNOTES_USE_FAKE_LLM", DEFAULT_USE_FAKE_LLM)
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", DEFAULT_OPENAI_API_KEY)
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL)
TRUSTED_ORIGINS = frozenset(
    origin
    for origin in (
        item.strip()
        for item in os.environ.get("FIELDNOTES_TRUSTED_ORIGINS", DEFAULT_TRUSTED_ORIGINS).split(",")
    )
    if origin
)


class ConfigurationError(ValueError):
    """Raised when process configuration is invalid."""


def format_missing_openai_api_key_message() -> str:
    """Return actionable guidance when live mode lacks credentials."""

    return (
        "Missing OPENAI_API_KEY.\n\n"
        "Either:\n"
        "1. export OPENAI_API_KEY=your_key\n"
        "2. export FIELDNOTES_USE_FAKE_LLM=1"
    )


def determine_llm_mode() -> str:
    """Resolve effective LLM mode from current environment."""

    api_key = env_value("OPENAI_API_KEY", DEFAULT_OPENAI_API_KEY).strip()
    if api_key:
        return "live"
    if parse_env_flag(env_value("FIELDNOTES_USE_FAKE_LLM", DEFAULT_USE_FAKE_LLM)):
        return "fake"
    return "fake"


def apply_startup_llm_mode() -> str:
    """Apply effective startup LLM mode and emit operator-facing logs."""

    api_key = env_value("OPENAI_API_KEY", DEFAULT_OPENAI_API_KEY).strip()
    fake_requested = parse_env_flag(env_value("FIELDNOTES_USE_FAKE_LLM", DEFAULT_USE_FAKE_LLM))

    if api_key:
        os.environ["FIELDNOTES_USE_FAKE_LLM"] = "0"
        logger.info("OpenAI API detected. Running in live mode.")
        return "live"
    if fake_requested:
        os.environ["FIELDNOTES_USE_FAKE_LLM"] = "1"
        logger.info("Running in fake LLM mode.")
        return "fake"

    os.environ["FIELDNOTES_USE_FAKE_LLM"] = "1"
    logger.warning("No OPENAI_API_KEY detected.")
    logger.warning("Falling back to fake LLM mode.")
    logger.warning("Set OPENAI_API_KEY to enable live OpenAI responses.")
    return "fake"


@dataclass(frozen=True)
class StartupDiagnostics:
    version: str
    build_timestamp: str
    git_commit_hash: str | None
    retrieval_provider: str
    embeddings_provider: str
    embedding_model: str
    bm25_weight: float
    vector_weight: float
    max_retrieval_candidates: int
    max_context_chunks: int
    max_context_tokens: int
    startup_checks: dict[str, str]


def validate_retrieval_provider_name(name: str) -> str:
    """Validate configured retrieval provider name."""

    if name not in VALID_RETRIEVAL_PROVIDERS:
        raise ConfigurationError(
            f"Unknown FIELDNOTES_RETRIEVAL_PROVIDER: {name}. "
            f"Expected one of: {', '.join(sorted(VALID_RETRIEVAL_PROVIDERS))}"
        )
    return name


def validate_embeddings_provider_name(name: str) -> str:
    """Validate configured embeddings provider name."""

    if name not in VALID_EMBEDDINGS_PROVIDERS:
        raise ConfigurationError(
            f"Unknown FIELDNOTES_EMBEDDINGS_PROVIDER: {name}. "
            f"Expected one of: {', '.join(sorted(VALID_EMBEDDINGS_PROVIDERS))}"
        )
    return name


def validate_embedding_model_name(name: str) -> str:
    """Validate configured embedding model name."""

    normalized = name.strip()
    if not normalized:
        raise ConfigurationError("FIELDNOTES_EMBEDDING_MODEL must not be empty")
    return normalized


def validate_fusion_weight(name: str, value: str) -> float:
    """Validate retrieval fusion weight from environment."""

    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be numeric, got: {value}") from exc
    if parsed < 0:
        raise ConfigurationError(f"{name} must be >= 0, got: {value}")
    return parsed


def validate_positive_int(name: str, value: str) -> int:
    """Validate positive integer configuration."""

    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be integer, got: {value}") from exc
    if parsed <= 0:
        raise ConfigurationError(f"{name} must be > 0, got: {value}")
    return parsed


def parse_env_flag(value: str) -> bool:
    """Parse boolean-like environment flag."""

    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_value(name: str, default: str) -> str:
    """Read current environment value with fallback."""

    return os.environ.get(name, default)


def validate_runtime_configuration() -> StartupDiagnostics:
    """Validate startup configuration and local runtime prerequisites."""

    retrieval_provider = validate_retrieval_provider_name(
        env_value("FIELDNOTES_RETRIEVAL_PROVIDER", DEFAULT_RETRIEVAL_PROVIDER)
    )
    embeddings_provider = validate_embeddings_provider_name(
        env_value("FIELDNOTES_EMBEDDINGS_PROVIDER", DEFAULT_EMBEDDINGS_PROVIDER)
    )
    embedding_model = validate_embedding_model_name(
        env_value("FIELDNOTES_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    )
    bm25_weight = validate_fusion_weight(
        "FIELDNOTES_BM25_WEIGHT",
        env_value("FIELDNOTES_BM25_WEIGHT", DEFAULT_BM25_WEIGHT),
    )
    vector_weight = validate_fusion_weight(
        "FIELDNOTES_VECTOR_WEIGHT",
        env_value("FIELDNOTES_VECTOR_WEIGHT", DEFAULT_VECTOR_WEIGHT),
    )
    max_retrieval_candidates = validate_positive_int(
        "FIELDNOTES_MAX_RETRIEVAL_CANDIDATES",
        env_value("FIELDNOTES_MAX_RETRIEVAL_CANDIDATES", DEFAULT_MAX_RETRIEVAL_CANDIDATES),
    )
    max_context_chunks = validate_positive_int(
        "FIELDNOTES_MAX_CONTEXT_CHUNKS",
        env_value("FIELDNOTES_MAX_CONTEXT_CHUNKS", DEFAULT_MAX_CONTEXT_CHUNKS),
    )
    max_context_tokens = validate_positive_int(
        "FIELDNOTES_MAX_CONTEXT_TOKENS",
        env_value("FIELDNOTES_MAX_CONTEXT_TOKENS", DEFAULT_MAX_CONTEXT_TOKENS),
    )

    llm_mode = apply_startup_llm_mode()
    fake_llm = llm_mode == "fake"

    startup_checks = {
        "responses_api": "ok" if fake_llm else "configured",
        "workspace_permissions": _validate_workspace_permissions(),
        "sqlite_write_access": _validate_sqlite_write_access(),
        "sandbox": _validate_sandbox_runtime(),
    }

    return StartupDiagnostics(
        version=FIELDNOTES_VERSION,
        build_timestamp=datetime.now(UTC).isoformat(),
        git_commit_hash=_resolve_git_commit_hash(),
        retrieval_provider=retrieval_provider,
        embeddings_provider=embeddings_provider,
        embedding_model=embedding_model,
        bm25_weight=bm25_weight,
        vector_weight=vector_weight,
        max_retrieval_candidates=max_retrieval_candidates,
        max_context_chunks=max_context_chunks,
        max_context_tokens=max_context_tokens,
        startup_checks=startup_checks,
    )


def _validate_workspace_permissions() -> str:
    WORKSPACE_REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    probe = WORKSPACE_REGISTRY_DIR / ".write_probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)
    return "ok"


def _validate_sqlite_write_access() -> str:
    WORKSPACE_REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    probe_db = WORKSPACE_REGISTRY_DIR / ".startup_probe.db"
    connection = sqlite3.connect(probe_db)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS probe (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO probe DEFAULT VALUES")
        connection.commit()
    finally:
        connection.close()
    probe_db.unlink(missing_ok=True)
    return "ok"


def _validate_sandbox_runtime() -> str:
    if not Path(sys.executable).exists():
        raise ConfigurationError(f"Python executable not found: {sys.executable}")
    if sys.platform != "win32":
        try:
            import resource  # noqa: F401
        except Exception as exc:  # pragma: no cover
            raise ConfigurationError("resource module unavailable for sandbox limits") from exc

    with TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        workspace_root = temp_root / "workspace"
        artifacts_dir = workspace_root / "artifacts"
        workspace_root.mkdir()
        artifacts_dir.mkdir()
        script = temp_root / "probe.py"
        result_path = artifacts_dir / "result.json"
        script.write_text(
            "write_result({'ok': True})\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            [sys.executable, "-I", str(ROOT_DIR / "backend" / "sandbox" / "runtime_runner.py")],
            cwd=workspace_root,
            env=build_sandbox_environment(
                workspace_root=workspace_root,
                artifacts_dir=artifacts_dir,
                script_path=script,
                result_path=result_path,
                chart_path=artifacts_dir / "chart.png",
            ),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if completed.returncode != 0 or not result_path.exists():
            raise ConfigurationError(
                "Sandbox availability check failed: "
                f"{completed.stderr.strip() or completed.stdout.strip() or 'no result payload'}"
            )
    return "ok"


def _resolve_git_commit_hash() -> str | None:
    git_dir = ROOT_DIR / ".git"
    if not git_dir.exists():
        return None
    head = git_dir / "HEAD"
    if not head.exists():
        return None
    head_value = head.read_text(encoding="utf-8").strip()
    if head_value.startswith("ref: "):
        ref_path = git_dir / head_value[5:]
        if ref_path.exists():
            return ref_path.read_text(encoding="utf-8").strip()[:12]
        return None
    return head_value[:12]
