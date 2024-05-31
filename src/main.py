from typing import Union
from fastapi import FastAPI, Request
from fastapi.responses import Response
from python_ms_core import Core


from src.services.servicebus_service import ServiceBusService

service_bus_instance = ServiceBusService()


app = FastAPI()


class OctetStreamResponse(Response):
    media_type = 'application/octet-stream'


@app.get('/')
def root():
    return {'Hello': 'World'}


@app.get('/ping')
def ping():
    return {'msg': 'Ping Successful'}
