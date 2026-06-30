import requests
import pytest

from app.ingestion.github_loader import (
    GitHubDocumentLoader,
    GitHubLoaderError,
    parse_github_file_url,
)


class FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, headers: dict[str, str], timeout: int) -> FakeResponse:
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return self.response


def test_parse_blob_url_builds_file_ref() -> None:
    file_ref = parse_github_file_url(
        "https://github.com/renanfulas/supportFAQagent/blob/main/README.md",
    )

    assert file_ref.owner == "renanfulas"
    assert file_ref.repo == "supportFAQagent"
    assert file_ref.ref == "main"
    assert file_ref.path == "README.md"
    assert (
        file_ref.contents_api_url
        == "https://api.github.com/repos/renanfulas/supportFAQagent/contents/README.md?ref=main"
    )


def test_parse_raw_url_builds_file_ref() -> None:
    file_ref = parse_github_file_url(
        "https://raw.githubusercontent.com/renanfulas/supportFAQagent/main/docs/navigation.md",
    )

    assert file_ref.owner == "renanfulas"
    assert file_ref.repo == "supportFAQagent"
    assert file_ref.ref == "main"
    assert file_ref.path == "docs/navigation.md"


def test_loader_fetches_file_via_contents_api() -> None:
    session = FakeSession(FakeResponse(200, "# Hello from GitHub\n"))
    loader = GitHubDocumentLoader(session=session)

    document = loader.load_document(
        "https://github.com/renanfulas/supportFAQagent/blob/main/README.md",
    )

    assert document.source == "https://github.com/renanfulas/supportFAQagent/blob/main/README.md"
    assert document.title == "Readme"
    assert document.content == "# Hello from GitHub"
    assert session.calls[0]["url"] == (
        "https://api.github.com/repos/renanfulas/supportFAQagent/contents/README.md?ref=main"
    )
    assert session.calls[0]["headers"]["Accept"] == "application/vnd.github.raw+json"


def test_loader_sends_bearer_token_when_provided() -> None:
    session = FakeSession(FakeResponse(200, "content"))
    loader = GitHubDocumentLoader(token="ghp_test", session=session)

    loader.load_document(
        "https://raw.githubusercontent.com/renanfulas/supportFAQagent/main/README.md",
    )

    assert session.calls[0]["headers"]["Authorization"] == "Bearer ghp_test"


@pytest.mark.parametrize("status_code", [403, 404, 500])
def test_loader_raises_helpful_error_for_failed_requests(status_code: int) -> None:
    session = FakeSession(FakeResponse(status_code, ""))
    loader = GitHubDocumentLoader(session=session)

    with pytest.raises(GitHubLoaderError):
        loader.load_document(
            "https://github.com/renanfulas/supportFAQagent/blob/main/README.md",
        )


def test_loader_rejects_non_file_github_html_url() -> None:
    with pytest.raises(GitHubLoaderError, match="blob"):
        parse_github_file_url("https://github.com/renanfulas/supportFAQagent")
