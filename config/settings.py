"""
运行期配置管理

通过 Pydantic Settings 从环境变量读取配置，支持 .env 文件。
敏感信息（API Key、密码）绝不硬编码，必须通过环境变量注入。
"""

import os
from typing import Optional
from pydantic_settings import BaseSettings


# 计算项目根目录（config/settings.py 的上级目录）
# 这样无论从哪里启动，都能正确定位 .env 文件
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_FILE_PATH = os.path.join(_PROJECT_ROOT, ".env")


class Settings(BaseSettings):
    """
    应用运行期配置。
    所有字段优先从环境变量读取，其次从 .env 文件读取。
    """

    # ============================================================
    # LLM 配置（必填）
    # ============================================================
    LLM_API_KEY: str
    LLM_BASE_URL: str = "https://api.deepseek.com/v1"
    LLM_MODEL: str = "deepseek-chat"
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 2048

    # ============================================================
    # RAG 配置（可选）
    # ============================================================
    RAG_ENABLED: bool = False
    RAG_BASE_URL: str = ""
    RAG_API_KEY: str = ""
    RAG_TOP_K: int = 3

    # ============================================================
    # 数据库配置（可选）
    # ============================================================
    DB_ENABLED: bool = False
    DB_URL: str = "sqlite:///data/chat_sessions.db"
    DB_ECHO: bool = False  # 是否打印 SQL 日志

    # ============================================================
    # 应用配置
    # ============================================================
    APP_NAME: str = "ITR-智能客服"
    APP_DEBUG: bool = False
    APP_PORT: int = 8000

    # ============================================================
    # 会话控制参数
    # ============================================================
    MAX_INFO_COLLECTION_ROUNDS: int = 3
    MAX_TOTAL_ROUNDS: int = 10

    class Config:
        env_file = _ENV_FILE_PATH
        env_file_encoding = "utf-8"
        case_sensitive = True


def get_project_root() -> str:
    """获取项目根目录路径"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_config_dir() -> str:
    """获取配置目录路径"""
    return os.path.join(get_project_root(), "config")


# 全局单例
settings = Settings()
