from qm_calculator import QMCalculator, QualityMetricResult
import random
import geopandas as gpd
import sys

class QMFixedCalculator(QMCalculator):
    '''
    Dummy quality metric calculator that assigns a random score to each edge in the input file
    '''

    def __init__(self, edges_file_path:str, output_file_path:str, polygon_file_path:str=None):
        self.edges_file_path = edges_file_path
        self.output_file_path = output_file_path
        self.polygon_file_path = polygon_file_path
        pass

    def calculate_quality_metric(self):
        gdf = gpd.read_file(self.edges_file_path)
        gdf['fixed_score'] = random.randint(0, 100)
        gdf.to_file(self.output_file_path)
        return QualityMetricResult(success=True, message="QMFixedCalculator", output_file=self.output_file_path)

    def algorithm_name(self):
        return "QMFixedCalculator"


if __name__ == '__main__':
    osw_edge_file_path = sys.argv[1]  # First argument: OSW edge file path
    qm_file_path = sys.argv[2]        # Second argument: Quality metric output file path

    # Check if the optional third argument (xn_polygon_path) is provided
    if len(sys.argv) > 3:
        xn_polygon_path = sys.argv[3]  # Third argument: Intersection polygon file path (optional)
        qm_calculator = QMFixedCalculator(osw_edge_file_path, qm_file_path, xn_polygon_path)
        print(qm_calculator.calculate_quality_metric())
         
    else:
        # If the third argument is not provided, call without xn_polygon_path
        qm_calculator = QMFixedCalculator(osw_edge_file_path, qm_file_path)
        print(qm_calculator.calculate_quality_metric())
         