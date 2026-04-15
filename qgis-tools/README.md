# qgis-tools/ (Legacy Compatibility)

This folder is a legacy compatibility location for generated plugins.

The canonical destination is now:

```
plugins/generated/
```

Current tooling can still read from `qgis-tools/` when explicitly requested
for backwards compatibility.

## Recommended flow

1. Generate plugins into `plugins/generated/`.
2. Link plugins into your QGIS profile with:

```powershell
.\scripts\setup_plugins.ps1 -Category generated -IncludeLegacyGenerated
```

```bash
bash scripts/setup_plugins.sh --category generated --include-legacy-generated
```
