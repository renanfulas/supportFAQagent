from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote, urlparse

import requests

from app.ingestion.models import KnowledgeDocument


DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_USER_AGENT = "supportFAQagent-github-loader/0.1"


class GitHubLoaderError(RuntimeError):
    """Raised when GitHub content cannot be fetched safely."""


@dataclass(frozen=True)
class GitHubFileRef:
    owner: str
    repo: str
    ref: str
    path: str

    @property
    def contents_api_url(self) -> str:
        encoded_path = quote(self.path, safe="/")
        return (
            f"https://api.github.com/repos/{self.owner}/{self.repo}/contents/"
            f"{encoded_path}?ref={quote(self.ref, safe='')}"
        )

    @property
    def source_url(self) -> str:
        return (
            f"https://github.com/{self.owner}/{self.repo}/blob/{self.ref}/{self.path}"
        )

    @property
    def title(self) -> str:
        filename = self.path.rsplit("/", 1)[-1]
        stem = filename.rsplit(".", 1)[0]
        return stem.replace("-", " ").replace("_", " ").title()


def parse_github_file_url(url: str) -> GitHubFileRef:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    parts = [part for part in parsed.path.split("/") if part]

    if host == "github.com":
        if len(parts) < 5 or parts[2] != "blob":
            raise GitHubLoaderError(
                "GitHub HTML URLs must use /owner/repo/blob/<ref>/<path>.",
            )
        return GitHubFileRef(
            owner=parts[0],
            repo=parts[1],
            ref=parts[3],
            path="/".join(parts[4:]),
        )

    if host == "raw.githubusercontent.com":
        if len(parts) < 4:
            raise GitHubLoaderError(
                "Raw GitHub URLs must use /owner/repo/<ref>/<path>.",
            )
        return GitHubFileRef(
            owner=parts[0],
            repo=parts[1],
            ref=parts[2],
            path="/".join(parts[3:]),
        )

    if host == "api.github.com":
        if len(parts) < 6 or parts[0:4] != ["repos", parts[1], parts[2], "contents"]:
            raise GitHubLoaderError(
                "GitHub API URLs must use /repos/{owner}/{repo}/contents/{path}.",
            )
        owner = parts[1]
        repo = parts[2]
        path = "/".join(parts[4:])
        ref = "main"
        if parsed.query:
            for query_item in parsed.query.split("&"):
                key, _, value = query_item.partition("=")
                if key == "ref" and value:
                    ref = value
                    break
        return GitHubFileRef(owner=owner, repo=repo, ref=ref, path=path)

    raise GitHubLoaderError(
        "Unsupported GitHub URL. Use github.com/blob, raw.githubusercontent.com, or the contents API.",
    )


class GitHubDocumentLoader:
    def __init__(
        self,
        token: str | None = None,
        session: requests.Session | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._token = token.strip() if token else None
        self._session = session or requests.Session()
        self._timeout_seconds = timeout_seconds

    def load_document(self, url: str) -> KnowledgeDocument:
        file_ref = parse_github_file_url(url)
        content = self._fetch_raw_contents(file_ref)
        return KnowledgeDocument(
            source=file_ref.source_url,
            title=file_ref.title,
            content=content.strip(),
        )

    def load_documents(self, urls: Iterable[str]) -> list[KnowledgeDocument]:
        return [self.load_document(url) for url in urls]

    def _fetch_raw_contents(self, file_ref: GitHubFileRef) -> str:
        headers = {
            "Accept": "application/vnd.github.raw+json",
            "User-Agent": DEFAULT_USER_AGENT,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        response = self._session.get(
            file_ref.contents_api_url,
            headers=headers,
            timeout=self._timeout_seconds,
        )

        if response.status_code == 404:
            raise GitHubLoaderError(
                f"GitHub file not found: {file_ref.source_url}",
            )

        if response.status_code == 403:
            raise GitHubLoaderError(
                "GitHub denied access. Use a repository contents URL/path and provide a token when the repository is private or rate limited.",
            )

        if response.status_code >= 400:
            raise GitHubLoaderError(
                f"GitHub request failed with status {response.status_code}.",
            )

        text = response.text
        if not text.strip():
            raise GitHubLoaderError(
                f"GitHub returned empty content for {file_ref.source_url}",
            )
        return text
