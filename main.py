import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse

app = FastAPI()

CHANNEL_ID = os.getenv("AMO_CHANNEL_ID")
TEAM_ID = os.getenv("AMO_TEAM_ID")
AMO_LOGIN = os.getenv("AMO_LOGIN")
AMO_PASSWORD = os.getenv("AMO_PASSWORD")

MESSAGE_URL = f"https://api.amo.io/v1.3/direct/{CHANNEL_ID}/messages"

current_token = {"access_token": os.getenv("AMO_ACCESS_TOKEN", "")}


@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <html><body>
    <h2>amo.tm Token Updater</h2>
    <p>Paste your token from web.amo.tm console:</p>
    <textarea id="token" rows="5" cols="80"></textarea><br><br>
    <button onclick="updateToken()">Update Token</button>
    <div id="result"></div>
    <script>
    async function updateToken() {
        const token = document.getElementById('token').value.trim();
        const res = await fetch('/update-token', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({token})
        });
        const data = await res.json();
        document.getElementById('result').innerHTML = '<p style="color:green">'+JSON.stringify(data)+'</p>';
    }
    </script>
    </body></html>
    """


@app.post("/update-token")
async def update_token(request: Request):
    data = await request.json()
    token = data.get("token", "").strip()
    if token.startswith("'") or token.startswith('"'):
        token = token[1:-1]
    current_token["access_token"] = token
    return {"status": "ok", "token_preview": token[:20] + "..."}


async def send_message(text: str):
    headers = {
        "Authorization": f"Bearer {current_token['access_token']}",
        "Content-Type": "application/json",
        "X-Team-Id": str(TEAM_ID)
    }
    payload = {"type": "text", "text": text}
    async with httpx.AsyncClient() as client:
        response = await client.post(MESSAGE_URL, json=payload, headers=headers)
        return response.status_code, response.text


@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
    except:
        data = dict(await request.form())

    name = data.get("Фамилия Имя Родителя", data.get("name", ""))
    phone = data.get("Телефон Родителя", data.get("phone", ""))
    region = data.get("Время по отношению к МСК", data.get("region", ""))
    time_pref = data.get("Когда связаться куратору: предпочтительное время", data.get("time", ""))
    amocrm_link = data.get("Ссылка на карточку сделки amoCRM", data.get("amocrm_link", ""))

    message = f"""🚨 Новая передача 🚨 Ссылка на amoCRM:
Ссылка на amoCRM: {amocrm_link}
Фамилия и имя родителя: {name}
Телефон родителя: {phone}
Регион и время: {region}
Предпочтительное время для связи: {time_pref}
❗️ Без подтверждения сообщения взятие в работу сообщение считается непринятым."""

    status, response_text = await send_message(message)
    return JSONResponse({"status": status, "response": response_text})


@app.get("/health")
async def health():
    return {"status": "ok", "token_set": bool(current_token["access_token"])}