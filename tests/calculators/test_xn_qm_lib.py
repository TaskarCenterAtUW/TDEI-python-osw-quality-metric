import os
import unittest
from unittest.mock import patch, MagicMock, ANY
import networkx as nx
import geopandas as gpd
from shapely.geometry import Point, LineString, Polygon, MultiPolygon, MultiLineString
from src.calculators.xn_qm_lib import (
    add_edges_from_linestring, graph_from_gdf, group_G_pts, edges_are_connected,
    tile_tra_score, get_stats, get_measures_from_polygon, qm_func,
    create_voronoi_diagram, calculate_xn_qm
)

PROJ = 'epsg:26910'

class TestQualityMetrics(unittest.TestCase):

    def setUp(self):
        self.graph = nx.Graph()
        self.graph.add_edge((0, 0), (1, 1))
        self.graph.add_edge((1, 1), (2, 2))
        self.polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        self.multi_polygon = MultiPolygon([self.polygon])
        self.gdf = MagicMock(spec=gpd.GeoDataFrame)

    def test_add_edges_from_linestring(self):
        graph = nx.Graph()
        line = LineString([(0, 0), (1, 1), (2, 2)])
        add_edges_from_linestring(graph, line, {"attr": "value"})
        self.assertEqual(len(graph.edges), 2)

    def test_graph_from_gdf(self):
        mock_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_gdf.iterrows.return_value = iter([
            (0, MagicMock(geometry=LineString([(0, 0), (1, 1)]))),
            (1, MagicMock(geometry=LineString([(1, 1), (2, 2)]))),
        ])
        graph = graph_from_gdf(mock_gdf)
        self.assertEqual(len(graph.edges), 2)

    def test_group_G_pts(self):
        group = group_G_pts(self.graph, self.polygon)
        self.assertIsInstance(group, dict)
        self.assertGreater(len(group), 0)

    def test_edges_are_connected(self):
        e1_pts = [(0, 0), (1, 1)]
        e2_pts = [(2, 2)]
        connected = edges_are_connected(self.graph, e1_pts, e2_pts)
        self.assertTrue(connected)

    def test_tile_tra_score(self):
        total, connected, pairs = tile_tra_score(self.graph, self.polygon)
        self.assertGreater(total, 0)
        self.assertGreater(connected, 0)
        self.assertIsInstance(pairs, list)

    @patch('src.calculators.xn_qm_lib.get_stats')
    def test_get_stats(self, mock_get_stats):
        mock_get_stats.return_value = {"tra_score": 1.0}
        stats = get_stats(self.polygon, self.graph, self.gdf)
        self.assertIn("tra_score", stats)

    @patch('src.calculators.xn_qm_lib.gpd.clip')
    @patch('src.calculators.xn_qm_lib.graph_from_gdf')
    @patch('src.calculators.xn_qm_lib.get_stats')
    def test_get_measures_from_polygon(self, mock_get_stats, mock_graph_from_gdf, mock_clip):
        # Mock the cropped GeoDataFrame
        mock_cropped_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_clip.return_value = mock_cropped_gdf

        # Mock the graph and stats
        mock_graph = MagicMock()
        mock_graph_from_gdf.return_value = mock_graph
        mock_get_stats.return_value = {"tra_score": 1.0}

        # Call the function
        measures = get_measures_from_polygon(self.polygon, self.gdf)

        # Assertions
        mock_clip.assert_called_once_with(self.gdf, self.polygon)
        mock_graph_from_gdf.assert_called_once_with(mock_cropped_gdf)
        mock_get_stats.assert_called_once_with(self.polygon, mock_graph, mock_cropped_gdf)

        self.assertIn("tra_score", measures)
        self.assertEqual(measures["tra_score"], 1.0)

    @patch('src.calculators.xn_qm_lib.get_measures_from_polygon')
    def test_qm_func(self, mock_get_measures):
        # Mock the feature and its geometry
        mock_feature = MagicMock()
        mock_feature.geometry = self.polygon

        # Mock the 'loc' method to behave like a dictionary
        mock_feature.loc = {}

        # Mock the return value of get_measures_from_polygon
        mock_get_measures.return_value = {"tra_score": 1.0}

        # Call the function
        result = qm_func(mock_feature, self.gdf)

        # Assertions
        self.assertEqual(result.loc["tra_score"], 1.0)
        mock_get_measures.assert_called_once_with(self.polygon, self.gdf)

    @patch('src.calculators.xn_qm_lib.gpd.GeoDataFrame')
    @patch('src.calculators.xn_qm_lib.voronoi_diagram')
    @patch('src.calculators.xn_qm_lib.gnx.graph_edges_to_gdf')
    def test_create_voronoi_diagram(self, mock_graph_edges_to_gdf, mock_voronoi_diagram, mock_geo_dataframe):
        # Mock graph and bounds
        mock_graph = MagicMock()
        mock_bounds = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])

        # Mock the GeoDataFrame created from graph edges
        mock_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_gdf.crs = 'epsg:4326'  # Mock the CRS attribute
        mock_graph_edges_to_gdf.return_value = mock_gdf

        # Mock the boundary and unary_union attributes of the GeoDataFrame
        mock_boundary = MagicMock()
        mock_unary_union = MagicMock()
        mock_gdf.boundary = mock_boundary
        mock_boundary.unary_union = mock_unary_union

        # Mock the voronoi_diagram output
        mock_voronoi = MagicMock()
        mock_voronoi_diagram.return_value = mock_voronoi

        # Mock the clipped Voronoi GeoDataFrame
        mock_voronoi_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_voronoi_gdf.set_crs = MagicMock(return_value=mock_voronoi_gdf)
        mock_voronoi_gdf_clipped = MagicMock(spec=gpd.GeoDataFrame)
        mock_voronoi_gdf_clipped.to_crs = MagicMock(return_value=mock_voronoi_gdf_clipped)

        # Mock GeoDataFrame creation and clipping
        mock_geo_dataframe.return_value = mock_voronoi_gdf
        gpd.clip = MagicMock(return_value=mock_voronoi_gdf_clipped)

        # Call the function
        result = create_voronoi_diagram(mock_graph, mock_bounds)

        # Assertions
        mock_graph_edges_to_gdf.assert_called_once_with(mock_graph)
        mock_voronoi_diagram.assert_called_once_with(mock_unary_union, envelope=mock_bounds)
        mock_voronoi_gdf.set_crs.assert_called_once_with(mock_gdf.crs)
        gpd.clip.assert_called_once_with(mock_voronoi_gdf, mock_bounds)
        self.assertEqual(result, mock_voronoi_gdf_clipped)


    @patch('src.calculators.xn_qm_lib.gpd.read_file')
    @patch('src.calculators.xn_qm_lib.dask_geopandas.from_geopandas')
    def test_calculate_xn_qm(self, mock_from_geopandas, mock_read_file):
        mock_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_read_file.return_value = mock_gdf
        mock_from_geopandas.return_value.apply.return_value.compute.return_value = mock_gdf
        result = calculate_xn_qm("test_edges.geojson", "test_output.geojson", "test_polygon.geojson")
        self.assertIsNone(result)

    @patch('src.calculators.xn_qm_lib.gpd.read_file')
    def test_calculate_xn_qm_exception(self, mock_read_file):
        mock_read_file.side_effect = Exception("Mocked exception")
        result = calculate_xn_qm("test_edges.geojson", "test_output.geojson", "test_polygon.geojson")
        self.assertEqual(result, -1)

    def test_graph_from_gdf_multilinestring(self):
        mock_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_multilinestring = MultiLineString([
            LineString([(0, 0), (1, 1)]),
            LineString([(1, 1), (2, 2)])
        ])
        mock_gdf.iterrows.return_value = iter([
            (0, MagicMock(geometry=mock_multilinestring)),
        ])
        graph = graph_from_gdf(mock_gdf)
        self.assertEqual(len(graph.edges), 2)

    @patch('src.calculators.xn_qm_lib.tile_tra_score')
    def test_get_stats_exception(self, mock_tile_tra_score):
        mock_tile_tra_score.side_effect = Exception("Mocked exception")
        stats = get_stats(self.polygon, self.graph, self.gdf)
        self.assertIn("tra_score", stats)
        self.assertEqual(stats["tra_score"], -1)

    @patch('src.calculators.xn_qm_lib.gpd.clip')
    @patch('src.calculators.xn_qm_lib.graph_from_gdf')
    @patch('src.calculators.xn_qm_lib.get_stats')
    def test_get_measures_from_polygon_multipolygon(self, mock_get_stats, mock_graph_from_gdf, mock_clip):
        # Mock the cropped GeoDataFrame
        mock_cropped_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_clip.return_value = mock_cropped_gdf

        # Mock the graph and stats
        mock_graph = MagicMock()
        mock_graph_from_gdf.return_value = mock_graph
        mock_get_stats.return_value = {"tra_score": 1.0}

        # MultiPolygon with one geometry
        mock_multipolygon = MultiPolygon([self.polygon])

        # Call the function
        measures = get_measures_from_polygon(mock_multipolygon, self.gdf)

        # Assertions
        mock_clip.assert_called_once_with(self.gdf, self.polygon)
        mock_graph_from_gdf.assert_called_once_with(mock_cropped_gdf)
        mock_get_stats.assert_called_once_with(self.polygon, mock_graph, mock_cropped_gdf)

        self.assertIn("tra_score", measures)
        self.assertEqual(measures["tra_score"], 1.0)

    @patch('src.calculators.xn_qm_lib.create_voronoi_diagram')
    @patch('src.calculators.xn_qm_lib.ox.graph.graph_from_polygon')
    @patch('src.calculators.xn_qm_lib.gpd.read_file')
    @patch('src.calculators.xn_qm_lib.dask_geopandas.from_geopandas')
    def test_calculate_xn_qm_without_polygon(
            self, mock_from_geopandas, mock_read_file, mock_graph_from_polygon, mock_create_voronoi
    ):
        # Mock data and behaviors
        mock_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_tile_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_transformed_gdf = MagicMock(spec=gpd.GeoDataFrame)
        mock_selected_gdf = MagicMock(spec=gpd.GeoDataFrame)

        mock_read_file.return_value = mock_gdf
        mock_graph_from_polygon.return_value = MagicMock()
        mock_create_voronoi.return_value = mock_tile_gdf

        # Mock method chaining for the `tile_gdf` object
        mock_tile_gdf.to_crs.return_value = mock_transformed_gdf
        mock_transformed_gdf.__getitem__.return_value = mock_selected_gdf

        # Mock dask-geopandas behavior
        mock_from_geopandas.return_value.apply.return_value.compute.return_value = mock_selected_gdf

        # Call the function without polygon
        result = calculate_xn_qm("test_edges.geojson", "test_output.geojson")

        # Assertions
        mock_read_file.assert_called_once_with("test_edges.geojson")
        mock_graph_from_polygon.assert_called_once()
        mock_create_voronoi.assert_called_once()
        mock_tile_gdf.to_crs.assert_called_once_with(PROJ)
        mock_transformed_gdf.__getitem__.assert_called_once_with(["geometry"])
        mock_from_geopandas.assert_called_once_with(mock_selected_gdf, npartitions=os.cpu_count())
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
