"""
应用配置 — 所有敏感信息从系统环境变量读取
"""
import os
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()

# ── PostgreSQL 数据库配置 ──
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "15432"))
DB_USER = os.getenv("DB_USER", "data_agent")
DB_PASSWORD = os.getenv("DB_PASSWORD", "Simple@123")
DB_NAME = os.getenv("DB_NAME", "data_agent_db")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql+psycopg://{quote_plus(DB_USER)}:{quote_plus(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}",
)

# ── LLM / Anthropic-compatible 配置 ──
ANTHROPIC_API_KEY = (
    os.getenv("ANTHROPIC_API_KEY")
    or os.getenv("ANTHROPIC_AUTH_TOKEN")
    or os.getenv("DEEPSEEK_API_KEY")
    or ""
)
ANTHROPIC_BASE_URL = os.getenv(
    "ANTHROPIC_BASE_URL",
    "https://api.deepseek.com/anthropic",
)
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-pro")

# ── CSV 导入配置 ──
CSV_MAX_FILE_SIZE_MB = int(os.getenv("CSV_MAX_FILE_SIZE_MB", "10"))
CSV_MAX_ROWS = int(os.getenv("CSV_MAX_ROWS", "100000"))
CSV_BATCH_SIZE = int(os.getenv("CSV_BATCH_SIZE", "500"))
