import zipfile
from src.config import Config
from src.calculators import QMXNLibCalculator, QMFixedCalculator, QMCalculator
import json
import os
import tempfile
import logging
import time

logging.basicConfig()
logger = logging.getLogger("QualityMetricCalculator")
logger.setLevel(logging.INFO)


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

    def calculate_quality_metric(self, input_file, algorithm_names, output_path, ixn_file=None):
        """
        Calculates quality metrics for input files using specified algorithms.

        Args:
            input_file (str): The path to the input file. (dataset.zip file)
            algorithm_names (list): A list of algorithm names to be used for calculating quality metrics.
            output_path (str): The path to the output zip file.

        Returns:
            None

        """
        try:
            with zipfile.ZipFile(input_file, 'r') as input_zip:
                input_unzip_folder = tempfile.TemporaryDirectory()
                input_files_path = self.extract_zip(input_zip, input_unzip_folder.name)
            # logging.info(f"Extracted input files: {file_list}")
            # input_files_path = [os.path.join(input_unzip_folder.name, file) for file in file_list]
            output_unzip_folder = tempfile.TemporaryDirectory()
            logger.info(f"Started calculating quality metrics for input files: {input_files_path}")
            # Get only the edges file out of the input files
            edges_file_path = [file_path for file_path in input_files_path if 'edges' in file_path]
            if len(edges_file_path) == 0:
                raise Exception('Edges file not found in input files.')
            edges_file_path = edges_file_path[0]
            edges_file_basename = os.path.basename(edges_file_path)
            edges_file_without_extension = os.path.splitext(edges_file_basename)[0]
            for algorithm_name in algorithm_names:
                qm_edges_output_path = os.path.join(output_unzip_folder.name, f'{algorithm_name}_qm.geojson')
                qm_calculator = self.get_osw_qm_calculator(algorithm_name, ixn_file, edges_file_path, qm_edges_output_path)
                start_time = time.time()
                qm_calculator.calculate_quality_metric()
                end_time = time.time()
                logger.info(f"Time taken to calculate quality metrics for {algorithm_name}: {end_time - start_time} seconds")
            # Copy the rest of the files from input to output
            # Dont copy the other files here.
            # for file_path in input_files_path:
            #     if 'edges' in file_path:
            #         continue
            #     file_basename = os.path.basename(file_path)
            #     output_file_path = os.path.join(output_unzip_folder.name, file_basename)
            #     os.rename(file_path, output_file_path)

            logger.info(f"Finished calculating quality metrics for input files: {input_files_path}")
            logger.info(f'Zipping output files to {output_path}')
            self.zip_folder(output_unzip_folder.name, output_path)
            logger.info(f'Cleaning up temporary folders.')
            input_unzip_folder.cleanup()
            output_unzip_folder.cleanup()
        except Exception as e:
            logging.error(f'Error calculating quality metrics: {e}')
            raise e

    def get_osw_qm_calculator(self, algorithm_name:str, ixn_file:str=None, edges_file:str=None, output_file:str=None) -> QMCalculator:
        """
        Returns an instance of the specified quality metric calculator.

        Args:
            algorithm_name (str): The name of the quality metric calculator.

        Returns:
            QMCalculator: An instance of the specified quality metric calculator.

        """
        if algorithm_name == 'ixn':
            return QMXNLibCalculator(edges_file, output_file, ixn_file)
        else:
            return QMFixedCalculator(edges_file, output_file)

    def zip_folder(self, input_folder, output_zip):
        """
        Zips a folder and its contents.

        Args:
            input_folder (str): The path to the folder to be zipped.
            output_zip (str): The path to the output zip file.

        Returns:
            None

        """
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
        input_file_paths = []
        # Get the file paths for all the files using os.walk
        for root, dirs, files in os.walk(unzip_folder):
            for file in files:
                input_file_paths.append(os.path.join(root, file))
        return input_file_paths

    def parse_and_calculate_quality_metric(self, input_file, algorithm_names, ixn_file=None):
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
                logger.warning('Algorithm not found : ' + algo_name)
            else:
                if algo_name != 'ixn':
                    algo_instances.append(config.algorithm_dictionary[algo_name]())
        with open(input_file, 'r') as input_file:
            input_json = json.load(input_file)
            for feature in input_json['features']:
                for calculator in algo_instances:
                    feature[calculator.qm_metric_tag()] = calculator.calculate_quality_metric(feature)

        if 'ixn' in algorithm_names:
            # get the edges file from the input

            ixn_calculator = QMXNLibCalculator()
            input_json = ixn_calculator.calculate_quality_metric(input_file, ixn_file)
             
        end_time = time.time()
        logger.info(f"Time taken to calculate quality metrics for {input_file}: {end_time - start_time} seconds")
        return input_json
