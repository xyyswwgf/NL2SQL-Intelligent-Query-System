"""
应用配置 — 所有敏感信息从系统环境变量读取
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── 数据库配置 ──
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "nl2sql_db")

# ── LLM / Anthropic 配置 ──
# ANTHROPIC_AUTH_TOKEN 已通过 settings.json 注入到环境
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_AUTH_TOKEN", "")
ANTHROPIC_BASE_URL = os.getenv(
    "ANTHROPIC_BASE_URL",
    "https://api.deepseek.com/anthropic",
)
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-pro")

# ── CSV 导入配置 ──
CSV_MAX_FILE_SIZE_MB = int(os.getenv("CSV_MAX_FILE_SIZE_MB", "10"))
CSV_MAX_ROWS = int(os.getenv("CSV_MAX_ROWS", "100000"))
CSV_BATCH_SIZE = int(os.getenv("CSV_BATCH_SIZE", "500"))
