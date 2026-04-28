"""allow 装饰器多角色权限判定测试"""

from flask import Flask, jsonify
import pytest

from Auth import allow, create_jwt


@pytest.mark.unit
def test_allow_passes_when_roles_intersect():
    app = Flask(__name__)

    @app.get("/_test")
    @allow(role=["admin", "finance"])
    def _endpoint():
        return jsonify({"code": 200})

    token = create_jwt(
        {
            "user_id": 1,
            "role": "worker",
            "roles": ["worker", "finance"],
        }
    )

    with app.test_client() as client:
        response = client.get("/_test", headers={"x-token": token})
        assert response.status_code == 200


@pytest.mark.unit
def test_allow_denies_when_no_role_intersection():
    app = Flask(__name__)

    @app.get("/_test")
    @allow(role=["admin", "finance"])
    def _endpoint():
        return jsonify({"code": 200})

    token = create_jwt({"user_id": 1, "role": "worker", "roles": ["worker"]})

    with app.test_client() as client:
        response = client.get("/_test", headers={"x-token": token})
        assert response.status_code == 403
