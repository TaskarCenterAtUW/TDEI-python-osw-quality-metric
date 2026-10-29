This is a synthetic OSM response modeled on the Goldendale boundary case.
It is not a downloaded OSM snapshot. Nodes and ways are constructed to cover:

- A junction inside the dataset hull with northern and western approaches outside.
- A one-way northern approach.
- A curved southern approach with an intermediate node removed by simplification.
- An interior T-junction that seeds tiles and has a complete scoring polygon.
- A southern continuation beyond the 500 m download buffer, which must be
  removed before simplification to preserve the original tile seed graph.

`expected.json` was captured with OSMnx 2.0.7 by executing the application's
committed code before the compatibility-module refactor (`fa89a7a`).
It records the query, both simplified graphs, projected tile geometries, and
scoring polygons with their approach metadata.
Geometry comparisons allow 1 micrometer in projected coordinates and 1e-12
degrees in geographic coordinates to accommodate projection roundoff.

For an OSMnx upgrade, review its internal query/cache/graph helpers and the
buffer/simplification/truncation pipeline. Inspect baseline differences before
changing the recorded version or expected values. Do not regenerate this fixture
just to make a failing test pass. The test makes no live API calls and needs no key.
