from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient) -> None:
    """health check 관련 동작을 검증한다."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_endpoint(client: TestClient) -> None:
    """readiness endpoint가 DB 연결 상태를 반영하는지 검증한다."""
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}
