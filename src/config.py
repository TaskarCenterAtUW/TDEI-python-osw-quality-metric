import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from src.calculators import QMFixedCalculator, QMXNLibCalculator

load_dotenv()


class Config(BaseSettings):
    app_name: str = 'osw-quality-metric-service-python'
    incoming_topic_name: str = os.environ.get('QUALITY_REQ_TOPIC', '')
    incoming_topic_subscription: str = os.environ.get('QUALITY_REQ_SUB', '')
    outgoing_topic_name: str = os.environ.get('QUALITY_RES_TOPIC', '')
    storage_container_name: str = os.environ.get('CONTAINER_NAME', 'osw')
    algorithm_dictionary: dict = {"fixed": QMFixedCalculator, "ixn": QMXNLibCalculator}
    max_concurrent_messages: int = os.environ.get('MAX_CONCURRENT_MESSAGES', 1)
    partition_count: int = os.environ.get('PARTITION_COUNT', 2)

    def get_download_folder(self) -> str:
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(root_dir, 'downloads')

    def get_assets_folder(self) -> str:
        root_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(root_dir, 'assets')
