# Stream Segmenter: Preserve Attributes Fix

## Issue Summary

The stream segmenter logic was breaking when `PRESERVE_ATTRS` was enabled because field definitions were being copied incompletely from source layers to output layers.

## Root Cause

When `preserve_attrs=True`, the algorithm copies source fields to the output schema. The original implementation only copied three field attributes:

```python
# ❌ BROKEN CODE
out_fields.append(
    QgsField(fname, field.type(), field.typeName())
)
```

This creates an **incomplete field definition** that is missing:
- `length` - Maximum width for strings, accuracy for numbers
- `precision` - Decimal places for numeric fields  
- `comment` - Field documentation/metadata

## Why It Breaks

QGIS uses these field attributes for validation and storage:

1. **String Truncation**: Without the correct `length`, long string values get truncated to default width (often 0 or -1)
2. **Type Mismatches**: Numeric fields without proper `precision` may reject valid values
3. **Silent Failures**: `setAttributes()` may fail silently when values don't meet field constraints
4. **Data Loss**: Field comments and metadata are lost

## The Fix

All four algorithm files were updated to properly copy ALL field attributes:

### Files Fixed:
1. `stream_segmenter_algorithm.py` (lines 382-398)
2. `batch_stream_segmenter_algorithm.py` (lines 254-277)
3. `stream_order_algorithm.py` (lines 275-292)
4. `batch_stream_order_algorithm.py` (lines 410-427)

### New Implementation:

```python
# ✅ FIXED CODE
for field in source.fields():
    fname = field.name()
    # Create proper copy with all attributes
    new_field = QgsField(
        fname,
        field.type(),
        field.typeName(),
        field.length(),      # ← Added
        field.precision(),   # ← Added
        field.comment(),     # ← Added
    )
    # Rename if conflicts with new field names
    if fname in NEW_FIELD_NAMES:
        new_field.setName(fname + "_src")
    out_fields.append(new_field)
```

## Benefits

✅ **Complete field preservation** - All attributes copied correctly  
✅ **No data truncation** - String fields retain their full width  
✅ **Metadata preserved** - Field comments and documentation maintained  
✅ **Reliable attribute assignment** - `setAttributes()` no longer fails  
✅ **Better field naming** - Conflicts handled after field creation using `setName()`

## Testing

A comprehensive test suite was added in `tests/test_preserve_attrs_fix.py` that validates:
- Field length preservation
- Field precision preservation  
- Field comment preservation
- Conflict field renaming
- All new fields correctly added

## Additional Notes

### Why Not Use the Copy Constructor?

QGIS provides `QgsField(field)` copy constructor, but we need to conditionally rename fields that conflict with new field names. The approach taken:

1. Creates a complete copy with all attributes
2. Conditionally renames using `setName()` only when needed
3. Maintains clarity about which attributes are being preserved

This is more explicit than:
```python
new_field = QgsField(field)  # Copy constructor
if fname in NEW_FIELD_NAMES:
    new_field.setName(fname + "_src")
```

Both approaches work, but the explicit parameter passing makes it clear what's being preserved.

## Related Issues

This same pattern should be checked in any QGIS Processing algorithm that:
- Copies fields from source to output with `preserve_attrs` option
- Modifies field schemas dynamically
- Uses `setAttributes()` for bulk attribute assignment

## Version Info

- **Fixed Date**: 2026-03-30
- **QGIS Compatibility**: 3.0+
- **Affected Algorithms**: Stream Segmenter, Batch Stream Segmenter, Stream Order, Batch Stream Order
