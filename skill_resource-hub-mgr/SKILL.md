---
name: "resource-hub-mgr"
description: "Use when working with a resource hub: initialize or repair hub structure, add/remove resources, edit resource_hub_config.json, or search existing image/video assets by natural-language description."
---

# Resource Hub Manager

Use this skill when the user wants to manage a `resource hub`, update `resource_hub_config.json`, search existing media by description, or explain why a hub is inconsistent.

## Reference map

- Read `references/resource_hub.CN.md` for hub schema, naming rules, config semantics, and resource constraints.
- Read `references/hub_workflows.md` for init, import, remove, repair, and general workflow routing.
- Read `references/search_workflow.md` for asset search and recommendation tasks.
- Read `references/config_editing.md` for `resource_hub_config.json` edits.

## Deterministic helpers

Prefer the bundled scripts for repeatable work:

- `scripts/run_python.sh init_hub.py --hub <hub_root>`
- `scripts/run_python.sh add_resource.py --hub <hub_root> --source <asset> [--source <asset> ...] [--name <resource_name> ...]`
- `scripts/run_python.sh remove_resource.py --hub <hub_root> --name <resource_name> [--name <resource_name> ...] [--type video|image ...]`
- `scripts/run_python.sh repair_hub.py --hub <hub_root>`
- `scripts/run_python.sh validate_hub.py <hub_root>`
- `scripts/run_python.sh find_resources.py --hub <hub_root> --query "..." [filters]`
- `scripts/run_python.sh update_config.py --hub <hub_root> ...`

## Operating rules

- Identify the hub root first. Prefer a user-provided path; otherwise look for `resource_hub_config.json`.
- Treat `index.json` as the single source of truth for each resource type.
- Prefer the bundled scripts over hand-editing files.
- Do not operate on the same hub concurrently. Batch imports should run sequentially in a single invocation, and separate tasks should not read or write the same hub at the same time.
- After changing config or hub contents, run `validate_hub.py`.
- If validation or a config change implies the hub is out of sync, ask before running `repair_hub.py` unless the user already clearly authorized automatic repair.
- When the user asks for assets by description, run `find_resources.py` first and inspect the top matches before recommending them.
- If results are weak, say so clearly and suggest importing assets or improving descriptions instead of overstating confidence.

## Task routing

- For init, import, remove, and repair tasks, follow `references/hub_workflows.md`.
- For config changes, follow `references/config_editing.md`.
- For search and recommendation requests, follow `references/search_workflow.md`.

## Naming and reporting

- If the user does not provide a resource name, prefer letting `add_resource.py` choose it instead of inventing one outside the import workflow.
- For batch imports, repeat `--source`; if explicit names are needed, repeat `--name` in the same order and with the same count.
- During import, the script auto-names the resource:
  - from content sensing only when the detected resource type has `with_description` enabled
  - otherwise from the source file stem
- If any resource name was chosen automatically, explicitly report the final chosen name and whether it came from content sensing or file-stem fallback.
- For any state-changing task, report what changed, any warnings, and suggested next steps such as validation or repair.
