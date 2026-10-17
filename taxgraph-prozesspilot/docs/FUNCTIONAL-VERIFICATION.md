# Final reconciliation verification

Functional Integration V3 was reconciled with main commit
`114327a8abfef6776c8df3759162f802ba956558` (PR #2, local demo role switcher).
The concurrent role labels, APP_LOCAL_ROLE, guarded demo-role cookie behavior,
configuration response, tests and original UI assets are preserved. Production
still ignores the demo-role cookie. The switcher remains available in `/studio`;
the integrated `/prozesse` uses the same resolved server identity.

Final local run after reconciliation:

```text
python -m pytest -q --ignore=tests/test_mcp_client.py
105 passed, 4 warnings in 9.92s
```

The four warnings are Starlette deprecation warnings about the upstream test's
per-request cookie parameter. No fiscal assertion was removed. The unchanged
MCP tests were excluded because httpx2 / the required MCP SDK are unavailable
in this container; full CI remains separately configured and is not claimed green.

The offline Chromium DOM + real FastAPI TestClient transport was rerun after
reconciliation: author negative-net-assets execution, viewer read-only access,
and reviewer attribution/approval all passed, with no JavaScript page errors.
All browser JavaScript syntax, Python compilation and startup shell syntax passed.
This is not public deployment or live-network browser acceptance.

See FUNCTIONAL-INTEGRATION.md for the architecture, legal-source research,
source-export limitations and earlier 104-test verification before reconciliation.
