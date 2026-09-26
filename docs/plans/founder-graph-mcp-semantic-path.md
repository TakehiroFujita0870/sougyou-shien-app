# MCP semantic relation path

## Scope

Add a typed, additive `semantic_relation_path` projection to the existing MCP
`search` result when its `SearchHit` contains validated `RelationPathStep`
values for formal assertions. Preserve the existing `relation_path` string
array exactly. Do not add tools or expose Brief prose, source/chunk content,
private fields, or physical assertion scaffolding.

## Acceptance

- A formal step projects only assertion identity, traversal/stored endpoints,
  predicate, status, confidence, validity window, Brief ID/section reference,
  and Evidence IDs that pass the existing owner-scoped shareable projection.
- Malformed or mismatched typed paths fail closed and do not replace/change the
  legacy `relation_path` output.
- Runtime-malformed `status` and traversal direction values are rejected before
  enum/set membership checks, so a bad in-process value cannot fail the whole
  search projection.
- Legacy-only paths retain their previous output and do not gain an inferred
  assertion ID.
- If a path mixes formal assertion steps with legacy relationships, omit the
  entire semantic projection rather than returning a partial formal fragment.
- Tests cover additive output, unchanged legacy output, malformed pairing, and
  local-only Evidence omission. No source, chunk, or Brief body is returned.

## Boundary

This packet changes only the MCP projection contract. Neo4j assertion traversal
and same-snapshot latest-Brief validation remain a separate dependent read
adapter change after the Brief gateway seam is merged. No database, runtime,
service, or authorization behavior changes here.
