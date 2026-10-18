"""Демо код-ассистента без API-ключа: агентский цикл на моке LLM.

Прогоняет два сценария задания на синтетическом мини-проекте 1С:
1. «Найди все места, где используется компонент» — search_files по проекту;
2. «Задокументируй объект в docs/» — read_file + write_file (новый файл),
   с консультацией аналитика (ask_analyst) и авто-журналом в README.md.
Плюс проверка инвариантов: попытки писать за пределы workspace и в .github
отклоняются guard-слоем.

    python demo.py            # создаёт временный проект, прогоняет, показывает итог
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent.assistant import CodeAssistant
from agent.fs_tools import FileTools
from agent.guard import WorkspaceGuard
from agent.mock_llm import MockLLM, text_step, tool_step

# ---------------------------------------------------------------- мини-проект
FILES = {
    "Configuration.xml": """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" version="2.17">
  <Configuration uuid="demo">
    <Properties><Name>ДемоПроект</Name></Properties>
    <ChildObjects>
      <Catalog>ФинансовыеПоказатели</Catalog>
      <Document>ФинансовыйФакт</Document>
    </ChildObjects>
  </Configuration>
</MetaDataObject>
""",
    "Catalogs/#U0424#U0438#U043d#U0430#U043d#U0441#U043e#U0432#U044b#U0435#U041f#U043e#U043a#U0430#U0437#U0430#U0442#U0435#U043b#U0438.xml": """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" version="2.17">
  <Catalog uuid="c1">
    <Properties><Name>ФинансовыеПоказатели</Name>
      <Synonym><v8:item><v8:content>Финансовые показатели</v8:content></v8:item></Synonym>
    </Properties>
    <ChildObjects>
      <Attribute uuid="a1"><Properties><Name>ЕдиницаИзмерения</Name></Properties></Attribute>
    </ChildObjects>
  </Catalog>
</MetaDataObject>
""",
    "Documents/ФинансовыйФакт.xml": """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" version="2.17">
  <Document uuid="d1">
    <Properties><Name>ФинансовыйФакт</Name></Properties>
    <ChildObjects>
      <Attribute uuid="a2"><Properties><Name>Показатель</Name>
        <Type><d8p1:Type>CatalogRef.ФинансовыеПоказатели</d8p1:Type></Type>
      </Properties></Attribute>
    </ChildObjects>
  </Document>
</MetaDataObject>
""",
    "Documents/ФинансовыйФакт/Ext/ObjectModule.bsl": """#Область ОбработчикиСобытий

Процедура ОбработкаПроведения(Отказ, РежимПроведения)

	// Фиксируем фактическое значение показателя
	Если Не ЗначениеЗаполнено(Показатель) Тогда
		Отказ = Истина;
		Возврат;
	КонецЕсли;

КонецПроцедуры

#КонецОбласти
""",
    ".github/workflows/ci.yml": "name: ci\non: [push]\n",
}


def build_demo_project(root: Path) -> None:
    for rel, content in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------- мок-сценарий
DOC_MD = """# Справочник «ФинансовыеПоказатели»

## Назначение
Хранит перечень финансовых показателей, по которым ведётся план/факт.

## Состав
- Реквизит `ЕдиницаИзмерения` — единица измерения показателя.

## Где используется
- Документ `ФинансовыйФакт` — реквизит `Показатель`
  (тип `CatalogRef.ФинансовыеПоказатели`), проверяется в
  `ОбработкаПроведения` (ObjectModule.bsl).
"""

SCRIPT = [
    tool_step([("search_files", {"query": "ФинансовыеПоказатели"})]),
    tool_step([("read_file", {"path": "Documents/ФинансовыйФакт/Ext/ObjectModule.bsl"}),
               ("list_files", {"subdir": "docs"})]),
    tool_step([("ask_analyst", {
        "question": "Документирую только справочник или сразу и документ ФинансовыйФакт?"})]),
    tool_step([("write_file", {
        "path": "docs/Справочник_ФинансовыеПоказатели.md",
        "content": DOC_MD,
        "change_summary": "Добавлена документация по справочнику «ФинансовыеПоказатели»"})]),
    # Попытки нарушить инварианты — должны быть отклонены guard-слоем:
    tool_step([("write_file", {
        "path": "../outside.txt", "content": "x",
        "change_summary": "попытка выйти за workspace"})]),
    tool_step([("write_file", {
        "path": ".github/workflows/evil.yml", "content": "x",
        "change_summary": "попытка писать в .github"})]),
    text_step(
        "Готово.\n"
        "1) «ФинансовыеПоказатели» используется в: Configuration.xml, карточке "
        "справочника, реквизите «Показатель» документа ФинансовыйФакт и его "
        "ObjectModule.bsl.\n"
        "2) Создана документация: docs/Справочник_ФинансовыеПоказатели.md, "
        "запись внесена в журнал README.md.\n"
        "Аналитику: загрузить изменённую выгрузку в конфигуратор не требуется — "
        "менялась только документация."),
]


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="ca1c_demo_"))
    workspace = tmp / "DemoProject"
    build_demo_project(workspace)
    print(f"Демо-проект: {workspace}")

    guard = WorkspaceGuard(workspace)
    tools = FileTools(guard, confirm=lambda a, d: True)  # в демо всё подтверждаем
    mock = MockLLM(SCRIPT)
    assistant = CodeAssistant(tools, llm=mock,
                              ask=lambda q: f"(автоответ аналитика: только справочник)")

    task = ("Найди, где используется справочник ФинансовыеПоказатели, "
            "и напиши по нему документацию в docs/")
    print(f"\nЗАДАЧА: {task}\n{'─' * 70}")
    answer = assistant.run_task(task)
    print(f"\nФИНАЛЬНЫЙ ОТВЕТ АССИСТЕНТА:\n{answer}")

    print(f"\n{'─' * 70}\nВЫЗВАННЫЕ ИНСТРУМЕНТЫ:")
    for name, args in mock.calls_log:
        short = {k: (v[:60] + "…" if isinstance(v, str) and len(v) > 60 else v)
                 for k, v in args.items()}
        print(f"  {name} {short}")

    print(f"\n{'─' * 70}\nREADME.md (журнал доработок):")
    print((workspace / "README.md").read_text(encoding="utf-8"))
    print(f"{'─' * 70}\nДерево после работы:")
    for p in sorted(workspace.rglob("*")):
        if p.is_file():
            print(" ", p.relative_to(workspace))

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nВременный проект удалён (это сделал демо-скрипт, не ассистент — "
          f"у ассистента операции удаления нет).")


if __name__ == "__main__":
    main()
