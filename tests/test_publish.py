import json
import time

import httpx
import pytest

from sixwords.publish import PublishError, SupabaseClient

BASE_URL = "https://example.supabase.co"
ANON_KEY = "anon-key"


class FakeSupabase:
    """Records requests and plays back canned responses per path."""

    def __init__(self):
        self.requests = []
        self.responses = {}

    def respond(self, path, status_code=200, body=None):
        self.responses[path] = (status_code, body if body is not None else {})

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status_code, body = self.responses.get(request.url.path, (200, {}))
        return httpx.Response(status_code, json=body)


@pytest.fixture()
def fake():
    return FakeSupabase()


def _client(fake, tmp_path):
    return SupabaseClient(
        base_url=BASE_URL,
        anon_key=ANON_KEY,
        credentials_path=tmp_path / "credentials.json",
        transport=httpx.MockTransport(fake.handler),
    )


def _grant(access="access-token", refresh="refresh-token", expires_in=3600):
    return {"access_token": access, "refresh_token": refresh, "expires_in": expires_in}


def _sign_in(client, fake):
    fake.respond("/auth/v1/verify", body=_grant())
    client.verify_code("adam@example.com", "123456")


def test_unconfigured_client_raises(monkeypatch, tmp_path):
    import sixwords.publish as publish_mod

    monkeypatch.setattr(publish_mod, "DEFAULT_SUPABASE_URL", "")
    monkeypatch.setattr(publish_mod, "DEFAULT_SUPABASE_ANON_KEY", "")
    monkeypatch.delenv("SIXWORDS_SUPABASE_URL", raising=False)
    monkeypatch.delenv("SIXWORDS_SUPABASE_ANON_KEY", raising=False)
    with pytest.raises(PublishError, match="not configured"):
        SupabaseClient(credentials_path=tmp_path / "credentials.json")


def test_login_flow_saves_session(fake, tmp_path):
    client = _client(fake, tmp_path)
    client.request_code("adam@example.com")
    _sign_in(client, fake)

    otp_request = fake.requests[0]
    assert otp_request.url.path == "/auth/v1/otp"
    assert otp_request.headers["apikey"] == ANON_KEY
    assert json.loads(otp_request.content)["email"] == "adam@example.com"

    saved = json.loads((tmp_path / "credentials.json").read_text())
    assert saved["access_token"] == "access-token"
    assert saved["email"] == "adam@example.com"
    assert client.signed_in_email() == "adam@example.com"


def test_login_with_pasted_link_verifies_token_hash(fake, tmp_path):
    client = _client(fake, tmp_path)
    fake.respond("/auth/v1/verify", body=_grant())
    link = f"{BASE_URL}/auth/v1/verify?token=abc123&type=magiclink&redirect_to=x"
    client.verify_code("adam@example.com", link)

    verify = fake.requests[-1]
    assert json.loads(verify.content) == {"type": "magiclink", "token_hash": "abc123"}
    assert client.signed_in_email() == "adam@example.com"


def test_login_with_clicked_redirect_url_saves_tokens(fake, tmp_path):
    client = _client(fake, tmp_path)
    url = "http://localhost:3000/#access_token=frag-access&refresh_token=frag-refresh&expires_at=1785893271&token_type=bearer&type=signup"
    client.verify_code("adam@example.com", url)

    assert fake.requests == []  # tokens come from the URL; no server call
    saved = json.loads((tmp_path / "credentials.json").read_text())
    assert saved["access_token"] == "frag-access"
    assert saved["refresh_token"] == "frag-refresh"
    assert saved["expires_at"] == 1785893271


def test_login_with_tokenless_link_raises(fake, tmp_path):
    client = _client(fake, tmp_path)
    with pytest.raises(PublishError, match="no sign-in token"):
        client.verify_code("adam@example.com", "https://example.com/?type=magiclink")


def test_publish_sends_bearer_token_and_payload(fake, tmp_path):
    client = _client(fake, tmp_path)
    _sign_in(client, fake)
    fake.respond("/rest/v1/ideas", status_code=201)

    url = client.publish(slug="shoes", title="Shoes", story="six words", doc={"a": 1})

    insert = fake.requests[-1]
    assert insert.url.path == "/rest/v1/ideas"
    assert insert.headers["Authorization"] == "Bearer access-token"
    assert json.loads(insert.content) == {
        "slug": "shoes",
        "title": "Shoes",
        "story": "six words",
        "doc": {"a": 1},
    }
    assert url == "https://sixwordidea.com/ideas/shoes.json"


def test_publish_without_session_raises(fake, tmp_path):
    client = _client(fake, tmp_path)
    with pytest.raises(PublishError, match="sixwords login"):
        client.publish(slug="s", title="t", story="w", doc={})


def test_publish_refreshes_expired_session(fake, tmp_path):
    client = _client(fake, tmp_path)
    _sign_in(client, fake)
    session = json.loads((tmp_path / "credentials.json").read_text())
    session["expires_at"] = time.time() - 10
    (tmp_path / "credentials.json").write_text(json.dumps(session))

    fake.respond("/auth/v1/token", body=_grant(access="fresh-token"))
    fake.respond("/rest/v1/ideas", status_code=201)
    client.publish(slug="s", title="t", story="w", doc={})

    insert = fake.requests[-1]
    assert insert.headers["Authorization"] == "Bearer fresh-token"


def test_publish_duplicate_slug(fake, tmp_path):
    client = _client(fake, tmp_path)
    _sign_in(client, fake)
    fake.respond("/rest/v1/ideas", status_code=409)
    with pytest.raises(PublishError, match="already published"):
        client.publish(slug="shoes", title="t", story="w", doc={})


def test_list_ideas(fake, tmp_path):
    ideas = [{"slug": "shoes", "title": "Shoes", "story": "six words", "doc": {}}]
    fake.respond("/rest/v1/ideas", body=ideas)
    assert _client(fake, tmp_path).list_ideas() == ideas
