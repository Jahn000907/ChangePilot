"""企业数据中心只读 API 的 Golden Seed 验收。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_data_center_reads_golden_seed_without_changing_counts() -> None:
    client = TestClient(create_app())
    before = client.get("/api/v1/data/summary")
    assert before.status_code == 200
    counts = before.json()
    assert counts["suppliers"] > 0
    assert counts["purchase_orders"] > 0

    for path in (
        "/api/v1/data/suppliers?search=SUP-001",
        "/api/v1/data/supplier-parts?part_number=BRG-6204-A",
        "/api/v1/data/inventory?part_number=BRG-6204-A",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()

    for collection, child_field in (
        ("purchase-orders", "lines"),
        ("production-orders", "requirements"),
        ("sales-orders", "lines"),
    ):
        rows = client.get(f"/api/v1/data/{collection}")
        assert rows.status_code == 200 and rows.json()
        number = rows.json()[0]["order_number"]
        detail = client.get(f"/api/v1/data/{collection}/{number}")
        assert detail.status_code == 200 and detail.json()[child_field]
        assert client.get(f"/api/v1/data/{collection}/missing").status_code == 404

    assert client.get("/api/v1/data/summary").json() == counts
