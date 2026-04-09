# Search Workflow

Use this reference when the user describes the asset they want instead of naming a known resource.

## Goals

- Search existing hub assets before suggesting imports or outside sourcing.
- Prefer exact-fit recommendations when the user gives hard constraints.
- Be honest when the current hub does not contain a strong match.

## Recommended process

1. Infer likely filters from the request:
   - `video` or `image`
   - alpha / transparent background
   - minimum resolution
   - minimum fps for video
2. Run `scripts/run_python.sh find_resources.py --hub <hub_root> --query "..." [filters]`.
3. Inspect the top 1-3 matches in `index.json` before recommending them.
4. In the final answer, include:
   - resource name
   - resource type
   - best variation path
   - why it matches
   - where it falls short, if applicable
5. If the hub does not contain a strong match, say so directly and suggest importing assets or improving descriptions.

## Practical notes

- If the user asks for "transparent", require alpha.
- If the user asks for "animation", "motion", "loading", or "loop", prefer `video`.
- If the user asks for "background", "still", "cover", or "poster", prefer `image` unless the request clearly implies motion.
- If the top matches are weak, say that confidence is low.
- If search quality appears degraded because descriptions or vectors are stale, recommend `repair_hub.py`.
- If the right semantic content exists but the best variation does not meet technical constraints, call that out separately.
- Do not oversell a weak result just because it is the top hit.
