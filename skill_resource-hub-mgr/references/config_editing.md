# Config Editing

Use this reference when the user wants Codex to modify `resource_hub_config.json`.

## Preferred editing method

- Use `scripts/run_python.sh update_config.py` for deterministic changes.
- After any write, run `scripts/run_python.sh validate_hub.py`.
- If the new config implies existing resources may now be out of sync, ask the user whether to run `scripts/run_python.sh repair_hub.py` before repairing, unless the user already clearly authorized automatic repair.

## Common paths

- `description_language`
- `video.transcoders`
- `image.transcoders`
- `video.with_description`
- `image.with_description`
- `content_sense.open_ai_base_url_env`
- `content_sense.open_ai_base_url`
- `content_sense.open_ai_api_key_env`
- `content_sense.model`
- `content_sense.cache_time_hours`
- `content_sense.video_understanding_mode`
- `text_vectorization.api_key_env`
- `text_vectorization.base_url_env`
- `text_vectorization.base_url`
- `text_vectorization.model`
- `text_vectorization.dimensions`

## Common changes

- Set repository description language to English:
  - set `description_language` to `"en"`
- Set repository description language to Simplified Chinese:
  - set `description_language` to `"zh-CN"`
- Enable image descriptions:
  - set `image.with_description` to `{"resolution": "720p"}`
- Enable video descriptions:
  - set `video.with_description` to `{"resolution": "720p"}`
- Switch video understanding mode:
  - set `content_sense.video_understanding_mode` to `"frames"` or `"direct_upload"`
- Change content-sense base URL env:
  - set `content_sense.open_ai_base_url_env` to the target provider base URL env var name such as `"OPENAI_COMPATIBLE_BASE_URL"`
- Change content-sense cache TTL:
  - set `content_sense.cache_time_hours` to a non-negative hour value such as `24`, `72`, or `144`
- Enable text vectorization:
  - set `text_vectorization` to `{"api_key_env": "ARK_COMPATIBLE_API_KEY", "base_url_env": "ARK_COMPATIBLE_BASE_URL", "model": "doubao-embedding-vision-251215", "dimensions": 1024}`
- Change text-vector base URL env:
  - set `text_vectorization.base_url_env` to the target Ark-compatible endpoint env var name such as `"ARK_COMPATIBLE_BASE_URL"`
- Change text-vector dimensions:
  - set `text_vectorization.dimensions` to a positive integer such as `512` or `1024`
- Replace transcoders:
  - set `video.transcoders` or `image.transcoders` to the full target list

## Safety notes

- When enabling `with_description`, ensure `content_sense` is complete.
- When changing `description_language`, tell the user that existing descriptions may need a repair pass to regenerate in the new language.
- When setting `video_understanding_mode` to `direct_upload`, make sure the configured provider and model actually support direct video input.
- For OpenAI GPT-5.4 family models, prefer `frames`; `direct_upload` is mainly for OpenAI-compatible non-GPT providers that support direct video upload.
- `content_sense.cache_time_hours` is a local reuse TTL for cached cloud file ids; changing it affects whether future re-sensing uploads again.
- Prefer `content_sense.open_ai_base_url_env` and `text_vectorization.base_url_env`; inline `open_ai_base_url` and `base_url` remain only for backward compatibility.
- `text_vectorization` is independent from `content_sense`; enabling it does not by itself create descriptions.
- Current text vectorization requires the Volcengine Ark SDK.
- After changing `text_vectorization.base_url_env`, `text_vectorization.base_url`, `text_vectorization.model`, or `text_vectorization.dimensions`, tell the user that a `repair_hub.py` pass is needed to rebuild stored `text_vector` payloads.
- When changing transcoder targets, tell the user that a follow-up repair or regeneration step may be needed.
- A config edit may justify repair, but should not silently trigger repair unless the user explicitly asked for it or has already granted standing permission for automatic repair.
