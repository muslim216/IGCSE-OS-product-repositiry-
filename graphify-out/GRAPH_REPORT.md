# Graph Report - avora  (2026-08-24)

## Corpus Check
- 356 files · ~414,794 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 45 nodes · 72 edges · 7 communities
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `12cc97ea`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- structured_complete
- record_usage
- ai.py
- _anthropic_system
- AIUnavailableError
- text_complete
- resolve_surface

## God Nodes (most connected - your core abstractions)
1. `structured_complete()` - 11 edges
2. `text_complete()` - 10 edges
3. `resolve_surface()` - 7 edges
4. `AIUnavailableError` - 6 edges
5. `AiResponse` - 6 edges
6. `get_client()` - 6 edges
7. `_anthropic_system()` - 6 edges
8. `record_usage()` - 6 edges
9. `get_gemini_client()` - 5 edges
10. `stream_complete()` - 5 edges

## Surprising Connections (you probably didn't know these)
- `get_client()` --calls--> `AIUnavailableError`  [EXTRACTED]
  backend/app/services/ai.py → backend/app/services/ai.py  _Bridges community 4 → community 3_
- `resolve_surface()` --calls--> `AIUnavailableError`  [EXTRACTED]
  backend/app/services/ai.py → backend/app/services/ai.py  _Bridges community 4 → community 6_
- `stream_complete()` --calls--> `resolve_surface()`  [EXTRACTED]
  backend/app/services/ai.py → backend/app/services/ai.py  _Bridges community 6 → community 3_
- `structured_complete()` --calls--> `resolve_surface()`  [EXTRACTED]
  backend/app/services/ai.py → backend/app/services/ai.py  _Bridges community 6 → community 0_
- `text_complete()` --calls--> `resolve_surface()`  [EXTRACTED]
  backend/app/services/ai.py → backend/app/services/ai.py  _Bridges community 6 → community 5_

## Import Cycles
- None detected.

## Communities (7 total, 0 thin omitted)

### Community 0 - "structured_complete"
Cohesion: 0.25
Nodes (9): AiResponse, _gemini_parts(), One AI call's result, normalized across providers so callers (and record_usage)…, Translate Anthropic content blocks into google-genai Part dicts., The parsed payload of a `structured_complete` response, typed as non-optional.…, A structured (schema-constrained) completion for one surface. `content` is a…, require_parsed(), structured_complete() (+1 more)

### Community 1 - "record_usage"
Cohesion: 0.25
Nodes (8): AiFeature, AsyncSession, estimate_cost_usd(), model_pricing(), MODEL_PRICING merged with the AI_MODEL_PRICING env override (env wins).…, None when the model has no configured price — never a guess., Record one AI call's usage, including its provider, prompt version and…, record_usage()

### Community 2 - "ai.py"
Cohesion: 0.29
Nodes (7): file_block(), _gemini_usage(), _GeminiUsage, The single choke point every AI-calling service routes through. Two things live…, Build a document (PDF) or image content block from stored file bytes.…, The exact keys _gemini_usage yields. A plain `dict[str, int]` would type-check…, TypedDict

### Community 3 - "_anthropic_system"
Cohesion: 0.29
Nodes (7): AsyncAnthropic, _anthropic_system(), get_client(), Assemble Anthropic system blocks. `cache_extra` marks the *last* extra block…, Stream a reply chunk by chunk. Anthropic-only: streaming is used by the student…, stream_complete(), TextBlockParam

### Community 4 - "AIUnavailableError"
Cohesion: 0.40
Nodes (5): AIUnavailableError, get_gemini_client(), The google-genai client. Imported lazily so the SDK stays an optional…, Raised when AI features are used without an API key configured., RuntimeError

### Community 5 - "text_complete"
Cohesion: 0.50
Nodes (4): Any, _joined_system(), A plain-text completion for one surface. Never sets `parsed` — there is no…, text_complete()

### Community 6 - "resolve_surface"
Cohesion: 0.50
Nodes (4): AiProvider, (provider, model) for one AI surface, from settings. A blank per-surface model…, resolve_surface(), str

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `record_usage()` connect `record_usage` to `structured_complete`, `ai.py`?**
  _High betweenness centrality (0.135) - this node is a cross-community bridge._
- **Why does `structured_complete()` connect `structured_complete` to `ai.py`, `_anthropic_system`, `AIUnavailableError`, `text_complete`, `resolve_surface`?**
  _High betweenness centrality (0.113) - this node is a cross-community bridge._
- **Why does `text_complete()` connect `text_complete` to `structured_complete`, `ai.py`, `_anthropic_system`, `AIUnavailableError`, `resolve_surface`?**
  _High betweenness centrality (0.113) - this node is a cross-community bridge._