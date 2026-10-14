from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_forecast_endpoint():
    body = {
        "as_of": "2026-09-15",
        "budget": 250,
        "method": "blend",
        "transactions": [
            {"date": "2026-08-05", "amount": 200, "merchant": "FairPrice", "category": "Groceries"},
            {"date": "2026-09-02", "amount": 150, "merchant": "Chagee", "category": "Food"},
        ],
    }
    r = client.post("/forecast", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["spent_so_far"] == 150
    assert data["forecast_total"] == 250  # 150 + 200 * 15/30
    assert data["risk"]["alert"] is False


def test_rejects_negative_amount():
    r = client.post("/forecast", json={"transactions": [{"date": "2026-09-01", "amount": -5}]})
    assert r.status_code == 422
