# Render Provider Contract

RUINFORM's intelligence core must not depend on one image generator.

The provider boundary is intentionally tiny:

```python
class RenderProvider(Protocol):
    async def render(self, request: RenderRequest) -> ProviderRender: ...
```

## Input

`RenderRequest` contains:

- approved `candidate_id`
- renderer-ready prompt compiled from the Visual Brief
- explicit negative constraints
- source image references with evidence IDs
- requested aspect ratio

## Output

`ProviderRender` contains:

- provider name
- generated image URL
- provider job ID when available
- small provider metadata map

## Higgsfield adapter

The intended first production adapter is Higgsfield. The adapter should translate `RenderRequest` into the Higgsfield generation call, attach source images as references where the selected model supports them, and return the completed image URL/job ID as `ProviderRender`.

The adapter must not perform product reasoning. It renders. THE MAKER owns the reasoning, evidence, approval and retry policy.

## Why not make Higgsfield an MCP server immediately?

Rendering is a narrow action with a clean typed tool contract, so a direct tool/provider adapter is simpler for V1. MCP becomes more useful when RUINFORM needs a broader remote capability surface such as catalogs, supplier systems, CAD services, workshop hardware or external manufacturing networks.

If a remote Render MCP is added later, its primary tool should remain equivalent to:

`render.generate(RenderRequest) -> ProviderRender`

so the intelligence pipeline does not change.

## Trust boundary

No provider output goes directly to the user. Every render returns to RUINFORM's Render Review and deterministic acceptance gate first.
