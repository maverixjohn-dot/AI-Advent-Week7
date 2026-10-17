"""Общий контекст приложения: хранилище, репозитории, RAG, MCP, агент."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from data import seeds
from data.repositories import (
    UserRepo, TicketRepo, DialogRepo, FeedbackRepo, KBRepo,
    AgentConfigRepo, LogRepo,
)
from data.storage import JsonStore
from domain.agent import SupportAgent
from domain.deepseek_client import DeepSeekClient
from domain.log_service import LogService
from domain.mcp_client import MCPClient
from domain.rag.embedder import get_embedder, DEFAULT_MODEL
from domain.rag.knowledge import KnowledgeBase
from domain.rag.retriever import Retriever
from domain.rag.vectorstore import VectorStore

STORAGE_DIR = Path(os.environ.get(
    "STORAGE_DIR", str(Path(__file__).resolve().parent.parent / "storage")))

store = JsonStore(STORAGE_DIR)
seeds.ensure_seeded(store)

users = UserRepo(store)
tickets = TicketRepo(store)
dialogs = DialogRepo(store)
feedback = FeedbackRepo(store)
kb_repo = KBRepo(store)
agent_configs = AgentConfigRepo(store)

log_repo = LogRepo(store)
log_service = LogService(log_repo)

deepseek = DeepSeekClient()
mcp = MCPClient(os.environ.get("MCP_URL", "http://localhost:8001/mcp"))

vector_store = VectorStore(STORAGE_DIR / "rag")
knowledge = KnowledgeBase(seeds.kb_dir(store), vector_store, kb_repo,
                          get_embedder, log_service)
retriever = Retriever(vector_store, get_embedder, log_service)

agent = SupportAgent(agent_configs, dialogs, feedback, deepseek, mcp,
                     retriever, log_service)

# Состояние индекса базы знаний (для отображения в админке)
index_status: dict = {"state": "idle", "detail": "индекс не построен"}


def ensure_mcp_server() -> bool:
    """При локальном запуске (MCP_URL указывает на localhost) поднимает
    MCP-сервер подпроцессом, если он ещё не запущен.

    В Docker MCP_URL указывает на контейнер mcp-server — автозапуск
    пропускается. Отключить: MCP_AUTOSTART=0.
    """
    if mcp.ping():
        return True
    if os.environ.get("MCP_AUTOSTART", "1") == "0":
        log_service.log("system.mcp.unavailable", url=mcp.url,
                        reason="автозапуск отключён (MCP_AUTOSTART=0)")
        return False
    host = urlparse(mcp.url).hostname or ""
    if host not in ("localhost", "127.0.0.1", "::1"):
        log_service.log("system.mcp.unavailable", url=mcp.url,
                        reason="URL нелокальный, автозапуск не применим")
        return False
    root = Path(__file__).resolve().parent.parent
    env = dict(os.environ)
    env.setdefault("STORAGE_DIR", str(STORAGE_DIR))
    env.setdefault("MCP_PORT", str(urlparse(mcp.url).port or 8001))
    log_service.log("system.mcp.autostart", url=mcp.url)
    subprocess.Popen([sys.executable, "-m", "mcp_server.server"],
                     cwd=str(root), env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            if mcp.ping():
                log_service.log("system.mcp.ready", url=mcp.url)
                return True
        except Exception:
            pass
        time.sleep(1)
    log_service.log("system.mcp.failed", url=mcp.url)
    return False


def ensure_index(force: bool = False) -> None:
    """Строит индекс RAG, если он пуст (или force=True — всегда)."""
    if index_status["state"] == "building":
        return
    if not force and vector_store.count() > 0:
        index_status.update(state="ready",
                            detail=f"{vector_store.count()} чанков")
        return
    index_status.update(state="building", detail="")
    try:
        stats = knowledge.rebuild()
        index_status.update(
            state="ready",
            detail=f"{stats['files']} файлов, {stats['chunks']} чанков")
    except Exception as e:
        index_status.update(state="error", detail=str(e))
        log_service.log("rag.error", error=str(e), stage="ensure_index")
