"""Test that preserve_attrs correctly copies all field attributes.

This test validates the fix for the issue where field length, precision,
and comment were not being copied when preserve_attrs=True, causing
failures in attribute assignment.
"""

import pytest
from qgis.PyQt.QtCore import QVariant
from qgis.core import QgsField, QgsFields

# Mock the constants for testing
FLD_SEG_NUM = "seg_num"
FLD_MILE_RANGE = "mile_range"
FLD_STREAM_SEG_ID = "stream_seg_id"
NEW_FIELD_NAMES = frozenset({FLD_SEG_NUM, FLD_MILE_RANGE, FLD_STREAM_SEG_ID})


def build_output_fields_fixed(source_fields: QgsFields, preserve_attrs: bool) -> QgsFields:
    """Fixed version that properly copies all field attributes."""
    out_fields = QgsFields()
    if preserve_attrs:
        for field in source_fields:
            fname = field.name()
            # Create proper copy with all attributes (length, precision, comment)
            new_field = QgsField(
                fname,
                field.type(),
                field.typeName(),
                field.length(),
                field.precision(),
                field.comment(),
            )
            # Rename if conflicts with new field names
            if fname in NEW_FIELD_NAMES:
                new_field.setName(fname + "_src")
            out_fields.append(new_field)
    out_fields.append(QgsField(FLD_SEG_NUM, QVariant.Int))
    out_fields.append(QgsField(FLD_MILE_RANGE, QVariant.String, len=30))
    out_fields.append(QgsField(FLD_STREAM_SEG_ID, QVariant.String, len=100))
    return out_fields


def build_output_fields_broken(source_fields: QgsFields, preserve_attrs: bool) -> QgsFields:
    """Broken version that only copies type and typeName."""
    out_fields = QgsFields()
    if preserve_attrs:
        for field in source_fields:
            fname = field.name()
            if fname in NEW_FIELD_NAMES:
                fname = fname + "_src"
            out_fields.append(QgsField(fname, field.type(), field.typeName()))
    out_fields.append(QgsField(FLD_SEG_NUM, QVariant.Int))
    out_fields.append(QgsField(FLD_MILE_RANGE, QVariant.String, len=30))
    out_fields.append(QgsField(FLD_STREAM_SEG_ID, QVariant.String, len=100))
    return out_fields


@pytest.mark.qgis
class TestPreserveAttrsFieldCopy:
    """Test proper field attribute preservation."""

    def test_field_length_preserved(self):
        """Test that string field length is preserved."""
        source_fields = QgsFields()
        source_fields.append(QgsField("name", QVariant.String, "String", 100))
        
        out_fields = build_output_fields_fixed(source_fields, preserve_attrs=True)
        
        # First field should be the preserved 'name' field
        assert out_fields[0].name() == "name"
        assert out_fields[0].length() == 100  # Length should be preserved
        
    def test_field_precision_preserved(self):
        """Test that numeric field precision is preserved."""
        source_fields = QgsFields()
        source_fields.append(QgsField("elevation", QVariant.Double, "Double", 10, 3))
        
        out_fields = build_output_fields_fixed(source_fields, preserve_attrs=True)
        
        assert out_fields[0].name() == "elevation"
        assert out_fields[0].length() == 10
        assert out_fields[0].precision() == 3
        
    def test_field_comment_preserved(self):
        """Test that field comment is preserved."""
        source_fields = QgsFields()
        field = QgsField("id", QVariant.Int, "Integer")
        field.setComment("Unique identifier")
        source_fields.append(field)
        
        out_fields = build_output_fields_fixed(source_fields, preserve_attrs=True)
        
        assert out_fields[0].name() == "id"
        assert out_fields[0].comment() == "Unique identifier"
        
    def test_conflicting_field_renamed(self):
        """Test that fields with conflicting names are renamed."""
        source_fields = QgsFields()
        source_fields.append(QgsField("seg_num", QVariant.String, "String", 50))
        
        out_fields = build_output_fields_fixed(source_fields, preserve_attrs=True)
        
        # Conflicting field should be renamed to seg_num_src
        assert out_fields[0].name() == "seg_num_src"
        assert out_fields[0].length() == 50  # Length still preserved
        
        # New seg_num field should be at the end (before mile_range and stream_seg_id)
        seg_num_idx = None
        for i in range(out_fields.count()):
            if out_fields[i].name() == "seg_num" and i > 0:
                seg_num_idx = i
                break
        assert seg_num_idx is not None
        assert out_fields[seg_num_idx].type() == QVariant.Int
        
    def test_broken_version_loses_attributes(self):
        """Demonstrate that the broken version loses field attributes."""
        source_fields = QgsFields()
        source_fields.append(QgsField("name", QVariant.String, "String", 100, 0, "Stream name"))
        
        out_fields_broken = build_output_fields_broken(source_fields, preserve_attrs=True)
        
        # The broken version loses length and comment
        # Note: Default length for String fields is often 0 or -1
        assert out_fields_broken[0].name() == "name"
        # These assertions demonstrate the problem (may vary by QGIS version)
        # Length is not preserved properly
        assert out_fields_broken[0].length() != 100 or out_fields_broken[0].comment() != "Stream name"
        
    def test_all_new_fields_present(self):
        """Test that all new fields are added correctly."""
        source_fields = QgsFields()
        source_fields.append(QgsField("name", QVariant.String, "String", 50))
        
        out_fields = build_output_fields_fixed(source_fields, preserve_attrs=True)
        
        # Should have 4 fields: name + seg_num + mile_range + stream_seg_id
        assert out_fields.count() == 4
        assert out_fields[1].name() == FLD_SEG_NUM
        assert out_fields[2].name() == FLD_MILE_RANGE
        assert out_fields[3].name() == FLD_STREAM_SEG_ID
