# TDEI-python-osw-quality-metric
Quality metric calculator for OSW record.

# Introduction:
This service calculates the specific quality metric of a given OSW dataset. There are two algorithms that it supports:
- fixed calculation (assumes a random score )
- xn calculation. Scores local intersection polygons, then averages their scores onto either supplied tiles or generated intersection tiles. Generated tiles come from [flagstones](https://pypi.org/project/flagstones/): Voronoi tiles seeded on consolidated road junctions in the UTM zone of the data, with fallback grid cells over any ground the junction tiles leave. Polygon generation reuses the same OSM seed graph as tiling.

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
INTERSECTION_DISTANCE=50 # Optional polygon side distance in meters
DEBUG_INTERSECTION_POLYGONS=false # Optional intermediate per-polygon score GeoJSON
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

The intersection calculator has one scoring workflow: create local polygons,
score OSW connectivity inside each polygon, and average those scores onto tiles.
Polygon sides are perpendicular to cleaned street approaches, 50 meters from the
intersection center by default. Nearby connected intersection nodes within 20
meters are clustered, directions within 10 degrees are merged, and gaps above
135 degrees receive closing sides to prevent spikes. Scoring includes all input
OSW edges and requires two distinct boundary points for same-side connectivity.

The final GeoJSON keeps one feature per tile in EPSG:4326. `tra_score` is the
arithmetic mean of valid assigned polygon scores, and `ext:intersection_count` is
the number of assigned polygons (including any whose scoring failed). Assignment
uses polygon representative points, with polygon overlap as a fallback for tiles
without assignments. Missing or failed scores are `-1` and are excluded from
averages; a tile with no valid score remains `-1`. Fallback grid tiles with no
nearby intersection also receive `-1`. Generated tiles retain
`tile_algorithm_version`.

```shell
python -m src.calculators.qm_xn_lib_calculator edges.geojson ixn_qm.geojson \
    --debug-intersection-polygons
```

An optional third positional argument supplies precomputed tiles. With debug
enabled, `ixn_qm_intersection_scores.geojson` is saved alongside the final output,
with `tra_score` plus diagnostic properties `ext:intersection_id`, `ext:degree`,
`ext:side_count`, `ext:cap_side_count`, `ext:polygon_distance_m`, `ext:total_edges`,
and `ext:connect_edges`. Service runs include it in the output ZIP.
`ext:total_edges` and `ext:connect_edges` refer to polygon-side pairs, including
same-side pairs. New informational/debug properties use the `ext:` namespace;
the existing `tra_score` and `tile_algorithm_version` names are preserved.
Debug output is disabled by default and can be controlled in the library:

```python
calculator = QMXNLibCalculator(
    edges_file_path="edges.geojson",
    output_file_path="ixn_qm.geojson",
    debug_intersection_polygons=False,
    intersection_distance=50.0,
)
result = calculator.calculate_quality_metric()
```
