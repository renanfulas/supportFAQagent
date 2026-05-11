from fastapi.testclient import TestClient

from app.main import create_app


def create_test_client() -> TestClient:
    return TestClient(create_app())
