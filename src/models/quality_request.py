from dataclasses import dataclass
from typing import Optional


@dataclass
class RequestData:
    jobId: str
    data_file: str
    algorithms: str
    intersectionFile: Optional[str] = None


@dataclass
class QualityRequest:
    messageType: str
    messageId: str
    data: RequestData
    def __post_init__(self):
        self.data = RequestData(**self.data)