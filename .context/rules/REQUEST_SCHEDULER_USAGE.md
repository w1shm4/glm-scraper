# Request Scheduler Usage

This project includes `request_scheduler.py` to prevent concurrency problems and API rate-limit issues.

Use it as the single path for outbound API calls.

## Quick start

1) Copy `.env-example` to `.env` and set `Z_API_KEY`.  
2) Import `schedule_api_request` and wrap every API request:

```python
from request_scheduler import schedule_api_request

result = await schedule_api_request(
    lambda api_key: client.get(
        "/z-api/endpoint",
        headers={"x-api-key": api_key},
    ),
    request_name="z_api_get_endpoint",
)
```

That is enough to get:

- rate limiting (`requests_per_second`)
- concurrency control (`max_concurrency`)
- retries with exponential backoff + jitter

## Why this fixes concurrency issues

If many tasks call your API at once, requests can overlap, spike, and fail.

`RequestScheduler` solves that by:

1. Queueing calls behind a semaphore (`max_concurrency`)
2. Spacing calls by minimum interval (`1 / requests_per_second`)
3. Retrying transient failures with backoff

## Recommended rule

Do **not** call API clients directly in app code.  
Always do:

```python
await schedule_api_request(
    lambda api_key: client.get(..., headers={"x-api-key": api_key}),
    request_name="...",
)
```

## Common patterns

### GET request

```python
data = await schedule_api_request(
    lambda api_key: client.get("/z-api/items", headers={"x-api-key": api_key}),
    request_name="z_api_get_items",
)
```

### POST request

```python
payload = {"name": "test"}
created = await schedule_api_request(
    lambda api_key: client.post(
        "/z-api/items",
        json=payload,
        headers={"x-api-key": api_key},
    ),
    request_name="z_api_create_item",
)
```

### In a loop (safe way)

```python
for item_id in item_ids:
    item = await schedule_api_request(
        lambda api_key, item_id=item_id: client.get(
            f"/z-api/items/{item_id}",
            headers={"x-api-key": api_key},
        ),
        request_name=f"z_api_get_item_{item_id}",
    )
    # process item
```

Note the `lambda ..., item_id=item_id` pattern. It captures the correct loop value.

## Tuning scheduler limits

Defaults are created in `create_default_scheduler()` inside `request_scheduler.py`.

You can tune:

- `requests_per_second`: lower it if your API throttles easily
- `max_concurrency`: keep at `1` for fragile APIs, increase carefully
- `max_retries`: number of retries before failing
- `base_backoff_seconds`: retry delay base
- `max_jitter_seconds`: random jitter to avoid burst retries

Example:

```python
from request_scheduler import RequestScheduler, SchedulerConfig

scheduler = RequestScheduler(
    SchedulerConfig(
        requests_per_second=2.0,
        max_concurrency=1,
        max_retries=5,
        base_backoff_seconds=0.8,
        max_jitter_seconds=0.3,
    )
)
```

Then call:

```python
result = await scheduler.schedule(
    lambda: client.get("/z-api/endpoint"),
    request_name="custom_scheduler_example",
)
```

## Failure behavior

If a request still fails after all retries, scheduler raises:

- `RuntimeError("<request_name> failed after X retries")`

Catch it where needed:

```python
try:
    result = await schedule_api_request(
        lambda api_key: client.get(
            "/z-api/endpoint",
            headers={"x-api-key": api_key},
        ),
        request_name="z_api_critical_call",
    )
except RuntimeError as exc:
    # log / alert / fallback
    print(exc)
```

## Best practices

- Use meaningful `request_name` values for debugging
- Keep all API calls behind scheduler (no bypasses)
- Start conservative (`max_concurrency=1`) and increase slowly
- If API errors rise, lower RPS first

## File references

- Scheduler code: `request_scheduler.py`
- Agent rule: `.cursor/rules/use-request-scheduler.mdc`
- Env template: `.env-example` (plus requested alias `.env-exmaple`)
