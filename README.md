# Neuro D&D

Neuro D&D - это настольная ролевая игра на базе AI, разработанная с использованием Python, FastAPI и чистого HTML/CSS/JS. Проект разработан для локального запуска в Windows "из коробки".

## Архитектура

Проект имеет четкое разделение на три основных компонента:

-   **`server/`**: Бэкенд на FastAPI, обрабатывающий всю игровую логику, API-запросы и взаимодействие с AI (Gemini).
-   **`frontend/`**: Клиентская часть, написанная на чистом HTML/CSS/JavaScript. Это одностраничное приложение (SPA) для взаимодействия с игрой.
-   **`data/`**: Хранилище данных SQLite (`neuro_dnd.db`). Здесь содержатся профили пользователей, кампании, журналы и т.д.

## Генерация изображений

После ответа AI-мастера фронтенд отправляет описание сцены на серверный эндпоинт `/api/ai/image`. Сервер вызывает Cloudflare Workers AI text-to-image модель и возвращает `data:image/...;base64,...`, который сразу отображается под текстом сцены. Аватары персонажей генерируются тем же API, сохраняются файлами в `data/generated/avatars/`, а в SQLite-профиле хранится только URL аватара — так база не раздувается большими base64-строками.

Для работы нужны переменные окружения:

- `CLOUDFLARE_ACCOUNT_ID` — Account ID из Cloudflare Dashboard → Workers AI → Use REST API.
- `CLOUDFLARE_API_TOKEN` — Workers AI API Token. Не храните реальный токен в Git.
- `CLOUDFLARE_IMAGE_MODEL` — модель генерации изображений, по умолчанию `@cf/black-forest-labs/flux-1-schnell`.
- `CLOUDFLARE_IMAGE_STEPS` — число шагов генерации, от 1 до 8; по умолчанию `4`.

## Быстрый старт (Windows)

1.  **Клонируйте репозиторий:**
    ```bash
    git clone <repository-url>
    cd neuro-dnd
    ```

2.  **Настройка окружения:**
    Запустите `setup.bat`, чтобы создать виртуальное окружение и установить все необходимые зависимости.
    ```bash
    setup.bat
    ```
    После выполнения скрипта будет создан файл `.env`. Откройте его в текстовом редакторе и вставьте API-ключ Google Gemini, а также Account ID и Workers AI API Token от Cloudflare.
    ```
    GEMINI_API_KEY=__PUT_YOUR_KEY_HERE__
    GEMINI_MODEL=gemini-2.0-flash
    GEMINI_FALLBACK_MODELS=gemini-2.0-flash,gemini-2.0-flash-exp,gemini-1.5-flash-latest
    CLOUDFLARE_ACCOUNT_ID=__PUT_YOUR_ACCOUNT_ID_HERE__
    CLOUDFLARE_API_TOKEN=__PUT_YOUR_TOKEN_HERE__
    CLOUDFLARE_IMAGE_MODEL=@cf/black-forest-labs/flux-1-schnell
    CLOUDFLARE_IMAGE_STEPS=4
    ```

> Если раньше в `.env` стояло `GEMINI_MODEL=gemini-pro` или `GEMINI_MODEL=gemini-1.5-flash`, замените его на `GEMINI_MODEL=gemini-2.0-flash`. Сервер также автоматически переводит эти старые значения на актуальную модель и пробует fallback-модели из `GEMINI_FALLBACK_MODELS`.
> Проект полностью переведён на новый SDK `google-genai`; старый `google.generativeai` больше не используется. Новый `run_dev.bat` печатает путь к активному `server/api/ai.py`, выбранную Gemini-модель и наличие пакета `google-genai` перед стартом сервера.

### Исправление старой Gemini-модели на Windows

Если в логах запуска есть `import google.generativeai as genai`, установка старого `google-generativeai` или ошибка `models/gemini-1.5-flash is not found`, значит запущена старая копия файлов или старый `.env`. Выполните из корня проекта:

```bat
fix_gemini.bat
```

Скрипт установит нужный проекту `google-genai`, сохранит `.env.bak`, выставит `GEMINI_MODEL=gemini-2.0-flash` и `GEMINI_FALLBACK_MODELS=gemini-2.0-flash,gemini-2.0-flash-exp,gemini-1.5-flash-latest`, затем напечатает активный путь к AI-модулю.

3.  **Запуск сервера:**
    Запустите `run_dev.bat`, чтобы активировать виртуальное окружение и запустить веб-сервер.
    ```bash
    run_dev.bat
    ```
    Сервер будет доступен по адресу `http://localhost:8000`. Он также будет доступен с других устройств в вашей локальной сети по вашему локальному IP-адресу (например, `http://192.168.1.10:8000`).

4.  **Начало игры:**
    Откройте `http://localhost:8000` в вашем браузере. Зарегистрируйтесь и начните свою первую кампанию!
