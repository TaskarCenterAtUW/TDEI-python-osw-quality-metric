# Intersection scoring: downstream migration

## Release note (unreleased)

The intersection metric now scores intersection polygons and assigns their
scores to output tiles. The previous tile-based calculation scored connectivity
across the tile boundary itself. Consequently, unchanged tile geometries do not
imply comparable scores. Consumers should label and retain the scoring version
and avoid silently combining historical and current results.

The current version is `intersection-approaches-v2`. It counts actual street
approaches, excluding artificial closing sides of the polygon. Same-approach
connectivity still requires two distinct boundary contacts connected through the
pedestrian network inside the polygon. A fully connected T junction earns 1
(six connected pairs out of six); merely connecting one contact on each of its
three approaches earns 0.5. Version 1 already used this approach-only formula;
the polygon scorer before version 1 included closing sides.

Version 2 replaces version 1's connected-component clustering with deterministic,
nearest-first merging of road-connected groups. A merge is accepted only if every
pair of members is at most 20 m apart; ties use node IDs. For custom polygon
distances below 20 m, that smaller distance also limits cluster diameter. This
keeps members within the polygon's inscribed circle. Every emitted polygon is
checked for member containment; failure aborts the calculation.

Previously, seven road-connected junctions 20 m apart could form a 120 m cluster
whose end junctions lay outside its polygon. Version 2 splits such chains into
bounded groups. The resulting polygon counts, approaches, assignments, and scores
can change. Tile generation, the connectivity formula (including same-approach
requirements), and polygon overlap handling are unchanged. Keep v1 and v2 results
distinguishable when comparing or caching scores.

Debug polygons additionally expose `ext:cluster_diameter_m` (maximum pairwise
distance; zero for singletons), `ext:cluster_member_count`, and
`ext:cluster_members_covered` (true for every emitted polygon). These properties
describe the OSM junction cluster, not its assigned output tiles.

## Output contract

The service ZIP contains `ixn_qm.geojson`, a GeoJSON FeatureCollection with one
feature per output tile and longitude/latitude coordinates (EPSG:4326).
Select this filename explicitly; do not select the first GeoJSON in the ZIP.
Other requested algorithms produce separate files. Debug mode, disabled by
default, additionally produces `ixn_qm_intersection_scores.geojson`, whose features
are scoring polygons, not tiles. Library callers choose their own output filename;
the debug filename adds `_intersection_scores` to its stem.

| Tile property | Meaning and consumer handling |
| --- | --- |
| `tra_score` | Number in [0, 1], or -1 when unavailable. Zero is a valid score. Show -1 as unavailable/N/A, separately from zero; exclude it from score summaries and numeric color scales. Never clamp it to zero. |
| `ext:intersection_count` | Integer number of assigned polygons, including failed scores. It is neither the valid-score denominator nor a distinct-intersection count across tiles. |
| `ext:scoring_algorithm_version` | `intersection-approaches-v2`. Preserve alongside cached/exported scores. An absent value means legacy/unversioned, not this version. An unfamiliar value needs explicit compatibility review. |
| `tile_algorithm_version` | Present for generated tiles; describes tiling only. Absent for supplied tiles. Do not use it as the scoring version. |

Accept additional properties, including `ext:*`, without rejecting the dataset.
Read colon-containing names with bracket access, for example
`properties["ext:scoring_algorithm_version"]`. Supplied tile properties are not
carried forward; consumers must not depend on input attributes or GeoJSON feature
IDs being preserved as stable identifiers.

Each tile receives the **unweighted arithmetic mean** of valid assigned polygon
scores. A polygon's representative point determines primary assignment. Only
tiles without primary assignments use polygon overlap as a fallback. This can
assign a polygon to multiple tiles; tile counts and averages are not automatically
dataset-wide intersection counts or intersection-weighted averages.

For assigned scores `[0, 1, -1]`, the tile score is 0.5 and its intersection count
is 3. The count must not be used to reconstruct a pooled connectivity ratio.
A tile with only failed polygons has score -1 and a positive count; one with no
assigned polygons has score -1 and count 0. Thus -1 alone does not identify the
cause. Debug output can help inspect assignments and failed polygon scores.
The number of unavailable tiles is dataset-dependent.

Keep zero values when computing summaries. If there are no valid values, show
N/A rather than zero or a NaN string. If reporting an average across tiles, label
it as such and report how many tiles were unavailable. Version identity describes
the scoring rule, not the full run provenance: comparisons also depend on the
pedestrian data, OSM road snapshot/filter, polygon distance, and supplied tiles.

## Job status versus score availability

A successful calculation can contain some or all scores equal to -1. For example,
a valid response with no qualifying OSM roads produces unavailable scores and a
server-log warning. The warning is not a new property in the GeoJSON or response.

Authentication, download, and other calculation failures fail the service job;
partial outputs are not packaged/uploaded as success. The failure response has
`success: false`, `status: "failed"`, and `qm_dataset_url: null`. Consumers should
handle this separately from a successful output with unavailable scores.
The CLI exits 0 for successful outputs (including unavailable scores), 1 for
calculation failures, and 2 for invalid arguments.

## Consumer acceptance examples

Import [the synthetic supplied-tile example](../tests/fixtures/consumer_contract/ixn_qm.geojson)
into the consumer. These are illustrative rectangles, not measured street results.
Listed in file order, the expected tile properties are:

| Case | Score | Assigned polygons | Expected presentation |
| --- | --- | --- | --- |
| Valid zero | 0 | 1 | Zero connectivity, included in summaries |
| Full credit | 1 | 1 | Full connectivity |
| Mixed scores `[0, 1, -1]` | 0.5 | 3 | Mean 0.5; count includes the failure |
| All assigned polygons failed | -1 | 1 | Unavailable |
| No assigned polygons | -1 | 0 | Unavailable |

Across this example, the mean of the three valid tile scores is 0.5 and two tiles
are unavailable. All features carry the scoring version; none requires a tiling
version. Verify imports preserve the `ext:*` properties, the legend distinguishes
zero from unavailable, and cached/exported results retain the scoring version.
Also exercise a generated-tile output, debug-enabled ZIP, legacy/unversioned
output, and failed-job response before deploying the consumer integration.

## Verification scope

The producer regression test in `tests/services/test_osw_qm_calculator_service.py`
supplies controlled polygon scores, runs the real tile aggregation, serialization,
and ZIP packaging, and compares the output against the example. It runs with debug
both enabled and disabled. Separate calculator tests cover scoring and generated
tile metadata. These tests do not exercise deployed consumer applications.

Read-only GitHub code searches on 2026-10-27 found no `tra_score` matches in
`TaskarCenterAtUW/workspaces-frontend`, `workspaces-backend`,
`TDEI-user-management-ts`, `TDEI-dataset-viewer`, or `TDEI-quality-dashboard`.
Search indexing and default-branch scope limit this evidence; it is not proof
of compatibility. **Portal/Workspaces runtime acceptance remains unverified.**
Their maintainers should run the examples above against the actual deployed
import, legend, summary, and export paths before promoting this scoring change.
