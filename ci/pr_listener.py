"""Слушатель вебхуков Gitea: AI-ревью pull request'ов без внешнего хостинга.

Замена GitHub Action для локального Gitea (или VPS позже):

    python -m ci.pr_listener              # слушает 127.0.0.1:8788
    python -m ci.pr_listener --port 9000

Поток: Gitea шлёт pull_request-вебхук -> мы отвечаем 202 и в фоне:
1. git fetch origin refs/pull/<N>/head (Gitea отдаёт PR по этому ref);
2. создаём изолированный git worktree на PR head (рабочее дерево пользователя
   не трогаем);
3. строим RAG-индекс в отдельный data-каталог, запускаем agent.review;
4. публикуем результат комментарием в PR через Gitea API;
5. удаляем worktree и временные файлы.

Переменные окружения:
    A1C_DUMP_ROOT        — локальный репозиторий выгрузки (у него remote origin
                           указывает на Gitea)
    GITEA_URL            — например http://127.0.0.1:3000
    GITEA_TOKEN          — токен пользователя Gitea (право на комментарии)
    A1C_WEBHOOK_SECRET   — секрет вебхука (задаётся в настройках вебхука Gitea)
    DEEPSEEK_API_KEY     — ключ LLM
Только stdlib: новых зависимостей нет.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

log = logging.getLogger(__name__)

GITEA_URL = os.getenv("GITEA_URL", "http://127.0.0.1:3000").rstrip("/")
GITEA_TOKEN = os.getenv("GITEA_TOKEN", "")
WEBHOOK_SECRET = os.getenv("A1C_WEBHOOK_SECRET", "")
REVIEW_TIMEOUT = int(os.getenv("A1C_REVIEW_TIMEOUT", "900"))

_review_lock = threading.Lock()  # ревью по одному: CPU и память ограничены


def _verify_signature(body: bytes, signature: str) -> bool:
    """X-Gitea-Signature = hex(HMAC-SHA256(secret, body))."""
    if not WEBHOOK_SECRET:
        return False
    expected = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


def _post_comment(repo_full_name: str, pr_number: int, body: str) -> None:
    if not GITEA_TOKEN:
        log.warning("GITEA_TOKEN не задан — комментарий не опубликован. Текст ревью:\n%s", body)
        return
    url = f"{GITEA_URL}/api/v1/repos/{repo_full_name}/issues/{pr_number}/comments"
    req = urllib.request.Request(
        url, data=json.dumps({"body": body}).encode(),
        headers={"Authorization": f"token {GITEA_TOKEN}",
                 "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        log.info("Комментарий в PR #%d: HTTP %d", pr_number, resp.status)


def _review_pr(repo_full_name: str, pr_number: int, base_ref: str, head_sha: str) -> None:
    """Фоновая работа: fetch -> worktree -> индекс -> ревью -> комментарий."""
    with _review_lock:
        dump_root = config.DUMP_ROOT
        worktree = Path(tempfile.mkdtemp(prefix=f"a1c-pr{pr_number}-")) / "wt"
        data_dir = Path(tempfile.mkdtemp(prefix=f"a1c-pr{pr_number}-data"))
        review_file = worktree.parent / "review.md"
        try:
            # 1. забираем head PR; Gitea отдаёт его как refs/pull/<N>/head
            try:
                _git(dump_root, "fetch", "origin", f"refs/pull/{pr_number}/head")
            except subprocess.CalledProcessError:
                log.warning("refs/pull/%d/head недоступен, пробую по sha", pr_number)
                _git(dump_root, "fetch", "origin", head_sha)
            # 2. изолированное рабочее дерево на PR head
            _git(dump_root, "worktree", "add", "--detach", str(worktree), "FETCH_HEAD")

            env = dict(os.environ, A1C_DUMP_ROOT=str(worktree),
                       A1C_DATA_DIR=str(data_dir))
            # 3. индекс RAG на состоянии PR + ревью
            subprocess.run([sys.executable, "-m", "indexer.indexer", "--full"],
                           cwd=config.BASE_DIR, env=env, check=True,
                           capture_output=True, text=True, timeout=REVIEW_TIMEOUT)
            subprocess.run([sys.executable, "-m", "agent.review",
                            "--base", f"origin/{base_ref}",
                            "--out", str(review_file)],
                           cwd=config.BASE_DIR, env=env, check=True,
                           capture_output=True, text=True, timeout=REVIEW_TIMEOUT)
            if not review_file.exists():
                log.info("PR #%d: изменений нет, комментарий не нужен", pr_number)
                return
            # 4. комментарий в PR
            _post_comment(repo_full_name, pr_number,
                          review_file.read_text(encoding="utf-8"))
        except subprocess.CalledProcessError as e:
            log.error("PR #%d: шаг упал: %s\n%s", pr_number, e.cmd,
                      (e.stderr or "")[-2000:])
        except Exception:
            log.exception("PR #%d: ревью не удалось", pr_number)
        finally:
            # 5. уборка: worktree + временные каталоги (review.md, индекс)
            try:
                _git(dump_root, "worktree", "remove", "--force", str(worktree))
            except Exception as e:
                log.warning("Не удалось удалить worktree %s: %s", worktree, e)
            shutil.rmtree(worktree.parent, ignore_errors=True)
            shutil.rmtree(data_dir, ignore_errors=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "a1c-pr-listener"

    def log_message(self, fmt, *args):  # в наш лог, не в stderr
        log.info("HTTP " + fmt, *args)

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._json(200, {"status": "ok"})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/gitea-webhook":
            return self._json(404, {"error": "not found"})
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if not _verify_signature(body, self.headers.get("X-Gitea-Signature", "")):
            return self._json(401, {"error": "bad signature"})
        if self.headers.get("X-Gitea-Event") != "pull_request":
            return self._json(202, {"status": "ignored", "reason": "not a PR event"})
        try:
            payload = json.loads(body)
            pr = payload["pull_request"]
            action = payload.get("action", "")
            if action not in ("opened", "synchronize", "reopened"):
                return self._json(202, {"status": "ignored", "reason": f"action={action}"})
            repo_name = payload["repository"]["full_name"]
            number = int(payload["number"])
            base_ref = pr["base"]["ref"]
            head_sha = pr["head"]["sha"]
        except (KeyError, ValueError, TypeError) as e:
            return self._json(400, {"error": f"bad payload: {e}"})

        threading.Thread(target=_review_pr,
                         args=(repo_name, number, base_ref, head_sha),
                         daemon=True).start()
        log.info("PR #%d (%s -> %s): ревью поставлено в очередь", number, base_ref, head_sha[:7])
        self._json(202, {"status": "queued", "pr": number})


def cli() -> None:
    ap = argparse.ArgumentParser(description="Слушатель вебхуков Gitea для AI-ревью PR")
    ap.add_argument("--host", default=os.getenv("A1C_LISTEN_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("A1C_LISTEN_PORT", "8788")))
    args = ap.parse_args()

    config.setup_logging()
    problems = [p for p in config.validate() if "DUMP_ROOT" in p]
    if problems:
        sys.exit("ОШИБКА: " + "; ".join(problems))
    if not WEBHOOK_SECRET:
        log.warning("A1C_WEBHOOK_SECRET не задан — все вебхуки будут отклонены (401)")
    log.info("Слушаю http://%s:%d/gitea-webhook (Gitea: %s)", args.host, args.port, GITEA_URL)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    cli()
