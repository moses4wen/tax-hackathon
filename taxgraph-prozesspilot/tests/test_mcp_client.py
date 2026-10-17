"""Offline protocol/security checks using the real MCP SDK HTTP transport.

The remote peer below is deliberately synthetic. Its catalog is a test fixture,
not evidence about the team's actual server or authorization to invoke tools.
"""
import asyncio
import json
import logging
import os
import runpy
import subprocess
import sys

import httpx2
import pytest

from app.mcp_client import discover_mcp
from test_app import cases_by_letter, client, execute


ENDPOINT = "https://34-38-10-198.sslip.io/mcp"
SECRET = "synthetic-mcp-test-credential-DO-NOT-USE"
MODERN = "2026-07-28"
LEGACY = "2024-11-05"


class RemotePeer:
    """Minimal real JSON-RPC peer; never replaces the SDK session/client."""

    def __init__(self, *, modern=False, capabilities=None, echo=False, paginate=False):
        self.modern = modern
        self.capabilities = capabilities if capabilities is not None else {
            "tools": {}, "resources": {}, "prompts": {}}
        self.echo = echo
        self.paginate = paginate
        self.requests = []
        self.messages = []
        self.factory_options = []

    def client_factory(self, **kwargs):
        self.factory_options.append(kwargs)
        return httpx2.AsyncClient(transport=httpx2.MockTransport(self.respond), **kwargs)

    def respond(self, request):
        self.requests.append(request)
        if request.method != "POST":
            return httpx2.Response(405)
        body = json.loads(request.content)
        self.messages.append(body)
        method = body["method"]
        if "id" not in body:
            return httpx2.Response(202)
        if method == "server/discover":
            if not self.modern:
                return self.error(body, -32601, "Nur Legacy-Handschlag unterstützt")
            result = {"supportedVersions": [MODERN], "capabilities": self.capabilities,
                      "_meta": {"serverInfo": {"name": "Synthetischer Prüfserver", "version": "1"}}}
        elif method == "initialize":
            result = {"protocolVersion": LEGACY, "capabilities": self.capabilities,
                      "serverInfo": {"name": "Synthetischer Prüfserver", "version": "1"}}
        elif method == "tools/list":
            suffix = "2" if body.get("params", {}).get("cursor") else "1"
            name = "synthetic_review_" + suffix
            result = {"tools": [{"name": name, "description": "Synthetisches Testwerkzeug",
                       "inputSchema": {"type": "object", "properties": {
                           "synthetic_text": {"type": "string"}}, "required": ["synthetic_text"]}}]}
            if self.paginate and suffix == "1":
                result["nextCursor"] = "synthetic-next-page"
            if self.echo:
                result["tools"][0]["description"] = "Untrusted echo: " + SECRET
                result["tools"][0]["inputSchema"]["properties"][SECRET] = {"default": SECRET}
        elif method == "resources/list":
            result = {"resources": [{"uri": "synthetic://source", "name": "Synthetische Quelle"}]}
        elif method == "resources/templates/list":
            result = {"resourceTemplates": [{"uriTemplate": "synthetic://source/{id}",
                                             "name": "Synthetische Vorlage"}]}
        elif method == "prompts/list":
            result = {"prompts": [{"name": "synthetic_prompt", "description": "Testvorlage"}]}
        else:
            return self.error(body, -32601, "Unerlaubte Testmethode: " + method)
        if self.modern:
            result.update(resultType="complete", cacheScope="private", ttlMs=0)
        return httpx2.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    @staticmethod
    def error(body, code, message):
        return httpx2.Response(200, json={"jsonrpc": "2.0", "id": body["id"],
                                         "error": {"code": code, "message": message}})

    @property
    def methods(self):
        return [message["method"] for message in self.messages]


def discover(monkeypatch, peer, **kwargs):
    monkeypatch.setenv("MCP_API_KEY", SECRET)
    return asyncio.run(discover_mcp(http_client_factory=peer.client_factory,
                                   timeout_seconds=1.0, **kwargs))


def test_missing_key_never_constructs_a_network_client(monkeypatch):
    monkeypatch.delenv("MCP_API_KEY", raising=False)

    def forbidden(**kwargs):
        pytest.fail("Discovery darf ohne MCP_API_KEY keine Verbindung öffnen")

    result = asyncio.run(discover_mcp(http_client_factory=forbidden))
    assert result["status"] == "not_configured"
    assert result["tools"] == []


@pytest.mark.parametrize("modern", [False, True], ids=["legacy-initialize", "modern-discover"])
def test_official_sdk_negotiates_and_discovers_without_tool_invocation(monkeypatch, modern):
    peer = RemotePeer(modern=modern)
    result = discover(monkeypatch, peer)
    assert result["status"] == "connected", result
    assert result["protocol_version"] == (MODERN if modern else LEGACY)
    assert result["tools"][0]["name"] == "synthetic_review_1"
    assert result["tools"][0]["inputSchema"]["required"] == ["synthetic_text"]
    assert result["resources"][0]["uri"] == "synthetic://source"
    assert result["resource_templates"][0]["uriTemplate"] == "synthetic://source/{id}"
    assert result["prompts"][0]["name"] == "synthetic_prompt"
    assert peer.methods[0] == "server/discover"
    assert ("initialize" in peer.methods) is not modern
    assert not set(peer.methods) & {"tools/call", "resources/read", "prompts/get"}
    assert all(str(req.url) == ENDPOINT for req in peer.requests)
    assert all(req.headers["x-api-key"] == SECRET for req in peer.requests)
    assert all("authorization" not in req.headers for req in peer.requests)
    assert all(SECRET not in json.dumps(message) for message in peer.messages)
    options = peer.factory_options[0]
    assert options["trust_env"] is False
    assert options["follow_redirects"] is False


def test_pagination_preserves_actual_tool_schemas(monkeypatch):
    peer = RemotePeer(paginate=True, capabilities={"tools": {}})
    result = discover(monkeypatch, peer)
    assert result["status"] == "connected", result
    assert [tool["name"] for tool in result["tools"]] == ["synthetic_review_1", "synthetic_review_2"]
    calls = [message for message in peer.messages if message["method"] == "tools/list"]
    assert calls[1]["params"]["cursor"] == "synthetic-next-page"


@pytest.mark.parametrize("capabilities", [{}, {"tools": {}}])
def test_unadvertised_capabilities_are_not_requested(monkeypatch, capabilities):
    peer = RemotePeer(capabilities=capabilities)
    result = discover(monkeypatch, peer)
    assert result["status"] == "connected", result
    assert result["resources"] == result["resource_templates"] == result["prompts"] == []
    assert not set(peer.methods) & {"resources/list", "resources/templates/list", "prompts/list"}
    assert ("tools/list" in peer.methods) is ("tools" in capabilities)


def test_untrusted_catalog_cannot_echo_credential_in_nested_values_or_keys(monkeypatch):
    peer = RemotePeer(echo=True, capabilities={"tools": {}})
    result = discover(monkeypatch, peer)
    assert result["status"] == "connected", result
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_failure_is_safe_and_does_not_return_remote_body(monkeypatch, status):
    peer = RemotePeer()

    def denied(request):
        peer.requests.append(request)
        return httpx2.Response(status, text="Remote error echoes " + SECRET)

    peer.respond = denied
    result = discover(monkeypatch, peer)
    assert result["status"] == "authentication_failed", result
    assert SECRET not in json.dumps(result)
    assert result["tools"] == []


@pytest.mark.parametrize("error_type,expected", [
    (httpx2.ConnectTimeout, "timeout"), (httpx2.ReadTimeout, "timeout"),
    (httpx2.ConnectError, "unavailable"), (httpx2.RemoteProtocolError, "protocol_error"),
])
def test_transport_failure_is_safe(monkeypatch, error_type, expected):
    peer = RemotePeer()

    def failed(request):
        raise error_type("Untrusted transport message " + SECRET, request=request)

    peer.respond = failed
    result = discover(monkeypatch, peer)
    assert result["status"] == expected, result
    assert SECRET not in json.dumps(result)
    assert result["tools"] == []


@pytest.mark.parametrize("location", ["https://untrusted.invalid/mcp",
    "https://34-38-10-198.sslip.io/other", "http://34-38-10-198.sslip.io/mcp"])
def test_redirect_never_transmits_key_to_another_target(monkeypatch, location):
    peer = RemotePeer()

    def redirected(request):
        peer.requests.append(request)
        if str(request.url) == ENDPOINT:
            return httpx2.Response(307, headers={"Location": location})
        return httpx2.Response(500, text="Credential already leaked")

    peer.respond = redirected
    result = discover(monkeypatch, peer)
    assert result["status"] != "connected"
    assert peer.requests
    assert all(str(req.url) == ENDPOINT for req in peer.requests)
    assert SECRET not in json.dumps(result)


def test_malformed_server_result_is_a_safe_protocol_failure(monkeypatch):
    peer = RemotePeer(capabilities={"tools": {}})
    respond = peer.respond

    def malformed(request):
        if request.method == "POST":
            body = json.loads(request.content)
            if body["method"] == "tools/list":
                return httpx2.Response(200, json={"jsonrpc": "2.0", "id": body["id"],
                    "result": {"tools": "invalid " + SECRET}})
        return respond(request)

    peer.respond = malformed
    result = discover(monkeypatch, peer)
    assert result["status"] == "protocol_error", result
    assert SECRET not in json.dumps(result)


def test_partial_catalog_is_not_published_as_a_complete_discovery(monkeypatch):
    peer = RemotePeer()
    respond = peer.respond

    def failed_later(request):
        if request.method == "POST":
            body = json.loads(request.content)
            if body["method"] == "resources/list":
                return peer.error(body, -32603, "Synthetischer Katalogfehler " + SECRET)
        return respond(request)

    peer.respond = failed_later
    result = discover(monkeypatch, peer)
    assert "tools/list" in peer.methods
    assert result["status"] == "protocol_error"
    assert result["tools"] == result["resources"] == []
    assert SECRET not in json.dumps(result)


def test_repeated_pagination_cursor_fails_without_looping(monkeypatch):
    peer = RemotePeer(capabilities={"tools": {}}, paginate=True)
    respond = peer.respond

    def repeated_cursor(request):
        response = respond(request)
        if request.method == "POST":
            body = json.loads(request.content)
            if body["method"] == "tools/list":
                data = response.json()
                data["result"]["nextCursor"] = "synthetic-next-page"
                return httpx2.Response(200, json=data)
        return response

    peer.respond = repeated_cursor
    result = discover(monkeypatch, peer)
    assert result["status"] == "protocol_error"
    assert peer.methods.count("tools/list") == 2
    assert result["tools"] == []


def test_deadline_covers_an_unresponsive_protocol_request(monkeypatch):
    peer = RemotePeer()

    async def stalled(request):
        await asyncio.sleep(10)
        return httpx2.Response(500)

    peer.respond = stalled
    monkeypatch.setenv("MCP_API_KEY", SECRET)
    result = asyncio.run(discover_mcp(http_client_factory=peer.client_factory,
                                    timeout_seconds=0.02))
    assert result["status"] == "timeout"
    assert result["tools"] == []


def test_secret_echo_is_not_emitted_by_sdk_debug_logging(monkeypatch, caplog):
    peer = RemotePeer(echo=True, capabilities={"tools": {}})
    with caplog.at_level(logging.DEBUG):
        result = discover(monkeypatch, peer)
    assert result["status"] == "connected"
    assert SECRET not in caplog.text


@pytest.mark.parametrize("namespace", ["mcp", "httpx2", "httpcore2"])
def test_lazily_created_protocol_logger_cannot_leak_credential(monkeypatch, caplog, namespace):
    peer = RemotePeer(capabilities={"tools": {}})
    respond = peer.respond

    def late_logger(request):
        # HTTP transports may import lower-level protocol modules only when
        # the first connection is opened, after the logging guard was entered.
        logger = logging.getLogger(namespace + ".synthetic_lazy_connection")
        logger.debug("Remote echo %s", SECRET)
        try:
            raise RuntimeError("Remote exception echo " + SECRET)
        except RuntimeError:
            logger.exception("Synthetischer Protokollfehler")
        return respond(request)

    peer.respond = late_logger
    with caplog.at_level(logging.DEBUG):
        result = discover(monkeypatch, peer)
    assert result["status"] == "connected"
    assert SECRET not in caplog.text


def test_protocol_logging_from_an_unrelated_task_remains_available(monkeypatch, caplog):
    peer = RemotePeer(capabilities={"tools": {}})
    respond = peer.respond
    monkeypatch.setenv("MCP_API_KEY", SECRET)

    async def concurrent_discovery():
        started, logged = asyncio.Event(), asyncio.Event()

        async def during_request(request):
            started.set()
            await logged.wait()
            return respond(request)

        async def other_task():
            await started.wait()
            logging.getLogger("mcp.synthetic_unrelated_task").warning("Unabhängiges Taskprotokoll bleibt sichtbar")
            logged.set()

        peer.respond = during_request
        result, _ = await asyncio.gather(
            discover_mcp(http_client_factory=peer.client_factory, timeout_seconds=1.0), other_task())
        return result

    with caplog.at_level(logging.DEBUG):
        result = asyncio.run(concurrent_discovery())
    assert result["status"] == "connected"
    assert "Unabhängiges Taskprotokoll bleibt sichtbar" in caplog.text


def test_cli_redacts_echoed_secret_after_actual_sdk_discovery(monkeypatch, capsys):
    import app.mcp_client as adapter
    original = adapter.discover_mcp
    peer = RemotePeer(echo=True, capabilities={"tools": {}})
    monkeypatch.setenv("MCP_API_KEY", SECRET)

    async def offline_discover():
        return await original(http_client_factory=peer.client_factory, timeout_seconds=1.0)

    monkeypatch.setattr(adapter, "discover_mcp", offline_discover)
    with pytest.raises(SystemExit) as exit_:
        runpy.run_path("scripts/discover_mcp.py", run_name="__main__")
    assert exit_.value.code == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "connected"
    assert SECRET not in captured.out + captured.err


def test_mcp_failure_does_not_break_local_execution_or_leak_key_in_api_or_audit(client, monkeypatch):
    peer = RemotePeer()

    def unavailable(request):
        raise httpx2.ConnectError("Synthetic outage", request=request)

    peer.respond = unavailable
    assert discover(monkeypatch, peer)["status"] == "unavailable"
    run = execute(client, cases_by_letter(client)["A"])
    assert run["result"]["status"] == "FREIGABE_OFFEN"
    audit = client.get(f'/api/runs/{run["run_id"]}/audit').json()
    assert audit["integrity"]["valid"]
    assert SECRET not in json.dumps(audit)
    assert SECRET not in client.get("/api/config").text
    assert SECRET not in client.get("/assets/app.js").text


def test_cli_missing_key_reports_safe_configuration_status(monkeypatch):
    env = os.environ.copy()
    env.pop("MCP_API_KEY", None)
    result = subprocess.run([sys.executable, "scripts/discover_mcp.py"], env=env,
                            text=True, capture_output=True, timeout=10)
    payload = json.loads(result.stdout)
    assert payload["status"] == "not_configured"
    assert SECRET not in result.stdout + result.stderr
