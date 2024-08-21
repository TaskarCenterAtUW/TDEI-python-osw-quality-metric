import os.path
import shutil
from urllib.parse import urlparse

from python_ms_core import Core
from python_ms_core.core.queue.models.queue_message import QueueMessage
from dataclasses import asdict
from src.config import Config
from src.services.storage_service import StorageService
import logging
from src.models.quality_request import QualityRequest
from src.models.quality_response import QualityMetricResponse, ResponseData
from src.services.osw_qm_calculator_service import OswQmCalculator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("QualityMetricService")
logger.setLevel(logging.INFO)


class ServiceBusService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        self.config = Config()
        self.core = Core()
        self.incoming_topic = self.core.get_topic(self.config.incoming_topic_name,
                                                  max_concurrent_messages=self.config.max_concurrent_messages)
        self.storage_service = StorageService(core=self.core)
        # Start listening to the things
        self.incoming_topic.subscribe(self.config.incoming_topic_subscription, self.handle_message)
        pass

    def handle_message(self, msg: QueueMessage):
        # Logs and creates a thread for processing
        self.process_message(msg=msg)

    def process_message(self, msg: QueueMessage):
        logger.info(f"Processing message {msg.messageId}")
        # Parse the message
        quality_request = QualityRequest(messageType=msg.messageType, messageId=msg.messageId, data=msg.data)
        # Download the file
        input_file_url = quality_request.data.data_file
        parsed_url = urlparse(input_file_url)
        file_name = os.path.basename(parsed_url.path)
        download_folder = os.path.join(self.config.get_download_folder(), msg.messageId)
        os.makedirs(download_folder, exist_ok=True)
        download_path = os.path.join(download_folder, file_name)
        try:
            self.storage_service.download_remote_file(input_file_url, download_path)
            # Process the file
            output_folder = os.path.join(download_folder, 'qm')
            os.makedirs(output_folder, exist_ok=True)
            output_file_local_path = os.path.join(output_folder, 'qm-output.zip')
            qm_calculator = OswQmCalculator()
            algorithm_names = quality_request.data.algorithms.split(',')
            qm_calculator.calculate_quality_metric(download_path, algorithm_names, output_file_local_path)
            # Upload the file
            output_file_remote_path = f'{self.get_directory_path(input_file_url)}/qm-{quality_request.data.jobId}-output.zip'
            output_file_url = self.storage_service.upload_local_file(output_file_local_path, output_file_remote_path)
            logger.info(f'Uploaded file to {output_file_url}')

            response_data = {
                'status': 'success',
                'message': 'Quality metrics calculated successfully',
                'success': True,
                'dataset_url': input_file_url,
                'qm_dataset_url': output_file_url
            }
        except Exception as e:
            logger.error(f'Failed to process message {msg.messageId} with error {e}')
            response_data = {
                'status': 'failed',
                'message': f'Failed to process message {msg.messageId} with error {e}',
                'success': False,
                'dataset_url': input_file_url,
                'qm_dataset_url': ''
            }

        response = QualityMetricResponse(
            messageType=msg.messageType,
            messageId=msg.messageId,
            data=response_data
        )
        self.send_response(msg=response)
        # Process the message
        # Clean up the download_folder
        logger.info('Cleaning up download folder')
        shutil.rmtree(download_folder)
        pass

    def send_response(self, msg: QueueMessage):
        try:
            queue_message = QueueMessage.data_from({
                'messageId': msg.messageId,
                'messageType': msg.messageType,
                'data': asdict(msg.data)
            })
            self.core.get_topic(topic_name=self.config.outgoing_topic_name).publish(data=queue_message)
            logger.info(f"Publishing response for message {msg.messageId}")
        except Exception as e:
            logger.error(f'Failed to send response for message {msg.messageId} with error {e}')
        pass

    def get_directory_path(self, remote_url: str) -> str:
        # https://tdeisamplestorage.blob.core.windows.net/osw/test_upload/df/fff/500mb_file.zip
        # should give output test_upload/df/fff/
        parsed_url = urlparse(remote_url)
        dirname = os.path.dirname(parsed_url.path)
        folder_path = dirname.split('/')[2:]
        folder_path = '/'.join(folder_path)
        return folder_path

    # def get_directory_path(self,remote_url:str)-> str:
    #     # https://tdeisamplestorage.blob.core.windows.net/osw/test_upload/500mb_file.zip
    #     # should give output test_upload
    #     parsed_url = urlparse(remote_url)
    #     file_name = os.path.basename(parsed_url.path)
    #     os.path.dirname(parsed_url.path)
    #     container = parsed_url.path.split('/')[1]
    #     folder_path = parsed_url.path.split('/')[2]
    #     return os.path.join(self.config.get_download_folder(),file_name)
