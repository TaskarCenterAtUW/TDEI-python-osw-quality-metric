from .qm_calculator import QMCalculator
import random


class QMFixedCalculator(QMCalculator):
    def __init__(self):
        pass
    
    def calculate_quality_metric(self, feature: dict) -> float:
        return 10.5
    def qm_metric_tag(self) -> str:
        return "ext:qm:fixed"


class QMRandomCalculator(QMCalculator):
    def __init__(self):
        pass
    
    def calculate_quality_metric(self, feature: dict) -> float:
        return random.randfloat(30, 100)

    def qm_metric_tag(self) -> str:
        return "ext:qm:random"