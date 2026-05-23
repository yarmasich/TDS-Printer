# TDS Printer Server

FastAPI бэкенд — **только JSON API**. Веб-интерфейс живёт отдельно в
`../frontend/` (Vue 3 + Vite), бэк его не отдаёт. Так бэкенд можно
переиспользовать (мобильный клиент, скрипты, другой фронт), а фронт
деплоить независимо.

## Что это

Заменяет per-планшетный SharedPreferences одним центральным сервером в
локальной сети. Все шаблоны, авторизации, причины и история печати живут
в одной БД. Печатает сам — рендерит битмап (PIL) и шлёт raw TCP на принтеры.

## Текущее состояние (MVP)

- [x] FastAPI + SQLite
- [x] CRUD: шаблоны, причины, авторизованные операторы, история печати
- [x] Веб-UI: Print Panel (`/`) и Admin (`/admin`)
- [ ] **Print engine — заглушка** (логирует в stdout, реальную отправку байт на принтер
      добавим следующим шагом, портируя `PandaRawPrinter.buildPrintJob` из smali)
- [ ] Excel импорт + поиск
- [x] Admin login (JWT, env credentials)

## Запуск

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env              # задайте ADMIN_* (см. ниже)
set -a && source .env && set +a   # или export вручную
alembic upgrade head              # создаёт / мигрирует БД
uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    --reload --reload-dir app --reload-dir alembic
```

### Admin login

Панель `/admin` и изменяющие API (шаблоны, импорт, CRUD проектов и т.д.)
требуют JWT после `POST /api/auth/login`. **Print** и **Kiosk** без пароля.

Переменные окружения (см. `.env.example`):

- `ADMIN_USERNAME` — логин
- `ADMIN_PASSWORD` — пароль
- `ADMIN_JWT_SECRET` — случайная длинная строка для подписи токена

Без этих переменных вход в админку отключён (`503` на login).

Чтобы посмотреть UI — поднимите фронт отдельно: `cd ../frontend && npm run dev`,
откройте `http://localhost:5173`.

Эндпоинты:
- `GET /` — служебный JSON-баннер (`{service, docs, openapi, health, frontend}`)
- `GET /docs` — Swagger
- `GET /openapi.json` — спека (фронт качает её для генерации типов)
- `GET /health` — `{ok: true}`
- `GET /api/*` — REST

> ⚠️ **Важно**: с обычным `--reload` uvicorn смотрит **весь cwd**, включая
> `data/tds.db`. Каждая запись в SQLite меняет mtime файла — uvicorn
> перезапускается прямо в момент транзакции, остаются хвосты от прерванных
> писем и SQLite начинает возвращать `attempt to write a readonly database`.
> Поэтому всегда передавайте `--reload-dir app --reload-dir alembic` (или
> запускайте без `--reload` в продакшне). И обязательно из активированного
> venv — `source .venv/bin/activate`, иначе пойдёт системный uvicorn.

Откройте `http://localhost:8000/` — это страница печати,
`http://localhost:8000/admin` — админка с CRUD,
`http://localhost:8000/docs` — Swagger.

## Миграции БД (Alembic)

Источник истины для схемы — модели в `app/models.py`. Любое изменение
модели надо превращать в миграцию.

```bash
# Применить все накопленные миграции (нужно при первом запуске и после git pull)
alembic upgrade head

# После того как поменяли модель — сгенерировать миграцию
alembic revision --autogenerate -m "add foo to template"
# Откройте сгенерированный файл в alembic/versions/, прочитайте, поправьте если надо

# Накатить
alembic upgrade head

# Откатить на 1 ревизию
alembic downgrade -1

# Текущее состояние
alembic current

# Полный список
alembic history
```

SQLite поддерживает только ограниченный `ALTER TABLE`. У нас включён
`render_as_batch=True` — alembic эмулирует ALTER через CREATE-COPY-DROP, так
что большинство правок (rename column, change type, add NOT NULL, …) работают.
Сложные случаи (например, изменение типа FK) могут потребовать ручной правки
миграции.

Стартап-хук `init_db()` мы убрали — теперь схемой управляет **только** alembic.
Если запустить uvicorn до `alembic upgrade head` — будут 500-ки на запросах к БД.

## Структура

```
app/
├── main.py              — приложение, маунты роутов
├── db.py                — SQLite engine + create_all
├── models.py            — Template, Reason, AuthName, PrintLog
├── printer.py           — STUB печати (TODO: порт PandaRawPrinter)
├── api/
│   ├── templates.py     — CRUD
│   ├── reasons.py       — CRUD
│   ├── auth_names.py    — CRUD
│   ├── print.py         — POST /api/print
│   └── history.py       — GET /api/history
├── web/
│   ├── routes.py        — Jinja страницы
│   └── templates/       — base, index, admin
└── static/
    └── style.css        — lifted из WebAdminServer
data/tds.db              — БД (создаётся автоматически)
```

## Развёртывание на mini-PC / Raspberry Pi

1. На сервере (Raspberry Pi OS / Ubuntu) поставить Python 3.11+.
2. Скопировать проект, `pip install -e .`.
3. systemd unit:
   ```
   [Unit]
   Description=TDS Printer Server
   After=network.target

   [Service]
   ExecStart=/path/to/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
   WorkingDirectory=/opt/tds-server
   Restart=always
   User=pi

   [Install]
   WantedBy=multi-user.target
   ```
4. На каждом планшете: установить **Fully Kiosk Browser**, указать homepage
   `http://<server-ip>:8000/`, включить landscape lock + immersive.

## Следующие шаги

1. **Print engine**: порт `PandaRawPrinter.buildPrintJob` на Python (PIL для
   рендеринга текста, ручная упаковка 1-бит растра, `socket` для отправки
   на `ip:port`). См. `app/printer.py`.
2. **Импорт XLSX**: `openpyxl` для парсинга, перенос полей из `XlsxReader`.
3. **Поиск**: `SearchFilters` + индексы по `LabelRow`.
4. **Авторизация**: cookie-сессии + PIN.
5. **Миграция данных с планшетов**: одноразовая команда, читающая
   SharedPreferences старого APK и заливающая в БД.
