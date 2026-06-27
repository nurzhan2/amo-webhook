import os
import asyncio
import logging
import base64
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

_browser_ctx = {"playwright": None, "browser": None, "context": None, "page": None}


async def get_page():
    ctx = _browser_ctx
    if ctx["page"] and not ctx["page"].is_closed():
        try:
            await ctx["page"].evaluate("1+1")
            return ctx["page"]
        except Exception:
            logger.info("Страница умерла, переподключаемся...")

    if not ctx["playwright"]:
        ctx["playwright"] = await async_playwright().start()
        ctx["browser"] = await ctx["playwright"].chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        logger.info("Браузер запущен")

    ctx["context"] = await ctx["browser"].new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800}
    )
    ctx["page"] = await ctx["context"].new_page()
    await login(ctx["page"])
    return ctx["page"]


async def login(page):
    logger.info("Открываем amo.tm...")
    await page.goto("https://web.amo.tm/", wait_until="networkidle", timeout=60000)
    logger.info(f"После goto URL: {page.url}")

    # Если уже в канале — готово
    if CHANNEL_ID in page.url:
        logger.info("Уже в канале!")
        return

    # Пробуем найти форму логина
    try:
        await page.wait_for_selector("input[type='email'], input[name='email']", timeout=8000)
        logger.info("Нашли форму логина, вводим credentials...")
        await page.fill("input[type='email'], input[name='email']", AMO_LOGIN)
        await page.fill("input[type='password']", AMO_PASSWORD)
        await page.click("button[type='submit']")
        await page.wait_for_load_state("networkidle", timeout=30000)
        logger.info(f"После логина URL: {page.url}")
    except PlaywrightTimeout:
        logger.info("Форма логина не появилась — пробуем перейти в канал напрямую")

    # Переходим в канал
    logger.info(f"Переходим в канал...")
    await page.goto(CHANNEL_URL, wait_until="networkidle", timeout=60000)
    await asyncio.sleep(3)
    logger.info(f"Финальный URL: {page.url}")


async def take_screenshot():
    """Делаем скриншот текущего состояния страницы."""
    try:
        page = _browser_ctx["page"]
        if page and not page.is_closed():
            screenshot = await page.screenshot(type="jpeg", quality=50)
            return base64.b64encode(screenshot).decode()
    except Exception as e:
        logger.error(f"Скриншот не удался: {e}")
    return None


async def send_message_playwright(text: str) -> dict:
    try:
        page = await get_page()

        if CHANNEL_ID not in page.url:
            logger.info("Переходим в канал...")
            await page.goto(CHANNEL_URL, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)

        logger.info(f"Текущий URL перед поиском инпута: {page.url}")

        # Ждём загрузки
        await asyncio.sleep(2)

        # Логируем все найденные элементы
        all_inputs = await page.evaluate("""() => {
            const elements = [];
            // contenteditable
            document.querySelectorAll('[contenteditable]').forEach(el => {
                elements.push({type: 'contenteditable', tag: el.tagName, class: el.className.substring(0,50)});
            });
            // textarea
            document.querySelectorAll('textarea').forEach(el => {
                elements.push({type: 'textarea', tag: el.tagName, placeholder: el.placeholder});
            });
            // role textbox
            document.querySelectorAll('[role="textbox"]').forEach(el => {
                elements.push({type: 'textbox', tag: el.tagName, class: el.className.substring(0,50)});
            });
            return elements;
        }""")
        logger.info(f"Найденные input элементы: {all_inputs}")

        selectors = [
            "div[contenteditable='true']",
            "[contenteditable='true']",
            "textarea",
            "[role='textbox']",
            ".chat-input",
            ".message-input",
            "div[data-placeholder]",
        ]

        input_el = None
        for sel in selectors:
            try:
                els = await page.query_selector_all(sel)
                if els:
                    input_el = els[0]
                    logger.info(f"Нашли инпут по селектору: {sel}, кол-во: {len(els)}")
                    break
            except Exception as e:
                logger.info(f"Селектор {sel} не сработал: {e}")
                continue

        if not input_el:
            logger.error("Поле ввода не найдено!")
            return {"status": "error", "detail": "Поле ввода не найдено", "inputs_found": all_inputs, "url": page.url}

        await input_el.click()
        await asyncio.sleep(0.5)
        await input_el.type(text, delay=20)
        await asyncio.sleep(0.3)
        await page.keyboard.press("Enter")
        await asyncio.sleep(1)

        logger.info("Сообщение отправлено!")
        return {"status": "ok", "message": text[:50]}

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        _browser_ctx["page"] = None
        return {"status": "error", "detail": str(e)}


@app.on_event("startup")
async def startup():
    logger.info("Прогреваем браузер...")
    try:
        await get_page()
        logger.info("Браузер готов!")
    except Exception as e:
        logger.error(f"Ошибка прогрева: {e}")


@app.on_event("shutdown")
async def shutdown():
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
    <br><br>
    <button onclick="getScreenshot()">📷 Скриншот браузера</button>
    <div id="screenshot" style="margin-top:10px"></div>
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
    async function getScreenshot() {
        document.getElementById('screenshot').innerHTML = 'Делаем скриншот...';
        const res = await fetch('/screenshot');
        const data = await res.json();
        if (data.screenshot) {
            document.getElementById('screenshot').innerHTML =
                '<img src="data:image/jpeg;base64,' + data.screenshot + '" style="max-width:100%;border:1px solid #ccc">';
        } else {
            document.getElementById('screenshot').innerHTML = 'Скриншот не удался: ' + data.error;
        }
    }
    </script>
    </body></html>
    """


@app.get("/screenshot")
async def screenshot():
    img = await take_screenshot()
    if img:
        return {"screenshot": img}
    return {"error": "Скриншот не удался"}


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