import logging
import sys

from flask import Flask, jsonify, request, send_file


from data import backup
from controllers.auth_controller import auth_bp
from controllers.order_controller import order_bp
from controllers.cargo_controller import cargo_bp
from controllers.customer_controller import customer_bp
from controllers.log_controller import log_bp
from controllers.packing_controller import packing_bp
from controllers.work_finance_controller import work_finance_bp
from controllers.goods_name_controller import goods_name_bp
from controllers.customs_code_controller import customs_code_bp
from controllers.excel_template_controller import excel_template_bp
from controllers.transportation_controller import transportation_bp
from controllers.receivable_controller import receivable_bp
from controllers.intake_controller import intake_bp
from controllers.finance_ledger_controller import finance_ledger_bp
from controllers.finance_order_controller import finance_order_bp
from controllers.finance_legacy_controller import finance_legacy_bp
from controllers.finance_accounting_controller import finance_accounting_bp
from controllers.finance_revenue_controller import finance_revenue_bp
from controllers.supplier_reconciliation_controller import supplier_reconciliation_bp
from services.auth_service import init_admin_user
from controllers.oauth_controller import init_oauth

# ---------------------------------------------------------------------------
# App initialisation
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder="frontend/static")

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("log/error_log.log"),
        logging.StreamHandler(sys.stdout),
    ],
)

backup()
init_admin_user()

# ---------------------------------------------------------------------------
# Blueprint registration
# ---------------------------------------------------------------------------

app.register_blueprint(auth_bp)
app.register_blueprint(order_bp)
app.register_blueprint(cargo_bp)
app.register_blueprint(customer_bp)
app.register_blueprint(log_bp)
app.register_blueprint(packing_bp)
app.register_blueprint(work_finance_bp)
app.register_blueprint(goods_name_bp)
app.register_blueprint(customs_code_bp)
app.register_blueprint(excel_template_bp)
app.register_blueprint(transportation_bp)
app.register_blueprint(receivable_bp)
app.register_blueprint(intake_bp)
app.register_blueprint(finance_ledger_bp)
app.register_blueprint(finance_order_bp)
app.register_blueprint(finance_legacy_bp)
app.register_blueprint(finance_accounting_bp)
app.register_blueprint(finance_revenue_bp)
app.register_blueprint(supplier_reconciliation_bp)
init_oauth(app)


# ---------------------------------------------------------------------------
# Utility & static routes
# ---------------------------------------------------------------------------


@app.get("/ip")
def get_ip():
    return request.remote_addr


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def static_world(path):
    if path == "api" or path.startswith("api/"):
        return jsonify({"code": 404, "msg": "API接口不存在"}), 404
    try:
        return app.send_static_file(path)
    except Exception:
        return send_file("frontend/index.html", mimetype="text/html")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run()
