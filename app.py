import logging
import sys

from flask import Flask, request, send_file


from data import backup
from controllers.auth_controller import auth_bp
from controllers.order_controller import order_bp
from controllers.cargo_controller import cargo_bp
from controllers.customer_controller import customer_bp
from controllers.log_controller import log_bp
from controllers.packing_controller import packing_bp
from controllers.work_finance_controller import work_finance_bp
from services.auth_service import init_admin_user

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


# ---------------------------------------------------------------------------
# Utility & static routes
# ---------------------------------------------------------------------------


@app.get("/ip")
def get_ip():
    return request.remote_addr


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def static_world(path):
    try:
        return app.send_static_file(path)
    except Exception:
        return send_file("frontend/index.html", mimetype="text/html")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run()
