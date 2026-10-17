# AI-ассистент поддержки пользователей

Мини-сервис поддержки на базе проекта «агент_спецификаций_1с»:
отвечает на вопросы о продукте с опорой на базу знаний (RAG) и контекст
пользователя/тикета из CRM, подключённой через MCP.

## Возможности

- **Чат поддержки** (`/`): пользователь вводит email или номер тикета —
  ассистент через MCP подтягивает карточку пользователя и активный тикет
  и отвечает с их учётом. Под каждым ответом — источники из базы знаний.
- **RAG**: эмбеддинги `intfloat/multilingual-e5-large`, локально на CPU
  (sentence-transformers), векторный индекс FAISS, персистентный на диске.
- **MCP-сервер CRM** (`mcp_server/`): инструменты `get_user`, `find_user`,
  `list_users`, `create_user`, `list_tickets`, `get_ticket`,
  `add_ticket_comment`, `update_ticket_status`. Источник данных — через
  интерфейс `CRMProvider` (реализация по умолчанию — JSON-файлы; для
  реальной CRM реализуйте `domain/crm/base.py`).
- **Администрирование** (`/admin`): управление базой знаний (загрузка
  файлов, вставка текста, переиндексация, удаление), просмотр
  пользователей и тикетов, настройки агента (модель, температура,
  top-k и порог RAG, thinking mode).
- **Логи** (`/logs`): статистика (диалоги, средняя оценка, токены)
  и журнал событий dialog/rag/mcp/llm/feedback с фильтрацией.
- **Форма оценки**: после завершения диалога — оценка 1–5 и комментарий,
  сохраняются и видны в логах и статистике.

## Стек

Python 3.12, Flet 1.x (веб-режим), DeepSeek API (`deepseek-v4-pro`),
sentence-transformers + faiss-cpu, fastmcp. Хранение — JSON-файлы
с атомарной записью (слой репозиториев позволяет перейти на SQLite).

## Структура

```
main.py               # Flet-приложение, маршруты / /admin /logs
data/                 # модели, JSON-хранилище, репозитории, демо-данные
domain/
  agent.py            # агент поддержки: контекст + RAG + tool loop
  deepseek_client.py  # DeepSeek API, ключ из DEEPSEEK_API_KEY
  mcp_client.py       # синхронный клиент к MCP-серверу
  crm/                # интерфейс CRMProvider + JSON-реализация
  rag/                # chunking, embedder (e5-large), FAISS, retriever
mcp_server/server.py  # MCP-сервер CRM (fastmcp, streamable HTTP)
ui/                   # страницы Flet, светлая тема (оранж/серый/зелёный)
tests/run_tests.py    # сквозные проверки без внешних зависимостей
storage/              # данные (создаётся при первом запуске)
```

## Локальный запуск

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

export DEEPSEEK_API_KEY=sk-...          # Windows: set DEEPSEEK_API_KEY=sk-...

python main.py                          # http://127.0.0.1:8550
```

MCP-сервер CRM при локальном запуске **поднимается автоматически**
подпроцессом (порт 8001). Отключить автозапуск: `MCP_AUTOSTART=0`,
тогда сервер нужен отдельно: `python -m mcp_server.server`.
В Docker автозапуск не применяется — там MCP работает отдельным
контейнером.

При первом запуске скачается модель эмбеддингов (~2,2 ГБ) и построится
индекс демо-FAQ. Демо-доступ: `ivan.petrov@example.com` (тикет T-1001
про ошибку авторизации AUTH-403), `maria.s@example.com`, `T-1003`.

## Развёртывание на VPS (Docker Compose, доступ по IP:port)

Требования к VPS: 2 vCPU, **4 ГБ RAM** (модель e5-large + torch),
10 ГБ диска, Docker и Docker Compose plugin.

```bash
# 1. Скопировать проект на сервер (любым способом)
scp -r support_assistant user@<IP-VPS>:/opt/

# 2. На сервере: ключ в .env
cd /opt/support_assistant
cp .env.example .env && nano .env        # вписать DEEPSEEK_API_KEY

# 3. Сборка и запуск (сборка ~10–20 мин: torch + модель в образе)
docker compose up -d --build

# 4. Открыть порт в файрволе, если включён
sudo ufw allow 8550/tcp
```

Сервис доступен на `http://<IP-VPS>:8550`. Данные — в volume
`support_data` (диалоги, тикеты, база знаний, логи, индекс FAISS),
переживают пересборку контейнеров.

Проверка: `docker compose logs -f app`, `docker compose logs -f mcp-server`.
Обновление кода: `git pull` (или повторный scp) + `docker compose up -d --build`.

## Переменные окружения

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | ключ DeepSeek API (обязательно) |
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8550` | привязка веб-сервера |
| `MCP_URL` | `http://localhost:8001/mcp` | адрес MCP-сервера (в compose — `http://mcp-server:8001/mcp`) |
| `MCP_AUTOSTART` | `1` | локальный автозапуск MCP-сервера подпроцессом |
| `MCP_TRANSPORT` / `MCP_PORT` | `streamable-http` / `8001` | режим MCP-сервера (`stdio` для отладки) |
| `STORAGE_DIR` | `./storage` | каталог данных |
| `EMBED_MODEL` | `intfloat/multilingual-e5-large` | модель эмбеддингов |
| `CRM_PROVIDER` | `json` | провайдер CRM (точка расширения) |

## Тесты

```bash
python tests/run_tests.py
```

Покрывает: репозитории и хранилище, чанкинг, RAG на реальной модели
(первый прогон скачает e5-large), MCP-сервер через HTTP, полный цикл
агента с заглушкой LLM (диалог → вызов инструмента → ответ → оценка).

## Осознанные упрощения (учебный проект)

- Страницы `/admin` и `/logs` без аутентификации — по ТЗ.
- Flet держит состояние сессии в памяти одного процесса: перезапуск
  приложения сбрасывает открытые чаты (диалоги сохранены в JSON).
- MCP поверх JSON избыточен функционально, но оставляет готовую точку
  подключения реальной CRM без изменений агента.
- `deepseek-v4-pro` — дефолт по ТЗ; в `/admin` переключается на
  `deepseek-flash` (быстрее и дешевле для FAQ-диалогов).
