from abc import ABC, abstractmethod
from typing import NamedTuple

class QualityMetricResult(NamedTuple):
     success: bool
     message: str
     output_file: str

class QMCalculator(ABC):
    @abstractmethod
    def calculate_quality_metric(self) -> QualityMetricResult:
        pass
    @abstractmethod
    def algorithm_name(self) -> str:
        pass
