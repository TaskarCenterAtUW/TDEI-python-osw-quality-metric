# Testing document for testing a simple osm input.

from src.config import Config
from src.services.osw_qm_calculator_service import OswQmCalculator
import os

config = Config()

osw_qm_calculator = OswQmCalculator()

asset_folder = config.get_assets_folder()
download_folder = config.get_download_folder()
print(asset_folder)
print(download_folder)
test_path = os.path.join(asset_folder, 'osm-input.zip')
test_op_path = os.path.join(download_folder, 'osm-output.zip')
osw_qm_calculator.calculate_quality_metric(test_path, ['fixed'],test_op_path)