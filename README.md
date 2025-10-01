# ChatGPT Mentor Bot

Телеграм-бот «ChatGPT Mentor» помогает создавать напоминания, задачи, ритуалы и списки покупок. Репозиторий содержит код, который автоматически деплоится на сервер после слияния в ветку `main`.

## Запуск локально

1. Создайте виртуальное окружение и установите зависимости (на сервере используется аналогичное окружение `venv`):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Скопируйте файл `.env.example` в `.env` и добавьте токен Telegram-бота:

```bash
cp .env.example .env
# Отредактируйте файл и пропишите BOT_TOKEN=...
```

3. Запустите приложение:

```bash
python bot.py
```

Бот автоматически создаст базу данных `data/mentor.db` и начнёт polling. Схема БД создаётся и обновляется автоматически при старте, данные не теряются. В production токен берётся из `/opt/chatgpt_mentor/.env`, который подключается через `EnvironmentFile` в systemd-юните.

## Деплой

Деплой выполняется GitHub Actions воркфлоу `.github/workflows/deploy.yml`. После пуша в `main` репозиторий обновляется на сервере по SSH, обновляет зависимости в существующем `venv` и перезапускает systemd-сервис `mentor-bot`.

## Структура

- `bot.py` — основной вход и обработчики aiogram.
- `keyboards.py` — все клавиатуры.
- `storage.py` — работа с SQLite и модели данных.
- `scheduler.py` — планировщик напоминаний на базе APScheduler.
- `etc/systemd/system/mentor-bot.service` — unit-файл для сервиса.

Файл `.env` не хранится в репозитории, используйте `.env.example` как шаблон.
