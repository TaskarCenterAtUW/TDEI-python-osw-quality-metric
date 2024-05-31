from dataclasses import dataclass


@dataclass
class ResponseData:
    jobId: str
    status: str
    message: str
    success: bool
    dataset_url:str

@dataclass
class ConfidenceResponse:
    messageType: str
    messageId: str
    data: ResponseData

    def __post_init__(self):
        self.data = ResponseData(**self.data)