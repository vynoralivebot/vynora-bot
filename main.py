import os
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from database import hosts_collection, users_collection
from agora_token_builder import RtcTokenBuilder
import time

load_dotenv()
app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

AGORA_APP_ID = os.getenv("AGORA_APP_ID")
AGORA_APP_CERTIFICATE = os.getenv("AGORA_APP_CERTIFICATE")

@app.get("/api/hosts")
async def get_hosts():
    hosts = []
    async for host in hosts_collection.find({"status": "online"}):
        host["_id"] = str(host["_id"])
        hosts.append(host)
    return hosts

class CallTokenRequest(BaseModel):
    channel_name: str
    uid: int

@app.post("/api/agora/token")
async def generate_agora_token(data: CallTokenRequest):
    if not AGORA_APP_ID or not AGORA_APP_CERTIFICATE:
        raise HTTPException(status_code=500, detail="Agora credentials not configured")
    
    expiration_time_in_seconds = 3600
    current_timestamp = int(time.time())
    privilege_expired_ts = current_timestamp + expiration_time_in_seconds
    
    token = RtcTokenBuilder.build_token_with_uid(
        AGORA_APP_ID,
        AGORA_APP_CERTIFICATE,
        data.channel_name,
        data.uid,
        1, 
        privilege_expired_ts
    )
    return {"token": token}
