import pickle

cargo_path = './data/data/cargo_dat'
order_path = './data/data/order_dat'

if __name__ == "__main__":
    # {
    #   cargo_uid: {
    #       ...,
    #       origin_id,
    #       uid
    #       }
    # }
    cargo_data_point = {}
    # {
    #   order_uid: {
    #       ...,
    #       order_id: origin_id.spilt('-')[0],
    #       uid
    #       }
    # }
    order_data_point = {}

    with open(cargo_path, "rb") as f:
        cargo_data_point = pickle.load(f)
    with open(order_path, "rb") as f:
        order_data_point = pickle.load(f)

    # 添加双向绑定
    for order_uid, order in order_data_point.items():
        cargo_uid_list = []
        for cargo_uid, cargo in cargo_data_point.items():
            # Match when cargo is belong to order
            if(cargo['origin_id'].split('-')[0] == order['order_id']):
                # 双向绑定
                cargo_data_point[cargo_uid].update({
                    'target_order_uid': order_uid,
                })
                cargo_uid_list.append(cargo_uid)
        order_data_point[order_uid].update({
            'cargo_uid_list': cargo_uid_list,
        })

    # {
    #   cargo_uid: {
    #       ...,
    #       origin_id,
    #       uid,
    #       target_order_uid
    #       }
    # }
    with open(cargo_path, "wb") as f:
        pickle.dump(cargo_data_point, f)
    # {
    #   order_uid: {
    #       ...,
    #       order_id: origin_id.spilt('-')[0],
    #       uid,
    #       cargo_uid_list
    #       }
    # }
    with open(order_path, "wb") as f:
        pickle.dump(order_data_point, f)

    # 检查cargo和order文件保存情况
    with open(cargo_path, "rb") as f:
        cargo_data_point = pickle.load(f)
        print(cargo_data_point)
    with open(order_path, "rb") as f:
        order_data_point = pickle.load(f)
        print(cargo_data_point)
