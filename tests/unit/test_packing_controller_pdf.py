"""装箱单 PDF 导出接口测试"""

from io import BytesIO
from unittest.mock import patch

import pytest


@pytest.mark.unit
@pytest.mark.controller
@pytest.mark.packing
class TestPackingControllerPdf:
    def test_batch_export_packing_lists_pdf_success(self, client, admin_token):
        detail_1 = {
            "uid": "pl-1",
            "list_number": "PL-001",
            "customer_name": "客户A",
            "boxes": [{"uid": "b1"}, {"uid": "b2"}],
        }
        detail_2 = {
            "uid": "pl-2",
            "list_number": "PL-002",
            "customer_name": "客户B",
            "boxes": [{"uid": "c1"}, {"uid": "c2"}],
        }
        payload = {
            "selections": [
                {"packing_list_uid": "pl-1", "box_uids": ["b2"]},
                {"packing_list_uid": "pl-2", "box_uids": ["c1", "c2"]},
            ]
        }

        with patch(
            "controllers.packing_controller.packing_list_service.get_packing_list",
            side_effect=[detail_1, detail_2],
        ), patch(
            "controllers.packing_controller.build_packing_lists_pdf",
            return_value=BytesIO(b"%PDF-1.4 fake"),
        ) as mock_build:
            response = client.post(
                "/api/packing-lists/pdf",
                json=payload,
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        assert response.status_code == 200
        assert response.mimetype == "application/pdf"
        called_details = mock_build.call_args.args[0]
        assert len(called_details) == 2
        assert [box["uid"] for box in called_details[0]["boxes"]] == ["b2"]
        assert [box["uid"] for box in called_details[1]["boxes"]] == ["c1", "c2"]

    def test_batch_export_packing_lists_pdf_missing_selections(
        self, client, admin_token
    ):
        response = client.post(
            "/api/packing-lists/pdf",
            json={},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data["code"] == 400
        assert "selections is required" in data["msg"]
