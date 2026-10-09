"""品名管理接口测试。"""

import pytest

from data.DB import GoodsNameTable


def auth(token):
    return {"x-token": token}


@pytest.mark.unit
@pytest.mark.controller
class TestGoodsNameController:
    def test_create_and_list_english_name_with_category(
        self, client, admin_token
    ):
        response = client.post(
            "/api/goods-names",
            json={"name": "SHOES", "lang": "en", "category": "鞋包"},
            headers=auth(admin_token),
        )

        assert response.status_code == 200
        assert response.get_json()["data"]["category"] == "鞋包"

        response = client.get(
            "/api/goods-names?lang=en", headers=auth(admin_token)
        )
        assert response.status_code == 200
        assert response.get_json()["data"] == [
            {
                "id": 1,
                "name": "SHOES",
                "lang": "en",
                "category": "鞋包",
                "create_date": response.get_json()["data"][0]["create_date"],
                "update_date": response.get_json()["data"][0]["update_date"],
            }
        ]

    def test_manual_create_rejects_case_insensitive_duplicate(
        self, client, admin_token
    ):
        client.post(
            "/api/goods-names",
            json={"name": "SHOES", "lang": "en", "category": "鞋包"},
            headers=auth(admin_token),
        )
        response = client.post(
            "/api/goods-names",
            json={"name": "shoes", "lang": "en", "category": "其他"},
            headers=auth(admin_token),
        )

        assert response.status_code == 409
        assert response.get_json()["code"] == 409

    def test_update_category_and_preserve_it_when_omitted(
        self, client, admin_token
    ):
        created = client.post(
            "/api/goods-names",
            json={"name": "SHOES", "lang": "en", "category": "鞋包"},
            headers=auth(admin_token),
        ).get_json()["data"]

        response = client.put(
            f"/api/goods-names/{created['id']}",
            json={"name": "TRAINER", "category": "运动鞋"},
            headers=auth(admin_token),
        )
        assert response.get_json()["data"]["category"] == "运动鞋"

        response = client.put(
            f"/api/goods-names/{created['id']}",
            json={"name": "SANDAL"},
            headers=auth(admin_token),
        )
        assert response.get_json()["data"]["category"] == "运动鞋"

    def test_import_skips_database_and_file_duplicates(
        self, client, admin_token
    ):
        client.post(
            "/api/goods-names",
            json={"name": "SHOES", "lang": "en", "category": "旧分类"},
            headers=auth(admin_token),
        )
        response = client.post(
            "/api/goods-names/import",
            json={
                "items": [
                    {"name": "shoes", "category": "鞋包"},
                    {"name": "TRAINER", "category": "鞋包"},
                    {"name": "trainer", "category": "其他"},
                    {"name": "SANDAL", "category": "鞋包"},
                ]
            },
            headers=auth(admin_token),
        )

        assert response.status_code == 200
        data = response.get_json()["data"]
        assert data["created_count"] == 2
        assert data["skipped_count"] == 2
        assert [item["reason"] for item in data["skipped"]] == [
            "already_exists",
            "duplicate_in_file",
        ]

    def test_invalid_import_does_not_write_partial_data(
        self, client, admin_token, setup_test_database
    ):
        response = client.post(
            "/api/goods-names/import",
            json={
                "items": [
                    {"name": "SHOES", "category": "鞋包"},
                    {"name": "TRAINER", "category": ""},
                ]
            },
            headers=auth(admin_token),
        )

        assert response.status_code == 400
        assert setup_test_database.query(GoodsNameTable).count() == 0

    def test_import_requires_admin(self, client, clerk_token):
        response = client.post(
            "/api/goods-names/import",
            json={"items": [{"name": "SHOES", "category": "鞋包"}]},
            headers=auth(clerk_token),
        )

        assert response.status_code == 403
