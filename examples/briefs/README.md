# briefs/

Canonical brief templates and worked examples for first-time users.

Use this folder before calling `@new-plugin` or `@migrate-arc` so the agent can build from a concrete spec instead of freeform prompts.

---

## Quick Start

### A) Create a New Plugin (`@new-plugin`)

1. Copy [templates/template-new-plugin.yml](templates/template-new-plugin.yml).
2. Save your copy as `worked-examples/<plugin_name>_brief.yaml`.
3. Fill at least sections 1, 2, 3, and 4.
4. Run:

```text
@new-plugin Build this plugin from my brief at examples/briefs/worked-examples/<plugin_name>_brief.yaml.
```

### B) Migrate ArcGIS Tool (`@migrate-arc`)

1. Copy [templates/template-migrate-arc.yml](templates/template-migrate-arc.yml).
2. Save your copy as `worked-examples/<tool_name>_migration_brief.yaml`.
3. Fill at least sections 1, 2, and 3.
4. Run:

```text
@migrate-arc Use examples/briefs/worked-examples/<tool_name>_migration_brief.yaml and migrate <path-to-tool.py|.pyt|.tbx|.atbx>
```

---

## Templates

- New plugin template: [templates/template-new-plugin.yml](templates/template-new-plugin.yml)
- ArcGIS migration template: [templates/template-migrate-arc.yml](templates/template-migrate-arc.yml)

## Worked Examples

- [worked-examples/stream_segmenter_brief.yaml](worked-examples/stream_segmenter_brief.yaml)
- [worked-examples/dem_comparison_brief.yaml](worked-examples/dem_comparison_brief.yaml)

---

## Compatibility

Root-level files with the old names are kept as deprecated compatibility copies for one release cycle:

- `template-new-plugin.yml`
- `template-migrate-arc.yml`
- `stream_segmenter_brief.yaml`
- `dem_comparison_brief.yaml`

Canonical files are in this folder and should be used for all new work.
