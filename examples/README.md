# Examples

Runnable scripts that show how to use `interactsh-mcp` as a regular Python
library (rather than as an MCP server). Install the package and run any of
them directly:

```bash
pip install interactsh-mcp
python examples/01_one_shot.py
```

| File | Pattern |
| --- | --- |
| [`01_one_shot.py`](01_one_shot.py) | Single payload, single poll, auto-cleanup. The lowest-overhead usage. |
| [`02_session_manager.py`](02_session_manager.py) | Background polling + multiple payloads per session via `SessionManager`. |
| [`03_self_hosted_with_token.py`](03_self_hosted_with_token.py) | Targeting a self-hosted server started with `-auth`. |
| [`04_sync_wrapper.py`](04_sync_wrapper.py) | Calling the async API from synchronous code. |
