from dataclasses import dataclass


@dataclass
class RequestData:
    jobId: str
    data_file: str
    algorithms: str


@dataclass
class QualityRequest:
    messageType: str
    messageId: str
    data: RequestData
    def __post_init__(self):
        self.data = RequestData(**self.data)