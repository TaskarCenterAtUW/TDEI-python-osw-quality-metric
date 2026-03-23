# # Testing document for testing a simple osm input.

# from src.config import Config
from src.services.osw_qm_calculator_service import OswQmCalculator

osw_qm_calculator = OswQmCalculator(cores_to_use=1) # Configure the number of cores for dask here.
algorithms = "fixed" # Algorithms to use for calculating quality metrics.
algorithm_names = algorithms.split(',')
for algorithm in algorithm_names:
    print(algorithm)

result = osw_qm_calculator.calculate_quality_metric('src/assets/osm-input.zip', ['fixed'],'downloads/osm-output.zip') # Calculation code.
print(result)