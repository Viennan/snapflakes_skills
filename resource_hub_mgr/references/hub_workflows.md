# Hub Workflows

Use this reference when Codex needs to carry out resource-hub work as a skill rather than as a raw CLI wrapper.

## Core operating principles

- The skill must maintain a hub that conforms to `references/resource_hub.CN.md`.
- `index.json` is the single source of truth for each resource type.
- Any write should be reasoned about at the single-resource level. If a resource update fails midway, avoid leaving an obviously half-finished state.
- Always preserve the original file as the `original variation`.
- Only create transcodes for target specs that are actually realizable from the original.
- All media probing, detection, frame extraction, and transcoding must use `ffmpeg` / `ffprobe` command invocations directly, or Python wrappers around those commands only.
- All Python helpers should run through `scripts/run_python.sh`, which manages a local `.venv` under the skill directory.
- After changing config or hub contents, run `scripts/run_python.sh validate_hub.py`.
- `description` is the semantic text source for search; `text_vector` is an optional derived cache stored in `index.json`.
- If a config change or validation result implies that the hub no longer matches config, confirm with the user before running `scripts/run_python.sh repair_hub.py`, unless the user has already clearly authorized automatic repair.

## Task model

Codex should map user intent into one of these skill tasks:

1. Initialize a hub
2. Add or import resources
3. Remove resources
4. Repair a hub
5. Search and recommend resources
6. Edit config

The user does not need to speak in CLI parameters. Codex should infer the task from natural language and then carry out the matching workflow.

## 1. Initialize a hub

Expected behavior:
- Ensure the hub root exists.
- Ensure these paths exist:
  - `resource_hub_config.json`
  - `videos/`
  - `videos/index.json`
  - `images/`
  - `images/index.json`
- If `resource_hub_config.json` does not exist, create:

```json
{
    "description_language": "en",
    "video": {
        "transcoders": []
    },
    "image": {
        "transcoders": []
    }
}
```

- If `videos/index.json` or `images/index.json` does not exist, create `{"resources": []}`.
- Treat initialization as idempotent.
- If an existing JSON file is invalid, stop and report the problem instead of silently overwriting it.

## 2. Add or import resources

Expected behavior for each resource:
- Detect whether the file is `video` or `image`.
- Treat GIF, APNG, Animated WebP, and other time-based visual resources as `video`.
- Copy the source file into the resource directory. Do not move or link it.
- Store the copied original as `original.<format>`.
- Probe the original file and build the final `variations` list.
- Generate all missing, realizable transcodes required by the current config.
- If `with_description` is enabled for the resource type:
  - verify `content_sense` is complete
  - obey `content_sense.video_understanding_mode` for video
  - probe the chosen sensing input with `ffprobe` first and treat technical facts such as `has_alpha`, duration, fps, and resolution as authoritative
  - use distinct prompts for image and video assets
  - if `content_sense_cache` still matches the current provider, account env, input file, and cache TTL, reuse cached `file_id` values instead of re-uploading
  - if cache cannot be reused, upload fresh input files and refresh `content_sense_cache`
  - for video descriptions, require approximate timeline segmentation plus atmosphere or mood description
  - generate `description`
- If `text_vectorization` is enabled and the final `description` is non-empty:
  - vectorize `description` with the Volcengine Ark SDK
  - use the corpus-side instruction template required by the Doubao embedding guide
  - store the encoded vector string and its metadata in `text_vector`
- Write the final resource entry into the corresponding `index.json`.

Resource-level output should include:
- resource name
- whether the name was user-provided, derived from the file stem, or inferred from content
- detected type
- files created
- warnings

## 3. Remove resources

Expected behavior:
- Delete the resource directory.
- Remove the matching entry from the corresponding `index.json`.
- Report an error if the resource does not exist.

## 4. Repair a hub

Expected behavior:
- Run this workflow immediately only when the user explicitly asks for repair or has already given clear standing permission for automatic repair.
- If repair is only implied by a config change or by validation findings, first ask whether the user wants repair.
- Verify `resource_hub_config.json` is present and valid JSON.
- Ensure `videos/`, `images/`, and both `index.json` files exist.
- Scan all resource directories and repair what can be repaired.

For each resource directory:
- Re-probe the original file and normalize its metadata.
- Remove managed transcodes and regenerate the currently required set.
- Rebuild the resource entry directly into `index.json`.
- If a legacy `meta.json` still exists, migrate any usable description/cache information out of it and remove it.
- If `text_vectorization` is enabled, rebuild or refresh `text_vector` for non-empty descriptions.
- Warn about unmanaged extra files instead of deleting them automatically.

After resource repair:
- Rebuild `videos/index.json` and `images/index.json` from directory contents.
- Regenerate descriptions when `with_description` is enabled.
- Return warnings and any remaining unrepairable problems.

## 5. Search and recommend resources

Expected behavior:
- Use `scripts/run_python.sh find_resources.py` first.
- Convert explicit constraints into filters:
  - type
  - alpha
  - minimum resolution
  - minimum fps
- Use hard filters only to define the candidate set.
- After the candidate set is chosen, compute lexical score and vector similarity for every candidate in parallel.
- Do not require lexical hits before computing semantic vector similarity.
- Inspect the top results before recommending them.
- For each recommendation, explain why it matches and where it may fall short.
- If the hub lacks a good fit, say so clearly and suggest importing new assets or improving descriptions.

## 6. Edit config

Expected behavior:
- Prefer `scripts/run_python.sh update_config.py` for deterministic config edits.
- Use whole stable paths such as:
  - `description_language`
  - `video.transcoders`
  - `image.transcoders`
  - `video.with_description`
  - `image.with_description`
  - `content_sense.model`
  - `content_sense.cache_time_hours`
  - `content_sense.video_understanding_mode`
  - `text_vectorization`
  - `text_vectorization.api_key_env`
  - `text_vectorization.base_url`
  - `text_vectorization.model`
  - `text_vectorization.dimensions`
- After writing config, run `scripts/run_python.sh validate_hub.py`.
- If the user asks for OpenAI GPT-5.4, recommend `frames` mode. Reserve `direct_upload` for OpenAI-compatible providers that explicitly support direct video input.
- If the user enables or changes `text_vectorization`, explain that a repair pass is needed to materialize or refresh `text_vector`.
- If the config change means existing resources or transcodes may now be out of sync, tell the user that repair is recommended and ask whether to run it, unless they already authorized automatic repair.
- Explain operational consequences such as "a repair pass is now needed to materialize the new targets."

## Result reporting

For any state-changing workflow, Codex should report:
- what changed
- which files were created, updated, or removed
- warnings or unresolved issues
- suggested next steps such as validation, repair, or importing additional assets
- if any resource name was assigned automatically, the final report must explicitly list:
  - source file
  - chosen resource name
  - whether the name came from content sensing or file-stem fallback
  - any uniqueness suffix added during conflict resolution

When confidence is low, prefer explicit uncertainty over fabricated certainty.
