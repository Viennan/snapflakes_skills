# Search Workflow

Use this reference when the user describes the asset they want instead of naming a known resource.

## Goals

- Search existing hub assets before suggesting imports or outside sourcing.
- Prefer exact-fit recommendations when the user gives hard constraints.
- Be honest when the current hub does not contain a strong match.

## Recommended process

1. Run `scripts/find_resources.py` with the user's description.
   In practice, invoke it through `scripts/run_python.sh find_resources.py`.
2. Convert explicit constraints into filters:
   - `video` or `image`
   - alpha or transparent background
   - minimum resolution
   - minimum fps for video
3. Candidate-set rule:
   - if hard filters exist, the candidate set is the resources that pass those filters
   - if no hard filters exist, the candidate set is all resources
4. For every candidate resource, compute lexical score and semantic vector similarity in parallel.
   - lexical score must not be used as a precondition for whether vector similarity is computed
   - if a resource lacks a usable `text_vector`, keep the lexical result and surface that limitation honestly
5. Inspect the top 1-3 matches' resource entries in `index.json` before recommending them.
6. In the final answer, include:
   - resource name
   - resource type
   - best variation path
   - why it matches
   - where it falls short, if applicable

## Heuristics

- If the user asks for "transparent", require alpha.
- If the user asks for "animation", "motion", "loading", or "loop", prefer `video`.
- If the user asks for "background", "still", "cover", or "poster", prefer `image` unless the request clearly implies motion.
- If the top matches all have weak text overlap, say that confidence is low.
- If vector scores are missing or stale for many resources, say so explicitly and recommend `repair_hub.py`.
- If the right semantic content exists but the best variation does not meet technical constraints, call that out separately.
