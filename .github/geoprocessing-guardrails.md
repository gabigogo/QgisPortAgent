# Shared Geoprocessing Guardrails

This is the repository mirror of the authoritative guardrail policy in:

- [Authoritative Instructions](../.vscode/geoprocessing_guardrails.instructions.md)

Use this document for review and collaboration. Keep it synchronized with the authoritative
instruction file.

## 1) Distance and Unit Normalization (Mandatory)

1. Use meters as the computational base unit for all threshold and segmentation math.
2. Convert to miles, kilometers, or feet only for display fields and user-facing labels.
3. When measuring with QgsDistanceArea.measureLength(), branch on willUseEllipsoid():
   - True: measurement values are meters.
   - False: values are CRS-native units and must be converted to meters before computation.
4. Use QGIS unit conversion APIs for linear unit conversion:
   - QgsUnitTypes.fromUnitToUnitFactor(...)
   - Equivalent QGIS conversion helpers where appropriate.
5. Never assume all feet are international feet.
   Explicitly support US survey units through QGIS unit enums.

## 2) CRS and Transformation Safety

1. Never treat degree values as linear distance.
2. For geographic CRS workflows, use ellipsoidal measurement or reproject to an appropriate projected CRS before Euclidean length math.
3. If an algorithm accepts distance parameters and supports arbitrary CRS, include explicit conversion logic and clear warnings when unit assumptions are ambiguous.
4. Document the computational CRS/unit assumptions in algorithm help text and user docs.

## 3) Geometry and Topology Integrity

1. Validate null, empty, and invalid geometries before processing.
2. For multipart line workflows, state topology assumptions explicitly (for example connected chain requirement).
3. When topology assumptions fail, emit actionable warnings/errors that identify the failing feature context.
4. Avoid silent geometry drops; use non-fatal skip behavior only when clearly logged.

## 4) Output Schema and Identifier Safety

1. Never preserve a literal output fid attribute into destination writers where the sink manages primary keys.
2. Preserve source identity with src_fid-style fields when lineage is needed.
3. Guard against field name collisions and ensure deterministic rename behavior.
4. Validate attribute count and assignment success before addFeature operations.

## 5) Processing Robustness and Diagnostics

1. Add cancellation checks in long-running feature loops.
2. Report progress and state transitions through feedback channels.
3. Prefer non-fatal per-feature error handling when safe, with explicit diagnostics (feature id, segment/order id, and failure reason).
4. Never increment success counters unless write/insert operations succeed.

## 6) Performance and Scale

1. Avoid row-wise transliteration of cursor-style logic when vectorized or native processing alternatives exist.
2. Prefer native QGIS Processing algorithms for standard geospatial operations.
3. Use vectorized geopandas/pyogrio workflows and spatial indexing where dataset scale warrants it.
4. For repeated spatial lookups, use indexes and avoid O(n^2) feature scans.

## 7) Reproducibility and QA

1. Use deterministic ordering when output identity depends on iteration order.
2. Add regression tests for:
   - projected meter CRS,
   - projected US survey foot CRS,
   - geographic CRS.
3. For distance-based outputs, include spot checks comparing geometry-derived physical lengths against expected thresholds/labels.
4. Treat systematic drift between labels and physical lengths as a blocker until unit handling is corrected.

## 8) MCP Geoprocessing Execution Checklist

When executing geoprocessing through MCP, run this checklist:

1. Preflight:
   - ping
   - get_qgis_info
2. Inspect algorithm schema with get_processing_algorithms(...) before execution.
3. Inspect layer CRS/fields with get_layers() and get_layer_fields() before trusting unit-dependent results.
4. Execute processing with explicit, fully-resolved parameters.
5. Validate outputs after execution:
   - output layer exists,
   - feature count is plausible,
   - sample geometry lengths align with expected labels/thresholds.
6. If mismatch is systematic, suspect CRS-native-to-meter conversion handling first.

## 9) Migration-Specific QA Guardrails

1. Preserve strict single-file scope unless the user explicitly expands scope.
2. Emit confidence and caveat reporting for migrated blocks.
3. When source parsing is incomplete, use explicit fallback guidance instead of implied logic reconstruction.
4. For migrated distance-sensitive tools, include post-migration validation blocks that compare expected versus observed physical outputs.

## 10) Implementation Acceptance Criteria

A geoprocessing implementation is not complete until:

1. Computational unit path is explicit and meter-normalized.
2. CRS-dependent conversion behavior is explicit and tested.
3. Identifier/schema handling is sink-safe.
4. Runtime diagnostics are actionable.
5. Regression checks cover meter, US survey foot, and geographic scenarios.
