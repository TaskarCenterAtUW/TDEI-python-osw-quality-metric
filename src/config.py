import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings


load_dotenv()


class Config(BaseSettings):
    app_name: str = 'osw-quality-metric-service-python'
    incoming_topic_name: str = os.environ.get('QUALITY_REQ_TOPIC', '')
    incoming_topic_subscription: str = os.environ.get('QUALITY_REQ_SUB', '')
    outgoing_topic_name: str = os.environ.get('QUALITY_RES_TOPIC', '')
    storage_container_name: str = os.environ.get('CONTAINER_NAME', 'osw')

    def get_download_folder(self) -> str:
        root_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(root_dir, 'downloads')
