from abc import ABC, abstractmethod

class QMCalculator(ABC):
    @abstractmethod
    def calculate_quality_metric(self, feature:dict) -> float:
        pass