"""MCP business adapter: real user permissions and atomic mutation receipts."""
import hashlib
import json
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError

from Auth import get_payload_roles
from data.database import SessionFactory
from data.mcp import IDEMPOTENCY_CONSTRAINT, McpIdempotencyTable
from services import order_service, packing_list_service, tracking_service
from services.receivable_service import normalize_quote_payload
from utils.audit import record_audit

TOOL_SCOPES = {
    "create_order": "orders:create",
    "list_orders": "orders:list",
    "get_order": "orders:read",
    "get_tracking": "tracking:read",
    "create_packing_list": "packing_lists:create",
}
LIST_ROLES = {"admin", "store_manager", "salesperson", "clerk"}
PACKING_ROLES = {"admin", "store_manager", "salesperson", "worker", "employee"}


class BusinessInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class QuoteInput(BusinessInput):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False,
                              json_schema_extra={"anyOf": [{"required": ["unit_price"]}, {"required": ["quoted_price"]}]})
    unit_price: Decimal | None = Field(default=None, ge=0, description="每公斤单价，优先于quoted_price")
    quoted_price: Decimal | None = Field(default=None, ge=0, description="每公斤单价的兼容字段")
    surcharge: Decimal = Field(default=Decimal("0"), ge=0)
    quote_remark: str | None = None

    @model_validator(mode="after")
    def require_price(self):
        if self.unit_price is None and self.quoted_price is None:
            raise ValueError("unit_price or quoted_price is required")
        return self


class OrderInput(BusinessInput):
    customer_id: int | None = Field(default=None, gt=0)
    customer_name: str | None = Field(default=None, max_length=256)
    order_id: str | None = Field(default=None, max_length=128)
    transportation: str | None = Field(default=None, max_length=128)
    receiver: str | None = Field(default=None, max_length=256)
    receiver_phone: str | None = Field(default=None, max_length=64)
    mail: str | None = Field(default=None, max_length=256)
    country: str | None = Field(default=None, max_length=128)
    province: str | None = Field(default=None, max_length=128)
    city: str | None = Field(default=None, max_length=128)
    address: str | None = None
    en_name: str | None = Field(default=None, max_length=256)
    cn_name: str | None = Field(default=None, max_length=256)
    total_weight: float | None = Field(default=None, ge=0)
    post_code: str | None = Field(default=None, max_length=64)
    zip_code: str | None = Field(default=None, max_length=64)
    order_date: str | None = Field(default=None, max_length=32)
    tag_all: str | None = Field(default=None, max_length=256)
    salesman_id: int | None = Field(default=None, gt=0, description="业务负责人，操作人由OAuth身份决定")
    quote: QuoteInput | None = None

class CreateOrderInput(BusinessInput):
    order: OrderInput
    idempotency_key: str = Field(min_length=1, max_length=128)


class ListOrdersInput(BusinessInput):
    p: int = Field(default=1, description="页码，最小为1")
    s: int = Field(default=30, description="每页数量，限制在1到200之间")
    sf: str = Field(default="create_date", max_length=64)
    so: int = Field(default=1, ge=0, le=1)
    q: str = ""


class GetOrderInput(BusinessInput):
    uid: str = Field(min_length=1, max_length=32)


class GetTrackingInput(BusinessInput):
    order_id: str = Field(min_length=1, max_length=128, description="业务订单号，精确匹配未归档订单；不是内部UID或转单号")

    @field_validator("order_id", mode="before")
    @classmethod
    def strip_order_id(cls, value):
        return value.strip() if isinstance(value, str) else value


class CreatePackingListInput(BusinessInput):
    idempotency_key: str = Field(min_length=1, max_length=128)
    mark: str | None = Field(default=None, max_length=64)
    list_number: str | None = Field(default=None, max_length=64)
    customer_id: int | None = Field(default=None, gt=0)
    photos: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_mark(self):
        if not (self.list_number or self.mark or "").strip():
            raise ValueError("mark is required")
        return self


INPUT_MODELS = {
    "create_order": CreateOrderInput,
    "list_orders": ListOrdersInput,
    "get_order": GetOrderInput,
    "get_tracking": GetTrackingInput,
    "create_packing_list": CreatePackingListInput,
}


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


def _normalized_arguments(tool_name, arguments):
    model = INPUT_MODELS[tool_name].model_validate(arguments)
    if tool_name == "create_order":
        record = model.order.model_dump(exclude_none=True)
        if record.get("quote") is not None:
            record["quote"] = normalize_quote_payload(record["quote"])
        return record, model.idempotency_key
    if tool_name == "create_packing_list":
        return {"mark": (model.list_number or model.mark).strip().upper(),
                "customer_id": model.customer_id, "photos": model.photos}, model.idempotency_key
    return model.model_dump(), None


def _authorized(tool_name, operator):
    roles = set(get_payload_roles(operator))
    if tool_name == "list_orders":
        return bool(roles & LIST_ROLES)
    if tool_name == "create_packing_list":
        return bool(roles & PACKING_ROLES)
    # Other reads rely on the approved OAuth identity and their required scope.
    # Order creation/detail match REST's allow() without role restrictions.
    return True


def _identity(principal, tool_name, key):
    return {"user_id": principal["user_id"],
            "client_id_hash": _hash(principal["client_id"]),
            "tool_name": tool_name, "key_hash": _hash(key)}


def _audit(session, principal, tool_name, result, *, replay=False, target_id=None):
    target_type = "packing_list" if tool_name == "create_packing_list" else "order"
    data = result.get("data")
    target = target_id or result.get("uid") or (data.get("uid") if isinstance(data, dict) else None)
    event = {"create_order": "order_created", "create_packing_list": "packing_created"}.get(tool_name, "mcp_tool_call")
    record_audit(
        "mcp_tool_replay" if replay else event, target_type, target_id=target,
        action=tool_name, after_data={"code": result.get("code"), "uid": target},
        operator_payload=principal["operator_payload"], session=session,
        metadata={"transport": "mcp", "client_id": principal["client_id"],
                  "tool_name": tool_name, "replay": replay},
    )


def _idempotency_duplicate(exc):
    """Never treat a business integrity failure as a replay."""
    message = str(exc.orig)
    if IDEMPOTENCY_CONSTRAINT in message:
        return True
    return "UNIQUE constraint failed: mcp_idempotency.user_id, mcp_idempotency.client_id_hash, mcp_idempotency.tool_name, mcp_idempotency.key_hash" in message


def _read_replay(principal, tool_name, identity, arguments_hash):
    # A new session avoids MySQL REPEATABLE READ retaining a pre-conflict snapshot.
    with SessionFactory() as session:
        row = session.query(McpIdempotencyTable).filter_by(**identity).one_or_none()
        if row is None or row.result_json is None:
            raise RuntimeError("Idempotency receipt is not complete")
        if row.arguments_hash != arguments_hash:
            return {"code": 409, "msg": "idempotency_key was already used with different arguments"}
        result = json.loads(row.result_json)
        _audit(session, principal, tool_name, result, replay=True)
        session.commit()
        return result


def execute_tool(tool_name, arguments, principal):
    """Run synchronously in the MCP thread pool; identity never comes from inputs."""
    if tool_name not in INPUT_MODELS:
        return {"code": 404, "msg": "Unknown tool"}
    operator = principal["operator_payload"]
    if not _authorized(tool_name, operator):
        return {"code": 403, "msg": "当前用户角色无权执行此操作"}
    args, key = _normalized_arguments(tool_name, arguments)
    if key is None:
        if tool_name == "list_orders":
            result = order_service.list_orders(**args)
        elif tool_name == "get_tracking":
            result = tracking_service.get_tracking(**args)
        else:
            result = order_service.get_order(args["uid"], operator)
            if result.get("code") == 200 and result.get("data") is None:
                result = {"code": 404, "msg": "订单不存在", "data": None}
        result = json.loads(_json(result))
        with SessionFactory() as session:
            _audit(session, principal, tool_name, result, target_id=args.get("uid") or result.get("order_uid"))
            session.commit()
        return result
    identity = _identity(principal, tool_name, key)
    arguments_hash = _hash(_json(args))
    try:
        with SessionFactory() as session:
            receipt = McpIdempotencyTable(**identity, arguments_hash=arguments_hash)
            session.add(receipt)
            try:
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                if not _idempotency_duplicate(exc):
                    raise
                return _read_replay(principal, tool_name, identity, arguments_hash)
            if tool_name == "create_order":
                result = order_service.create_order(args, operator, session=session)
            else:
                data = packing_list_service.create_packing_list(
                    creator_id=principal["user_id"], session=session, **args)
                result = {"code": 200, "data": data}
            if result.get("code") != 200:
                session.rollback()
                return result
            result = json.loads(_json(result))
            _audit(session, principal, tool_name, result)
            receipt.result_json = _json(result)
            session.commit()
            return result
    except Exception as exc:
        # BusinessError is supplied by the shared business service, independent
        # of Flask response objects. Unexpected failures are handled by the SDK.
        if isinstance(exc, getattr(order_service, "BusinessError", ())):
            return {"code": exc.code, "msg": exc.msg}
        if isinstance(exc, ValueError) and tool_name == "create_packing_list":
            return {"code": 404, "msg": str(exc)}
        raise
