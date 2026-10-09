"""海关编码映射接口测试。"""

import pytest

from data.DB import CustomsCodeTable


def auth(token):
    return {"x-token": token}


@pytest.mark.unit
@pytest.mark.controller
class TestCustomsCodeController:
    def test_create_and_list_mapping(self, client, admin_token):
        response = client.post(
            "/api/customs-codes",
            json={"name": "SHOES", "code": "6404199000"},
            headers=auth(admin_token),
        )
        assert response.status_code == 200

        response = client.get("/api/customs-codes", headers=auth(admin_token))
        data = response.get_json()["data"]
        assert [(item["name"], item["code"]) for item in data] == [
            ("SHOES", "6404199000")
        ]

    def test_import_creates_updates_and_skips(self, client, admin_token):
        client.post(
            "/api/customs-codes",
            json={"name": "SHOES", "code": "OLD"},
            headers=auth(admin_token),
        )
        response = client.post(
            "/api/customs-codes/import",
            json={
                "items": [
                    {"name": "shoes", "code": "6404199000"},
                    {"name": "BAG", "code": "4202210090"},
                    {"name": "bag", "code": "SECOND"},
                ]
            },
            headers=auth(admin_token),
        )

        assert response.status_code == 200
        data = response.get_json()["data"]
        assert data["created_count"] == 1
        assert data["updated_count"] == 1
        assert data["skipped_count"] == 1
        assert data["skipped"][0]["reason"] == "duplicate_in_file"

        records = client.get(
            "/api/customs-codes", headers=auth(admin_token)
        ).get_json()["data"]
        assert {item["name"]: item["code"] for item in records} == {
            "BAG": "4202210090",
            "shoes": "6404199000",
        }

    def test_import_skips_unchanged_mapping(self, client, admin_token):
        client.post(
            "/api/customs-codes",
            json={"name": "SHOES", "code": "6404199000"},
            headers=auth(admin_token),
        )
        response = client.post(
            "/api/customs-codes/import",
            json={"items": [{"name": "shoes", "code": "6404199000"}]},
            headers=auth(admin_token),
        )
        data = response.get_json()["data"]
        assert data["created_count"] == 0
        assert data["updated_count"] == 0
        assert data["skipped"][0]["reason"] == "unchanged"

    def test_invalid_import_is_atomic(
        self, client, admin_token, setup_test_database
    ):
        response = client.post(
            "/api/customs-codes/import",
            json={
                "items": [
                    {"name": "SHOES", "code": "6404199000"},
                    {"name": "BAG", "code": ""},
                ]
            },
            headers=auth(admin_token),
        )
        assert response.status_code == 400
        assert setup_test_database.query(CustomsCodeTable).count() == 0

    def test_import_requires_admin(self, client, clerk_token):
        response = client.post(
            "/api/customs-codes/import",
            json={"items": [{"name": "SHOES", "code": "6404199000"}]},
            headers=auth(clerk_token),
        )
        assert response.status_code == 403
