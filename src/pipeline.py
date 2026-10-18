"""Сквозной пайплайн: PDF -> обезличивание -> классификация -> Excel + комментарий.

Порядок важен (приватность):
  1) парсинг и фильтр внутренних переводов — на СЫРЫХ данных, локально;
  2) маскировка описаний;
  3) наружу (LLM) уходит только обезличенный набор дата/сумма/описание.
"""
import os
from dataclasses import dataclass, field

from .aggregator import (DedupStore, InvariantError, aggregate_labeled,
                         file_hash, split_internal_transfers)
from .categories import (allowed_names, apply_mapping, load_categories,
                         load_mapping, load_members, validate_mapping)
from .classifier import make_classifier
from .excel_writer import read_plan, write_facts
from .masking import mask_dataframe
from .parser_tbank import parse_tbank_pdf

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TEMPLATE = os.path.join(BASE_DIR, "data", "template.xlsx")
DEFAULT_OUT_DIR = os.path.join(BASE_DIR, "output")
DEDUP_DB = os.path.join(BASE_DIR, "data", "processed_hashes.json")


@dataclass
class PipelineResult:
    out_xlsx: list[str] = field(default_factory=list)
    months: dict = field(default_factory=dict)     # агрегаты по месяцам
    plans: dict = field(default_factory=dict)      # плановые суммы (контекст чата)
    commentary: str = ""
    comment_mode: str = ""
    n_transactions: int = 0
    n_transfers_excluded: int = 0
    n_files: int = 0
    skipped_duplicates: list[str] = field(default_factory=list)
    balances: list[dict] = field(default_factory=list)  # из графы «Доступный остаток»
    exports_1c: list[str] = field(default_factory=list)
    unmapped: list[int] = field(default_factory=list)
    classifier_name: str = ""
    mapping_rules: int = 0                     # правил на листе «Маппинг»
    mapping_applied: int = 0                   # операций закрыто маппингом (кодом)
    mapping_unknown_targets: list[str] = field(default_factory=list)
    journal: list[dict] = field(default_factory=list)
    transactions_masked: list[dict] = field(default_factory=list)  # для таблицы в UI


def _allowed_names(cats: list[dict], owner: str | None) -> list[str]:
    """DEPRECATED: оставлено для совместимости; используйте
    categories.allowed_names(cats, owner, members)."""
    return [c["name"] for c in cats]


def run(pdf_paths, template_path: str = DEFAULT_TEMPLATE,
        out_dir: str = DEFAULT_OUT_DIR, classifier_backend: str | None = None,
        dedup: bool = True, members: list[str] | None = None) -> PipelineResult:
    """Обрабатывает одну или несколько выписок за один прогон.

    pdf_paths: список путей ИЛИ список кортежей (путь, владелец).
    Владелец — произвольный псевдоним (вводится пользователем); статьи вида
    «<статья> <псевдоним>» доступны только при совпадении псевдонима
    (список псевдонимов — data/members.json или параметр members).

    Дедупликация: уже обработанные файлы ПРОПУСКАЮТСЯ с предупреждением;
    если новых не осталось — отказ (иначе двойной учёт).
    """
    if isinstance(pdf_paths, str):
        pdf_paths = [pdf_paths]
    items = [(p, None) if isinstance(p, str) else p for p in pdf_paths]
    res = PipelineResult()
    store = DedupStore(DEDUP_DB)
    members = load_members() if members is None else members
    mapping = load_mapping(template_path)

    by_owner: dict[str | None, list] = {}
    new_digests = []
    for path, owner in items:
        digest = file_hash(path)
        if dedup and store.seen(digest):
            res.skipped_duplicates.append(os.path.basename(path))
            continue
        df, meta = parse_tbank_pdf(path)
        for b in meta.get("balances", []):
            res.balances.append({**b, "owner": owner,
                                 "file": os.path.basename(path)})
        by_owner.setdefault(owner, []).append(df)
        new_digests.append(digest)
    if not by_owner:
        raise InvariantError(
            "Все выбранные выписки уже были обработаны ранее. "
            "Повторная загрузка дала бы двойной учёт — отклонено."
        )
    res.n_files = sum(len(v) for v in by_owner.values())

    import pandas as pd
    cats = load_categories()
    res.mapping_rules = len(mapping)
    res.mapping_unknown_targets = validate_mapping(mapping, cats)
    classifier = make_classifier(cats, classifier_backend, mapping=mapping,
                                 members=members)
    res.classifier_name = classifier.name

    frames, transfers_total, raw_total = [], 0, 0
    for owner, dfs in by_owner.items():
        df = (pd.concat(dfs, ignore_index=True)
              .drop_duplicates(subset=["date", "amount", "description"])
              .reset_index(drop=True))
        raw_total += len(df)
        work, transfers = split_internal_transfers(df)   # I1 — ДО вызова LLM
        transfers_total += len(transfers)
        masked = mask_dataframe(work)              # приватная граница
        items_llm = [
            {"idx": i, "date": r["date"].strftime("%d.%m.%Y"),
             "amount": float(r["amount"]), "description": r["description"]}
            for i, (_, r) in enumerate(masked.iterrows())
        ]
        names = allowed_names(cats, owner, members)
        # Правила листа «Маппинг» применяет КОД — детерминированно,
        # до LLM: пользовательское правило не может быть проигнорировано.
        labels: list[str | None] = [None] * len(items_llm)
        to_llm = []
        for it in items_llm:
            hit = apply_mapping(it["description"], mapping, names)
            if hit:
                labels[it["idx"]] = hit
                res.mapping_applied += 1
            else:
                to_llm.append(it)
        if to_llm:
            llm_labels = classifier.classify(to_llm, names, owner=owner)
            res.unmapped.extend(getattr(classifier, "unmapped", []))
            for it, lab in zip(to_llm, llm_labels):
                labels[it["idx"]] = lab
        labels = [l or names[0] for l in labels]
        for it, lab in zip(items_llm, labels):
            res.transactions_masked.append(
                {**it, "category": lab, "owner": owner or "—"})
        frames.append(work.assign(category=labels))

    df_all = pd.concat(frames, ignore_index=True)
    res.n_transactions = raw_total               # всего распознано в выписках
    res.n_transfers_excluded = transfers_total

    res.months = aggregate_labeled(df_all, cats)   # I2: сверка сумм внутри

    plans_all = {}
    for month_key, agg in res.months.items():
        out_path, journal = write_facts(template_path, out_dir, month_key,
                                        agg["by_category"], cats)
        res.out_xlsx.append(out_path)
        res.journal.extend(journal)
        plans_all[month_key] = read_plan(template_path, month_key, cats)
        if os.environ.get("EXPORT_1C", "1") != "0":  # включён по умолчанию
            from .export_1c import export_month
            res.exports_1c.append(export_month(month_key, agg, cats, out_dir))
    for p in plans_all.values():
        res.plans.update(p)

    res.commentary, res.comment_mode = comment_factcheck(res.months, plans_all)

    if dedup:
        for d in new_digests:
            store.commit(d)                      # фиксируем только при успехе
    return res


def comment_factcheck(months, plans):
    from .advisor import comment
    # планы передаём плоско по именам категорий (один месяц — типовой случай)
    flat_plans = {}
    for _, p in plans.items():
        flat_plans.update(p)
    return comment(months, flat_plans)
