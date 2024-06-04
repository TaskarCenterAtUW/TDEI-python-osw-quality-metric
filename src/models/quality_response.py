from dataclasses import dataclass


@dataclass
class ResponseData:
    status: str
    message: str
    success: bool
    dataset_url:str
    qm_dataset_url:str

@dataclass
class QualityMetricResponse:
    messageType: str
    messageId: str
    data: ResponseData

    def __post_init__(self):
        self.data = ResponseData(**self.data)