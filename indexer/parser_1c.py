"""Парсер XML-выгрузки конфигурации 1С (формат конфигуратора, v2.x, иерархический).

Проверен на реальной выгрузке «Целеполагание». Результат работы:
- карта метаданных (для MCP-инструментов objects_tree / object_info / objects_list);
- документы для RAG: карточки объектов, чанки модулей .bsl, документация (README + docs).

Формы, макеты и служебные интерфейсные XML в RAG не индексируются — семантики проекта
они не несут (проверено на выгрузке: AutoCommandBar, Template, languageSettings).
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

log = logging.getLogger(__name__)

NS = {
    "md": "http://v8.1c.ru/8.3/MDClasses",
    "v8": "http://v8.1c.ru/8.1/data/core",
    "xr": "http://v8.1c.ru/8.3/xcf/readable",
}

# Каталог выгрузки -> тип метаданного
TYPE_DIRS = {
    "Catalogs": "Catalog",
    "Documents": "Document",
    "DocumentJournals": "DocumentJournal",
    "Reports": "Report",
    "DataProcessors": "DataProcessor",
    "InformationRegisters": "InformationRegister",
    "Constants": "Constant",
}

TYPE_RU = {
    "Catalog": "Справочник",
    "Document": "Документ",
    "DocumentJournal": "Журнал документов",
    "Report": "Отчёт",
    "DataProcessor": "Обработка",
    "InformationRegister": "Регистр сведений",
    "Constant": "Константа",
    "Subsystem": "Подсистема",
    "Configuration": "Конфигурация",
}

# Алиасы типов для разбора ввода пользователя: англ., русские полные и компактные
TYPE_ALIASES = {
    "catalog": "Catalog", "справочник": "Catalog",
    "document": "Document", "документ": "Document",
    "documentjournal": "DocumentJournal", "журнал документов": "DocumentJournal",
    "журналдокументов": "DocumentJournal", "журнал": "DocumentJournal",
    "report": "Report", "отчёт": "Report", "отчет": "Report",
    "dataprocessor": "DataProcessor", "обработка": "DataProcessor",
    "informationregister": "InformationRegister", "регистр сведений": "InformationRegister",
    "регистрсведений": "InformationRegister",
    "constant": "Constant", "константа": "Constant",
    "subsystem": "Subsystem", "подсистема": "Subsystem",
}


def norm_type(raw: str) -> str:
    """'РегистрСведений' | 'регистр сведений' | 'InformationRegister' -> 'InformationRegister'."""
    return TYPE_ALIASES.get(raw.strip().lower(), raw.strip())


CHILD_RU = {
    "Attribute": "Реквизит",
    "Dimension": "Измерение",
    "Resource": "Ресурс",
    "TabularSection": "Табличная часть",
    "Form": "Форма",
    "Template": "Макет",
    "Command": "Команда",
}

# Процедура/функция с опциональной аннотацией &НаСервере и т.п.
RE_PROC = re.compile(
    r"(?mi)^[ \t]*(?:&[^\n]*\n[ \t]*)?(Процедура|Функция)\s+([А-Яа-яЁёA-Za-z0-9_]+)\s*\("
)
RE_REGION = re.compile(r"(?mi)^[ \t]*#Область\s+(\S+)")


def _text(el, path: str):
    r = el.find(path, NS)
    return (r.text or "").strip() if r is not None else None


def _synonym(props) -> str | None:
    item = props.find("md:Synonym/v8:item/v8:content", NS)
    return (item.text or "").strip() if item is not None else None


def _human_types(props) -> list[str]:
    """Типы реквизита в читаемом виде: cfg:CatalogRef.X -> СправочникСсылка.X и т.п."""
    out: list[str] = []
    type_el = props.find("md:Type", NS)
    if type_el is None:
        return out
    for t in type_el.findall("v8:Type", NS):
        raw = t.text or ""
        if raw.startswith("cfg:"):
            body = raw[4:]
            m = re.match(r"(\w+)\.(.+)", body)
            if m:
                prefix, ref = m.group(1), m.group(2)
                base = prefix[:-3] if prefix.endswith("Ref") else prefix
                ru = TYPE_RU.get(base, base)
                out.append(f"{ru}Ссылка.{ref}" if prefix.endswith("Ref") else f"{ru}.{ref}")
            else:
                out.append(body)
        elif raw == "xs:decimal":
            nq = type_el.find("v8:NumberQualifiers", NS)
            if nq is not None:
                d = _text(nq, "v8:Digits") or "10"
                f_ = _text(nq, "v8:FractionDigits") or "0"
                out.append(f"Число({d},{f_})")
            else:
                out.append("Число")
        elif raw == "xs:string":
            sq = type_el.find("v8:StringQualifiers", NS)
            if sq is not None:
                ln = _text(sq, "v8:Length")
                out.append(f"Строка({ln})" if ln else "Строка")
            else:
                out.append("Строка")
        elif raw == "xs:boolean":
            out.append("Булево")
        elif raw in ("xs:dateTime", "xs:date"):
            out.append("Дата")
        else:
            out.append(raw)
    return out


@dataclass
class MetaObject:
    """Объект метаданных конфигурации."""

    type: str  # Catalog, Document, ...
    name: str
    synonym: str = ""
    path: str = ""  # путь к XML относительно корня выгрузки
    config_version: str = ""
    attributes: list[dict] = field(default_factory=list)
    tabular_sections: list[dict] = field(default_factory=list)
    dimensions: list[dict] = field(default_factory=list)
    resources: list[dict] = field(default_factory=list)
    forms: list[str] = field(default_factory=list)
    templates: list[str] = field(default_factory=list)
    modules: list[dict] = field(default_factory=list)  # {kind, path, size}
    extra: dict = field(default_factory=dict)  # специфика типа
    subsystems: list[str] = field(default_factory=list)  # заполняется обратной связью

    @property
    def full_name(self) -> str:
        return f"{self.type}.{self.name}"

    @property
    def type_ru(self) -> str:
        return TYPE_RU.get(self.type, self.type)


def _parse_child_attribute(child) -> dict:
    p = child.find("md:Properties", NS)
    return {
        "name": _text(p, "md:Name") or "?",
        "synonym": _synonym(p) or "",
        "types": _human_types(p),
    }


def parse_object_xml(xml_path: Path, dump_root: Path) -> MetaObject | None:
    """Парсит XML одного объекта метаданных. Неподдержанные файлы -> None."""
    try:
        tree = etree.parse(str(xml_path))
    except etree.XMLSyntaxError as e:
        log.warning("Битый XML %s: %s", xml_path, e)
        return None
    root = tree.getroot()
    if not root.tag.endswith("MetaDataObject"):
        return None
    obj_el = root[0]
    otype = etree.QName(obj_el).localname
    if otype not in TYPE_RU:
        return None
    p = obj_el.find("md:Properties", NS)
    if p is None:
        return None

    rel = str(xml_path.relative_to(dump_root))
    mo = MetaObject(type=otype, name=_text(p, "md:Name") or xml_path.stem,
                    synonym=_synonym(p) or "", path=rel)

    co = obj_el.find("md:ChildObjects", NS)
    if co is not None:
        for child in co:
            tag = etree.QName(child).localname
            if tag == "Attribute":
                mo.attributes.append(_parse_child_attribute(child))
            elif tag == "Dimension":
                mo.dimensions.append(_parse_child_attribute(child))
            elif tag == "Resource":
                mo.resources.append(_parse_child_attribute(child))
            elif tag == "TabularSection":
                tp = child.find("md:Properties", NS)
                ts = {"name": _text(tp, "md:Name") or "?", "synonym": _synonym(tp) or "",
                      "attributes": []}
                tco = child.find("md:ChildObjects", NS)
                if tco is not None:
                    for a in tco.findall("md:Attribute", NS):
                        ts["attributes"].append(_parse_child_attribute(a))
                mo.tabular_sections.append(ts)
            elif tag == "Form":
                mo.forms.append((child.text or "").strip())
            elif tag == "Template":
                mo.templates.append((child.text or "").strip())

    # Специфика типов
    if otype == "DocumentJournal":
        docs = p.findall("md:RegisteredDocuments/xr:Item", NS)
        mo.extra["registered_documents"] = [(d.text or "").strip() for d in docs]
    elif otype == "Catalog":
        mo.extra["hierarchical"] = _text(p, "md:Hierarchical") == "true"
        ht = _text(p, "md:HierarchyType")
        if ht:
            mo.extra["hierarchy_type"] = ht
        lc = _text(p, "md:LevelCount")
        if lc:
            mo.extra["level_count"] = lc
    elif otype == "Constant":
        mo.extra["types"] = _human_types(p)
    elif otype == "Document":
        mo.extra["posting"] = _text(p, "md:Posting") == "Allow"
        rr = p.findall("md:RegisterRecords/xr:Item", NS)
        mo.extra["register_records"] = [(r.text or "").strip() for r in rr]
    elif otype == "Report":
        dcs = p.find("md:MainDataCompositionSchema", NS)
        mo.extra["main_dcs"] = (dcs.text or "").strip() if dcs is not None and dcs.text else ""

    mo.modules = _discover_modules(xml_path, dump_root)
    return mo


def _discover_modules(xml_path: Path, dump_root: Path) -> list[dict]:
    """Модули .bsl объекта: Ext/ObjectModule.bsl, Forms/<Ф>/Ext/Form/Module.bsl и т.д."""
    obj_dir = xml_path.with_suffix("")
    if not obj_dir.is_dir():
        return []
    mods: list[dict] = []
    for bsl in sorted(obj_dir.rglob("*.bsl")):
        rel = str(bsl.relative_to(dump_root))
        fname = bsl.name
        if fname == "ObjectModule.bsl":
            kind = "Модуль объекта"
        elif fname == "ManagerModule.bsl":
            kind = "Модуль менеджера"
        elif fname == "Module.bsl" and "/Forms/" in rel:
            form_name = rel.split("/Forms/")[1].split("/")[0]
            kind = f"Модуль формы «{form_name}»"
        elif fname == "Module.bsl" and "/Commands/" in rel:
            cmd_name = rel.split("/Commands/")[1].split("/")[0]
            kind = f"Модуль команды «{cmd_name}»"
        else:
            kind = "Модуль"
        mods.append({"kind": kind, "path": rel, "size": bsl.stat().st_size})
    return mods


def parse_dump_info(dump_root: Path) -> dict[str, str]:
    """ConfigDumpInfo.xml: полное имя метаданного -> configVersion (для инкрементальной переиндексации)."""
    cdi = dump_root / "ConfigDumpInfo.xml"
    if not cdi.exists():
        return {}
    tree = etree.parse(str(cdi))
    out: dict[str, str] = {}
    for m in tree.getroot().iter("{http://v8.1c.ru/8.3/xcf/dumpinfo}Metadata"):
        name, ver = m.get("name"), m.get("configVersion")
        if name and ver:
            out[name] = ver
    return out


def parse_subsystems(dump_root: Path) -> list[dict]:
    """Подсистемы с учётом вложенности по папкам. Возвращает плоский список:
    [{name, synonym, parent, content: [полные имена объектов]}]."""
    root_dir = dump_root / "Subsystems"
    if not root_dir.is_dir():
        return []
    result: list[dict] = []

    def walk(directory: Path, parent: str | None):
        for xml in sorted(directory.glob("*.xml")):
            mo = parse_object_xml(xml, dump_root)  # type может быть Subsystem
            tree = etree.parse(str(xml))
            obj_el = tree.getroot()[0]
            p = obj_el.find("md:Properties", NS)
            name = _text(p, "md:Name") or xml.stem
            content = [(i.text or "").strip()
                       for i in p.findall("md:Content/xr:Item", NS)]
            result.append({"name": name, "synonym": _synonym(p) or "",
                           "parent": parent or "", "content": content})
            # вложенные подсистемы лежат в <ИмяПодсистемы>/Subsystems/
            sub_dir = directory / xml.stem / "Subsystems"
            if sub_dir.is_dir():
                walk(sub_dir, name)

    walk(root_dir, None)
    return result


def parse_configuration(dump_root: Path) -> dict:
    cfg_xml = dump_root / "Configuration.xml"
    tree = etree.parse(str(cfg_xml))
    obj_el = tree.getroot()[0]
    p = obj_el.find("md:Properties", NS)
    return {
        "name": _text(p, "md:Name") or "",
        "synonym": _synonym(p) or "",
        "compatibility": _text(p, "md:CompatibilityMode") or "",
        "run_mode": _text(p, "md:DefaultRunMode") or "",
        "script_variant": _text(p, "md:ScriptVariant") or "",
        "vendor": _text(p, "md:Vendor") or "",
        "version": _text(p, "md:Version") or "",
    }


def build_metadata_map(dump_root: Path) -> dict:
    """Полная карта конфигурации. Пишется в data/metadata_map.json."""
    dump_root = Path(dump_root)
    versions = parse_dump_info(dump_root)
    objects: list[MetaObject] = []

    for dir_name, _type in TYPE_DIRS.items():
        type_dir = dump_root / dir_name
        if not type_dir.is_dir():
            continue
        for xml in sorted(type_dir.glob("*.xml")):
            mo = parse_object_xml(xml, dump_root)
            if mo is None:
                continue
            mo.config_version = versions.get(mo.full_name, "")
            objects.append(mo)

    subsystems = parse_subsystems(dump_root)
    # обратная связь: объект -> подсистемы
    by_full_name = {o.full_name: o for o in objects}
    for s in subsystems:
        for item in s["content"]:
            if item in by_full_name:
                by_full_name[item].subsystems.append(s["name"])

    cfg = parse_configuration(dump_root)
    log.info("Карта метаданных: %d объектов, %d подсистем, конфигурация «%s»",
             len(objects), len(subsystems), cfg["name"])
    return {
        "configuration": cfg,
        "objects": [vars(o) for o in objects],
        "subsystems": subsystems,
    }


# ---------------------------------------------------------------------------
# Документы для RAG
# ---------------------------------------------------------------------------

def object_card(o: dict) -> str:
    """Текстовая карточка объекта метаданных — основа ответов о структуре."""
    lines = [f"{TYPE_RU.get(o['type'], o['type'])} {o['name']}"
             + (f" ({o['synonym']})" if o["synonym"] else "")]
    if o.get("subsystems"):
        lines.append(f"Подсистемы: {', '.join(o['subsystems'])}")
    for attr in o.get("attributes", []):
        lines.append(f"Реквизит: {attr['name']}"
                     + (f" ({attr['synonym']})" if attr["synonym"] else "")
                     + f" — {', '.join(attr['types']) or 'тип не задан'}")
    for ts in o.get("tabular_sections", []):
        lines.append(f"Табличная часть: {ts['name']}")
        for a in ts["attributes"]:
            lines.append(f"  Реквизит ТЧ: {a['name']} — {', '.join(a['types']) or 'тип не задан'}")
    for d in o.get("dimensions", []):
        lines.append(f"Измерение: {d['name']} — {', '.join(d['types']) or ''}")
    for r in o.get("resources", []):
        lines.append(f"Ресурс: {r['name']} — {', '.join(r['types']) or ''}")
    if o.get("forms"):
        lines.append(f"Формы: {', '.join(o['forms'])}")
    if o.get("templates"):
        lines.append(f"Макеты: {', '.join(o['templates'])}")
    if o.get("modules"):
        lines.append("Модули: " + ", ".join(m["kind"] for m in o["modules"]))
    extra = o.get("extra", {})
    if extra.get("registered_documents"):
        lines.append("Регистрирует документы: " + ", ".join(extra["registered_documents"]))
    if extra.get("register_records"):
        lines.append("Движения по регистрам: " + ", ".join(extra["register_records"]))
    elif o["type"] == "Document":
        lines.append("Движений по регистрам нет")
    if o["type"] == "Catalog" and extra.get("hierarchical"):
        lines.append(f"Иерархический, уровней: {extra.get('level_count', 'не ограничено')}")
    if o["type"] == "Constant":
        lines.append("Тип: " + (", ".join(extra.get("types", [])) or "не задан"))
    return "\n".join(lines)


def chunk_bsl(path: Path, dump_root: Path) -> list[dict]:
    """Модуль .bsl -> чанки по процедурам/функциям (не по токенам)."""
    src = path.read_text(encoding="utf-8-sig", errors="replace")
    rel = str(path.relative_to(dump_root))
    matches = list(RE_PROC.finditer(src))
    chunks: list[dict] = []
    if not matches:
        if src.strip():
            chunks.append({"name": "<весь модуль>", "text": src.strip()})
        return chunks
    header = src[: matches[0].start()].strip()
    if header:
        chunks.append({"name": "<заголовок модуля>", "text": header})
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(src)
        body = src[m.start():end].strip()
        region = ""
        for rm in RE_REGION.finditer(src, 0, m.start()):
            region = rm.group(1)
        chunks.append({"name": m.group(2), "region": region, "text": body})
    return chunks


def chunk_markdown(path: Path, dump_root: Path) -> list[dict]:
    """README/docs: чанки по заголовкам ##/### с хлебными крошками."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    rel = str(path.relative_to(dump_root))
    chunks: list[dict] = []
    current_title, buf = path.stem, []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            chunks.append({"name": current_title, "text": f"{current_title}\n{body}"})

    for line in text.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            flush()
            buf = []
            current_title = m.group(2).strip()
        else:
            buf.append(line)
    flush()
    return chunks


def collect_documents(dump_root: Path, mmap: dict) -> list[dict]:
    """Все документы RAG: карточки объектов + чанки модулей + документация.

    Формат: {id, kind, source, object, text, version}. version нужна инкрементальной
    переиндексации: для объектов — configVersion из ConfigDumpInfo, для доков — sha1.
    """
    dump_root = Path(dump_root)
    docs: list[dict] = []

    for o in mmap["objects"]:
        docs.append({
            "id": f"card:{o['type']}.{o['name']}",
            "kind": "object_card",
            "source": o["path"],
            "object": f"{o['type']}.{o['name']}",
            "text": object_card(o),
            "version": o.get("config_version", ""),
        })
        for mod in o.get("modules", []):
            bsl_path = dump_root / mod["path"]
            if not bsl_path.exists():
                continue
            for ch in chunk_bsl(bsl_path, dump_root):
                region = f" (область {ch['region']})" if ch.get("region") else ""
                docs.append({
                    "id": f"module:{mod['path']}#{ch['name']}",
                    "kind": "module",
                    "source": mod["path"],
                    "object": f"{o['type']}.{o['name']}",
                    "text": f"{mod['kind']} объекта {o['name']}{region}, "
                            f"{ch['name']}:\n{ch['text']}",
                    "version": o.get("config_version", ""),
                })

    for md in [dump_root / "README.md"] + sorted((dump_root / "docs").rglob("*.md")) \
            if (dump_root / "docs").is_dir() else [dump_root / "README.md"]:
        if not md.exists():
            continue
        sha = hashlib.sha1(md.read_bytes()).hexdigest()[:16]
        for ch in chunk_markdown(md, dump_root):
            docs.append({
                "id": f"doc:{md.relative_to(dump_root)}#{ch['name']}",
                "kind": "doc",
                "source": str(md.relative_to(dump_root)),
                "object": "",
                "text": ch["text"],
                "version": sha,
            })
    log.info("Документов для RAG: %d", len(docs))
    return docs
