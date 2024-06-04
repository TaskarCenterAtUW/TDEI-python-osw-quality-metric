# Testing document for testing a simple osm input.

from src.config import Config
from src.services.osw_qm_calculator_service import OswQmCalculator
import os
# import urllib.parse as urlparse
from urllib.parse import urlparse

config = Config()

osw_qm_calculator = OswQmCalculator()

asset_folder = config.get_assets_folder()
download_folder = config.get_download_folder()
print(asset_folder)
print(download_folder)
test_path = os.path.join(asset_folder, 'osm-input.zip')
test_op_path = os.path.join(download_folder, 'osm-output.zip')
# osw_qm_calculator.calculate_quality_metric(test_path, ['fixed'],test_op_path)

# def get_directory_path(remote_url:str)-> str:
#         # https://tdeisamplestorage.blob.core.windows.net/osw/test_upload/df/fff/500mb_file.zip
#         # should give output test_upload/df/fff/
#         parsed_url = urlparse(remote_url)
#         dirname = os.path.dirname(parsed_url.path)
#         folder_path = dirname.split('/')[2:]
#         folder_path = '/'.join(folder_path)
#         return folder_path
# print(get_directory_path('https://tdeisamplestorage.blob.core.windows.net/osw/test_upload/df/fff/500mb_file.zip'))
