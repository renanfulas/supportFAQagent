import argparse

from app.ingestion.github_loader import GitHubDocumentLoader


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch a GitHub file through the official contents API.",
    )
    parser.add_argument("url", help="GitHub blob/raw/API URL for a file.")
    parser.add_argument(
        "--token",
        default=None,
        help="GitHub token for private repositories or higher rate limits.",
    )
    args = parser.parse_args()

    loader = GitHubDocumentLoader(token=args.token)
    document = loader.load_document(args.url)

    print(f"source={document.source}")
    print(f"title={document.title}")
    print(f"chars={len(document.content)}")
    print(document.content)


if __name__ == "__main__":
    main()
