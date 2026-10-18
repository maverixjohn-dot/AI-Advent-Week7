"""Финассистент — Flet UI (светлая тема: серый фон + оранжевые акценты).

Запуск:  python3 main.py        (десктопное окно)
         python3 main.py --web  (в браузере, localhost:8550)

Вкладки:
  «Разбор выписок» — загрузка PDF (выписки + справки об остатках),
                     итоги по статьям, обезличенные операции;
  «Финансовый помощник» — комментарий аналитика + чат в контексте данных;
  «Логи» — журнал работы.

PDF не покидают машину; в LLM уходят только обезличенные строки
(дата, сумма, описание мерчанта). Остатки в LLM не отправляются.
"""
import os
import sys
import threading

import flet as ft

# --- .env без внешних зависимостей (переменные ОС имеют приоритет) -----------
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    for line in open(env_path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import openpyxl                                               # noqa: E402
from src.advisor import chat                                  # noqa: E402
from src.aggregator import InvariantError                     # noqa: E402
from src.categories import load_categories, load_members      # noqa: E402
from src.excel_writer import (find_month_columns, load_balance_rows,  # noqa: E402
                              read_plan, write_balances)
from src.parser_balances import parse_balances_pdf            # noqa: E402
from src.pipeline import (DEDUP_DB, DEFAULT_OUT_DIR,  # noqa: E402
                          DEFAULT_TEMPLATE, run)

ORANGE = "#E8702A"
ORANGE_DARK = "#C55A11"
ORANGE_SOFT = "#FDE9DA"
TEAL = "#0E9594"
TEAL_DARK = "#0A6E6D"
TEAL_SOFT = "#DCF3F2"
VIOLET = "#7C5CBF"
VIOLET_DARK = "#5B3E9E"
VIOLET_SOFT = "#ECE5F8"
BLUE = "#2F80ED"
BLUE_SOFT = "#E0EDFC"
GREEN = "#2E9E5B"
GREEN_SOFT = "#DFF2E6"
GRAY_BG = "#F4F4F6"
GRAY_PANEL = "#ECECEF"
GRAY_TEXT = "#3C3C43"
GRAY_MUTED = "#6E6E73"
RED = "#B00020"


def card(content, **kw):
    return ft.Container(
        content=content, bgcolor="white", border_radius=14, padding=16,
        border=ft.border.all(1, "#E4E4E8"),
        shadow=ft.BoxShadow(blur_radius=10, spread_radius=-4,
                            color="#1A000000", offset=ft.Offset(0, 3)),
        **kw)


def section_title(text, icon, color=ORANGE):
    return ft.Row([ft.Container(
                       content=ft.Icon(icon, color="white", size=14),
                       bgcolor=color, border_radius=8, width=26, height=26,
                       alignment=ft.alignment.center),
                   ft.Text(text, size=14, weight=ft.FontWeight.BOLD,
                           color=GRAY_TEXT)], spacing=8)


def main(page: ft.Page):
    page.title = "Финассистент"
    page.bgcolor = GRAY_BG
    page.window_width = 1280
    page.window_height = 860
    page.theme = ft.Theme(
        color_scheme=ft.ColorScheme(primary=ORANGE, on_primary="white",
                                    surface=GRAY_PANEL, background=GRAY_BG),
    )
    page.padding = 0

    state = {"pdfs": [], "balance_pdfs": [], "busy": False,
             "balances": [], "last_out": None, "owners": {},
             "chat_history": [], "months": {}, "plans": {}}

    cats = load_categories()
    months = list(find_month_columns(
        openpyxl.load_workbook(DEFAULT_TEMPLATE)["Финансовый план"]).keys())
    balance_rows = load_balance_rows()

    # ------------------------------------------------------------ журнал
    log = ft.Column([], scroll=ft.ScrollMode.AUTO, expand=True, spacing=4)
    status = ft.Text("Готов к работе", size=12, color="#FFF3E8")

    def log_msg(text, color=GRAY_TEXT, icon=ft.icons.CHEVRON_RIGHT):
        log.controls.append(ft.Row([
            ft.Icon(icon, size=14, color=color),
            ft.Text(text, size=12, color=color, selectable=True, expand=True),
        ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.START))
        status.value = text
        page.update()

    # ------------------------------------------------------------ пикеры
    stmt_list = ft.Column([], spacing=6)
    bal_list = ft.Column([], spacing=4)

    def refresh_lists():
        rows = []
        for p in state["pdfs"]:
            owner_tf = ft.TextField(
                label="Владелец (псевдоним)", hint_text="напр. Я / Супруга",
                width=220, dense=True, text_size=12,
                value=state["owners"].get(p) or "",
                on_change=lambda e, path=p: state["owners"].__setitem__(
                    path, e.control.value.strip() or None))
            rows.append(ft.Row([
                ft.Icon(ft.icons.PICTURE_AS_PDF, color=ORANGE_DARK, size=18),
                ft.Text(os.path.basename(p), size=12, expand=True,
                        overflow=ft.TextOverflow.ELLIPSIS),
                owner_tf,
            ], spacing=8))
        stmt_list.controls = rows or [ft.Text("файлы не выбраны", size=12,
                                              color=GRAY_MUTED)]
        bal_list.controls = [ft.Text(os.path.basename(p), size=12)
                             for p in state["balance_pdfs"]] or \
                            [ft.Text("файлы не выбраны", size=12,
                                     color=GRAY_MUTED)]
        run_btn.disabled = not state["pdfs"] or state["busy"]
        page.update()

    def on_pick_statements(e: ft.FilePickerResultEvent):
        if e.files:
            state["pdfs"] = [f.path for f in e.files]
            refresh_lists()
            log_msg(f"Выбрано выписок: {len(state['pdfs'])}",
                    GRAY_TEXT, ft.icons.UPLOAD_FILE)

    def on_pick_balances(e: ft.FilePickerResultEvent):
        if e.files:
            state["balance_pdfs"] = [f.path for f in e.files]
            refresh_lists()
            parse_balances()

    stmt_picker = ft.FilePicker(on_result=on_pick_statements)
    bal_picker = ft.FilePicker(on_result=on_pick_balances)
    page.overlay.extend([stmt_picker, bal_picker])

    # ------------------------------------------------------------- остатки
    month_dd = ft.Dropdown(
        label="Месяц (колонка «Факт»)",
        value=months[8] if len(months) > 8 else months[0],
        options=[ft.dropdown.Option(m) for m in months], width=260, dense=True,
        text_size=12)
    balance_table = ft.Column([], spacing=6)
    write_bal_btn = ft.ElevatedButton(
        "Записать остатки в Excel", icon=ft.icons.SAVE_ALT,
        bgcolor=TEAL, color="white", disabled=True,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)))

    def render_balances():
        options = [ft.dropdown.Option(str(r["row"]),
                                      f'{r["name"]}  ({r["section"]})')
                   for r in balance_rows]
        balance_table.controls.clear()
        for i, b in enumerate(state["balances"]):
            dd = ft.Dropdown(options=options, width=330, dense=True,
                             label="Строка финплана", text_size=12)
            state["balances"][i]["target_row"] = dd
            src = f' · {b["source"]}' if b.get("source") else ""
            own = f' · {b["owner"]}' if b.get("owner") else ""
            balance_table.controls.append(ft.Row([
                ft.Text(f'{b["label"]} · {b["kind"]}{own}{src}', size=12,
                        width=270, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(f'{b["amount"]:,.2f} ₽', size=12,
                        weight=ft.FontWeight.BOLD, color=GRAY_TEXT),
                dd,
            ], spacing=10))
        write_bal_btn.disabled = not state["balances"]
        page.update()

    def parse_balances():
        state["balances"] = []
        try:
            for p in state["balance_pdfs"]:
                state["balances"].extend(parse_balances_pdf(p))
        except ValueError as ex:
            log_msg(f"Остатки: {ex}", RED, ft.icons.ERROR_OUTLINE)
            page.update()
            return
        render_balances()
        log_msg(f"Остатки распознаны: {len(state['balances'])} позиций — "
                f"выберите строки финплана", GRAY_TEXT, ft.icons.ACCOUNT_BALANCE)

    def on_write_balances(_):
        entries = [{"row": int(b["target_row"].value), "value": b["amount"]}
                   for b in state["balances"]
                   if b.get("target_row") and b["target_row"].value]
        if not entries:
            log_msg("Остатки: не выбраны целевые строки финплана", RED,
                    ft.icons.ERROR_OUTLINE)
            page.update()
            return
        target = state["last_out"] or DEFAULT_TEMPLATE
        try:
            out_path, journal = write_balances(target, DEFAULT_OUT_DIR,
                                               month_dd.value, entries)
        except Exception as ex:  # noqa: BLE001
            log_msg(f"Остатки: ошибка записи — {ex}", RED, ft.icons.ERROR_OUTLINE)
        else:
            state["last_out"] = out_path
            for j in journal:
                log_msg(f"Остаток: {j['col']} = {j['new']:,.2f} ₽",
                        GRAY_TEXT, ft.icons.EDIT_NOTE)
            log_msg(f"Файл: {out_path}", ORANGE_DARK, ft.icons.CHECK_CIRCLE)
        page.update()

    write_bal_btn.on_click = on_write_balances

    # --------------------------------------------------------------- выписки
    run_btn = ft.ElevatedButton(
        "Разобрать выписки", icon=ft.icons.AUTO_AWESOME,
        bgcolor=ORANGE, color="white", disabled=True, height=44,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10),
                             text_style=ft.TextStyle(size=14,
                                                     weight=ft.FontWeight.BOLD)))
    ops_area = ft.Column([], scroll=ft.ScrollMode.AUTO, spacing=10)
    totals_area = ft.Column([], scroll=ft.ScrollMode.AUTO, spacing=10)
    commentary_text = ft.Markdown(
        "Сначала разберите выписку на первой вкладке.",
        extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)

    test_mode = ft.Checkbox(
        label="Тестовый режим: разрешить повторную обработку "
              "(суммы в Excel задвоятся!)", value=False)

    def on_reset_dedup(_):
        if os.path.exists(DEDUP_DB):
            os.remove(DEDUP_DB)
            log_msg("Журнал обработанных файлов очищен — выписки можно "
                    "загружать заново", "#B26A00", ft.icons.REFRESH)
        else:
            log_msg("Журнал обработанных файлов пуст", GRAY_MUTED,
                    ft.icons.INFO_OUTLINE)
        page.update()

    def on_run(_):
        state["busy"] = True
        run_btn.disabled = True
        ops_area.controls.clear()
        totals_area.controls.clear()
        log_msg(f"Читаю PDF ({len(state['pdfs'])} шт.)…", GRAY_TEXT,
                ft.icons.HOURGLASS_TOP)

        def worker():
            try:
                pdf_args = [(p, state["owners"].get(p)) for p in state["pdfs"]]
                res = run(pdf_args, template_path=DEFAULT_TEMPLATE,
                          classifier_backend=backend,
                          dedup=not test_mode.value)
            except InvariantError as ex:
                log_msg(f"ОТКАЗ (инвариант): {ex}", RED, ft.icons.BLOCK)
                log_msg("Для повторной обработки той же выписки включите "
                        "«Тестовый режим» или нажмите «Забыть обработанные "
                        "файлы»", GRAY_MUTED, ft.icons.INFO_OUTLINE)
            except ValueError as ex:
                log_msg(f"Ошибка разбора: {ex}", RED, ft.icons.ERROR_OUTLINE)
            except Exception as ex:  # noqa: BLE001
                log_msg(f"Неожиданная ошибка: {type(ex).__name__}: {ex}",
                        RED, ft.icons.ERROR_OUTLINE)
            else:
                state["last_out"] = res.out_xlsx[-1] if res.out_xlsx else None
                state["months"], state["plans"] = res.months, res.plans
                show_result(res)
            finally:
                state["busy"] = False
                run_btn.disabled = not state["pdfs"]
                page.update()

        threading.Thread(target=worker, daemon=True).start()

    run_btn.on_click = on_run

    # ------------------------------------------------- итоги и операции
    def totals_table(month_key, agg):
        plans = read_plan(DEFAULT_TEMPLATE, month_key, cats)
        rows, tsv = [], ["Статья\tФакт\tПлан\tОтклонение"]
        for name, v in sorted(agg["by_category"].items(),
                              key=lambda x: abs(x[1]), reverse=True):
            fact = abs(v)
            plan = plans.get(name)
            dev = (fact - plan) if plan else None
            color = RED if (dev and dev > 0 and v < 0) else GRAY_TEXT
            rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(name, size=12)),
                ft.DataCell(ft.Text(f"{fact:,.2f}", size=12)),
                ft.DataCell(ft.Text(f"{plan:,.0f}" if plan else "—", size=12)),
                ft.DataCell(ft.Text(f"{dev:+,.0f}" if dev is not None else "—",
                                    size=12, color=color)),
            ]))
            tsv.append(f"{name}\t{fact:.2f}\t{plan or ''}\t"
                       f"{f'{dev:+.0f}' if dev is not None else ''}")
        tsv_text = "\n".join(tsv)

        def copy_click(_):
            try:
                page.set_clipboard(tsv_text)
                log_msg("Итоги скопированы в буфер (TSV)", GRAY_TEXT,
                        ft.icons.COPY)
            except Exception:
                log_msg("Буфер недоступен — скопируйте из TSV-поля вручную",
                        RED, ft.icons.ERROR_OUTLINE)

        return card(ft.Column([
            ft.Row([
                section_title(month_key, ft.icons.CALENDAR_MONTH, GREEN),
                ft.Text(f'доходы {agg["income_total"]:,.0f} ₽ · '
                        f'расходы {abs(agg["expense_total"]):,.0f} ₽',
                        size=12, color=GRAY_MUTED),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.DataTable(
                columns=[ft.DataColumn(ft.Text("Статья")),
                         ft.DataColumn(ft.Text("Факт"), numeric=True),
                         ft.DataColumn(ft.Text("План"), numeric=True),
                         ft.DataColumn(ft.Text("Откл."), numeric=True)],
                rows=rows, heading_row_color=GREEN_SOFT, border_radius=8,
                data_row_min_height=32),
            ft.Row([
                ft.OutlinedButton("Копировать итоги", icon=ft.icons.COPY,
                                  on_click=copy_click,
                                  style=ft.ButtonStyle(
                                      color=ORANGE_DARK,
                                      side=ft.BorderSide(1, ORANGE))),
            ]),
            ft.ExpansionTile(
                title=ft.Text("TSV для ручного копирования", size=11,
                              color=GRAY_MUTED),
                controls=[ft.TextField(value=tsv_text, multiline=True,
                                       read_only=True, min_lines=3,
                                       max_lines=6, text_size=11,
                                       bgcolor=GRAY_PANEL)],
                tile_padding=ft.padding.only(left=4, right=4),
                controls_padding=ft.padding.only(top=4)),
        ], spacing=8))

    def show_result(res):
        log_msg(f"Файлов: {res.n_files}, операций: {res.n_transactions}, "
                f"внутренних переводов исключено: {res.n_transfers_excluded}",
                GRAY_TEXT, ft.icons.SUMMARIZE)
        if res.skipped_duplicates:
            log_msg(f"Пропущены дубликаты: {', '.join(res.skipped_duplicates)}",
                    "#B26A00", ft.icons.COPY_ALL)
        log_msg(f"Классификатор: {res.classifier_name}", GRAY_MUTED,
                ft.icons.SMART_TOY)
        if res.mapping_rules:
            log_msg(f"Маппинг: {res.mapping_rules} правил, "
                    f"применено кодом к {res.mapping_applied} операциям "
                    f"(DeepSeek их не перекрывает)", GRAY_TEXT,
                    ft.icons.RULE)
        for t in res.mapping_unknown_targets:
            log_msg(f"Маппинг: статья «{t}» не найдена в финплане — "
                    f"добавьте строку в шаблон и запустите "
                    f"tools/rebuild_categories.py", RED, ft.icons.WARNING_AMBER)
        if res.unmapped:
            log_msg(f"{len(res.unmapped)} операций не распознаны — в «Прочие»",
                    "#B26A00", ft.icons.WARNING_AMBER)
        for p in res.out_xlsx:
            log_msg(f"Excel: {p}", ORANGE_DARK, ft.icons.CHECK_CIRCLE)
        for p in res.exports_1c:
            log_msg(f"Экспорт 1С: {p}", ORANGE_DARK, ft.icons.UPLOAD_FILE)

        rows = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(t["date"], size=11)),
                ft.DataCell(ft.Text(t["owner"], size=11)),
                ft.DataCell(ft.Text(f'{t["amount"]:+,.2f}', size=11)),
                ft.DataCell(ft.Text(t["description"][:40], size=11)),
                ft.DataCell(ft.Text(t["category"], size=11,
                                    color=ORANGE_DARK)),
            ]) for t in res.transactions_masked
        ]
        ops_area.controls.append(card(ft.Column([
            section_title("Что ушло в AI (после обезличивания)",
                          ft.icons.PRIVACY_TIP, BLUE),
            ft.DataTable(
                columns=[ft.DataColumn(ft.Text("Дата")),
                         ft.DataColumn(ft.Text("Владелец")),
                         ft.DataColumn(ft.Text("Сумма")),
                         ft.DataColumn(ft.Text("Описание (обезличено)")),
                         ft.DataColumn(ft.Text("Категория"))],
                rows=rows, heading_row_color=BLUE_SOFT,
                data_row_min_height=30),
        ], spacing=8)))

        for month_key, agg in res.months.items():
            totals_area.controls.append(totals_table(month_key, agg))

        commentary_text.value = res.commentary

        if res.balances:
            state["balances"].extend(res.balances)
            render_balances()
            log_msg(f"Из графы «Доступный остаток»: {len(res.balances)} "
                    f"остатков на конец периода — форма остатков",
                    "#B26A00", ft.icons.ACCOUNT_BALANCE)

    # ------------------------------------------------- чат с помощником
    chat_list = ft.ListView(spacing=8, auto_scroll=True)
    chat_input = ft.TextField(
        hint_text="Спросите про траты, экономию или вложения…",
        expand=True, dense=True, border_radius=12, text_size=13,
        on_submit=lambda e: send_chat(None))
    send_btn = ft.IconButton(icon=ft.icons.SEND_ROUNDED, icon_color=ORANGE,
                             on_click=lambda e: send_chat(None))

    def bubble(text, mine):
        return ft.Row([
            ft.Container(
                content=ft.Text(text, size=13, selectable=True,
                                color=GRAY_TEXT),
                bgcolor=ORANGE_SOFT if mine else TEAL_SOFT,
                border_radius=14, padding=12, width=520,
                border=ft.border.all(1, ORANGE if mine else TEAL),
            )
        ], alignment=(ft.MainAxisAlignment.END if mine
                      else ft.MainAxisAlignment.START))

    def send_chat(preset):
        question = preset or chat_input.value.strip()
        if not question:
            return
        chat_input.value = ""
        chat_list.controls.append(bubble(question, True))
        page.update()

        def worker():
            if not state["months"]:
                answer, mode = ("Сначала разберите выписку — тогда обсудим "
                                "цифры. Общие вопросы тоже можно, но без "
                                "контекста отвечу абстрактно.", "rules")
                if os.environ.get("DEEPSEEK_API_KEY"):
                    answer, mode = chat(question, {}, {},
                                        state["chat_history"])
            else:
                answer, mode = chat(question, state["months"],
                                    state["plans"], state["chat_history"])
            state["chat_history"].append({"role": "user", "content": question})
            state["chat_history"].append({"role": "assistant",
                                          "content": answer})
            chat_list.controls.append(bubble(answer, False))
            log_msg(f"Чат ({mode}): {question[:60]}", GRAY_MUTED,
                    ft.icons.CHAT_BUBBLE_OUTLINE)
            page.update()

        threading.Thread(target=worker, daemon=True).start()

    def chip(text, color=ORANGE_DARK):
        soft = {TEAL: TEAL_SOFT, ORANGE: ORANGE_SOFT, VIOLET: VIOLET_SOFT,
                BLUE: BLUE_SOFT}.get(color, ORANGE_SOFT)
        return ft.Container(
            content=ft.Text(text, size=12, color=color,
                            weight=ft.FontWeight.W_500),
            bgcolor=soft, border_radius=16, padding=ft.padding.symmetric(8, 14),
            border=ft.border.all(1, color), ink=True,
            on_click=lambda e: send_chat(text))

    # ------------------------------------------------------------- layout
    pick_stmt_btn = ft.OutlinedButton(
        "Выбрать выписки PDF (можно несколько)…", icon=ft.icons.UPLOAD_FILE,
        on_click=lambda _: stmt_picker.pick_files(
            dialog_title="Справки Т-Банка (PDF)", allowed_extensions=["pdf"],
            allow_multiple=True),
        style=ft.ButtonStyle(color=ORANGE_DARK, side=ft.BorderSide(1, ORANGE)))
    pick_bal_btn = ft.OutlinedButton(
        "Выбрать справки об остатках PDF…", icon=ft.icons.ACCOUNT_BALANCE,
        on_click=lambda _: bal_picker.pick_files(
            dialog_title="Справки об остатках (PDF)", allowed_extensions=["pdf"],
            allow_multiple=True),
        style=ft.ButtonStyle(color=TEAL_DARK, side=ft.BorderSide(1, TEAL)))

    backend = os.environ.get(
        "CLASSIFIER_BACKEND",
        "deepseek" if os.environ.get("DEEPSEEK_API_KEY") else "rules")

    tab_parse = ft.Column([
        card(ft.Column([
            section_title("Выписки о движении средств", ft.icons.RECEIPT_LONG,
                          ORANGE),
            ft.Row([pick_stmt_btn, run_btn], spacing=12),
            stmt_list,
            ft.Row([
                test_mode,
                ft.TextButton("Забыть обработанные файлы",
                              icon=ft.icons.REFRESH,
                              style=ft.ButtonStyle(color=GRAY_MUTED),
                              on_click=on_reset_dedup),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ], spacing=10)),
        card(ft.Column([
            section_title("Остатки по счетам", ft.icons.ACCOUNT_BALANCE, TEAL),
            ft.Row([pick_bal_btn, month_dd], spacing=12),
            bal_list,
            balance_table,
            write_bal_btn,
        ], spacing=10)),
        totals_area,
        ops_area,
    ], spacing=12, scroll=ft.ScrollMode.AUTO, expand=True)

    tab_helper = ft.Column([
        card(ft.Column([
            section_title("Комментарий аналитика", ft.icons.INSIGHTS, VIOLET),
            ft.Container(commentary_text, bgcolor=VIOLET_SOFT,
                         border_radius=12, padding=14),
        ], spacing=8)),
        card(ft.Column([
            section_title("Чат с финансовым помощником",
                          ft.icons.CHAT_BUBBLE_OUTLINE, BLUE),
            ft.Row([chip("Где можно сэкономить?", TEAL),
                    chip("Топ-3 статей расходов", ORANGE),
                    chip("Куда вложить свободные средства?", VIOLET),
                    chip("Что изменилось против плана?", BLUE)],
                   wrap=True, spacing=8),
            ft.Container(content=chat_list, height=320, bgcolor=GRAY_BG,
                         border_radius=12, padding=10),
            ft.Row([chat_input, send_btn], spacing=8),
        ], spacing=10)),
    ], spacing=12, scroll=ft.ScrollMode.AUTO, expand=True)

    tab_logs = ft.Column([
        card(ft.Column([
            ft.Row([
                section_title("Журнал работы", ft.icons.TERMINAL, GRAY_MUTED),
                ft.TextButton("Очистить", icon=ft.icons.DELETE_OUTLINE,
                              style=ft.ButtonStyle(color=GRAY_MUTED),
                              on_click=lambda _: (log.controls.clear(),
                                                  page.update())),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Container(content=log, bgcolor=GRAY_BG, border_radius=12,
                         padding=10, expand=True),
        ], spacing=8), expand=True),
    ], expand=True)

    tabs = ft.Tabs(
        selected_index=0, expand=True, animation_duration=250,
        indicator_color=ORANGE, label_color=ORANGE_DARK,
        unselected_label_color=GRAY_MUTED, divider_color="#E4E4E8",
        tabs=[
            ft.Tab(text="Разбор выписок", icon=ft.icons.RECEIPT_LONG,
                   content=ft.Container(tab_parse, padding=16)),
            ft.Tab(text="Финансовый помощник", icon=ft.icons.SUPPORT_AGENT,
                   content=ft.Container(tab_helper, padding=16)),
            ft.Tab(text="Логи", icon=ft.icons.TERMINAL,
                   content=ft.Container(tab_logs, padding=16)),
        ])

    header = ft.Container(
        padding=ft.padding.symmetric(18, 20),
        gradient=ft.LinearGradient(
            begin=ft.alignment.center_left, end=ft.alignment.center_right,
            colors=[ORANGE_DARK, ORANGE, TEAL]),
        content=ft.Row([
            ft.Row([
                ft.Container(bgcolor="#33FFFFFF", border_radius=10, width=34,
                             height=34,
                             content=ft.Icon(ft.icons.ACCOUNT_BALANCE_WALLET,
                                             color="white", size=20),
                             alignment=ft.alignment.center),
                ft.Column([
                    ft.Text("Финассистент", size=20,
                            weight=ft.FontWeight.BOLD, color="white"),
                    ft.Text("Выписки → финплан. Файлы не покидают компьютер; "
                            "в AI — только обезличенные строки.", size=11,
                            color="#FDE9DA"),
                ], spacing=1),
            ], spacing=12),
            ft.Row([
                ft.Container(
                    content=ft.Text(f"классификатор: {backend}", size=11,
                                    color="white"),
                    bgcolor="#40FFFFFF" if backend != "rules" else "#8E8E93",
                    border_radius=12,
                    padding=ft.padding.symmetric(6, 12)),
                status,
            ], spacing=12),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN))

    page.add(ft.Column([header, tabs], expand=True, spacing=0))
    page.update()


if __name__ == "__main__":
    if "--web" in sys.argv:
        ft.app(target=main, view=ft.AppView.WEB_BROWSER, port=8550)
    else:
        ft.app(target=main)
