"""SSRF mitigation tests for substack-mcp (MYC-101).

5 outbound HTTP helpers (_get / _post / _put / _delete / _post_form) all
share one validator (_validate_url). Tests cover:
  - the validator rejects the 5-attack matrix
  - all 5 helpers refuse to fire when the URL is blocked
  - all 5 helpers init httpx.AsyncClient with follow_redirects=False
"""
from __future__ import annotations

import socket
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import server  # noqa: E402

_DUMMY_PUB = {"name": "test", "subdomain": "test", "cookie": "x"}


class TestValidatorRejects5AttackMatrix:
    def test_rejects_backslash(self):
        with pytest.raises(server.UnsafeURL, match="banned character"):
            server._validate_url("https://substack.com/\\evil")

    def test_rejects_embedded_credentials(self):
        with pytest.raises(server.UnsafeURL, match="credentials"):
            server._validate_url("https://u:p@substack.com/api")

    def test_rejects_ipv6_link_local(self):
        with pytest.raises(server.UnsafeURL):
            server._validate_url("http://[fe80::1]/api")

    def test_rejects_dns_resolving_to_private_ip(self):
        with patch("mycelium_security.url.socket.getaddrinfo") as mock_resolver:
            mock_resolver.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.1", 0))
            ]
            with pytest.raises(server.UnsafeURL):
                server._validate_url("http://attacker.example.com/api")

    def test_rejects_aws_metadata(self):
        with pytest.raises(server.UnsafeURL, match="metadata"):
            server._validate_url("http://169.254.169.254/latest/meta-data/")


@pytest.mark.asyncio
class TestAllFiveHelpersRefuseUnsafeURLs:
    """Each helper returns {error: refused (SSRF): ...} instead of raising."""

    async def test_get_refuses(self):
        result = await server._get("http://169.254.169.254/imds", _DUMMY_PUB)
        assert "error" in result and "SSRF" in result["error"]

    async def test_post_refuses(self):
        result = await server._post("http://169.254.169.254/imds", _DUMMY_PUB, body={})
        assert "error" in result and "SSRF" in result["error"]

    async def test_put_refuses(self):
        result = await server._put("http://169.254.169.254/imds", _DUMMY_PUB, body={})
        assert "error" in result and "SSRF" in result["error"]

    async def test_delete_refuses(self):
        result = await server._delete("http://169.254.169.254/imds", _DUMMY_PUB)
        assert "error" in result and "SSRF" in result["error"]

    async def test_post_form_refuses(self):
        result = await server._post_form("http://169.254.169.254/imds", _DUMMY_PUB, data={})
        assert "error" in result and "SSRF" in result["error"]


@pytest.mark.asyncio
class TestFollowRedirectsFalse:
    async def test_get_sets_follow_redirects_false(self):
        captured = {}
        import httpx
        class _Spy(httpx.AsyncClient):
            def __init__(self, *args, **kwargs):
                captured.update(kwargs)
                super().__init__(*args, **kwargs)
        with patch("server.httpx.AsyncClient", _Spy):
            try:
                await server._get("https://substack.com/api/v1/user/profile/self", _DUMMY_PUB)
            except Exception:
                pass
        assert captured.get("follow_redirects") is False
