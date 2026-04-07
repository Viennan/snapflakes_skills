---
name: "resource-hub-mgr"
description: "Use when working with a resource hub: initialize or repair hub structure, add/remove resources, inspect or validate metadata, edit resource_hub_config.json, or search existing image/video assets by natural-language description."
---

# Resource Hub Manager

Use this skill when the user wants Codex to manage a `resource hub`, change `resource_hub_config.json`, find existing media assets by description, or explain why a hub is inconsistent.

## When to load references

- Read `references/resource_hub.CN.md` for hub schema, naming rules, config semantics, and resource constraints.
- Read `references/hub_workflows.md` before doing init/add/remove/repair/index/resource-entry style work or when you need the skill's operational contract.
- Read `references/search_workflow.md` when the user wants recommendations such as "find a transparent blue loading animation" or "look for a calm office background image".
- Read `references/config_editing.md` when the user wants to enable descriptions, change description language, change transcoders, or switch video understanding mode.

## Deterministic helpers

Prefer the bundled scripts for repeatable work:

- `resource_hub_mgr/scripts/run_python.sh init_hub.py --hub <hub_root>`
- `resource_hub_mgr/scripts/run_python.sh add_resource.py --hub <hub_root> --source <asset> [--name <resource_name>]`
- `resource_hub_mgr/scripts/run_python.sh remove_resource.py --hub <hub_root> --name <resource_name> [--type video|image]`
- `resource_hub_mgr/scripts/run_python.sh repair_hub.py --hub <hub_root>`
- `resource_hub_mgr/scripts/run_python.sh get_index.py --hub <hub_root> --type video|image`
- `resource_hub_mgr/scripts/run_python.sh get_meta.py --hub <hub_root> --type video|image --name <resource_name>`
- `resource_hub_mgr/scripts/run_python.sh validate_hub.py <hub_root>`
- `resource_hub_mgr/scripts/run_python.sh find_resources.py --hub <hub_root> --query "..." [filters]`
- `resource_hub_mgr/scripts/run_python.sh update_config.py --hub <hub_root> ...`

The wrapper bootstraps and reuses `resource_hub_mgr/.venv`, so future Python dependencies stay isolated from the system environment.
All media probing, detection, frame extraction, and transcoding must go through `ffmpeg` / `ffprobe` or Python wrappers around those commands. Do not introduce direct FFmpeg API bindings such as `pyav`.
Text vectorization for semantic search must use the Volcengine Ark SDK with `doubao-embedding-vision-251215`, not the OpenAI SDK.

## Default workflow

1. Identify the hub root. Prefer a user-provided path; otherwise look for `resource_hub_config.json`.
2. Treat `index.json` as the single source of truth for each resource type.
3. For config edits, use `update_config.py` instead of manual JSON editing whenever possible.
4. After changing config or managed metadata, run `validate_hub.py`.
5. When the user asks for assets by description, run `find_resources.py` first, then inspect the top matches' entries in `index.json` before recommending them.
6. When the user asks for init/add/remove/repair/index/resource-entry work, follow `references/hub_workflows.md` and adapt the workflow to the user's natural-language request.
7. If search results are weak, say so clearly and suggest importing new assets or improving descriptions instead of overstating confidence.

## Task guidance

### Config edits

- Prefer setting whole stable paths such as `description_language`, `video.transcoders`, `image.with_description`, or `content_sense.video_understanding_mode`.
- For semantic search configuration, also prefer whole stable paths such as `text_vectorization`, `text_vectorization.api_key_env`, or `text_vectorization.dimensions`.
- Explain any operational consequence of the config change, especially when a follow-up `repair` is likely needed.
- If the requested change affects description generation, mention provider compatibility, description language, and the current `video_understanding_mode`.
- If the requested change affects text vectorization, mention that `repair_hub.py` is needed to materialize or refresh `text_vector` entries in `index.json`.
- For OpenAI GPT-5.4 family models, treat `frames` as the safe default. Use `direct_upload` only when the configured OpenAI-compatible provider explicitly supports direct video input.
- If the user changes `content_sense.cache_time_hours`, explain that it only controls local reuse of uploaded cloud file ids, not guaranteed provider-side retention.

### Resource search and recommendation

- Use hard filters when the request implies them: resource type, alpha, minimum resolution, minimum fps.
- Hard filters only define the candidate set. After that, lexical score and vector similarity should be computed for every candidate in parallel.
- Recommend assets with a short reason tied to the user's request, not just raw scores.
- Include the best matching variation path when giving a final recommendation.

### Import naming

- If the user provides an asset without a resource name and content sensing is enabled for the detected resource type, you may infer a suitable resource name from sensed content.
- Auto-generated names should be short, descriptive, and safe as directory names. Prefer lowercase ASCII hyphen-case when generating new names.
- If content sensing is unavailable for that asset, fall back to the source file stem and state that assumption.
- If any resource name was chosen automatically, explicitly report the final chosen name to the user before ending the task.

### Content sensing

- Treat `ffprobe` results as the source of truth for technical media facts such as alpha support, duration, fps, and resolution.
- Do not ask the model to guess whether an image or video has alpha; pass the probed fact into the prompt and make it authoritative.
- Use different prompts for image and video understanding.
- The generated resource text is a single `description`, whose language is controlled by `resource_hub_config.json.description_language`.
- For video descriptions, require time-ranged timeline summaries and atmosphere or mood description, not only static scene labels.
- Reuse cached cloud `file_id` values from `index.json` resource entries when the provider/account/input file still match and the configured cache TTL has not expired.

### Text Vectorization

- `description` is the corpus text for semantic retrieval; `text_vector` is its optional derived cache stored in `index.json`.
- The vector payload must be encoded as a string, currently `base64-f32le`, instead of a JSON float array.
- Follow the Doubao embedding guide's task split:
  - corpus-side vectorization uses `Instruction:Compress the text into one word.\nQuery:`
  - query-side vectorization uses the fixed `Target_modality: text.\nInstruction:{}\nQuery:` template with a retrieval-oriented instruction body
- Do not use lexical hits as a precondition for whether vector similarity is computed.

### Repair and manual management

- Prefer the deterministic helpers for init/add/remove/repair/index/resource-entry work instead of hand-editing files.
- For workflows that still need manual judgment, follow `references/hub_workflows.md`, then run `validate_hub.py`.
- Prefer natural-language task decomposition over CLI-shaped thinking. Translate requests like "import these two files", "repair the hub", or "show me the best matching transparent animation" directly into the corresponding workflow.
