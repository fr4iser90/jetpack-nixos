import os


def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key, "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
MAX_TOOL_ROUNDS = int(os.environ.get("AGENT_MAX_TOOL_ROUNDS", "8"))
DATA_DIR = os.environ.get("AGENT_DATA_DIR", "/data")
OPTIONAL_API_KEY = os.environ.get("AGENT_API_KEY", "").strip()
SYSTEM_PROMPT_EXTRA = os.environ.get("AGENT_SYSTEM_PROMPT", "").strip()

# If Ollama returns no tool_calls but JSON tool intent in message content (e.g. Nemotron), parse and run.
CONTENT_TOOL_FALLBACK = _env_bool("AGENT_CONTENT_TOOL_FALLBACK", True)

# postgresql://USER:PASSWORD@HOST:5432/DBNAME
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Optional directory of extra *.py plugins (same TOOLS/HANDLERS contract as app.plugins).
PLUGINS_EXTRA_DIR = os.environ.get("AGENT_PLUGINS_EXTRA_DIR", "").strip()

# Comma-separated SHA256 hex digests (64 chars). If set, each extra *.py must match one entry.
# Read on each extra-plugin scan (reload) so container env updates take effect without code change.
# Multi-tenant HTTP: stable user id per request (comma-separated header names; first non-empty wins).
# Default fits Open WebUI with ENABLE_FORWARD_USER_INFO_HEADERS=true (X-OpenWebUI-User-Id).
# Without AGENT_API_KEY, clients can spoof headers.
def _user_sub_headers() -> list[str]:
    raw = (os.environ.get("AGENT_USER_SUB_HEADER") or "").strip()
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    return ["X-OpenWebUI-User-Id", "X-Agent-User-Sub"]


USER_SUB_HEADERS = _user_sub_headers()
TENANT_ID_HEADER = (os.environ.get("AGENT_TENANT_ID_HEADER") or "X-Agent-Tenant-Id").strip()
DEFAULT_EXTERNAL_SUB = (os.environ.get("AGENT_DEFAULT_EXTERNAL_SUB") or "default").strip() or "default"

# Fernet URL-safe base64 key for encrypting user_secrets at rest (generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
SECRETS_MASTER_KEY = (os.environ.get("AGENT_SECRETS_MASTER_KEY") or "").strip()

# Optional base URL for curl examples in register_secrets / secrets_help (e.g. https://agent.example.com). Else 127.0.0.1:AGENT_HTTP_PORT.
PUBLIC_BASE_URL = (os.environ.get("AGENT_PUBLIC_URL") or "").strip().rstrip("/")
HTTP_EXAMPLE_PORT = (os.environ.get("AGENT_HTTP_PORT") or "8088").strip()


def plugins_allowed_sha256() -> frozenset[str] | None:
    raw = os.environ.get("AGENT_PLUGINS_ALLOWED_SHA256", "").strip()
    if not raw:
        return None
    digests = frozenset(p.strip().lower() for p in raw.split(",") if p.strip())
    return digests if digests else None
