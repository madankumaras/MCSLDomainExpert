import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

BASE_DIR = Path(__file__).parent

# Anthropic / Claude
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Primary model — deep reasoning, code gen, visual exploration
CLAUDE_SONNET_MODEL = os.getenv("CLAUDE_SONNET_MODEL", "claude-sonnet-4-6")
# Fast/cheap model — card processing, feature detection, lightweight tasks
CLAUDE_HAIKU_MODEL = os.getenv("CLAUDE_HAIKU_MODEL", "claude-haiku-4-5-20251001")
# Default model used by the domain expert chat
DOMAIN_EXPERT_MODEL = os.getenv("DOMAIN_EXPERT_MODEL", CLAUDE_SONNET_MODEL)

# Ollama — kept ONLY for embeddings (Anthropic has no embedding model)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")

# ChromaDB
CHROMA_PATH = str(BASE_DIR / "data" / "chroma_db")
CHROMA_COLLECTION = "mcsl_knowledge"
# Separate collection for source code (backend + frontend)
CHROMA_CODE_COLLECTION = "mcsl_code_knowledge"

# Shopify store
STORE = os.getenv("STORE", "")
SHOPIFY_ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN", "")
SHOPIFY_API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2023-01")

# MCSL knowledge sources
MCSL_AUTOMATION_REPO_PATH = os.getenv(
    "MCSL_AUTOMATION_REPO_PATH",
    str(Path.home() / "Documents" / "mcsl-test-automation"),
)

MCSL_CHROME_AUTH_PATH = os.getenv(
    "MCSL_CHROME_AUTH_PATH",
    str(Path(MCSL_AUTOMATION_REPO_PATH) / "auth-chrome.json"),
)

WIKI_PATH = os.getenv(
    "WIKI_PATH",
    str(Path.home() / "Documents" / "mcsl-wiki" / "wiki"),
)

STOREPEPSAAS_SHARED_PATH = os.getenv(
    "STOREPEPSAAS_SHARED_PATH",
    str(Path.home() / "Documents" / "storepep-react" / "storepepSAAS" / "server" / "src" / "shared"),
)
# Aliases used by ingest pipeline (match --sources argument names)
STOREPEPSAAS_SERVER_PATH = os.getenv(
    "STOREPEPSAAS_SERVER_PATH",
    str(Path.home() / "Documents" / "storepep-react" / "storepepSAAS" / "server" / "src" / "shared"),
)
STOREPEPSAAS_CLIENT_PATH = os.getenv(
    "STOREPEPSAAS_CLIENT_PATH",
    str(Path.home() / "Documents" / "storepep-react" / "storepepSAAS" / "client" / "src"),
)

# File extensions to index from source code directories
CODE_FILE_EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", ".php", ".java", ".py", ".go", ".rb", ".cs"]

# Google Sheets
GOOGLE_SHEETS_ID = os.getenv(
    "GOOGLE_SHEETS_ID", "1oVtOaM2PesVR_TkuVaBKpbp_qQdmq4FQnN43Xew0FuY"
)
GOOGLE_CREDENTIALS_PATH = os.getenv(
    "GOOGLE_CREDENTIALS_PATH", str(BASE_DIR / "credentials.json")
)

# RAG settings
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
TOP_K_RESULTS = 8
MEMORY_WINDOW = 10

# Shopify app iframe selector — INFRA-04 placeholder for Phase 2
APP_IFRAME_SELECTOR = "iframe[name='app-iframe']"
