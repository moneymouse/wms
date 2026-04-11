# Import all model modules so that every table is registered with Base.metadata
from .DB import cargo_model, order_model, RecordExist  # registers orders + cargos
from .customer.Customer import (  # registers customers + receivers
    add_customer_record,
    get_customer_record,
    save_customer_record,
    list_customer_records,
    list_receiver_records,
    del_receiver_record,
    del_customer_record,
    get_customer_detail,
    get_all_customers_detail,
    update_customer_info,
)
from .excels import formatter
from .backup import backup

# Import OperationLogTable so it is also registered
import utils.log  # noqa: F401  registers operation_logs table

# Import UserTable so it is registered
from .user.User import user_model  # noqa: F401  registers users table

# Import PackingList and Box models so they are registered
from .packing import (
    packing_list_model,
    box_model,
)  # noqa: F401  registers packing tables

# Import finance models so they are registered
from .finance import bonus_rate_model  # noqa: F401  registers bonus_rates table
from .finance import bonus_item_model  # noqa: F401  registers bonus_items table
