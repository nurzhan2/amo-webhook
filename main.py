import os
import httpx
import json
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

# Config from environment variables
CLIENT_ID = os.getenv("AMO_CLIENT_ID")
CLIENT_SECRET = os.getenv("AMO_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("AMO_REFRESH_TOKEN")
CHANNEL_ID = os.getenv("AMO_CHANNEL_ID")
TEAM_ID = os.getenv("AMO_TEAM_ID")

TOKEN_URL = "https://id.amo.tm/oauth2/access_token"
MESSAGE_URL = f"https://api.amo.io/v1.3/direct/{CHANNEL_ID}/messages"

# Store current access token in memory
current_token = {"access_token": None, "refresh_token": REFRESH_TOKEN}


async def get_access_token():
    """Get fresh access token using refresh token"""
    async with httpx.AsyncClient() as client:
        response = await client.post(TOKEN_URL, json={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": current_token["refresh_token"]
        })
        data = response.json()
        if "access_token" in data:
            current_token["access_token"] = data["access_token"]
            if "refresh_token" in data:
                current_token["refresh_token"] = data["refresh_token"]
            return data["access_token"]
        raise Exception(f"Token refresh failed: {data}")


async def send_message(text: str):
    """Send message to amo.tm channel"""
    if not current_token["access_token"]:
        await get_access_token()

    headers = {
        "Authorization": f"Bearer {current_token['access_token']}",
        "Content-Type": "application/json",
        "X-Team-Id": str(TEAM_ID)
    }

    payload = {"type": "text", "text": text}

    async with httpx.AsyncClient() as client:
        response = await client.post(MESSAGE_URL, json=payload, headers=headers)

        # If token expired, refresh and retry
        if response.status_code == 401:
            await get_access_token()
            headers["Authorization"] = f"Bearer {current_token['access_token']}"
            response = await client.post(MESSAGE_URL, json=payload, headers=headers)

        return response.status_code, response.text


@app.post("/webhook")
async def webhook(request: Request):
    """Receive webhook from Albato and send message to amo.tm"""
    try:
        data = await request.json()
    except:
        data = dict(await request.form())

    # Build message text from form data
    name = data.get("name", data.get("Фамилия Имя Родителя", ""))
    phone = data.get("phone", data.get("Телефон Родителя", ""))
    region = data.get("region", data.get("Время по отношению к МСК", ""))
    time_pref = data.get("time", data.get("Когда связаться куратору: предпочтительное время", ""))
    amocrm_link = data.get("amocrm_link", data.get("Ссылка на карточку сделки amoCRM", ""))

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
    return {"status": "ok"}