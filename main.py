import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

CHANNEL_ID = os.getenv("AMO_CHANNEL_ID")
TEAM_ID = os.getenv("AMO_TEAM_ID")
AMO_LOGIN = os.getenv("AMO_LOGIN")
AMO_PASSWORD = os.getenv("AMO_PASSWORD")

# amo.tm app credentials (from their frontend)
APP_ID = "g;8;33i709;<e044h;0;;43035753d3f3337"
APP_SECRET = "zPNtGXQ\\PO6:DP:vO:OnhVz4zrI48MeP]:}rNz7eXfh{KxPEPkUwd|HUYmv\\ts9G"

MESSAGE_URL = f"https://api.amo.io/v1.3/direct/{CHANNEL_ID}/messages"
TOKEN_URL = "https://id.amo.tm/oauth2/access_token"

current_token = {"access_token": None}


async def get_token():
    async with httpx.AsyncClient() as client:
        response = await client.post(TOKEN_URL, data={
            "grant_type": "password",
            "client_id": APP_ID,
            "client_secret": APP_SECRET,
            "username": AMO_LOGIN,
            "password": AMO_PASSWORD,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        data = response.json()
        if "access_token" in data:
            current_token["access_token"] = data["access_token"]
            return data["access_token"]
        raise Exception(f"Auth failed: {data}")


async def send_message(text: str):
    if not current_token["access_token"]:
        await get_token()

    headers = {
        "Authorization": f"Bearer {current_token['access_token']}",
        "Content-Type": "application/json",
        "X-Team-Id": str(TEAM_ID)
    }
    payload = {"type": "text", "text": text}

    async with httpx.AsyncClient() as client:
        response = await client.post(MESSAGE_URL, json=payload, headers=headers)
        if response.status_code == 401:
            await get_token()
            headers["Authorization"] = f"Bearer {current_token['access_token']}"
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