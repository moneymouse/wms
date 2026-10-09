"""测试数据工厂"""

import time
from faker import Faker
from typing import Dict, Any, Optional

fake = Faker("zh_CN")


class UserFactory:
    """用户数据工厂"""

    @staticmethod
    def create_user_data(
        phone: Optional[str] = None,
        name: Optional[str] = None,
        password: str = "test123456",
        **kwargs,
    ) -> Dict[str, Any]:
        """创建用户数据"""
        return {
            "phone": phone or fake.phone_number(),
            "name": name or fake.name(),
            "password": password,
            **kwargs,
        }

    @staticmethod
    def create_admin_data() -> Dict[str, Any]:
        """创建管理员数据"""
        return UserFactory.create_user_data(
            phone="13800000001", name="管理员测试", password="admin123"
        )

    @staticmethod
    def create_store_manager_data() -> Dict[str, Any]:
        """创建店长数据"""
        return UserFactory.create_user_data(
            phone="13800000002", name="店长测试", password="manager123"
        )

    @staticmethod
    def create_employee_data() -> Dict[str, Any]:
        """创建员工数据"""
        return UserFactory.create_user_data(
            phone="13800000003", name="员工测试", password="employee123"
        )


class OrderFactory:
    """订单数据工厂"""

    @staticmethod
    def create_order_data(
        order_id: Optional[str] = None,
        customer_name: Optional[str] = None,
        receiver: Optional[str] = None,
        cargo_uid_list: Optional[list] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """创建订单数据"""
        return {
            "order_id": order_id or f"ORD{fake.random_number(digits=6)}",
            "customer_name": customer_name or fake.company(),
            "receiver": receiver or fake.name(),
            "receiver_phone": fake.phone_number(),
            "address": fake.address(),
            "city": fake.city(),
            "province": fake.province(),
            "country": "中国",
            "zip_code": fake.postcode(),
            "cargo_count": fake.random_int(min=1, max=5),
            "cargo_uid_list": cargo_uid_list if cargo_uid_list is not None else [],
            "tag_all": f"TAG{fake.random_number(digits=3)}",
            "order_date": time.strftime("%Y-%m-%d %H:%M"),
            **kwargs,
        }

    @staticmethod
    def create_test_order_data() -> Dict[str, Any]:
        """创建测试用订单数据"""
        return OrderFactory.create_order_data(
            order_id="TEST001", customer_name="测试客户", receiver="测试收件人"
        )


class CargoFactory:
    """货物数据工厂"""

    @staticmethod
    def create_cargo_data(
        origin_id: Optional[str] = None,
        transfer_id: Optional[str] = None,
        waybill_id: str = "AUTO",
        **kwargs,
    ) -> Dict[str, Any]:
        """创建货物数据"""
        # 明确区分：waybill_id="AUTO"表示自动生成，waybill_id=None表示无运单号
        actual_waybill = None
        if waybill_id == "AUTO":
            actual_waybill = f"WB{fake.random_number(digits=8)}"
        elif waybill_id is not None:
            actual_waybill = waybill_id

        return {
            "origin_id": origin_id or f"ORD{fake.random_number(digits=6)}-1",
            "transfer_id": transfer_id or f"TR{fake.random_number(digits=6)}",
            "waybill_id": actual_waybill,
            "weight": fake.pyfloat(min_value=0.1, max_value=10.0, right_digits=2),
            "count": fake.random_int(min=1, max=3),
            "status": 0,
            "tag": f"TAG{fake.random_number(digits=3)}_1",
            **kwargs,
        }

    @staticmethod
    def create_test_cargo_data() -> Dict[str, Any]:
        """创建测试用货物数据"""
        return CargoFactory.create_cargo_data(
            origin_id="TEST001-1", transfer_id="TR001", waybill_id="WB001"
        )


class CustomerFactory:
    """客户数据工厂"""

    @staticmethod
    def create_customer_data(
        customer_name: Optional[str] = None, receiver: Optional[str] = None, **kwargs
    ) -> Dict[str, Any]:
        """创建客户数据"""
        return {
            "customer_name": customer_name or fake.company(),
            "receiver": receiver or fake.name(),
            "receiver_phone": fake.phone_number(),
            "address": fake.address(),
            "city": fake.city(),
            "province": fake.province(),
            "country": "中国",
            "zip_code": fake.postcode(),
            **kwargs,
        }

    @staticmethod
    def create_customer_with_sensitive_data(
        customer_name: Optional[str] = None,
        phone: Optional[str] = None,
        wechat: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """创建包含敏感信息的完整客户数据"""
        data = CustomerFactory.create_customer_data(customer_name=customer_name, **kwargs)
        # 添加客户级别的敏感字段
        data["phone"] = phone or fake.phone_number()
        data["wechat"] = wechat or f"wx_{fake.user_name()}"
        return data


class FileFactory:
    """文件数据工厂"""

    @staticmethod
    def create_waybill_data(count: int = 3) -> list:
        """创建转运单数据"""
        return [
            {
                "transfer_id": f"TR{fake.random_number(digits=6)}",
                "waybill_id": f"WB{fake.random_number(digits=8)}",
            }
            for _ in range(count)
        ]

    @staticmethod
    def create_waybill_txt_content(waybill_data: list) -> str:
        """创建转运单txt文件内容"""
        lines = []
        for item in waybill_data:
            lines.append(f"{item['transfer_id']},{item['waybill_id']}")
        return "\n".join(lines)

    @staticmethod
    def create_waybill_excel_data(waybill_data: list) -> list:
        """创建转运单Excel数据"""
        return [
            {"a": item["transfer_id"], "b": item["waybill_id"]} for item in waybill_data
        ]


class AuthFactory:
    """认证相关数据工厂"""

    @staticmethod
    def create_register_data(
        phone: Optional[str] = None,
        name: Optional[str] = None,
        password: str = "test123456",
    ) -> Dict[str, Any]:
        """创建注册数据"""
        return {
            "phone": phone or fake.phone_number(),
            "name": name or fake.name(),
            "password": password,
        }

    @staticmethod
    def create_login_data(phone: str, password: str = "test123456") -> Dict[str, Any]:
        """创建登录数据"""
        return {"phone": phone, "password": password}

    @staticmethod
    def create_approve_data(role: str = "employee") -> Dict[str, Any]:
        """创建审核通过数据"""
        return {"role": role}

    @staticmethod
    def create_reject_data(remark: str = "不符合要求") -> Dict[str, Any]:
        """创建审核拒绝数据"""
        return {"remark": remark}


class ResponseFactory:
    """响应数据工厂"""

    @staticmethod
    def create_success_response(
        data: Any = None, msg: str = "success"
    ) -> Dict[str, Any]:
        """创建成功响应"""
        response = {"code": 200, "msg": msg}
        if data is not None:
            response["data"] = data
        return response

    @staticmethod
    def create_error_response(code: int, msg: str) -> Dict[str, Any]:
        """创建错误响应"""
        return {"code": code, "msg": msg}

    @staticmethod
    def create_paginated_response(
        data: list, total: int, page: int = 1, page_size: int = 30
    ) -> Dict[str, Any]:
        """创建分页响应"""
        return {
            "code": 200,
            "data": data,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
