# Issues: Summarizer Signal Error & UI Progress Not Visible

## Issue 1 — `signal only works in main thread of the main interpreter`

**Error log:**
```
[warning] summarizer_llm_error  error=signal only works in main thread of the main interpreter
```

**File:** `backend/app/modules/summarizer.py` — `_call_llm_sync()` (line ~152)

### Root Cause

`_call_llm_sync` uses `signal.alarm(90)` to enforce a hard 90-second timeout on the LLM call. However, this method is synchronous and is offloaded to a thread pool worker via `run_in_executor`:

```
summarise()                   ← async event loop (main thread)
  └─ run_in_executor(...)     ← spawns a thread pool worker
       └─ _call_llm_sync()    ← runs inside a worker THREAD (not main thread)
            └─ signal.alarm() ← CRASHES — signals only work in main thread
```

Python's `signal` module is hard-restricted: `signal.alarm()` and `signal.signal()` can only be called from the **main thread of the main interpreter**. Thread pool workers are not the main thread, so Python raises `ValueError: signal only works in main thread` every single time.

### Consequence

- The 90-second timeout is completely non-functional. If the LLM hangs, it hangs forever.
- The error is caught and the code returns `None`, triggering the template fallback.
- **Every listing silently falls back to a template-generated summary** instead of an LLM-generated one.

### Fix Required

Replace `signal.alarm()` with `asyncio.wait_for()`, which is the correct way to enforce timeouts in an async context:

```python
# Instead of run_in_executor + signal.alarm, use asyncio timeout directly:
async def _summarise_one(self, listing: BusinessListing) -> BusinessListing:
    prompt = self._build_prompt(listing)
    try:
        response = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, self._call_llm_sync_no_signal, prompt),
            timeout=90.0,
        )
    except asyncio.TimeoutError:
        response = None
    text = response or _template_summary(listing)
    return listing.model_copy(update={"summary": text})
```

---

## Issue 2 — UI Not Showing Pipeline Progress

### Root Cause

This is a direct consequence of Issue 1. Because `signal.alarm()` fails immediately and `_call_llm_sync` returns `None` instantly, the entire summarizer stage completes in milliseconds using template fallbacks.

The SSE pipeline events fire in near-instant succession:

```
reviews_aggregated  → (fast)
scoring_complete    → (fast)
summary_ready       → (instant — template summaries, no LLM wait)
done
```

The browser receives all these events so quickly that the UI cannot visually distinguish them as separate steps. It appears as though no progress happened and the result just appears.

### Secondary Cause

The frontend step update logic in `frontend/src/hooks/useSearch.ts` rebuilds the entire pipeline step list from scratch on every SSE event. When events arrive faster than a render cycle, intermediate states are never painted to the screen — the browser only renders the final state.

### Fix Required

Once Issue 1 is fixed (LLM timeout works via `asyncio.wait_for`), the summarizer will actually call the LLM and take time. This naturally slows down the `summary_ready` event, making the step-by-step progress visible in the UI again.

---

## Summary

| # | Issue | File | Root Cause | Impact |
|---|-------|------|------------|--------|
| 1 | `signal only works in main thread` | `summarizer.py:_call_llm_sync` | `signal.alarm()` cannot run in thread pool workers | LLM timeout broken; all summaries are templates |
| 2 | UI progress not visible | `summarizer.py` + `useSearch.ts` | Summarizer stage completes instantly due to Issue 1 | Pipeline steps appear to skip; no visible progress |

Both issues are resolved by fixing the timeout mechanism in `summarizer.py` to use `asyncio.wait_for()` instead of `signal.alarm()`.
