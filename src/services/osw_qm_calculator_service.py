import zipfile
from src.config import Config
from src.calculators import QMFixedCalculator
import json
import os
import tempfile
import logging
import time

logging.basicConfig()


class OswQmCalculator:
    """
    A class that calculates quality metrics for input files using specified algorithms.

    Attributes:
        None

    Methods:
        calculate_quality_metric: Calculates quality metrics for input files using specified algorithms.
        zip_folder: Zips a folder and its contents.
        extract_zip: Extracts a zip file to a specified folder.
        parse_and_calculate_quality_metric: Parses and calculates quality metrics for a specific input file.

    """

    def calculate_quality_metric(self, input_file, algorithm_names, output_path):
        """
        Calculates quality metrics for input files using specified algorithms.

        Args:
            input_file (str): The path to the input file. (dataset.zip file)
            algorithm_names (list): A list of algorithm names to be used for calculating quality metrics.
            output_path (str): The path to the output zip file.

        Returns:
            None

        """
        with zipfile.ZipFile(input_file, 'r') as input_zip:
            input_unzip_folder = tempfile.TemporaryDirectory()
            file_list = self.extract_zip(input_zip, input_unzip_folder.name)
        logging.info(f"Extracted input files: {file_list}")
        input_files_path = [os.path.join(input_unzip_folder.name, file) for file in file_list]
        output_unzip_folder = tempfile.TemporaryDirectory()
        logging.info(f"Started calculating quality metrics for input files: {input_files_path}")
        for input_file in input_files_path:
            qm_calculated_json = self.parse_and_calculate_quality_metric(input_file, algorithm_names)
            qm_calculated_file_path = os.path.join(output_unzip_folder.name, os.path.basename(input_file))
            with open(qm_calculated_file_path, 'w') as qm_file:
                json.dump(qm_calculated_json, qm_file)
        logging.info(f"Finished calculating quality metrics for input files: {input_files_path}")
        logging.info(f'Zipping output files to {output_path}')
        self.zip_folder(output_unzip_folder.name, output_path)
        logging.info(f'Cleaning up temporary folders.')
        input_unzip_folder.cleanup()
        output_unzip_folder.cleanup()

    def zip_folder(self, input_folder, output_zip):
        """
        Zips a folder and its contents.

        Args:
            input_folder (str): The path to the folder to be zipped.
            output_zip (str): The path to the output zip file.

        Returns:
            None

        """
        print(output_zip)
        with zipfile.ZipFile(output_zip, 'w') as output_zip:
            for root, dirs, files in os.walk(input_folder):
                for file in files:
                    output_zip.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), input_folder))

    def extract_zip(self, input_zip, unzip_folder) -> [str]:
        """
        Extracts a zip file to a specified folder.

        Args:
            input_zip (zipfile.ZipFile): The zip file to be extracted.
            unzip_folder (str): The path to the folder where the zip file will be extracted.

        Returns:
            list: A list of extracted file names.

        """
        input_zip.extractall(unzip_folder)
        input_files = [name for name in os.listdir(unzip_folder) if os.path.isfile(os.path.join(unzip_folder, name))]
        return input_files

    def parse_and_calculate_quality_metric(self, input_file, algorithm_names):
        """
        Parses and calculates quality metrics for a specific input file.

        Args:
            input_file (str): The path to the input file.
            algorithm_names (list): A list of algorithm names to be used for calculating quality metrics.

        Returns:
            dict: A dictionary containing the calculated quality metrics.

        """
        # Mark it first with fixed calculator
        start_time = time.time()
        config = Config()
        algo_instances = []
        for algo_name in algorithm_names:
            if not algo_name in config.algorithm_dictionary:
                logging.warning('Algorithm not found : ' + algo_name)
            else:
                algo_instances.append(config.algorithm_dictionary[algo_name]())
        with open(input_file, 'r') as input_file:
            input_json = json.load(input_file)
            for feature in input_json['features']:
                for calculator in algo_instances:
                    feature[calculator.qm_metric_tag()] = calculator.calculate_quality_metric(feature)
        end_time = time.time()
        logging.info(f"Time taken to calculate quality metrics for {input_file}: {end_time - start_time} seconds")
        return input_json
