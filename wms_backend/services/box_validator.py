"""
Box Validator - 箱子有效性验证器

采用策略模式实现，符合开闭原则：
- 添加新的验证规则只需创建新的 BoxValidator 子类
- 不需要修改现有代码
"""

from abc import ABC, abstractmethod
from typing import List


class BoxValidator(ABC):
    """箱子验证器抽象基类"""

    @abstractmethod
    def is_valid(self, box: dict) -> bool:
        """检查箱子是否有效"""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """获取验证器名称"""
        pass

    def get_error_message(self) -> str:
        """获取验证失败时的错误信息"""
        return f"Failed validation: {self.get_name()}"


class WeightValidator(BoxValidator):
    """重量验证：只有称重过的箱子才有效

    业务规则：
    - weight 不为 None
    - weight > 0
    """

    def is_valid(self, box: dict) -> bool:
        weight = box.get("weight")
        return weight is not None and weight > 0

    def get_name(self) -> str:
        return "weight_check"

    def get_error_message(self) -> str:
        return "Box must be weighed (weight > 0)"


class BoxValidationChain:
    """验证链：可扩展添加新的验证规则

    使用示例：
        validator = BoxValidationChain()
        validator.add_validator(WeightValidator())
        validator.add_validator(SomeOtherValidator())

        if validator.is_valid(box):
            # 箱子有效

        valid_boxes = validator.filter_valid_boxes(boxes)
    """

    def __init__(self):
        self._validators: List[BoxValidator] = []

    def add_validator(self, validator: BoxValidator) -> "BoxValidationChain":
        """添加验证器，支持链式调用"""
        self._validators.append(validator)
        return self

    def remove_validator(self, name: str) -> "BoxValidationChain":
        """移除指定名称的验证器"""
        self._validators = [v for v in self._validators if v.get_name() != name]
        return self

    def is_valid(self, box: dict) -> bool:
        """检查箱子是否通过所有验证"""
        return all(v.is_valid(box) for v in self._validators)

    def validate(self, box: dict) -> dict:
        """验证箱子并返回详细结果

        Returns:
            {
                "valid": bool,
                "errors": [{"validator": str, "message": str}, ...]
            }
        """
        errors = []
        for validator in self._validators:
            if not validator.is_valid(box):
                errors.append(
                    {
                        "validator": validator.get_name(),
                        "message": validator.get_error_message(),
                    }
                )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
        }

    def filter_valid_boxes(self, boxes: List[dict]) -> List[dict]:
        """过滤出所有有效的箱子"""
        return [b for b in boxes if self.is_valid(b)]

    def get_validators(self) -> List[str]:
        """获取所有验证器名称"""
        return [v.get_name() for v in self._validators]


# ---------------------------------------------------------------------------
# Default validator chain - 默认验证链
# ---------------------------------------------------------------------------

# 当前只有重量验证，未来可扩展
# 例如：可以添加 ItemNameValidator, WorkerValidator 等
default_validator = BoxValidationChain().add_validator(WeightValidator())


# ---------------------------------------------------------------------------
# 扩展示例（供未来参考）
# ---------------------------------------------------------------------------

# class ItemNameValidator(BoxValidator):
#     """品名验证：品名不能为空"""
#
#     def is_valid(self, box: dict) -> bool:
#         item_name = box.get("item_name")
#         return item_name is not None and len(str(item_name).strip()) > 0
#
#     def get_name(self) -> str:
#         return "item_name_check"

# class WorkerValidator(BoxValidator):
#     """工人验证：必须有至少一个打包工人"""
#
#     def is_valid(self, box: dict) -> bool:
#         workers = box.get("workers", [])
#         return len(workers) > 0
#
#     def get_name(self) -> str:
#         return "worker_check"
