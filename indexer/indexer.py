"""Индексатор: выгрузка 1С -> карта метаданных + документы -> эмбеддинги -> FAISS.

Запуск:
    python -m indexer.indexer            # инкрементально (по configVersion / sha1)
    python -m indexer.indexer --full     # полная переиндексация

Инкрементальность: configVersion объекта из ConfigDumpInfo.xml меняется только при
изменении объекта в конфигураторе — переиндексируем только изменённые источники.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from indexer import parser_1c
from indexer.embeddings import get_encoder
from indexer.store import VectorStore

log = logging.getLogger(__name__)


def run_index(full: bool = False) -> dict:
    config.setup_logging()
    started = time.time()
    if (not os.getenv("A1C_DUMP_ROOT", "").strip()
            or not config.DUMP_ROOT.exists()
            or not (config.DUMP_ROOT / "Configuration.xml").exists()):
        raise RuntimeError(
            f"Некорректный A1C_DUMP_ROOT: '{config.DUMP_ROOT}' "
            "(нет каталога или в нём нет Configuration.xml)")
    dump_root = config.DUMP_ROOT

    log.info("=== Индексация (%s), выгрузка: %s ===", "полная" if full else "инкрементальная", dump_root)

    mmap = parser_1c.build_metadata_map(dump_root)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.METADATA_MAP_FILE.write_text(
        json.dumps(mmap, ensure_ascii=False, indent=1), encoding="utf-8")

    documents = parser_1c.collect_documents(dump_root, mmap)

    encoder = get_encoder()
    store = None if full else VectorStore.load(config.DATA_DIR)
    if store is None:
        store = VectorStore(encoder.dim)

    existing_versions = {c["id"]: c.get("version", "") for c in store.chunks}
    new_ids = {d["id"] for d in documents}

    stale_sources = {c["source"] for c in store.chunks if c["id"] not in new_ids}
    to_embed = [d for d in documents
                if full or existing_versions.get(d["id"]) != d["version"]]
    changed_sources = {d["source"] for d in to_embed}

    removed = store.remove_sources(stale_sources | changed_sources)
    log.info("Устарело чанков: %d, к переиндексации источников: %d", removed,
             len(changed_sources))

    if to_embed:
        vectors = encoder.encode_passages([d["text"] for d in to_embed])
        store.add(vectors, to_embed)
        log.info("Перевекторизовано чанков: %d", len(to_embed))

    store.save(config.DATA_DIR)

    stats = {
        "mode": "full" if full else "incremental",
        "objects": len(mmap["objects"]),
        "subsystems": len(mmap["subsystems"]),
        "chunks_total": len(store.chunks),
        "chunks_reindexed": len(to_embed),
        "embed_model": getattr(encoder, "model_name", "hash"),
        "dump_root": str(dump_root),
        "duration_sec": round(time.time() - started, 2),
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    config.STATS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    log.info("=== Готово за %.1f с: %s ===", stats["duration_sec"], stats)
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Индексатор выгрузки 1С")
    ap.add_argument("--full", action="store_true", help="полная переиндексация")
    args = ap.parse_args()
    config.setup_logging()
    problems = [p for p in config.validate() if "DUMP_ROOT" in p]
    if problems:
        sys.exit("ОШИБКА конфигурации: " + "; ".join(problems))
    stats = run_index(full=args.full)
    print(json.dumps(stats, ensure_ascii=False, indent=1))
