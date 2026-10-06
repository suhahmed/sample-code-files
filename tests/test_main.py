import pytest

from app.main import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_index(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "version" in r.get_json()


@pytest.mark.parametrize("path", ["/healthz", "/readyz"])
def test_probes(client, path):
    r = client.get(path)
    assert r.status_code == 200


def test_metrics(client):
    client.get("/")
    r = client.get("/metrics")
    assert r.status_code == 200
    assert b"app_requests_total" in r.data
