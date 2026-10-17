"""Read-only MCP discovery; external results never enter the legal executor.

Credentials are read only from the server process environment.  This module is
not imported by the web application, so an absent SDK or remote service cannot
prevent local graph execution.  Tool calls are deliberately not implemented.
"""

import asyncio
import contextvars
import logging
import math
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import quote, quote_plus


MCP_ENDPOINT = "https://34-38-10-198.sslip.io/mcp"
MAX_PAGES = 100
MAX_ITEMS = 1000
_discovery_active = contextvars.ContextVar("mcp_discovery_active", default=False)

_MESSAGES = {
    "connected": "MCP-Verbindung hergestellt; Werkzeugausführung ist noch nicht freigegeben.",
    "not_configured": "MCP_API_KEY ist in der Serverumgebung nicht gesetzt.",
    "authentication_failed": "Der MCP-Server hat die Anmeldung abgelehnt.",
    "timeout": "Die MCP-Abfrage hat das Zeitlimit überschritten.",
    "unavailable": "Der MCP-Server ist derzeit nicht erreichbar.",
    "protocol_error": "Die MCP-Antwort ist ungültig oder die Ermittlung blieb unvollständig.",
    "sdk_unavailable": "Das erforderliche MCP-SDK ist nicht verfügbar. Bitte Abhängigkeiten installieren.",
}


class _DiscoveryError(Exception):
    pass


class _ProtocolLogFilter(logging.Filter):
    def filter(self, record):
        # SDK diagnostics may include remote payloads or exception tracebacks.
        # Install this at handlers rather than on the named loggers: logger
        # filters do not run for records propagated from child loggers, which
        # the SDK and HTTP stack may create lazily during a request.
        protocol_logger = (
            record.name in {"client", "mcp", "httpx2", "httpcore2"}
            or record.name.startswith(("client.", "mcp.", "httpx2.", "httpcore2."))
        )
        return not (_discovery_active.get() and protocol_logger)


@contextmanager
def _safe_protocol_logging():
    # Handler filters see propagated records from descendants created after
    # this context starts. Snapshot every currently registered handler so
    # custom non-root handlers and loggers with propagation disabled are
    # covered too. lastResort handles the no-handler path.
    handlers = {handler for handler in logging.getLogger().handlers}
    for logger in logging.Logger.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):
            handlers.update(logger.handlers)
    if logging.lastResort is not None:
        handlers.add(logging.lastResort)

    filter_ = _ProtocolLogFilter()
    token = _discovery_active.set(True)
    installed = []
    try:
        for handler in handlers:
            handler.addFilter(filter_)
            installed.append(handler)
        yield
    finally:
        try:
            for handler in installed:
                handler.removeFilter(filter_)
        finally:
            _discovery_active.reset(token)


def _redact(value, secret):
    variants = {secret, quote(secret, safe=""), quote_plus(secret)}
    if isinstance(value, str):
        for variant in sorted(variants, key=len, reverse=True):
            if variant:
                value = value.replace(variant, "[ENTFERNT]")
        return value
    if isinstance(value, dict):
        return {_redact(str(k), secret): _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    return value


def _dump(model):
    return model.model_dump(mode="json", by_alias=True, exclude_none=True) if model is not None else None


def _exception_leaves(error):
    yield error
    for child in getattr(error, "exceptions", ()):
        yield from _exception_leaves(child)
    cause = error.__cause__
    if cause is not None and cause is not error:
        yield from _exception_leaves(cause)


def _failure_status(error, httpx, http_statuses=()):
    errors = list(_exception_leaves(error))
    if any(status in (401, 403) for status in http_statuses) or any(
        isinstance(item, httpx.HTTPStatusError) and item.response.status_code in (401, 403) for item in errors
    ):
        return "authentication_failed"
    if any(isinstance(item, (TimeoutError, httpx.TimeoutException)) for item in errors):
        return "timeout"
    if any(isinstance(item, httpx.ProtocolError) for item in errors):
        return "protocol_error"
    if any(status >= 500 for status in http_statuses) or any(isinstance(item, httpx.TransportError) for item in errors):
        return "unavailable"
    return "protocol_error"


async def _list_all(client, method_name, field):
    items, cursor, seen = [], None, set()
    for _ in range(MAX_PAGES):
        page = await getattr(client, method_name)(cursor=cursor)
        items.extend(_dump(item) for item in getattr(page, field))
        if len(items) > MAX_ITEMS:
            raise _DiscoveryError("catalogue limit")
        cursor = page.next_cursor
        if cursor is None:
            return items
        if cursor in seen:
            raise _DiscoveryError("repeated cursor")
        seen.add(cursor)
    raise _DiscoveryError("page limit")


async def discover_mcp(*, timeout_seconds=15.0, http_client_factory=None):
    """Discover advertised metadata without transmitting case data or calling tools.

    ``http_client_factory`` is an internal test seam receiving the same secure
    httpx2.AsyncClient keyword arguments as the real network client.  It is not
    exposed through HTTP or configuration.  SDK auto negotiation supports both
    modern server/discover and the legacy initialize handshake.
    """
    result = {
        "status": "not_configured", "endpoint": MCP_ENDPOINT,
        "transport": "streamable-http", "authentication": "x-api-key",
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "protocol_version": None, "server_info": None, "capabilities": {},
        "tools": [], "resources": [], "resource_templates": [], "prompts": [],
        "execution_enabled": False,
    }

    def finish(status):
        result["status"] = status
        result["message"] = _MESSAGES[status]
        return _redact(result, secret)

    secret = os.environ.get("MCP_API_KEY", "")
    if not secret.strip():
        return finish("not_configured")
    if not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 60:
        raise ValueError("Das Zeitlimit muss zwischen 0 und 60 Sekunden liegen.")
    try:
        import httpx2
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client
    except ImportError:
        return finish("sdk_unavailable")

    async def enforce_endpoint(request):
        # Also protects against SDK-managed redirects and server-supplied URLs.
        if str(request.url) != MCP_ENDPOINT:
            raise _DiscoveryError("unexpected endpoint")

    http_statuses = []

    async def note_status(response):
        # The SDK may normalize HTTP failures to MCP errors. Retain only the
        # numeric transport status, never response bodies or credential headers.
        http_statuses.append(response.status_code)

    factory = http_client_factory or httpx2.AsyncClient
    try:
        with _safe_protocol_logging():
            async with asyncio.timeout(timeout_seconds):
                async with factory(
                    headers={"x-api-key": secret}, timeout=httpx2.Timeout(timeout_seconds),
                    follow_redirects=False, max_redirects=0, trust_env=False,
                    event_hooks={"request": [enforce_endpoint], "response": [note_status]},
                ) as http_client:
                    transport = streamable_http_client(
                        MCP_ENDPOINT, http_client=http_client, max_sse_event_size=1024 * 1024,
                    )
                    async with Client(
                        transport, mode="auto", cache=None, read_timeout_seconds=timeout_seconds,
                    ) as client:
                        capabilities = _dump(client.server_capabilities)
                        discovered = {
                            "protocol_version": client.protocol_version,
                            "server_info": _dump(client.server_info), "capabilities": capabilities,
                        }
                        # Unsupported namespaces are not probed. Empty catalogues
                        # and absent capabilities remain distinguishable.
                        if "tools" in capabilities:
                            discovered["tools"] = await _list_all(client, "list_tools", "tools")
                        if "resources" in capabilities:
                            discovered["resources"] = await _list_all(client, "list_resources", "resources")
                            discovered["resource_templates"] = await _list_all(client, "list_resource_templates", "resource_templates")
                        if "prompts" in capabilities:
                            discovered["prompts"] = await _list_all(client, "list_prompts", "prompts")
                # Publish only a fully completed snapshot, including cleanup.
                result.update(discovered)
        return finish("connected")
    except Exception as error:
        return finish(_failure_status(error, httpx2, http_statuses))
