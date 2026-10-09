"""Remote WMS MCP resource server, run with ``uvicorn mcp_server:app``.

OAuth authorization remains in Flask. This module never imports the REST app.
"""
import json
import logging
import os
from functools import partial
from urllib.parse import urlsplit

import anyio
from pydantic import ValidationError
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.routes import build_resource_metadata_url, create_protected_resource_routes
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

from services import mcp_service

logger = logging.getLogger(__name__)

OUTPUT_SCHEMA = {
    "type": "object", "required": ["code"],
    "properties": {
        "code": {"type": "integer"}, "msg": {"type": "string"},
        "uid": {"type": "string"}, "data": {},
        "total": {"type": "integer"},
    },
    "additionalProperties": True,
}
TRACKING_OUTPUT_SCHEMA = {
    **OUTPUT_SCHEMA,
    "properties": {
        **OUTPUT_SCHEMA["properties"],
        "order_id": {"type": "string", "description": "精确匹配的业务订单号"},
        "order_uid": {"type": "string", "description": "匹配订单的内部UID"},
        "queried_at": {"type": "string", "format": "date-time", "description": "本次查询时间（UTC），不是承运商更新时间"},
        "tracking_complete": {"type": "boolean", "description": "有转单号的物流查询是否全部成功；无转单号不计失败"},
        "data": {
            "type": "array",
            "description": "订单下未归档包裹的精简详情及物流信息",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["uid", "box_number", "item_name", "weight", "transfer_id", "waybill_id",
                             "warehouse_status", "warehouse_status_text", "tracking"],
                "properties": {
                    "uid": {"type": "string", "description": "包裹内部UID"},
                    "box_number": {"type": ["integer", "null"], "description": "箱号"},
                    "item_name": {"type": ["string", "null"], "description": "品名"},
                    "weight": {"type": ["number", "null"], "description": "重量"},
                    "transfer_id": {"type": ["string", "null"], "description": "原单号"},
                    "waybill_id": {"type": ["string", "null"], "description": "转单号"},
                    "warehouse_status": {"type": ["integer", "string", "null"], "description": "WMS记录的仓储状态"},
                    "warehouse_status_text": {"type": "string", "description": "待出库或已出库，与物流状态独立"},
                    "tracking": {
                        "type": ["object", "null"], "additionalProperties": False,
                        "description": "无转单号时为null；查询失败时在error中说明原因",
                        "required": ["status", "sub_status", "status_text", "description", "latest_event", "error"],
                        "properties": {
                            "status": {"type": ["string", "null"], "description": "17TRACK物流主状态"},
                            "sub_status": {"type": ["string", "null"], "description": "17TRACK物流子状态"},
                            "status_text": {"type": ["string", "null"], "description": "中文物流状态，如成功签收；查询失败时为空"},
                            "description": {"type": ["string", "null"], "description": "17TRACK子状态描述"},
                            "latest_event": {
                                "type": ["object", "null"], "additionalProperties": False,
                                "required": ["time", "location", "description"],
                                "properties": {field: {"type": ["string", "null"]}
                                               for field in ("time", "location", "description")},
                            },
                            "error": {
                                "type": ["object", "null"], "additionalProperties": False,
                                "required": ["code", "msg"],
                                "properties": {"code": {"type": "integer"}, "msg": {"type": "string"}},
                            },
                        },
                    },
                },
            },
        },
    },
}
TOOL_DESCRIPTIONS = {
    "create_order": "创建订单。order包含REST业务字段；身份由OAuth账号提供。重试请复用相同idempotency_key。可附带初始quote。",
    "list_orders": "按REST的p/s分页、q搜索、sf/so排序查询未归档订单。需要管理员、店长、业务员或文员角色。",
    "get_order": "按订单uid查询详情，保留编辑策略与版本信息；不存在时返回code=404。",
    "get_tracking": "按业务订单号order_id精确查询订单下未归档包裹的精简详情，含原单号、转单号、仓储状态、中文物流状态及最新事件。自动查询17TRACK，不缓存、不自动注册单号。需要tracking:read授权；部分物流失败仍返回包裹及各自error。",
    "create_packing_list": "创建装箱单。list_number优先于mark，唛头去空格转大写；创建人为OAuth账号。重试请复用idempotency_key。",
}


class WmsTokenVerifier(TokenVerifier):
    def __init__(self, resource):
        self.resource = resource

    async def verify_token(self, token):
        from services.oauth_service import validate_access_token

        principal = await anyio.to_thread.run_sync(
            partial(validate_access_token, token, self.resource)
        )
        if principal is None:
            return None
        return AccessToken(
            token=token, client_id=principal["client_id"],
            scopes=principal["scopes"], expires_at=principal["expires_at"],
            subject=str(principal["user_id"]), resource=principal["resource"],
            claims={"iss": principal["issuer"], "wms_principal": principal},
        )


class WmsMCPServer(MCPServer):
    async def list_tools(self):
        # Stable catalog: clients can discover a tool before granting its scope.
        return [Tool(
            name=name, description=TOOL_DESCRIPTIONS[name],
            input_schema=model.model_json_schema(),
            output_schema=TRACKING_OUTPUT_SCHEMA if name == "get_tracking" else OUTPUT_SCHEMA,
            annotations=ToolAnnotations(
                read_only_hint=name in {"list_orders", "get_order", "get_tracking"},
                destructive_hint=False, idempotent_hint=True, open_world_hint=name == "get_tracking",
            ),
            meta={"required_scope": mcp_service.TOOL_SCOPES[name]},
        ) for name, model in mcp_service.INPUT_MODELS.items()]

    async def call_tool(self, name, arguments, context=None):
        token = get_access_token()
        principal = (token.claims or {}).get("wms_principal") if token else None
        if principal is None:
            result = {"code": 401, "msg": "Authentication required"}
        elif name not in mcp_service.TOOL_SCOPES:
            result = {"code": 404, "msg": "Unknown tool"}
        elif mcp_service.TOOL_SCOPES[name] not in token.scopes:
            # HTTP clients get the step-up challenge in ToolScopeMiddleware.
            result = {"code": 403, "msg": "OAuth scope is insufficient"}
        else:
            try:
                result = await anyio.to_thread.run_sync(
                    partial(mcp_service.execute_tool, name, arguments, principal)
                )
            except ValidationError as exc:
                fields = sorted({".".join(str(part) for part in item["loc"]) for item in exc.errors()})
                result = {"code": 400, "msg": "Invalid arguments: " + ", ".join(fields)}
            except Exception:
                logger.exception("MCP tool %s failed", name)
                result = {"code": 500, "msg": "操作失败，请重试或联系管理员"}
        success = result.get("code") == 200
        if success and name == "list_orders":
            text = f"查询成功，本页{len(result.get('data') or [])}条，共{result.get('total', 0)}条。"
        elif success and name == "get_tracking":
            text = f"订单{result['order_id']}，共{result['total']}个包裹。"
            if not result["tracking_complete"]:
                text += "部分包裹物流暂不可用。"
        elif success:
            data = result.get("data")
            uid = result.get("uid") or (data.get("uid") if isinstance(data, dict) else None)
            text = f"操作成功{('，uid=' + str(uid)) if uid else ''}。"
        else:
            text = result.get("msg") or f"操作失败（{result.get('code')}）。"
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=result, is_error=not success,
        )


class ToolScopeMiddleware:
    """Issue HTTP 403 scope challenges before dispatching business mutations."""
    def __init__(self, app, resource_metadata_url):
        self.app = app
        self.resource_metadata_url = resource_metadata_url

    async def __call__(self, scope, receive, send):
        token = get_access_token()
        if scope["type"] != "http" or scope.get("method") != "POST" or token is None:
            await self.app(scope, receive, send)
            return
        messages, body = [], bytearray()
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 4 * 1024 * 1024:
                await JSONResponse({"error": "request_too_large"}, status_code=413)(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        try:
            envelope = json.loads(body)
        except (ValueError, UnicodeError):
            envelope = None
        if isinstance(envelope, dict) and envelope.get("method") == "tools/call":
            params = envelope.get("params")
            name = params.get("name") if isinstance(params, dict) else None
            required = mcp_service.TOOL_SCOPES.get(name) if isinstance(name, str) else None
            if required and not {"mcp", required}.issubset(token.scopes):
                challenge = f'Bearer error="insufficient_scope", scope="mcp {required}", resource_metadata="{self.resource_metadata_url}"'
                await JSONResponse(
                    {"error": "insufficient_scope", "error_description": "Additional OAuth scope is required"},
                    status_code=403, headers={"WWW-Authenticate": challenge},
                )(scope, receive, send)
                return
        iterator = iter(messages)

        async def replay_receive():
            message = next(iterator, None)
            return message if message is not None else await receive()

        await self.app(scope, replay_receive, send)


def create_mcp_app(*, resource_url=None, issuer_url=None, verifier=None):
    from services.oauth_service import validate_oauth_public_urls

    issuer_string, resource_string = validate_oauth_public_urls(
        issuer_url or os.environ["OAUTH_ISSUER_URL"],
        resource_url or os.environ["MCP_PUBLIC_URL"],
        allow_local_http=os.environ.get("OAUTH_ALLOW_LOCAL_HTTP", "").lower() in {"1", "true", "yes"},
    )
    # AuthSettings preserves an issuer's empty path. Constructing AnyHttpUrl
    # first would append '/' and break OAuth's exact issuer comparisons.
    auth_settings = AuthSettings(issuer_url=issuer_string, resource_server_url=resource_string,
                                 required_scopes=["mcp"], validate_token_resource=True)
    resource, issuer = auth_settings.resource_server_url, auth_settings.issuer_url
    server = WmsMCPServer(
        "迅达WMS", version="1.0.0", token_verifier=verifier or WmsTokenVerifier(str(resource)),
        auth=auth_settings,
    )
    public = urlsplit(str(resource))
    hosts = [item.strip() for item in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if item.strip()] or [public.netloc]
    origins = [item.strip() for item in os.environ.get("MCP_ALLOWED_ORIGINS", "").split(",") if item.strip()] or [f"{public.scheme}://{public.netloc}"]
    security = TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=origins)
    app = server.streamable_http_app(json_response=True, stateless_http=True, transport_security=security)
    metadata_routes = create_protected_resource_routes(
        resource_url=resource, authorization_servers=[issuer],
        scopes_supported=["mcp", *mcp_service.TOOL_SCOPES.values()],
        resource_name="迅达WMS",
    )
    metadata_path = metadata_routes[0].path
    app.routes[:] = [route for route in app.routes if getattr(route, "path", None) != metadata_path] + metadata_routes
    # Authentication and its request context must precede per-tool challenges.
    app.user_middleware.append(Middleware(
        ToolScopeMiddleware, resource_metadata_url=str(build_resource_metadata_url(resource)),
    ))
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "Mcp-Method", "Mcp-Name",
                       "Mcp-Protocol-Version", "Mcp-Session-Id", "Last-Event-ID"],
        expose_headers=["WWW-Authenticate", "Mcp-Session-Id"],
    )
    app.state.mcp_server = server
    return app


# ASGI factory mode lets tests import without production environment variables.
# The usual deployment supplies both public URLs and uses ``mcp_server:app``.
if os.environ.get("MCP_PUBLIC_URL") and os.environ.get("OAUTH_ISSUER_URL"):
    app = create_mcp_app()
