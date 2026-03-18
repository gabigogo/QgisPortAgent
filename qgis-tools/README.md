# qgis-tools/

This folder is the **migration output destination** for the QgisPortAgent.

Each successfully migrated ArcGIS tool produces a self-contained QGIS Processing Plugin
subdirectory here:

```
qgis-tools/
└── <tool_name>_plugin/
    ├── metadata.txt
    ├── __init__.py
    ├── main_plugin.py
    ├── requirements.txt
    ├── migration_report.md
    ├── tests/
    └── processing_provider/
        ├── __init__.py
        ├── provider.py
        └── <tool_name>_algorithm.py
```

## Installing a migrated plugin in QGIS

See the [root README](../README.md#installing-migrated-plugins-in-qgis) for full instructions
(symlink, copy, or ZIP install methods).

## Quick install (Windows — symlink method)

Open a **Command Prompt as Administrator** and run:

```bat
mklink /J "C:\Users\<YourUsername>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\<tool_name>_plugin" "<your-workspace>\qgis-tools\<tool_name>_plugin"
```

Then restart QGIS and enable the plugin via **Plugins → Manage and Install Plugins**.
