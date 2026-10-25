"""17TRACK v2.2 webhook. Acknowledgements follow the provider's HTTP contract."""

from flask import Blueprint, current_app, jsonify, request

from services import tracking_webhook_service as service


tracking_webhook_bp = Blueprint("tracking_webhook", __name__, url_prefix="/api/webhooks/17track")


@tracking_webhook_bp.post("")
def tracking_updated():
    if request.content_length is not None and request.content_length > 2 * 1024 * 1024:
        return jsonify({"code": 413, "msg": "17TRACK 回调内容过大"}), 413
    try:
        raw_body = request.stream.read(2 * 1024 * 1024 + 1)
        if len(raw_body) > 2 * 1024 * 1024:
            return jsonify({"code": 413, "msg": "17TRACK 回调内容过大"}), 413
        data = service.receive_update(raw_body, request.headers.get("sign"))
        # 17TRACK treats only HTTP 200 as successful delivery, including replay.
        return jsonify({"code": 200, "data": data})
    except PermissionError as exc:
        return jsonify({"code": 401, "msg": str(exc)}), 401
    except service.ExceptionConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409
    except Exception:
        # Never acknowledge a failed transaction. Provider retries can then
        # deliver the notice after a temporary DB/notification failure recovers.
        # Do not log the request/signature/key or raw provider payload.
        current_app.logger.error("17TRACK webhook transaction failed")
        return jsonify({"code": 503, "msg": "17TRACK 回调暂时处理失败，请重试"}), 503
