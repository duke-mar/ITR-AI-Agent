"""
DB Skill（数据库操作）

职责：
  - 封装数据库连接和 CRUD 操作
  - 支持 SQLite（开发）和 PostgreSQL（生产）
  - 提供会话持久化、消息归档等基础能力

当前状态：
  - 接口已定义，具体连接待配置
  - 需要用户在 .env 中配置 DB_URL
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .base import BaseSkill

logger = logging.getLogger(__name__)


class DBSkill(BaseSkill):
    """
    数据库操作 Skill。

    支持的数据库：
      - SQLite: sqlite:///path/to/db.sqlite3
      - PostgreSQL: postgresql+asyncpg://user:pass@host:port/db
      - MySQL: mysql+aiomysql://user:pass@host:port/db
    """

    def __init__(self, db_url: str, echo: bool = False, **kwargs):
        super().__init__(db_url=db_url, echo=echo, **kwargs)
        self.db_url = db_url
        self.echo = echo
        self._engine = None
        self._session_factory = None

        logger.info(f"DBSkill 初始化: db_url={db_url}")

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """建立数据库连接"""
        if self._engine is not None:
            return

        try:
            if self.db_url.startswith("sqlite"):
                # SQLite 同步模式（MVP 阶段简化）
                import aiosqlite
                self._engine = await aiosqlite.connect(self.db_url.replace("sqlite:///", ""))
                await self._init_sqlite_tables()
            else:
                # 异步数据库（PostgreSQL/MySQL）
                # TODO: 接入 SQLAlchemy async 或 Tortoise ORM
                logger.warning("异步数据库连接尚未实现，当前仅支持 SQLite")

            logger.info("数据库连接成功")
        except Exception as e:
            logger.error(f"数据库连接失败: {e}")
            raise

    async def close(self) -> None:
        """关闭数据库连接"""
        if self._engine:
            await self._engine.close()
            self._engine = None
            logger.info("数据库连接已关闭")

    # ------------------------------------------------------------------
    # 会话操作
    # ------------------------------------------------------------------

    async def save_session(self, session_id: str, state: Dict[str, Any]) -> None:
        """
        保存会话状态快照。

        Args:
            session_id: 会话唯一标识
            state: 完整 State 字典（会被 JSON 序列化）
        """
        if not self._engine:
            logger.warning("数据库未连接，跳过保存会话")
            return

        try:
            state_json = json.dumps(state, ensure_ascii=False, default=str)
            await self._engine.execute(
                """
                INSERT INTO sessions (session_id, state, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(session_id) DO UPDATE SET
                    state=excluded.state,
                    updated_at=excluded.updated_at
                """,
                (session_id, state_json),
            )
            await self._engine.commit()
            logger.info(f"会话已保存: {session_id}")
        except Exception as e:
            logger.error(f"保存会话失败: {e}")

    async def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        加载会话状态。

        Args:
            session_id: 会话唯一标识

        Returns:
            State 字典，或 None（会话不存在）
        """
        if not self._engine:
            return None

        try:
            cursor = await self._engine.execute(
                "SELECT state FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
            return None
        except Exception as e:
            logger.error(f"加载会话失败: {e}")
            return None

    async def list_sessions(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """列出会话列表（管理后台用）"""
        if not self._engine:
            return []

        cursor = await self._engine.execute(
            "SELECT session_id, updated_at FROM sessions ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [
            {"session_id": r[0], "updated_at": r[1]}
            for r in rows
        ]

    # ------------------------------------------------------------------
    # 业务数据操作
    # ------------------------------------------------------------------

    async def save_feedback(
        self,
        session_id: str,
        score: int,
        comment: Optional[str] = None,
    ) -> None:
        """保存用户反馈/满意度评分"""
        if not self._engine:
            logger.warning("数据库未连接，跳过保存反馈")
            return

        await self._engine.execute(
            """
            INSERT INTO feedback (session_id, score, comment, created_at)
            VALUES (?, ?, ?, datetime('now'))
            """,
            (session_id, score, comment),
        )
        await self._engine.commit()
        logger.info(f"反馈已保存: session_id={session_id}, score={score}")

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _init_sqlite_tables(self) -> None:
        """初始化 SQLite 表结构"""
        await self._engine.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                score INTEGER NOT NULL,
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_updated
                ON sessions(updated_at DESC);
            """
        )
        await self._engine.commit()
        logger.info("SQLite 表结构初始化完成")

    def health_check(self) -> bool:
        """检查数据库是否已连接"""
        return self._engine is not None
