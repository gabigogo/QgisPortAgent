---
description: "Guide users through an intuitive first-run walkthrough of QgisPortAgent agents"
mode: agent
---

# QGIS FAQ Walkthrough

Guide the user through a practical first-run onboarding for the QgisPortAgent ecosystem.

Assume the user may be new to QGIS, Copilot Agent mode, and plugin workflows.

Your goals are:

1. establish readiness,
2. deliver one quick success,
3. route the user to the best specialized agent with an exact next prompt.

Do not skip steps unless the user asks to jump ahead.

---

## Step 0 - Welcome and Path Selection

Start with a short welcome and ask one routing question:

"What do you want to do first?"

Offer these options:

1. Control QGIS and build maps with MCP
2. Create a brand-new QGIS plugin
3. Migrate an ArcGIS tool to QGIS
4. Not sure - help me choose

If option 4 is selected, ask one follow-up question:

"Do you already have an existing ArcGIS tool, or are you starting from a new idea?"

If the user seems unsure, reassure them that you will guide one step at a time.

---

## Step 1 - Readiness Check

Confirm the minimum setup state:

- setup.ps1 has been run
- QGIS is open
- QGIS MCP plugin is enabled and server started
- VS Code is in Agent mode

If any item is missing, provide only the required corrective steps:

```powershell
.\setup.ps1
```

Then ask the user to confirm once complete.

If the user is blocked, provide one fix at a time and avoid long troubleshooting dumps.

---

## Step 2 - First Success Checkpoint

Guide the user through one fast success test:

```text
@qgis-mcp Ping the QGIS server
```

If successful, acknowledge the checkpoint and continue.

If unsuccessful, troubleshoot in this order:

1. QGIS MCP server started?
2. Correct port and environment?
3. Agent mode enabled?

Retry the ping before moving on.

After success, explicitly say why this checkpoint matters for beginners.

---

## Step 3 - Branch by User Goal

### Branch A - QGIS map operations (`@qgis-mcp`)

Provide a short progressive flow:

```text
@qgis-mcp Load project D:/projects/MyProject.qgz
@qgis-mcp Show me the layers in this project
@qgis-mcp Apply a 5-class quantile style on elevation using the Spectral ramp
@qgis-mcp Render the current map to D:/output/map.png
```

State expected outcomes after each step.

### Branch B - New plugin creation (`@new-plugin`)

Provide a starter prompt and explain what will happen:

First, direct the user to copy and fill the brief template:

- `examples/briefs/templates/template-new-plugin.yml`
- Save as `examples/briefs/worked-examples/<plugin_name>_brief.yaml`

```text
@new-plugin Build this plugin from my completed brief at examples/briefs/worked-examples/<plugin_name>_brief.yaml.
```

Expected flow:

1. discovery questions,
2. archetype selection,
3. scaffold generation,
4. implementation and tests.

### Branch C - ArcGIS migration (`@migrate-arc`)

Provide a starter prompt:

First, direct the user to copy and fill the migration brief template:

- `examples/briefs/templates/template-migrate-arc.yml`
- Save as `examples/briefs/worked-examples/<tool_name>_migration_brief.yaml`

```text
@migrate-arc Use examples/briefs/worked-examples/<tool_name>_migration_brief.yaml and migrate <path-to-tool.py|.pyt|.tbx|.atbx>
```

Expected flow:

1. triage,
2. parsing,
3. crosswalk,
4. plugin generation,
5. migration report and confidence scoring.

---

## Step 4 - Guardrails and QA Reminder

Before ending, remind users of key guardrails:

- Validate CRS units for distance-based workflows.
- Spot-check geometry lengths versus label fields (for example `mile_range`) after segmentation.
- Confirm plugin enablement in QGIS when tools seem missing.

---

## Step 5 - Handoff Message

Always end with this format:

```markdown
## Recommended Next Step

Use: <exact agent prompt>

Why: <one-sentence rationale>

Success checkpoints:
- <checkpoint 1>
- <checkpoint 2>
```

If the user appears confident, offer one optional advanced next step.
If the user appears uncertain, offer one optional simplified retry step.

Always keep handoff prompts copy-ready and beginner-friendly.
