import asyncio
from fastapi.responses import Response
from fastapi import FastAPI, Depends
from functools import lru_cache
from src.services.servicebus_service import ServiceBusService
from src.config import Config

app = FastAPI()


@lru_cache()
def get_settings():
    return Config()


def start_servicebus_service():
    # Start the ServiceBusService (blocking call)
    service = ServiceBusService()


@app.on_event("startup")
async def startup_event(settings: Config = Depends(get_settings)):
    # Run the ServiceBusService in a background thread using asyncio
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, start_servicebus_service)


class OctetStreamResponse(Response):
    media_type = 'application/octet-stream'


@app.get('/')
def root():
    return {'Hello': 'World'}


@app.get('/ping')
def ping():
    return {'msg': 'Ping Successful'}
