import httpx

from dataforge.github_client import GitHubClient, languages_to_percent


def test_languages_to_percent_empty():
    assert languages_to_percent({}) == {}
    assert languages_to_percent({"Python": 0}) == {}


def test_languages_to_percent_rounds():
    assert languages_to_percent({"Python": 1, "SQL": 2}) == {"Python": 33.33, "SQL": 66.67}


def test_get_events_sends_only_pagination():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=[{"id": "1", "type": "PushEvent"}])

    client = GitHubClient()
    original = client._client
    client._client = httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(handler))
    try:
        payload = client.get_events("octocat", per_page=5)
    finally:
        client.close()
        original.close()

    assert payload == [{"id": "1", "type": "PushEvent"}]
    assert seen["path"] == "/users/octocat/events"
    assert seen["params"] == {"per_page": "5"}
    assert "since" not in seen["params"]


def test_client_context_reads_each_endpoint():
    payloads = {
        "/users/octocat": {"login": "octocat"},
        "/users/octocat/repos": [],
        "/repos/octocat/demo/languages": {"Python": 10},
        "/repos/octocat/demo/commits": [{"sha": "abc"}],
    }
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("authorization"))
        body = payloads.get(request.url.path)
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, json=body)

    with GitHubClient(token="test-token") as client:
        original = client._client
        client._client = httpx.Client(
            base_url="https://api.github.com",
            headers=original.headers,
            transport=httpx.MockTransport(handler),
        )
        try:
            assert client.get_user("octocat") == {"login": "octocat"}
            assert client.get_repos("octocat") == []
            assert client.get_repo_languages("octocat/demo") == {"Python": 10}
            assert client.get_commits("octocat/demo") == [{"sha": "abc"}]
        finally:
            original.close()

    assert seen_auth
    assert all(value == "Bearer test-token" for value in seen_auth)
