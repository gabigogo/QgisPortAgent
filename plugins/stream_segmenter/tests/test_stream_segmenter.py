"""Unit and integration tests for stream_segmenter.

Pure-Python helper tests run without QGIS.
Tests marked with @pytest.mark.qgis require QGIS Python bindings and are
skipped automatically when the bindings are unavailable.
"""

from __future__ import annotations

import math

import pytest
from shapely.geometry import LineString, MultiLineString

# ---------------------------------------------------------------------------
# Import helpers from utils.geometry (no QGIS required)
# ---------------------------------------------------------------------------
from plugins.stream_segmenter.utils.geometry import (
    FLD_MILE_RANGE,
    FLD_SEG_NUM,
    FLD_STREAM_SEG_ID,
    KM_TO_METRES,
    MILES_TO_METRES,
    cut_fraction,
    fmt_distance,
    load_reference_values,
    matches_reference,
    parse_range_start,
    sanitize_name,
    to_oriented_line,
)


# ===========================================================================
# _sanitize_name
# ===========================================================================
class TestSanitizeName:
    def test_strips_whitespace(self):
        assert sanitize_name("  Bear Creek  ") == "Bear_Creek"

    def test_replaces_interior_spaces(self):
        assert sanitize_name("Halls Bayou") == "Halls_Bayou"

    def test_empty_string(self):
        assert sanitize_name("") == ""

    def test_no_spaces(self):
        assert sanitize_name("BruffyCreek") == "BruffyCreek"

    def test_multiple_interior_spaces(self):
        assert sanitize_name("A B C") == "A_B_C"

    def test_already_underscored(self):
        assert sanitize_name("Bear_Creek") == "Bear_Creek"


# ===========================================================================
# _fmt
# ===========================================================================
class TestFmt:
    def test_whole_zero(self):
        assert fmt_distance(0.0) == "0"

    def test_whole_five(self):
        assert fmt_distance(5.0) == "5"

    def test_half(self):
        assert fmt_distance(0.5) == "0.5"

    def test_tenth(self):
        assert fmt_distance(2.1) == "2.1"

    def test_large_whole(self):
        assert fmt_distance(100.0) == "100"

    def test_rounds_to_one_decimal(self):
        # fmt_distance uses f"{v:.1f}" so 2.07 → "2.1"
        assert fmt_distance(2.07) == "2.1"


# ===========================================================================
# _cut_fraction
# ===========================================================================
class TestCutFraction:
    def test_first_half(self, simple_line):
        seg = cut_fraction(simple_line, 0.0, 0.5)
        assert seg is not None
        assert not seg.is_empty
        # Length should be ~5 (half of 10-unit line)
        assert abs(seg.length - 5.0) < 1e-6

    def test_second_half(self, simple_line):
        seg = cut_fraction(simple_line, 0.5, 1.0)
        assert seg is not None
        assert abs(seg.length - 5.0) < 1e-6

    def test_full_line(self, simple_line):
        seg = cut_fraction(simple_line, 0.0, 1.0)
        assert seg is not None
        assert abs(seg.length - simple_line.length) < 1e-6

    def test_first_coord_of_first_segment(self, simple_line):
        """For an oriented line starting at downstream (10,0), first segment
        should start at (10,0)."""
        oriented = LineString(list(simple_line.coords)[::-1])  # reversed
        seg = cut_fraction(oriented, 0.0, 0.5)
        assert seg is not None
        assert abs(seg.coords[0][0] - 10.0) < 1e-6
        assert abs(seg.coords[0][1] - 0.0) < 1e-6

    def test_returns_none_for_zero_fraction(self, simple_line):
        """start == end → degenerate → None."""
        seg = cut_fraction(simple_line, 0.5, 0.5)
        assert seg is None

    def test_three_equal_segments(self, simple_line):
        """10-unit line cut into 3 equal thirds."""
        segs = [cut_fraction(simple_line, i / 3, (i + 1) / 3) for i in range(3)]
        assert all(s is not None for s in segs)
        lengths = [s.length for s in segs]
        # Each should be ~3.33
        assert all(abs(ln - 10.0 / 3) < 1e-5 for ln in lengths)


# ===========================================================================
# _to_oriented_line  (shapely inputs via QgsGeometry-like mock)
# ===========================================================================
class TestToOrientedLine:
    """Tests using to_oriented_line(wkb_bytes) from utils.geometry."""

    def test_linestring_downstream_becomes_first(self, simple_line):
        """Last coord of input LineString should be first coord of output."""
        oriented, err = to_oriented_line(bytes(simple_line.wkb))
        assert err is None
        assert oriented is not None
        # Original last coord (10,0) must now be first
        assert abs(oriented.coords[0][0] - 10.0) < 1e-6
        assert abs(oriented.coords[0][1] - 0.0) < 1e-6

    def test_multilinestring_connected(self, connected_multiline):
        """Connected MultiLineString: downstream = last coord of last part."""
        oriented, err = to_oriented_line(bytes(connected_multiline.wkb))
        assert err is None
        assert oriented is not None
        # Downstream = (10, 0) must be first coord
        assert abs(oriented.coords[0][0] - 10.0) < 1e-6

    def test_multilinestring_disconnected_returns_error(self):
        """Disconnected MultiLineString should return an error message."""
        disconnected = MultiLineString(
            [[(0.0, 0.0), (1.0, 0.0)], [(5.0, 5.0), (6.0, 5.0)]]
        )
        oriented, err = to_oriented_line(bytes(disconnected.wkb))
        assert oriented is None
        assert err is not None
        assert "disconnected" in err.lower()

    def test_oriented_length_preserved(self, diagonal_line):
        """Reversing a line must preserve its total length."""
        oriented, err = to_oriented_line(bytes(diagonal_line.wkb))
        assert err is None
        assert abs(oriented.length - diagonal_line.length) < 1e-9


# ===========================================================================
# Unit / label arithmetic  (no QGIS)
# ===========================================================================
class TestSegmentLabelArithmetic:
    """Verify that segment labels and IDs are computed correctly."""

    def _run_labels(self, total_m, seg_len, use_km):
        """Simulate the label-generation loop from processAlgorithm."""
        seg_m = seg_len * (KM_TO_METRES if use_km else MILES_TO_METRES)
        unit_label = "km" if use_km else "mi"
        id_unit = "_km_" if use_km else "_mile_"
        stream_name = "Bear_Creek"
        n_segs = math.ceil(total_m / seg_m)
        total_user = total_m / (KM_TO_METRES if use_km else MILES_TO_METRES)
        pad = max(2, len(str(n_segs)))

        labels = []
        for i in range(n_segs):
            start_u = i * seg_len
            end_u = min((i + 1) * seg_len, total_user)
            seg_num = i + 1
            mile_range = f"{fmt_distance(start_u)}-{fmt_distance(end_u)} {unit_label}"
            seg_id = f"{stream_name}{id_unit}{seg_num:0{pad}d}"
            labels.append((seg_num, mile_range, seg_id))

        return labels

    def test_five_mile_stream_one_mile_segments(self):
        total_m = 5 * MILES_TO_METRES
        labels = self._run_labels(total_m, 1.0, use_km=False)
        assert len(labels) == 5
        assert labels[0] == (1, "0-1 mi", "Bear_Creek_mile_01")
        assert labels[4] == (5, "4-5 mi", "Bear_Creek_mile_05")

    def test_km_mode_labels(self):
        total_m = 3 * KM_TO_METRES
        labels = self._run_labels(total_m, 1.0, use_km=True)
        assert len(labels) == 3
        assert labels[0] == (1, "0-1 km", "Bear_Creek_km_01")
        assert labels[2] == (3, "2-3 km", "Bear_Creek_km_03")

    def test_partial_last_segment_label(self):
        """A 5.5-mile stream with 1-mile segments: last label should be '5-5.5 mi'."""
        total_m = 5.5 * MILES_TO_METRES
        labels = self._run_labels(total_m, 1.0, use_km=False)
        assert len(labels) == 6
        seg_num, mile_range, seg_id = labels[-1]
        assert seg_num == 6
        assert mile_range == "5-5.5 mi"

    def test_pad_width_expands_for_large_segment_count(self):
        """A 200-mile stream with 1-mile segments needs 3-digit padding."""
        total_m = 200 * MILES_TO_METRES
        labels = self._run_labels(total_m, 1.0, use_km=False)
        assert len(labels) == 200
        _, _, first_id = labels[0]
        assert first_id == "Bear_Creek_mile_001"
        _, _, last_id = labels[-1]
        assert last_id == "Bear_Creek_mile_200"

    def test_two_mile_segment_length(self):
        """6-mile stream with 2-mile segments → 3 segments."""
        total_m = 6 * MILES_TO_METRES
        labels = self._run_labels(total_m, 2.0, use_km=False)
        assert len(labels) == 3
        assert labels[0][1] == "0-2 mi"
        assert labels[1][1] == "2-4 mi"
        assert labels[2][1] == "4-6 mi"


# ===========================================================================
# QGIS integration smoke test
# ===========================================================================
@pytest.mark.qgis
class TestAlgorithmIntegration:
    """End-to-end test requiring QGIS bindings."""

    def test_algorithm_name_and_display(self):
        from plugins.stream_segmenter.processing_provider.algorithms.stream_segmenter_algorithm import (
            StreamSegmenterAlgorithm,
        )

        alg = StreamSegmenterAlgorithm()
        assert alg.name() == "stream_segmenter"
        assert "Segmenter" in alg.displayName()

    def test_parameter_count(self):
        from plugins.stream_segmenter.processing_provider.algorithms.stream_segmenter_algorithm import (
            StreamSegmenterAlgorithm,
        )

        alg = StreamSegmenterAlgorithm()
        alg.initAlgorithm()
        # INPUT, NAME_FIELD, SELECTED_ONLY, SEGMENT_LENGTH, USE_KM,
        # PRESERVE_ATTRS, OUTPUT = 7 parameters
        assert len(alg.parameterDefinitions()) == 7

    def test_provider_registers_algorithm(self):
        from plugins.stream_segmenter.processing_provider.provider import (
            StreamSegmenterProvider,
        )

        provider = StreamSegmenterProvider()
        provider.loadAlgorithms()
        alg_names = [a.name() for a in provider.algorithms()]
        assert "stream_segmenter" in alg_names

    def test_run_on_in_memory_layer(self):
        """Full processing run on a synthetic in-memory LineString layer."""
        import processing
        from qgis.core import (
            QgsFeature,
            QgsGeometry,
            QgsProject,
            QgsVectorLayer,
        )

        # Create an in-memory line layer with a 10 000-metre straight line.
        # CRS: EPSG:32614 (UTM Zone 14N, units = metres)
        layer = QgsVectorLayer(
            "LineString?crs=EPSG:32614&field=stream_name:string",
            "test_channels",
            "memory",
        )
        feat = QgsFeature(layer.fields())
        # ~6.2-mile horizontal line (10 000 m)
        feat.setGeometry(
            QgsGeometry.fromWkt("LINESTRING(0 0, 10000 0)")
        )
        feat["stream_name"] = "Test Creek"
        layer.dataProvider().addFeatures([feat])
        QgsProject.instance().addMapLayer(layer, False)

        result = processing.run(
            "stream_segmenter:stream_segmenter",
            {
                "INPUT": layer,
                "NAME_FIELD": "stream_name",
                "SELECTED_ONLY": False,
                "SEGMENT_LENGTH": 1.0,
                "USE_KM": False,
                "PRESERVE_ATTRS": False,
                "OUTPUT": "TEMPORARY_OUTPUT",
            },
        )

        out_layer = result["OUTPUT"]
        assert out_layer is not None
        features = list(out_layer.getFeatures())

        # 10 000 m ≈ 6.214 miles → ceil(6.214) = 7 segments
        assert len(features) == 7

        # First segment: seg_num=1, range="0-1 mi", id starts with "Test_Creek_mile_"
        first = features[0]
        assert first["seg_num"] == 1
        assert first["mile_range"].startswith("0-1")
        assert "Test_Creek_mile_" in first["stream_seg_id"]

        # Last segment: partial, end < 7.0 mi
        last = features[-1]
        assert last["seg_num"] == 7

        QgsProject.instance().removeMapLayer(layer.id())


# ===========================================================================
# Batch algorithm — pure-Python helpers (no QGIS required)
# ===========================================================================
class TestBatchCollectFiles:
    """Tests for collect_files() from utils.geometry (pure Python)."""

    @staticmethod
    def _alg():
        from plugins.stream_segmenter.utils.geometry import collect_files
        return collect_files

    def test_gpkg_filter_finds_gpkg(self, tmp_path):
        collect = self._alg()
        (tmp_path / "rivers.gpkg").write_text("")
        (tmp_path / "ignore.shp").write_text("")
        result = collect(tmp_path, "*.gpkg")
        assert len(result) == 1
        assert result[0].name == "rivers.gpkg"

    def test_multi_pattern_finds_both(self, tmp_path):
        collect = self._alg()
        (tmp_path / "a.gpkg").write_text("")
        (tmp_path / "b.shp").write_text("")
        (tmp_path / "c.txt").write_text("")
        result = collect(tmp_path, "*.gpkg *.shp")
        names = {f.name for f in result}
        assert names == {"a.gpkg", "b.shp"}

    def test_empty_filter_falls_back_to_default_extensions(self, tmp_path):
        collect = self._alg()
        (tmp_path / "rivers.gpkg").write_text("")
        (tmp_path / "notes.txt").write_text("")
        result = collect(tmp_path, "")
        assert any(f.name == "rivers.gpkg" for f in result)
        assert all(f.name != "notes.txt" for f in result)

    def test_no_matches_returns_empty(self, tmp_path):
        collect = self._alg()
        (tmp_path / "data.csv").write_text("")
        result = collect(tmp_path, "*.gpkg")
        assert result == []

    def test_non_recursive(self, tmp_path):
        """Files in sub-folders must NOT be returned."""
        collect = self._alg()
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.gpkg").write_text("")
        result = collect(tmp_path, "*.gpkg")
        assert result == []

    def test_results_are_sorted(self, tmp_path):
        collect = self._alg()
        for name in ["c.gpkg", "a.gpkg", "b.gpkg"]:
            (tmp_path / name).write_text("")
        result = collect(tmp_path, "*.gpkg")
        assert [f.name for f in result] == ["a.gpkg", "b.gpkg", "c.gpkg"]


# ===========================================================================
# Batch algorithm — QGIS integration
# ===========================================================================
@pytest.mark.qgis
class TestBatchAlgorithmIntegration:
    """End-to-end batch test requiring QGIS bindings."""

    def _make_line_layer(self, name: str, wkt: str, stream_name: str):
        """Helper: create an in-memory line layer with one feature."""
        from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer

        layer = QgsVectorLayer(
            f"LineString?crs=EPSG:32614&field=stream_name:string",
            name,
            "memory",
        )
        feat = QgsFeature(layer.fields())
        feat.setGeometry(QgsGeometry.fromWkt(wkt))
        feat["stream_name"] = stream_name
        layer.dataProvider().addFeatures([feat])
        return layer

    def test_batch_processes_folder_of_gpkgs(self, tmp_path):
        import processing
        from qgis.core import QgsVectorFileWriter, QgsVectorLayer

        # Write two synthetic GeoPackages to tmp_path
        for stem, wkt, sname in [
            ("creek_a", "LINESTRING(0 0, 5000 0)", "Creek_A"),
            ("creek_b", "LINESTRING(0 0, 3000 0)", "Creek_B"),
        ]:
            layer = self._make_line_layer(stem, wkt, sname)
            opts = QgsVectorFileWriter.SaveVectorOptions()
            opts.driverName = "GPKG"
            QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                str(tmp_path / f"{stem}.gpkg"),
                layer.transformContext(),
                opts,
            )

        out_folder = tmp_path / "output"
        result = processing.run(
            "stream_segmenter:batch_stream_segmenter",
            {
                "INPUT_FOLDER": str(tmp_path),
                "FILE_FILTER": "*.gpkg",
                "NAME_FIELD": "stream_name",
                "SEGMENT_LENGTH": 1.0,
                "USE_KM": False,
                "PRESERVE_ATTRS": False,
                "OUTPUT_FOLDER": str(out_folder),
            },
        )

        assert result["OUTPUT_FOLDER"] == str(out_folder)

        for stem in ["creek_a_segmented", "creek_b_segmented"]:
            gpkg = out_folder / f"{stem}.gpkg"
            assert gpkg.exists(), f"Expected output file {gpkg} not found"
            out_layer = QgsVectorLayer(str(gpkg), stem, "ogr")
            assert out_layer.isValid()
            features = list(out_layer.getFeatures())
            assert len(features) >= 1
            # First segment has seg_num = 1
            assert features[0]["seg_num"] == 1

    def test_batch_skips_file_with_missing_name_field(self, tmp_path):
        import processing
        from qgis.core import QgsFeature, QgsGeometry, QgsVectorFileWriter, QgsVectorLayer

        # Create a layer WITHOUT the expected name field
        layer = QgsVectorLayer(
            "LineString?crs=EPSG:32614&field=other_field:string",
            "no_name",
            "memory",
        )
        feat = QgsFeature(layer.fields())
        feat.setGeometry(QgsGeometry.fromWkt("LINESTRING(0 0, 5000 0)"))
        feat["other_field"] = "x"
        layer.dataProvider().addFeatures([feat])

        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            str(tmp_path / "no_name.gpkg"),
            layer.transformContext(),
            opts,
        )

        out_folder = tmp_path / "output"
        result = processing.run(
            "stream_segmenter:batch_stream_segmenter",
            {
                "INPUT_FOLDER": str(tmp_path),
                "FILE_FILTER": "*.gpkg",
                "NAME_FIELD": "stream_name",  # deliberately missing
                "SEGMENT_LENGTH": 1.0,
                "USE_KM": False,
                "PRESERVE_ATTRS": False,
                "OUTPUT_FOLDER": str(out_folder),
            },
        )

        # No output file should have been created
        assert not (out_folder / "no_name_segmented.gpkg").exists()


# ===========================================================================
# parse_range_start — pure Python (no QGIS required)
# ===========================================================================
class TestParseRangeStart:
    """Tests for parse_range_start() from utils.geometry."""

    @staticmethod
    def _fn():
        from plugins.stream_segmenter.utils.geometry import parse_range_start
        return parse_range_start

    def test_whole_miles_zero(self):
        assert self._fn()("0-1 mi") == 0.0

    def test_whole_miles_nonzero(self):
        assert self._fn()("4-5 mi") == 4.0

    def test_decimal_start_km(self):
        assert self._fn()("4.5-5 km") == 4.5

    def test_partial_last_segment(self):
        assert self._fn()("5-5.5 mi") == 5.0

    def test_large_value(self):
        assert self._fn()("199-200 mi") == 199.0

    def test_bad_string_returns_none(self):
        assert self._fn()("bad") is None

    def test_empty_string_returns_none(self):
        assert self._fn()("") is None

    def test_only_whitespace_returns_none(self):
        assert self._fn()("   ") is None


# ===========================================================================
# Table filter helpers — pure Python (no QGIS required)
# ===========================================================================
class TestLoadReferenceValues:
    """Tests for load_reference_values() from utils.geometry."""

    def test_load_csv_by_column_index(self, tmp_path):
        csv_path = tmp_path / "refs.csv"
        csv_path.write_text(
            "unit,name\nA100-00-00,Clear Creek\nA104-00-00,Clear Creek\n",
            encoding="utf-8",
        )

        values = load_reference_values(str(csv_path), "0", has_header=True)
        assert values == {"A100-00-00", "A104-00-00"}

    def test_load_csv_by_column_name(self, tmp_path):
        csv_path = tmp_path / "refs.csv"
        csv_path.write_text(
            "unit,name\nA100-00-00,Clear Creek\nA104-00-00,Clear Creek\n",
            encoding="utf-8",
        )

        values = load_reference_values(str(csv_path), "unit", has_header=True)
        assert values == {"A100-00-00", "A104-00-00"}

    def test_load_csv_without_header_uses_index(self, tmp_path):
        csv_path = tmp_path / "refs.csv"
        csv_path.write_text(
            "A100-00-00,Clear Creek\nA104-00-00,Clear Creek\n",
            encoding="utf-8",
        )

        values = load_reference_values(str(csv_path), "0", has_header=False)
        assert values == {"A100-00-00", "A104-00-00"}

    def test_load_xlsx_by_column_name(self, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")

        xlsx_path = tmp_path / "refs.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["unit", "name"])
        ws.append(["A100-00-00", "Clear Creek"])
        ws.append(["A104-00-00", "Clear Creek"])
        wb.save(str(xlsx_path))
        wb.close()

        values = load_reference_values(str(xlsx_path), "unit", has_header=True)
        assert values == {"A100-00-00", "A104-00-00"}

    def test_bad_column_name_raises(self, tmp_path):
        csv_path = tmp_path / "refs.csv"
        csv_path.write_text("unit\nA100-00-00\n", encoding="utf-8")

        with pytest.raises(ValueError):
            load_reference_values(str(csv_path), "missing", has_header=True)


class TestMatchesReference:
    """Tests for matches_reference() from utils.geometry."""

    def test_exact_match_true(self):
        refs = {"A100-00-00"}
        assert matches_reference("A100-00-00", refs, exact=True) is True

    def test_exact_match_false(self):
        refs = {"A100-00-00"}
        assert matches_reference("A100-00-00_mile_01", refs, exact=True) is False

    def test_partial_match_true(self):
        refs = {"A100-00-00"}
        assert matches_reference("A100-00-00_mile_01", refs, exact=False) is True

    def test_partial_match_false(self):
        refs = {"A100-00-00"}
        assert matches_reference("B100-00-00_mile_01", refs, exact=False) is False

    def test_empty_reference_set(self):
        assert matches_reference("A100-00-00", set(), exact=True) is False

    def test_none_candidate(self):
        refs = {"A100-00-00"}
        assert matches_reference(None, refs, exact=False) is False


# ===========================================================================
# Filter algorithm — pure-Python logic simulation (no QGIS required)
# ===========================================================================
class TestStreamSegmentFilterLogic:
    """Verify the filter conditions used by StreamSegmentFilterAlgorithm
    without invoking QGIS.  These tests drive the same parse_range_start
    helper that the algorithm uses internally."""

    @staticmethod
    def _keep_by_count(seg_num: int, n: int) -> bool:
        return int(seg_num) <= n

    @staticmethod
    def _keep_by_distance(mile_range: str, max_dist: float) -> bool:
        from plugins.stream_segmenter.utils.geometry import parse_range_start
        start = parse_range_start(mile_range)
        return start is not None and start < max_dist

    # ── By count ──────────────────────────────────────────────────────────

    def test_count_keeps_seg_1_when_n_is_1(self):
        assert self._keep_by_count(1, 1) is True

    def test_count_rejects_seg_2_when_n_is_1(self):
        assert self._keep_by_count(2, 1) is False

    def test_count_keeps_all_within_n(self):
        kept = [i for i in range(1, 11) if self._keep_by_count(i, 5)]
        assert kept == [1, 2, 3, 4, 5]

    def test_count_boundary_inclusive(self):
        assert self._keep_by_count(5, 5) is True
        assert self._keep_by_count(6, 5) is False

    # ── By distance ───────────────────────────────────────────────────────

    def test_distance_keeps_seg_starting_at_zero(self):
        assert self._keep_by_distance("0-1 mi", 5.0) is True

    def test_distance_keeps_seg_starting_just_below_threshold(self):
        assert self._keep_by_distance("4-5 mi", 5.0) is True

    def test_distance_rejects_seg_starting_at_threshold(self):
        # start == max_dist is excluded (strict less-than)
        assert self._keep_by_distance("5-6 mi", 5.0) is False

    def test_distance_rejects_seg_starting_above_threshold(self):
        assert self._keep_by_distance("6-7 mi", 5.0) is False

    def test_distance_works_with_decimal_start(self):
        assert self._keep_by_distance("4.5-5 km", 5.0) is True
        assert self._keep_by_distance("5-5.5 km", 5.0) is False

    def test_distance_rejects_bad_mile_range(self):
        assert self._keep_by_distance("bad_value", 5.0) is False

    def test_distance_filters_simulated_seven_segment_channel(self):
        """Simulate keeping segments of a 7-segment channel within 3 mi."""
        segments = [f"{i}-{i+1} mi" for i in range(7)]
        kept = [s for s in segments if self._keep_by_distance(s, 3.0)]
        assert kept == ["0-1 mi", "1-2 mi", "2-3 mi"]


# ===========================================================================
# Filter algorithm — QGIS integration
# ===========================================================================
@pytest.mark.qgis
class TestStreamSegmentFilterIntegration:
    """End-to-end filter test requiring QGIS bindings."""

    def _make_segmented_layer(self):
        """Build a synthetic segmented layer matching StreamSegmenter output."""
        from qgis.core import (
            QgsFeature,
            QgsField,
            QgsFields,
            QgsGeometry,
            QgsVectorLayer,
        )
        from qgis.PyQt.QtCore import QVariant

        layer = QgsVectorLayer(
            "LineString?crs=EPSG:32614"
            "&field=seg_num:integer"
            "&field=mile_range:string(30)"
            "&field=stream_seg_id:string(100)",
            "segmented",
            "memory",
        )

        def _add(seg_num, mile_range, stream_seg_id, wkt):
            feat = QgsFeature(layer.fields())
            feat.setGeometry(QgsGeometry.fromWkt(wkt))
            feat["seg_num"] = seg_num
            feat["mile_range"] = mile_range
            feat["stream_seg_id"] = stream_seg_id
            layer.dataProvider().addFeatures([feat])

        # Channel A: 5 segments
        for i in range(5):
            _add(i + 1, f"{i}-{i+1} mi", f"Creek_A_mile_{i+1:02d}",
                 f"LINESTRING({i*100} 0, {(i+1)*100} 0)")
        # Channel B: 3 segments
        for i in range(3):
            _add(i + 1, f"{i}-{i+1} mi", f"Creek_B_mile_{i+1:02d}",
                 f"LINESTRING({i*100} 100, {(i+1)*100} 100)")

        return layer

    def test_filter_by_count_n3(self):
        import processing

        layer = self._make_segmented_layer()
        result = processing.run(
            "stream_segmenter:stream_segment_filter",
            {
                "INPUT": layer,
                "FILTER_MODE": 0,  # by count
                "N_SEGMENTS": 3,
                "MAX_DISTANCE": 99.0,
                "OUTPUT": "TEMPORARY_OUTPUT",
            },
        )
        out = result["OUTPUT"]
        features = list(out.getFeatures())
        # Channel A: seg 1,2,3 kept; seg 4,5 dropped = 3
        # Channel B: seg 1,2,3 all kept = 3
        assert len(features) == 6
        assert all(f["seg_num"] <= 3 for f in features)

    def test_filter_by_distance_two_miles(self):
        import processing

        layer = self._make_segmented_layer()
        result = processing.run(
            "stream_segmenter:stream_segment_filter",
            {
                "INPUT": layer,
                "FILTER_MODE": 1,  # by distance
                "N_SEGMENTS": 99,
                "MAX_DISTANCE": 2.0,
                "OUTPUT": "TEMPORARY_OUTPUT",
            },
        )
        out = result["OUTPUT"]
        features = list(out.getFeatures())
        # Segments starting at 0 mi and 1 mi pass (start < 2.0).
        # Segments starting at 2, 3, 4 mi do not.
        # Channel A: 2 kept, Channel B: 2 kept = 4 total
        assert len(features) == 4
        for f in features:
            from plugins.stream_segmenter.utils.geometry import parse_range_start
            assert parse_range_start(f["mile_range"]) < 2.0

    def test_filter_preserves_all_input_fields(self):
        import processing

        layer = self._make_segmented_layer()
        result = processing.run(
            "stream_segmenter:stream_segment_filter",
            {
                "INPUT": layer,
                "FILTER_MODE": 0,
                "N_SEGMENTS": 1,
                "MAX_DISTANCE": 99.0,
                "OUTPUT": "TEMPORARY_OUTPUT",
            },
        )
        out = result["OUTPUT"]
        out_field_names = {f.name() for f in out.fields()}
        assert "seg_num" in out_field_names
        assert "mile_range" in out_field_names
        assert "stream_seg_id" in out_field_names

    def test_filter_algorithm_registered_in_provider(self):
        from plugins.stream_segmenter.processing_provider.provider import StreamSegmenterProvider

        provider = StreamSegmenterProvider()
        provider.loadAlgorithms()
        alg_names = [a.name() for a in provider.algorithms()]
        assert "stream_segment_filter" in alg_names
        assert "stream_segment_table_filter" in alg_names
        assert "batch_stream_segment_table_filter" in alg_names
