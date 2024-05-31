import json
import os.path
import shutil
import threading
from urllib.parse import urlparse

from python_ms_core import Core
from python_ms_core.core.queue.models.queue_message import QueueMessage

from src.config import Config
from src.services.storage_service import StorageService
import logging

logging.basicConfig()


class ServiceBusService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        self.config = Config()
        core = Core()
        self.incoming_topic = core.get_topic(self.config.incoming_topic_name)
        self.outgoing_topic = core.get_topic(self.config.outgoing_topic_name)
        self.storage_service = StorageService(core)
        # Start listening to the things
        self.incoming_topic.subscribe(self.config.input_sub, self.handle_message)
        pass

    def handle_message(self, msg: QueueMessage):
        # Logs and creates a thread for processing
        process_thread = threading.Thread(target=self.process_message, args=[msg])
        process_thread.start()

    def process_message(self, msg: QueueMessage):
        logging.info(f"Processing message {msg.message_id}")

        # Process the message
        pass

    def send_response(self, msg: QueueMessage):
        logging.info(f"Sending response for message {msg.message_id}")
        self.outgoing_topic.publish(msg)
        pass
