# TDEI-python-osw-quality-metric
Quality metric calculator for OSW record.

# Introduction:
This service calculates the specific quality metric of a given OSW dataset. There are two algorithms that it supports:
- fixed calculation (assumes a random score )
- xn calculation. Calculates the intersection quality metric based on either input sub-polygons or vornoi generated polygons.

## Requirements
python 3.10

## How to run the project with Python3.10
#### Create virtual env

`python3.10 -m venv .venv`

`source .venv/bin/activate`

#### Install requirements

`pip install -r requirements.txt`

#### Set up env file, create a .env file at project root level 

```shell
QUALITY_REQ_TOPIC
QUALITY_REQ_SUB
QUALITY_RES_TOPIC
PROVIDER=Azure
QUEUECONNECTION=Endpoint=sb://xxxxxxxxxxxxx
STORAGECONNECTION=DefaultEndpointsProtocol=https;xxxxxxxxxxxxx
MAX_CONCURRENT_MESSAGES=xxx # Optional if not provided defaults to 1
PARTITION_COUNT=xx # Optional number of partitions to use for dask library. defaults to 2
```
Note: Replace the endpoints with the actual endpoints of the environment you want to run the service in

`MAX_CONCURRENT_MESSAGES` is the maximum number of concurrent messages that the service can handle. If not provided, defaults to 1

### Run the Server 

`uvicorn src.main:app --reload`

remove `--reload` for non-debug mode


### Run the Server

`uvicorn src.main:app --reload`

### Run Unit tests

####  Run Coverage
`python -m coverage run --source=src -m unittest discover -s tests/unit_tests`

To run a single test use

`python -m unittest tests.unit_tests.service.test_osw_confidence_metric_calculator.TestOSWConfidenceMetric.test_calculate_score`

####  Run Coverage Report
`coverage report`

####  Run Coverage HTML report
`coverage html`


# Incoming message

```json
{
    "messageType": "mettric-calculation",
    "messageId": "message-id-from-msg",
    "data": {
      "jobId": "0b41ebc5-350c-42d3-90af-3af4ad3628fb",
      "data_file": "https://tdeisamplestorage.blob.core.windows.net/osw/test/wenatchee.zip",
      "algorithm": "fixed",
      "sub_regions_file":""
    }
  }

```

# Outgoing message
```json
{
    "status":"",
    "message":"",
    "success":true/false,
    "dataset_url":"",
    "qm_dataset_url":""
}

```

# Run the metrics locally
- Use [test.py](./test.py) to run the metrics on any dataset locally.