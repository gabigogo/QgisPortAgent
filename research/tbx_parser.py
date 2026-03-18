"""
tbx_parser.py — Binary ArcGIS .tbx parser (ArcMap OLE Compound File format).

Confirmed schema (reverse-engineered via corpus analysis):
  OLE Streams: Contents, Tool0..ToolN, Version

  Version stream:
    0x00-0x0d : 14 bytes (version header: e.g. 06 00 02 00 + padding)
    0x0e-0x11 : uint32-LE  char_count
    0x12+     : UTF-16-LE  toolbox_name  (char_count chars + 00 00 null term)

  Contents stream:
    0x00+    : WSTR(4-byte char_count)  alias
    bytes    : ~22 bytes binary
    WSTR     : (empty)
    bytes    : ~16 bytes binary
    XML blob : UTF-8 XML starting with '<?xml' (toolbox metadata/description)

  Tool<N> stream (N = 0-based index of each tool in the toolbox):
    0x00: uint32  tool_type   (3 = Script, 1 = ModelBuilder?)
    0x04: uint16  flags_a
    0x06: uint16  flags_b
    0x08: WSTR    tool_internal_name
    next: WSTR    tool_display_name
    next: WSTR    tool_description
    +16 binary bytes (help URL, tags etc. — mostly zero/small values)
    WSTR         script_relative_path  (e.g. "Scripts\\myscript.py")
    uint32       param_count
    [ repeated param_count times ]
      PARAM_MARKER_GUID (16 bytes): 12 6f d0 31 00 3f f8 47 a6 57 3a 2e 4e a8 5f e2
      uint16          unknown_07  (always 0x0007)
      WSTR            param_internal_name
      WSTR            param_display_name
      [ 24-byte binary block ]
        uint32  direction   0=Input, 1=Output
        bytes   type GUID   (16 bytes, identifies ArcGIS parameter interface)
        uint16  flags_c
        uint16  flags_d
      WSTR            gp_datatype_class   e.g. "GPFeatureRecordSetLayer", "GPString"
      WSTR            dt_display_1         e.g. "Feature Set"
      WSTR            dt_display_2         (duplicate of dt_display_1)
      WSTR            literal "Data Type"
      [ filter/default blob — variable length binary until next PARAM_MARKER_GUID ]

GP_TYPE_MAP maps ArcGIS GP class names to QGIS QgsProcessingParameterTypes:
"""

from __future__ import annotations
import re
import struct
import pathlib
from dataclasses import dataclass, field
from typing import Optional

try:
    import olefile
except ImportError as exc:
    raise ImportError("Install olefile:  pip install olefile") from exc


# ── Constants ─────────────────────────────────────────────────────────────────

PARAM_MARKER_GUID = bytes([
    0x12, 0x6f, 0xd0, 0x31, 0x00, 0x3f, 0xf8, 0x47,
    0xa6, 0x57, 0x3a, 0x2e, 0x4e, 0xa8, 0x5f, 0xe2,
])

# Map ArcGIS GP data type class → QGIS QgsProcessingParameter class + notes.
# Source: https://desktop.arcgis.com/en/arcmap/latest/analyze/creating-tools/defining-parameter-data-types-in-a-python-toolbox.htm
# Keys with "qgis_output" use a different QGIS class when direction == "Output".
GP_TYPE_MAP: dict[str, dict] = {

    # ── Raster / Image ────────────────────────────────────────────────────────
    "GPRasterLayer":            {"qgis": "QgsProcessingParameterRasterLayer",
                                 "note": ""},
    "DERasterDataset":          {"qgis": "QgsProcessingParameterRasterLayer",
                                 "qgis_output": "QgsProcessingParameterRasterDestination",
                                 "note": "Single raster dataset"},
    "GPRasterDataLayer":        {"qgis": "QgsProcessingParameterRasterLayer",
                                 "note": ""},
    "DERasterBand":             {"qgis": "QgsProcessingParameterBand",
                                 "note": "Single band of a raster"},
    "DERasterCatalog":          {"qgis": "QgsProcessingParameterRasterLayer",
                                 "note": "Raster catalog — no direct QGIS equivalent; use raster layer"},
    "GPRasterCatalogLayer":     {"qgis": "QgsProcessingParameterRasterLayer",
                                 "note": ""},
    "GPRasterFormulated":       {"qgis": "QgsProcessingParameterRasterLayer",
                                 "note": "Formulated raster (formula/constant cell values)"},
    "GPRasterCalculatorExpression": {"qgis": "QgsProcessingParameterExpression",
                                 "note": "Raster calculator expression"},
    "GPRasterBuilder":          {"qgis": "QgsProcessingParameterString",
                                 "note": "Raster type for mosaic datasets — review manually"},
    # Mosaic
    "DEMosaicDataset":          {"qgis": "QgsProcessingParameterRasterLayer",
                                 "qgis_output": "QgsProcessingParameterRasterDestination",
                                 "note": "Mosaic dataset"},
    "GPMosaicLayer":            {"qgis": "QgsProcessingParameterRasterLayer",
                                 "note": ""},

    # ── Vector / Feature ──────────────────────────────────────────────────────
    "GPFeatureLayer":           {"qgis": "QgsProcessingParameterFeatureSource",
                                 "qgis_output": "QgsProcessingParameterFeatureSink",
                                 "note": ""},
    "DEFeatureClass":           {"qgis": "QgsProcessingParameterFeatureSource",
                                 "qgis_output": "QgsProcessingParameterFeatureSink",
                                 "note": ""},
    "GPFeatureRecordSetLayer":  {"qgis": "QgsProcessingParameterFeatureSource",
                                 "note": "Interactive feature set — digitize features at runtime"},
    "DEShapeFile":              {"qgis": "QgsProcessingParameterFeatureSource",
                                 "qgis_output": "QgsProcessingParameterFeatureSink",
                                 "note": "Shapefile (also aliased as DEShapefile)"},
    "DEShapefile":              {"qgis": "QgsProcessingParameterFeatureSource",
                                 "qgis_output": "QgsProcessingParameterFeatureSink",
                                 "note": "Shapefile"},
    "GPRecordSet":              {"qgis": "QgsProcessingParameterVectorLayer",
                                 "note": "Interactive record set — type in values at runtime"},
    # Coverage (legacy ArcInfo format)
    "DECoverage":               {"qgis": "QgsProcessingParameterFile",
                                 "note": "Legacy ArcInfo coverage — convert to shapefile/GDB first"},
    "DECoverageFeatureClasses": {"qgis": "QgsProcessingParameterFeatureSource",
                                 "note": "Coverage feature class (arc, polygon, etc.)"},
    # Geometry primitives
    "GPLine":                   {"qgis": "QgsProcessingParameterGeometry",
                                 "note": "Line geometry value"},
    "GPPolygon":                {"qgis": "QgsProcessingParameterGeometry",
                                 "note": "Polygon geometry value"},
    "GPPoint":                  {"qgis": "QgsProcessingParameterPoint",
                                 "note": ""},
    "GPEnvelope":               {"qgis": "QgsProcessingParameterExtent",
                                 "note": "Bounding envelope (same as extent)"},

    # ── Table / Tabular ───────────────────────────────────────────────────────
    "GPTableView":              {"qgis": "QgsProcessingParameterVectorLayer",
                                 "note": ""},
    "DETable":                  {"qgis": "QgsProcessingParameterVectorLayer",
                                 "qgis_output": "QgsProcessingParameterVectorDestination",
                                 "note": ""},
    "DEDbaseTable":             {"qgis": "QgsProcessingParameterVectorLayer",
                                 "note": "dBASE table"},
    "GPValueTable":             {"qgis": "QgsProcessingParameterMatrix",
                                 "note": "Multi-column value table"},
    "GPMultiValue":             {"qgis": "QgsProcessingParameterMultipleLayers",
                                 "note": ""},
    "GPFieldMapping":           {"qgis": "QgsProcessingParameterString",
                                 "note": "Field mapping — no direct QGIS equivalent; encode as string or handle manually"},

    # ── File / Folder / Workspace ─────────────────────────────────────────────
    "DEWorkspace":              {"qgis": "QgsProcessingParameterFolderDestination",
                                 "note": "Geodatabase or folder workspace"},
    "DEFolder":                 {"qgis": "QgsProcessingParameterFolderDestination",
                                 "note": ""},
    "DEFile":                   {"qgis": "QgsProcessingParameterFile",
                                 "note": ""},
    "DETextFile":               {"qgis": "QgsProcessingParameterFile",
                                 "note": "Text file (.txt / .csv)"},
    "DETextfile":               {"qgis": "QgsProcessingParameterFile",
                                 "note": "Text file — lowercase 'f' variant"},
    "GPDataFile":               {"qgis": "QgsProcessingParameterFile",
                                 "note": "Generic data file"},
    "DELayer":                  {"qgis": "QgsProcessingParameterFile",
                                 "note": "ArcGIS layer file (.lyr) — no QGIS equivalent; use QLR or style file"},
    "DEPrjFile":                {"qgis": "QgsProcessingParameterFile",
                                 "note": "Projection file (.prj)"},
    "DEMapDocument":            {"qgis": "QgsProcessingParameterFile",
                                 "note": "ArcMap document (.mxd) — no QGIS equivalent; use QGIS project (.qgz)"},
    "DECadDrawingDataset":      {"qgis": "QgsProcessingParameterFile",
                                 "note": "CAD drawing dataset"},
    "DEDiskConnection":         {"qgis": "QgsProcessingParameterFolderDestination",
                                 "note": "Disk connection / path to storage device"},
    "DERemoteDatabaseFolder":   {"qgis": "QgsProcessingParameterFolderDestination",
                                 "note": "Remote database connection folder"},
    "DECatalogRoot":            {"qgis": "QgsProcessingParameterFolderDestination",
                                 "note": "ArcCatalog root node — map to top-level folder"},
    "DESpatialReferencesFolder": {"qgis": "QgsProcessingParameterFolderDestination",
                                 "note": "Folder containing coordinate system definitions"},

    # ── Scalar / String types ─────────────────────────────────────────────────
    "GPString":                 {"qgis": "QgsProcessingParameterString",
                                 "note": ""},
    "GPStringHidden":           {"qgis": "QgsProcessingParameterString",
                                 "note": "Encrypted/password string — set password=True on QgsProcessingParameterString"},
    "GPEncryptedString":        {"qgis": "QgsProcessingParameterString",
                                 "note": "Encrypted string — set password=True on QgsProcessingParameterString"},
    "GPLong":                   {"qgis": "QgsProcessingParameterNumber",
                                 "note": "Integer (QgsProcessingParameterNumber.Integer)"},
    "GPDouble":                 {"qgis": "QgsProcessingParameterNumber",
                                 "note": "Float (QgsProcessingParameterNumber.Double)"},
    "GPBoolean":                {"qgis": "QgsProcessingParameterBoolean",
                                 "note": ""},
    "GPVariant":                {"qgis": "QgsProcessingParameterString",
                                 "note": "Generic variant (bool/date/double/long/string) — review manually"},
    "GPCalculatorExpression":   {"qgis": "QgsProcessingParameterExpression",
                                 "note": "Field calculator expression"},
    "GPSQLExpression":          {"qgis": "QgsProcessingParameterExpression",
                                 "note": "SQL WHERE clause expression"},
    "GPINFOExpression":         {"qgis": "QgsProcessingParameterString",
                                 "note": "Legacy ArcInfo INFO expression"},
    "GPArcInfoItem":            {"qgis": "QgsProcessingParameterString",
                                 "note": "Legacy ArcInfo INFO item"},
    "DEArcInfoTable":           {"qgis": "QgsProcessingParameterFile",
                                 "note": "Legacy ArcInfo INFO table"},

    # ── Measurement / Units ───────────────────────────────────────────────────
    "GPLinearUnit":             {"qgis": "QgsProcessingParameterDistance",
                                 "note": "Linear unit + value (e.g. '100 Meters')"},
    "GPArealUnit":              {"qgis": "QgsProcessingParameterNumber",
                                 "note": "Areal unit + value — no direct QGIS equivalent"},
    "GPTimeUnit":               {"qgis": "QgsProcessingParameterString",
                                 "note": "Time unit + value (e.g. '30 Minutes') — no direct QGIS equivalent"},

    # ── Date / Time ───────────────────────────────────────────────────────────
    "GPDate":                   {"qgis": "QgsProcessingParameterString",
                                 "note": "Date/time value — use ISO 8601 string format"},

    # ── Coordinate Reference System ───────────────────────────────────────────
    "GPCoordinateSystem":       {"qgis": "QgsProcessingParameterCrs",
                                 "note": ""},
    "GPSpatialReference":       {"qgis": "QgsProcessingParameterCrs",
                                 "note": ""},
    "DECoordinateSystem":       {"qgis": "QgsProcessingParameterCrs",
                                 "note": ""},

    # ── Extent / Domain ───────────────────────────────────────────────────────
    "GPExtent":                 {"qgis": "QgsProcessingParameterExtent",
                                 "note": ""},
    "GPXYDomain":               {"qgis": "QgsProcessingParameterString",
                                 "note": "XY coordinate domain (min/max x,y) — encode as string"},
    "GPZDomain":                {"qgis": "QgsProcessingParameterString",
                                 "note": "Z coordinate domain (min/max z) — encode as string"},
    "GPMDomain":                {"qgis": "QgsProcessingParameterString",
                                 "note": "M coordinate domain (min/max m) — encode as string"},

    # ── Field ─────────────────────────────────────────────────────────────────
    "Field":                    {"qgis": "QgsProcessingParameterField",
                                 "note": ""},
    "GPFieldInfo":              {"qgis": "QgsProcessingParameterField",
                                 "note": "Field info / details within a FieldMap"},
    "Index":                    {"qgis": "QgsProcessingParameterString",
                                 "note": "Dataset index — no direct QGIS equivalent"},

    # ── Geodatabase containers ────────────────────────────────────────────────
    "DEFeatureDataset":         {"qgis": "QgsProcessingParameterFile",
                                 "note": "GDB Feature Dataset container — no QGIS equivalent; use folder/file path"},
    "DEGeodatasetType":         {"qgis": "QgsProcessingParameterFile",
                                 "note": "Generic geodataset — no direct QGIS equivalent"},
    "DEGeoDataServer":          {"qgis": "QgsProcessingParameterString",
                                 "note": "ArcSDE / geodata server connection — use connection string"},
    "DERelationshipClass":      {"qgis": "QgsProcessingParameterFile",
                                 "note": "GDB relationship class — no QGIS equivalent"},
    "DEGeometricNetwork":       {"qgis": "QgsProcessingParameterFile",
                                 "note": "Geometric network — no QGIS equivalent; use vector layers"},
    "DETopology":               {"qgis": "QgsProcessingParameterFile",
                                 "note": "GDB topology dataset — no QGIS equivalent"},
    "GPTopologyLayer":          {"qgis": "QgsProcessingParameterMapLayer",
                                 "note": "Topology layer reference"},

    # ── Dataset / Generic ─────────────────────────────────────────────────────
    "DEDatasetType":            {"qgis": "QgsProcessingParameterString",
                                 "note": "Abstract dataset type — verify manually"},
    "DEType":                   {"qgis": "QgsProcessingParameterString",
                                 "note": "Generic ArcCatalog dataset — verify manually"},
    "GPType":                   {"qgis": "QgsProcessingParameterString",
                                 "note": "Any-value type — review and refine manually"},

    # ── Generic Layer ─────────────────────────────────────────────────────────
    "GPLayer":                  {"qgis": "QgsProcessingParameterMapLayer",
                                 "note": "Any map layer reference"},
    "GPCompositeLayer":         {"qgis": "QgsProcessingParameterMapLayer",
                                 "note": "Composite (group) layer reference"},
    "GPGroupLayer":             {"qgis": "QgsProcessingParameterMapLayer",
                                 "note": "Group layer — use individual child layers in QGIS"},
    "GPMapServerLayer":         {"qgis": "QgsProcessingParameterMapLayer",
                                 "note": "Map server layer — add as WMS/ArcGIS REST source in QGIS"},
    "GPInternetTiledLayer":     {"qgis": "QgsProcessingParameterMapLayer",
                                 "note": "Internet tiled layer (WMTS/TMS) — add as XYZ or WMTS in QGIS"},

    # ── Cell Size (Spatial Analyst) ───────────────────────────────────────────
    "GPSACellSize":             {"qgis": "QgsProcessingParameterNumber",
                                 "note": "Spatial Analyst cell size (analysis_cell_size keyword also accepted)"},
    "GPCellSizeXY":             {"qgis": "QgsProcessingParameterNumber",
                                 "note": "XY cell size (two values) — use two separate Number params in QGIS"},

    # ── Network Analyst ───────────────────────────────────────────────────────
    "GPNALayer":                {"qgis": "QgsProcessingParameterVectorLayer",
                                 "note": "Network Analyst layer — manual review required; use QGIS Network Analysis or pgRouting"},
    "GPNetworkDatasetLayer":    {"qgis": "QgsProcessingParameterFile",
                                 "note": "Network dataset layer — no QGIS equivalent; use file path"},
    "DENetworkDataset":         {"qgis": "QgsProcessingParameterFile",
                                 "note": "Network dataset — no QGIS equivalent; use file path"},
    "NAClassFieldMap":          {"qgis": "QgsProcessingParameterString",
                                 "note": "Network Analyst class field map — no QGIS equivalent"},
    "GPNAHierarchySettings":    {"qgis": "QgsProcessingParameterString",
                                 "note": "Network hierarchy settings — no QGIS equivalent"},

    # ── Geocoding ─────────────────────────────────────────────────────────────
    "DEAddressLocator":         {"qgis": "QgsProcessingParameterFile",
                                 "note": "ArcGIS address locator — use file path; consider QGIS geocoding plugins"},
    "GPAddressLocatorStyle":    {"qgis": "QgsProcessingParameterFile",
                                 "note": "Address locator style template — use file path"},

    # ── TIN / Terrain / 3D ────────────────────────────────────────────────────
    "DETin":                    {"qgis": "QgsProcessingParameterFile",
                                 "note": "TIN dataset — no native QGIS equivalent; convert to raster DEM"},
    "GPTinLayer":               {"qgis": "QgsProcessingParameterFile",
                                 "note": "TIN layer reference — no native QGIS equivalent"},
    "GPTerrainLayer":           {"qgis": "QgsProcessingParameterFile",
                                 "note": "Terrain layer (mosaic of TINs) — no QGIS equivalent"},
    "GP3DADecimate":            {"qgis": "QgsProcessingParameterString",
                                 "note": "3D Analyst decimate settings — no QGIS equivalent"},

    # ── LiDAR / LAS ───────────────────────────────────────────────────────────
    "DELasDataset":             {"qgis": "QgsProcessingParameterFile",
                                 "note": "LAS dataset (.lasd) — use individual .las/.laz files in QGIS"},
    "GPLasDatasetLayer":        {"qgis": "QgsProcessingParameterFile",
                                 "note": "LAS dataset layer reference"},

    # ── Spatial Analyst parameters ────────────────────────────────────────────
    "GPSANeighborhood":         {"qgis": "QgsProcessingParameterString",
                                 "note": "Spatial Analyst neighborhood shape — encode as string"},
    "GPSARadius":               {"qgis": "QgsProcessingParameterNumber",
                                 "note": "Search radius for interpolation"},
    "GPSARemap":                {"qgis": "QgsProcessingParameterString",
                                 "note": "Raster reclassification remap table — encode as string or file"},
    "GPEvaluationScale":        {"qgis": "QgsProcessingParameterNumber",
                                 "note": "Weighted overlay evaluation scale range"},
    "GPSAExtractValues":        {"qgis": "QgsProcessingParameterString",
                                 "note": "Extract values parameter — encode as string"},
    "GPSAFuzzyFunction":        {"qgis": "QgsProcessingParameterString",
                                 "note": "Fuzzy membership function — encode as string"},
    "GPSAHorizontalFactor":     {"qgis": "QgsProcessingParameterString",
                                 "note": "Horizontal cost factor — encode as string"},
    "GPSAVerticalFactor":       {"qgis": "QgsProcessingParameterString",
                                 "note": "Vertical cost factor — encode as string"},
    "GPSASemiVariogram":        {"qgis": "QgsProcessingParameterString",
                                 "note": "Semivariogram parameters — encode as string"},
    "GPSATimeConfiguration":    {"qgis": "QgsProcessingParameterString",
                                 "note": "Solar radiation time configuration — encode as string"},
    "GPSATopoFeatures":         {"qgis": "QgsProcessingParameterFeatureSource",
                                 "note": "Topo-to-raster input features"},
    "GPSAWeightedOverlayTable": {"qgis": "QgsProcessingParameterMatrix",
                                 "note": "Weighted overlay input table"},
    "GPSAWeightedSum":          {"qgis": "QgsProcessingParameterString",
                                 "note": "Weighted sum specification — encode as string"},
    "GPSATransformationFunction": {"qgis": "QgsProcessingParameterString",
                                 "note": "Transformation function specification — encode as string"},
    "GPRandomNumberGenerator":  {"qgis": "QgsProcessingParameterString",
                                 "note": "RNG seed and type — encode as string"},
    # GDB env settings (rarely exposed as user params but can appear in ModelBuilder)
    "GPSAGDBEnvCompression":    {"qgis": "QgsProcessingParameterString",
                                 "note": "GDB raster compression type — encode as string"},
    "GPSAGDBEnvPyramid":        {"qgis": "QgsProcessingParameterString",
                                 "note": "GDB pyramid build setting — encode as string"},
    "GPSAGDBEnvStatistics":     {"qgis": "QgsProcessingParameterString",
                                 "note": "GDB statistics build setting — encode as string"},
    "GPSAGDBEnvTileSize":       {"qgis": "QgsProcessingParameterString",
                                 "note": "GDB tile size — encode as string"},

    # ── Geostatistical Analyst ────────────────────────────────────────────────
    "GPGALayer":                {"qgis": "QgsProcessingParameterMapLayer",
                                 "note": "Geostatistical layer — no direct QGIS equivalent; review manually"},
    "GPGASearchNeighborhood":   {"qgis": "QgsProcessingParameterString",
                                 "note": "Geostatistical search neighbourhood — encode as string"},
    "GPGAValueTable":           {"qgis": "QgsProcessingParameterMatrix",
                                 "note": "Geostatistical value table"},

    # ── Image / Web Services ──────────────────────────────────────────────────
    "DEImageServer":            {"qgis": "QgsProcessingParameterString",
                                 "note": "ArcGIS Image Service URL — add as WMS/WMTS/ArcGIS REST in QGIS"},
    "DEMapServer":              {"qgis": "QgsProcessingParameterString",
                                 "note": "ArcGIS Map Service URL — add as WMS/ArcGIS REST in QGIS"},
    "DEWCSCoverage":            {"qgis": "QgsProcessingParameterString",
                                 "note": "WCS coverage — add as WCS layer in QGIS"},
    "DEWMSMap":                 {"qgis": "QgsProcessingParameterString",
                                 "note": "WMS map — add as WMS layer in QGIS"},
    "GPGlobeServer":            {"qgis": "QgsProcessingParameterString",
                                 "note": "ArcGlobe server — no QGIS equivalent"},
    "DEGlobeServer":            {"qgis": "QgsProcessingParameterString",
                                 "note": "ArcGlobe server — no QGIS equivalent"},
    "DEGPServer":               {"qgis": "QgsProcessingParameterString",
                                 "note": "ArcGIS Geoprocessing server URL"},
    "DEServerConnection":       {"qgis": "QgsProcessingParameterString",
                                 "note": "ArcGIS server connection — encode as URL/connection string"},

    # ── Graph ─────────────────────────────────────────────────────────────────
    "GPGraph":                  {"qgis": "QgsProcessingParameterFile",
                                 "note": "ArcGIS graph object — no QGIS equivalent"},
    "GPGraphDataTable":         {"qgis": "QgsProcessingParameterString",
                                 "note": "Graph data table — no QGIS equivalent"},

    # ── Schematic ─────────────────────────────────────────────────────────────
    "DESchematicDataset":       {"qgis": "QgsProcessingParameterFile",
                                 "note": "Schematic dataset — no QGIS equivalent"},
    "DESchematicDiagram":       {"qgis": "QgsProcessingParameterFile",
                                 "note": "Schematic diagram — no QGIS equivalent"},
    "DESchematicDiagramClass":  {"qgis": "QgsProcessingParameterFile",
                                 "note": "Schematic diagram class — no QGIS equivalent"},
    "DESchematicFolder":        {"qgis": "QgsProcessingParameterFolderDestination",
                                 "note": "Schematic folder"},
    "GPSchematicLayer":         {"qgis": "QgsProcessingParameterMapLayer",
                                 "note": "Schematic layer — no QGIS equivalent"},

    # ── Parcel / Cadastral ────────────────────────────────────────────────────
    "DECadastralFabric":        {"qgis": "QgsProcessingParameterFile",
                                 "note": "Parcel fabric dataset — no QGIS equivalent"},
    "GPCadastralFabricLayer":   {"qgis": "QgsProcessingParameterMapLayer",
                                 "note": "Parcel fabric layer — no QGIS equivalent"},

    # ── VPF (legacy military format) ──────────────────────────────────────────
    "DEVPFCoverage":            {"qgis": "QgsProcessingParameterFile",
                                 "note": "Vector Product Format coverage — convert to GeoPackage/shapefile"},
    "DEVPFTable":               {"qgis": "QgsProcessingParameterFile",
                                 "note": "Vector Product Format table"},

    # ── Route / Linear Reference ──────────────────────────────────────────────
    "GPRouteMeasureEventProperties": {"qgis": "QgsProcessingParameterString",
                                 "note": "Route measure event properties — encode as string; use QGIS geometry-M"},

    # ── Tool / Toolbox references ─────────────────────────────────────────────
    "DETool":                   {"qgis": "QgsProcessingParameterString",
                                 "note": "ArcGIS tool reference — no QGIS equivalent"},
    "DEToolbox":                {"qgis": "QgsProcessingParameterFile",
                                 "note": "ArcGIS toolbox file — no QGIS equivalent"},
}


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class TbxParameter:
    index:          int
    internal_name:  str
    display_name:   str
    gp_class:       str         # ArcGIS GP data type class name
    dt_display:     str         # human-readable type label
    direction:      str         # "Input" | "Output"
    qgis_type:      str = ""    # mapped QGIS class
    qgis_note:      str = ""    # migration note

    def __post_init__(self):
        mapping = GP_TYPE_MAP.get(self.gp_class, {})
        if self.direction == "Output" and "qgis_output" in mapping:
            self.qgis_type = mapping["qgis_output"]
        else:
            self.qgis_type = mapping.get("qgis", f"⚠ UNMAPPED:{self.gp_class}")
        self.qgis_note = mapping.get("note", "")


@dataclass
class TbxTool:
    index:          int
    internal_name:  str
    display_name:   str
    description:    str
    script_path:    str
    tool_type:      int         # 1=Model, 3=Script (unverified)
    parameters:     list[TbxParameter] = field(default_factory=list)


@dataclass
class TbxToolbox:
    path:           pathlib.Path
    name:           str
    alias:          str
    tools:          list[TbxTool] = field(default_factory=list)


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _read_wstr(data: bytes, offset: int) -> tuple[str, int]:
    """Read one 4-byte char-count-prefixed UTF-16-LE string + null terminator.

    Args:
        data:   raw stream bytes
        offset: byte offset of the 4-byte char-count prefix

    Returns:
        (decoded_string, next_offset)

    Raises:
        ValueError: if char_count > 10000 (indicates misalignment / parsing error)
    """
    n = struct.unpack_from("<I", data, offset)[0]
    if n > 10_000:
        raise ValueError(f"char_count={n} at 0x{offset:06x} — likely misaligned")
    start = offset + 4
    raw = data[start : start + n * 2]
    text = raw.decode("utf-16-le", errors="replace")
    return text, start + n * 2 + 2  # skip 2-byte null terminator


def _find_all(data: bytes, needle: bytes) -> list[int]:
    positions, pos = [], 0
    while True:
        idx = data.find(needle, pos)
        if idx == -1:
            break
        positions.append(idx)
        pos = idx + 1
    return positions


def _scan_for_gp_type(data: bytes, start: int, window: int = 128) -> int | None:
    """Scan forward from *start* for a UTF-16-LE WSTR whose text matches a GP/DE
    type class name (e.g. 'GPFeatureLayer', 'DEFeatureClass').

    Returns the byte offset of the 4-byte char-count prefix on success,
    or None if not found within *window* bytes.

    Used to bridge the variable-length filter/domain blocks that appear between
    the direction/GUID/flags metadata and the gp_datatype_class WSTR for
    Input-direction parameters.
    """
    _GP_PAT = re.compile(r"^(GP|DE)[A-Z][A-Za-z]+$")
    for off in range(start, min(start + window, len(data) - 4), 2):
        try:
            n = struct.unpack_from("<I", data, off)[0]
            if 2 <= n <= 50:
                raw = data[off + 4 : off + 4 + n * 2]
                if len(raw) == n * 2:
                    s = raw.decode("utf-16-le", errors="strict")
                    if _GP_PAT.match(s):
                        return off
        except (struct.error, UnicodeDecodeError):
            pass
    return None


# ── Stream parsers ─────────────────────────────────────────────────────────────

def _parse_version_stream(data: bytes) -> str:
    """Extract toolbox name from the Version stream.

    Layout:
        0x00-0x0d : 14 header bytes (version codes + padding)
        0x0e-0x11 : uint32-LE char_count
        0x12+     : UTF-16-LE toolbox name
    """
    name, _ = _read_wstr(data, 0x0E)
    return name


def _parse_contents_alias(data: bytes) -> str:
    """Extract the toolbox alias from the Contents stream (first WSTR at offset 0)."""
    try:
        alias, _ = _read_wstr(data, 0)
        return alias
    except ValueError:
        return ""


def _parse_tool_stream(stream_index: int, data: bytes) -> TbxTool:
    """Parse a Tool<N> OLE stream and return a TbxTool.

    Known layout (confirmed against 6 corpus toolboxes):
      offset 0x00 : uint32 tool_type
      offset 0x04 : uint16 flags_a
      offset 0x06 : uint16 flags_b
      offset 0x08 : WSTR  internal_name
      after       : WSTR  display_name
      after       : WSTR  description
      +16 bytes   : binary (help URL placeholder, tags — mostly zeros)
      WSTR        : script_path
      uint32      : param_count
      [per param, located by PARAM_MARKER_GUID scan]
    """
    tool_type = struct.unpack_from("<I", data, 0)[0]

    off = 0x08
    try:
        internal_name, off = _read_wstr(data, off)
        display_name, off  = _read_wstr(data, off)
        description, off   = _read_wstr(data, off)
    except ValueError as exc:
        raise ValueError(f"Tool{stream_index}: header WSTRs failed — {exc}") from exc

    # Skip 16 binary bytes (empirically observed between description and script_path)
    off += 16

    try:
        script_path, off = _read_wstr(data, off)
    except ValueError:
        script_path = ""

    # param_count is the uint32 right after script_path null terminator
    try:
        # Try to read param_count; value ~0-50 is sane
        pc_candidate = struct.unpack_from("<I", data, off)[0]
        param_count = pc_candidate if pc_candidate <= 200 else 0
    except struct.error:
        param_count = 0

    # Parse parameters by scanning for PARAM_MARKER_GUID
    parameters = _parse_parameters(data)

    return TbxTool(
        index=stream_index,
        internal_name=internal_name,
        display_name=display_name,
        description=description,
        script_path=script_path,
        tool_type=tool_type,
        parameters=parameters,
    )


def _parse_parameters(data: bytes) -> list[TbxParameter]:
    """Locate and parse all parameter blocks in a Tool stream.

    Each parameter block is located by PARAM_MARKER_GUID (16 bytes).
    After the GUID + 2 control bytes:
      WSTR  internal_name
      WSTR  display_name
      24-byte binary block:
        uint32   direction   (0=Input, 1=Output)
        16 bytes param-type GUID
        4 bytes  flags
      WSTR  gp_datatype_class
      WSTR  dt_display_1
      WSTR  dt_display_2
      WSTR  "Data Type"  (literal sentinel)

    Returns:
        list of TbxParameter objects
    """
    guid_positions = _find_all(data, PARAM_MARKER_GUID)
    results = []

    for idx, gp in enumerate(guid_positions):
        off = gp + 16 + 2  # skip GUID + 0x07 0x00

        try:
            iname, off = _read_wstr(data, off)
            dname, off = _read_wstr(data, off)

            # 24-byte metadata block: direction uint32 + 16-byte GUID + 4 bytes
            direction_int = struct.unpack_from("<I", data, off)[0]
            direction = "Input" if direction_int == 0 else "Output"
            off += 24  # skip direction(4) + type-GUID(16) + flags(4)

            # Input params have an additional filter/domain block (typically
            # 22 bytes: 2-byte pad + 16-byte filter GUID + 4-byte flags).
            # Rather than hard-coding the size, scan forward for the first
            # GP/DE type WSTR to locate gp_class reliably.
            gp_cls_off = _scan_for_gp_type(data, off, window=128)
            if gp_cls_off is not None:
                off = gp_cls_off

            gp_cls, off   = _read_wstr(data, off)
            dt_disp1, off = _read_wstr(data, off)
            _,        off = _read_wstr(data, off)  # dt_display_2 (duplicate)
            _,        off = _read_wstr(data, off)  # "Data Type" sentinel

        except (ValueError, struct.error) as exc:
            # Non-fatal: append a placeholder with error note
            results.append(TbxParameter(
                index=idx,
                internal_name=f"__parse_error_{idx}__",
                display_name=str(exc),
                gp_class="",
                dt_display="",
                direction="Input",
            ))
            continue

        results.append(TbxParameter(
            index=idx,
            internal_name=iname,
            display_name=dname,
            gp_class=gp_cls,
            dt_display=dt_disp1,
            direction=direction,
        ))

    return results


# ── Public API ────────────────────────────────────────────────────────────────

def parse_tbx(path: str | pathlib.Path) -> TbxToolbox:
    """Parse a binary OLE .tbx file and return a TbxToolbox object.

    Args:
        path: path to the .tbx file (ArcGIS Desktop / ArcMap OLE format).
              Raises ValueError if the file is not a valid OLE compound file.

    Returns:
        TbxToolbox with name, alias, and a list of TbxTool objects (each
        containing TbxParameter objects with QGIS type mappings).

    Raises:
        ValueError: if the file is not a binary OLE .tbx (e.g. Pro XML format
                    — those files have no OLE magic bytes).
        olefile.NotOleFileError: if the OLE container is structurally invalid.
    """
    path = pathlib.Path(path)

    # Magic byte check
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic != b"\xD0\xCF\x11\xE0":
        raise ValueError(
            f"{path.name!r} is not a binary OLE .tbx "
            f"(magic={magic.hex()!r}). "
            "ArcGIS Pro .tbx files also use OLE format; check version stream."
        )

    with olefile.OleFileIO(str(path)) as ole:
        stream_names = ["/".join(e) for e in ole.listdir(streams=True)]

        # Version stream → toolbox name
        try:
            ver_data = ole.openstream(["Version"]).read()
            tb_name = _parse_version_stream(ver_data)
        except Exception:
            tb_name = path.stem

        # Contents stream → alias
        try:
            cont_data = ole.openstream(["Contents"]).read()
            alias = _parse_contents_alias(cont_data)
        except Exception:
            alias = ""

        # Tool streams (Tool0, Tool1, …)
        tools = []
        tool_idx = 0
        while f"Tool{tool_idx}" in stream_names:
            tool_data = ole.openstream([f"Tool{tool_idx}"]).read()
            tool = _parse_tool_stream(tool_idx, tool_data)
            tools.append(tool)
            tool_idx += 1

    return TbxToolbox(path=path, name=tb_name, alias=alias, tools=tools)


# ── CLI / pretty-print ────────────────────────────────────────────────────────

def _summarise(tbx: TbxToolbox) -> None:
    print(f"\nToolbox : {tbx.name!r}")
    print(f"Alias   : {tbx.alias!r}")
    print(f"Path    : {tbx.path}")
    print(f"Tools   : {len(tbx.tools)}")
    for tool in tbx.tools:
        print(f"\n  [{tool.index}] {tool.internal_name!r}  ({tool.display_name!r})")
        print(f"       type={tool.tool_type}  script={tool.script_path!r}")
        print(f"       params ({len(tool.parameters)}):")
        for p in tool.parameters:
            arrow = "→" if p.direction == "Output" else "←"
            warn = " ⚠" if p.qgis_type.startswith("⚠") else ""
            print(f"         {arrow} {p.internal_name:<35} {p.gp_class:<30} → {p.qgis_type}{warn}")


if __name__ == "__main__":
    import sys

    paths = sys.argv[1:] or [
        r"D:\01_dev\a-Arc2Qgis\arcgis-tools\GAFY09 Toolbox v2.tbx",
        r"D:\01_dev\a-Arc2Qgis\research\corpus\sun_position_arcmap.tbx",
        r"D:\01_dev\a-Arc2Qgis\research\corpus\geonames_arcmap.tbx",
    ]
    for p in paths:
        try:
            tbx = parse_tbx(p)
            _summarise(tbx)
        except Exception as exc:
            print(f"\n[ERROR] {p}: {exc}")
