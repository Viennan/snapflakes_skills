# Hub Workflows

Use this reference when Codex needs to carry out resource-hub work as a skill rather than as a raw CLI wrapper.

## Core rules

- Keep the hub aligned with `references/resource_hub.CN.md`.
- Infer the workflow from natural language; the user does not need to speak in CLI parameters.
- Prefer the bundled scripts through `scripts/run_python.sh`.
- `index.json` is the single source of truth for each resource type.
- After changing config or hub contents, run `scripts/run_python.sh validate_hub.py`.
- If a config change or validation result implies that the hub no longer matches config, confirm with the user before running `scripts/run_python.sh repair_hub.py`, unless the user has already clearly authorized automatic repair.

## Workflow map

Map user intent into one of these tasks:

1. Initialize a hub
2. Add or import resources
3. Remove resources
4. Repair a hub
5. Search and recommend resources
6. Edit config

## 1. Initialize a hub

- Run `scripts/run_python.sh init_hub.py --hub <hub_root>`.
- Treat init as idempotent.
- If existing hub files are invalid, stop and report the problem instead of overwriting them.
- After init, tell the user what was created or confirmed.

## 2. Add or import resources

- Run `scripts/run_python.sh add_resource.py --hub <hub_root> --source <asset> [--name <resource_name>]`.
- Use this workflow both for single-file imports and repeated multi-file imports.
- If the user did not provide a resource name, omit `--name` and let the import workflow auto-name the resource.
- The script auto-names the resource from content sensing only when `with_description` is enabled for that resource type; otherwise it falls back to the source file stem.
- Report the final chosen name clearly.
- After import, summarize the detected type, created files, and any warnings.
- Run validation after the import batch.

## 3. Remove resources

- Run `scripts/run_python.sh remove_resource.py --hub <hub_root> --name <resource_name> [--type video|image]`.
- If the user did not specify type and the name is ambiguous, resolve that before removal.
- Run validation after the removal.
- Report what was removed, or clearly say if the resource was not found.

## 4. Repair a hub

- Run this workflow immediately only when the user explicitly asks for repair or has already given clear standing permission for automatic repair.
- If repair is only implied by a config change or by validation findings, first ask whether the user wants repair.
- Run `scripts/run_python.sh repair_hub.py --hub <hub_root>` only after that approval boundary is clear.
- Run validation after repair.
- Summarize what was repaired, plus any warnings or remaining issues.

## 5. Search and recommend resources

- Use `scripts/run_python.sh find_resources.py` first.
- Apply obvious user constraints such as type, alpha, minimum resolution, or minimum fps.
- Inspect the top results before recommending them.
- For each recommendation, explain why it matches and where it may fall short.
- If the hub lacks a good fit, say so clearly and suggest importing new assets or improving descriptions.
- For more detailed search guidance, use `references/search_workflow.md`.

## 6. Edit config

- Prefer `scripts/run_python.sh update_config.py` for deterministic config edits.
- After writing config, run `scripts/run_python.sh validate_hub.py`.
- If the user enables or changes `text_vectorization`, explain that a repair pass is needed to materialize or refresh `text_vector`.
- If the config change means existing resources or transcodes may now be out of sync, tell the user that repair is recommended and ask whether to run it, unless they already authorized automatic repair.
- For concrete config paths and edit patterns, use `references/config_editing.md`.

## Result reporting

For any state-changing workflow, Codex should report:
- what changed
- which files were created, updated, or removed
- warnings or unresolved issues
- suggested next steps such as validation, repair, or importing additional assets
- if any resource name was assigned automatically, the final report must explicitly list:
  - source file
  - chosen resource name
  - whether the name came from the script's content-sense path or file-stem fallback
  - any uniqueness suffix added during conflict resolution

When confidence is low, prefer explicit uncertainty over fabricated certainty.
