# FieldCalculatorTools.pyt
#
# Hand-crafted example demonstrating the Python Toolbox (.pyt) format.
# This file is intentionally authored with:
#   - Python 2.7-era patterns (print statement, .iteritems(), basestring)
#     to exercise the Phase 0.2 Python 2.7 Scanner
#   - Row-wise arcpy.da.UpdateCursor loop to exercise the
#     Phase 4 Vectorization Mandate (must become geopandas column ops)
#   - Advanced-license dependency (arcpy.management.CalculateGeometryAttributes)
#
# Suitable for: QgisPortAgent migration demo / unit testing
# Source: Synthetic example — not tied to any ArcGIS installation

import arcpy


class Toolbox(object):
    def __init__(self):
        self.label = "Field Calculator Tools"
        self.alias = "fieldcalctools"
        self.tools = [AddAreaField, NormalizeField]


# ---------------------------------------------------------------------------
# Tool 1 — AddAreaField
# Computes the planar area of each polygon feature and writes it to a new
# numeric field.  Demonstrates:
#   - GPFeatureLayer input (Advanced license: CalculateGeometryAttributes)
#   - GPString optional field-name parameter with default value
#   - row-wise UpdateCursor (deliberately archaic — for vectorisation demo)
# ---------------------------------------------------------------------------
class AddAreaField(object):

    def __init__(self):
        self.label = "Add Area Field"
        self.description = (
            "Adds a DOUBLE field containing the planar polygon area "
            "in the native coordinate-reference-system units."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        in_fc = arcpy.Parameter(
            displayName="Input Feature Class",
            name="in_feature_class",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )

        field_name = arcpy.Parameter(
            displayName="Area Field Name",
            name="field_name",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        field_name.value = "AREA_CALC"

        out_fc = arcpy.Parameter(
            displayName="Output Feature Class",
            name="out_feature_class",
            datatype="DEFeatureClass",
            parameterType="Derived",
            direction="Output",
        )
        out_fc.parameterDependencies = [in_fc.name]
        out_fc.schema.clone = True

        return [in_fc, field_name, out_fc]

    def isLicensed(self):
        try:
            if arcpy.CheckExtension("Spatial") == "Available":
                return True
        except Exception:
            return False
        return False

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        in_fc = parameters[0].valueAsText
        field_name = parameters[1].valueAsText or "AREA_CALC"

        # Python 2 print statement — triggers Phase 0.2 scanner
        print "Adding field: " + field_name

        # Add the area field if it does not already exist
        existing_fields = [f.name for f in arcpy.ListFields(in_fc)]
        if field_name not in existing_fields:
            arcpy.management.AddField(in_fc, field_name, "DOUBLE")

        # Row-wise cursor — deliberately row-by-row for vectorisation demo.
        # QgisPortAgent must rewrite this as a geopandas column operation.
        with arcpy.da.UpdateCursor(in_fc, ["SHAPE@AREA", field_name]) as cursor:
            for row in cursor:
                row[1] = row[0]
                cursor.updateRow(row)

        arcpy.AddMessage("Area field populated for all rows.")


# ---------------------------------------------------------------------------
# Tool 2 — NormalizeField
# Normalises a numeric field to the 0–1 range (min-max scaling).
# Demonstrates:
#   - Python 2.7 .iteritems() usage
#   - basestring type check
#   - Two-pass row-wise cursor (find min/max, then update)
# ---------------------------------------------------------------------------
class NormalizeField(object):

    def __init__(self):
        self.label = "Normalize Field"
        self.description = (
            "Rescales the values in a numeric field to the [0, 1] range "
            "using min-max normalisation."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        in_fc = arcpy.Parameter(
            displayName="Input Feature Class",
            name="in_feature_class",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )

        src_field = arcpy.Parameter(
            displayName="Source Field",
            name="source_field",
            datatype="Field",
            parameterType="Required",
            direction="Input",
        )
        src_field.parameterDependencies = [in_fc.name]

        out_field = arcpy.Parameter(
            displayName="Output Normalised Field Name",
            name="out_field",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        out_field.value = "NORM_VALUE"

        return [in_fc, src_field, out_field]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        # Python 2.7-era basestring check — triggers Phase 0.2 scanner
        if parameters[2].value:
            if not isinstance(parameters[2].valueAsText, basestring):
                parameters[2].setErrorMessage("Field name must be a string.")
        return

    def execute(self, parameters, messages):
        in_fc = parameters[0].valueAsText
        src_field = parameters[1].valueAsText
        out_field = parameters[2].valueAsText or "NORM_VALUE"

        # Python 2-style dict iteration — triggers Phase 0.2 scanner
        meta = {"tool": "NormalizeField", "src": src_field, "out": out_field}
        for k, v in meta.iteritems():
            arcpy.AddMessage("{0}: {1}".format(k, v))

        # First pass: collect min and max
        values = []
        with arcpy.da.SearchCursor(in_fc, [src_field]) as cursor:
            for row in cursor:
                if row[0] is not None:
                    values.append(row[0])

        if not values:
            arcpy.AddWarning("No non-null values found; skipping.")
            return

        vmin = min(values)
        vmax = max(values)
        span = vmax - vmin

        # Add output field
        existing = [f.name for f in arcpy.ListFields(in_fc)]
        if out_field not in existing:
            arcpy.management.AddField(in_fc, out_field, "DOUBLE")

        # Second pass: write normalised values row-by-row
        # QgisPortAgent must rewrite as: gdf[out_field] = (gdf[src] - vmin) / span
        with arcpy.da.UpdateCursor(in_fc, [src_field, out_field]) as cursor:
            for row in cursor:
                if row[0] is not None and span > 0:
                    row[1] = (row[0] - vmin) / span
                else:
                    row[1] = 0.0
                cursor.updateRow(row)

        arcpy.AddMessage("Normalisation complete.")
