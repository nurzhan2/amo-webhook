import os
import asyncio
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

AMO_LOGIN = os.getenv("AMO_LOGIN", "ivan-sherba@mail.ru")
AMO_PASSWORD = os.getenv("AMO_PASSWORD", "12345_Shch")
CHANNEL_ID = os.getenv("AMO_CHANNEL_ID", "27a6a572-7167-11f1-8a0e-3e32d30acdd5")
CHANNEL_URL = f"https://web.amo.tm/channel/{CHANNEL_ID}"

# Глобальный браузер — переиспользуем между запросами
_browser_ctx = {"playwright": None, "browser": None, "context": None, "page": None}


async def get_page():
    """Получаем или переиспользуем страницу браузера."""
    ctx = _browser_ctx

    # Если страница уже открыта и жива — возвращаем
    if ctx["page"] and not ctx["page"].is_closed():
        try:
            await ctx["page"].evaluate("1+1")
            return ctx["page"]
        except Exception:
            logger.info("Страница умерла, переподключаемся...")

    # Запускаем новый браузер если нужно
    if not ctx["playwright"]:
        ctx["playwright"] = await async_playwright().start()
        ctx["browser"] = await ctx["playwright"].chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        logger.info("Браузер запущен")

    # Создаём новый контекст и страницу
    ctx["context"] = await ctx["browser"].new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )
    ctx["page"] = await ctx["context"].new_page()

    # Логинимся
    await login(ctx["page"])
    return ctx["page"]


async def login(page):
    """Логин в amo.tm."""
    logger.info("Открываем amo.tm...")
    await page.goto("https://web.amo.tm/", wait_until="networkidle", timeout=30000)

    # Проверяем — уже залогинены?
    if "channel" in page.url or "direct" in page.url:
        logger.info("Уже залогинены")
        return

    # Ищем форму логина
    try:
        logger.info("Вводим логин/пароль...")
        await page.wait_for_selector("input[type='email'], input[name='email'], input[placeholder*='mail'], input[placeholder*='Email']", timeout=10000)
        await page.fill("input[type='email'], input[name='email'], input[placeholder*='mail'], input[placeholder*='Email']", AMO_LOGIN)
        await page.fill("input[type='password']", AMO_PASSWORD)
        await page.click("button[type='submit']")
        await page.wait_for_load_state("networkidle", timeout=20000)
        logger.info(f"После логина URL: {page.url}")
    except PlaywrightTimeout:
        logger.warning("Форма логина не найдена — возможно уже залогинены")

    # Переходим в канал
    logger.info(f"Переходим в канал {CHANNEL_URL}")
    await page.goto(CHANNEL_URL, wait_until="networkidle", timeout=30000)
    logger.info(f"Текущий URL: {page.url}")


async def send_message_playwright(text: str) -> dict:
    """Отправляем сообщение через браузер."""
    try:
        page = await get_page()

        # Убеждаемся что мы в нужном канале
        if CHANNEL_ID not in page.url:
            logger.info("Переходим в канал...")
            await page.goto(CHANNEL_URL, wait_until="networkidle", timeout=20000)

        # Ждём поле ввода
        selectors = [
            "div[contenteditable='true']",
            "textarea[placeholder*='сообщение']",
            "textarea[placeholder*='message']",
            ".message-input",
            "[data-testid='message-input']",
            "div[role='textbox']",
        ]

        input_el = None
        for sel in selectors:
            try:
                input_el = await page.wait_for_selector(sel, timeout=5000)
                if input_el:
                    logger.info(f"Нашли поле ввода: {sel}")
                    break
            except PlaywrightTimeout:
                continue

        if not input_el:
            # Делаем скриншот для отладки
            await page.screenshot(path="/tmp/debug.png")
            return {"status": "error", "detail": "Поле ввода не найдено"}

        # Кликаем и вводим текст
        await input_el.click()
        await asyncio.sleep(0.3)

        # Очищаем и вводим
        await page.keyboard.press("Control+a")
        await input_el.type(text, delay=10)
        await asyncio.sleep(0.3)

        # Отправляем Enter
        await page.keyboard.press("Enter")
        await asyncio.sleep(1)

        logger.info("Сообщение отправлено!")
        return {"status": "ok", "message": text[:50] + "..."}

    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
        # Сбрасываем страницу при ошибке
        _browser_ctx["page"] = None
        return {"status": "error", "detail": str(e)}


@app.on_event("startup")
async def startup():
    """Прогреваем браузер при старте."""
    logger.info("Прогреваем браузер...")
    try:
        await get_page()
        logger.info("Браузер готов!")
    except Exception as e:
        logger.error(f"Ошибка прогрева: {e}")


@app.on_event("shutdown")
async def shutdown():
    """Закрываем браузер."""
    if _browser_ctx["browser"]:
        await _browser_ctx["browser"].close()
    if _browser_ctx["playwright"]:
        await _browser_ctx["playwright"].stop()


@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <html><body style="font-family:sans-serif;padding:20px">
    <h2>amo.tm Webhook (Playwright)</h2>
    <p>Статус: <strong>работает</strong></p>
    <h3>Тест отправки:</h3>
    <textarea id="msg" rows="4" cols="60">Тестовое сообщение</textarea><br><br>
    <button onclick="sendTest()">Отправить в канал</button>
    <div id="result" style="margin-top:10px"></div>
    <script>
    async function sendTest() {
        document.getElementById('result').innerHTML = 'Отправляем...';
        const msg = document.getElementById('msg').value;
        const res = await fetch('/test-send', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({text: msg})
        });
        const data = await res.json();
        document.getElementById('result').innerHTML =
            '<pre style="color:' + (data.status==='ok'?'green':'red') + '">' +
            JSON.stringify(data, null, 2) + '</pre>';
    }
    </script>
    </body></html>
    """


@app.post("/test-send")
async def test_send(request: Request):
    data = await request.json()
    text = data.get("text", "Тест")
    result = await send_message_playwright(text)
    return JSONResponse(result)


@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = dict(await request.form())

    name = data.get("Фамилия Имя Родителя", data.get("name", ""))
    phone = data.get("Телефон Родителя", data.get("phone", ""))
    region = data.get("Время по отношению к МСК", data.get("region", ""))
    time_pref = data.get("Когда связаться куратору: предпочтительное время", data.get("time", ""))
    amocrm_link = data.get("Ссылка на карточку сделки amoCRM", data.get("amocrm_link", ""))

    message = (
        f"🚨 Новая передача 🚨\n"
        f"Ссылка на amoCRM: {amocrm_link}\n"
        f"Фамилия и имя родителя: {name}\n"
        f"Телефон родителя: {phone}\n"
        f"Регион и время: {region}\n"
        f"Предпочтительное время для связи: {time_pref}\n"
        f"❗️ Без подтверждения сообщения взятие в работу считается непринятым."
    )

    result = await send_message_playwright(message)
    return JSONResponse(result)


@app.get("/health")
async def health():
    page_ok = _browser_ctx["page"] is not None and not _browser_ctx["page"].is_closed()
    return {"status": "ok", "browser_ready": page_ok, "channel": CHANNEL_ID}