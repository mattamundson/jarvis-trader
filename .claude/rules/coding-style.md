# Coding Style — JARVIS TRADER

## Python (engine/)

- **Async with graceful fallback**: All external calls (LLM, market data, broker) must be async and have fallback behavior when unavailable
- **Pydantic v2**: Use `model_config = ConfigDict(...)` not `class Config`. Use `model_validate()` not `parse_obj()`
- **ruff-clean**: All Python must pass `ruff check` with zero errors
- **File size**: 400 lines typical, 800 lines absolute maximum. Split by responsibility.
- **Function size**: 50 lines maximum per function
- **Error handling**: All FastAPI endpoints must have try/except with proper HTTPException
- **Imports**: Lazy imports for heavy dependencies (yfinance, anthropic) — defer inside functions if startup cost is high
- **Logging**: Use `logging.getLogger(__name__)` — never `print()` in production code

## TypeScript (dashboard/)

- **Next.js App Router**: Default to Server Components. Add `"use client"` only when interactivity or browser APIs are needed
- **fetchEngine/postEngine ONLY**: Never hardcode `http://localhost:8010` in dashboard components. All engine calls go through `lib/api.ts` functions
- **SWR for data fetching**: Use `useSWR` for polling/cached data. Use `useState`+`useEffect` only for one-off fetches
- **Tailwind only**: No inline styles, no CSS modules, no external component libraries beyond shadcn/ui
- **TypeScript strict**: No `any` types. Define interfaces in `lib/api.ts` and import them — don't redefine locally
- **"use client" boundary**: Push it as far down the component tree as possible

## General

- **No magic numbers**: Extract constants with meaningful names
- **No emojis in code or comments**
- **Conventional commits**: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`
