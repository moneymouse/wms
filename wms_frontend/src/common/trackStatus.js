export default {
    '0': {'badgeText': '在库', 'detail': false, 'status': 'default',},
    '1': {'badgeText': '出库', 'detail': false, 'status': 'processing',},
    'InfoReceived': {'badgeText': '收到信息', 'detail': true, 'title': '收到信息'},
    'InTransit_PickedUp': {'badgeText': '已揽收', 'detail': true, 'title': '已揽收，运输商已从发件人处取回包裹'},
    'InTransit_Other': {
        'badgeText': '运输途中',
        'detail': true,
        'title': '运输途中'
    },
    'InTransit_Departure': {'badgeText': '已离港', 'detail': true, 'title': '已离港，货物离开起运地（国家/地区）港口'},
    'InTransit_Arrival': {'badgeText': '已到港', 'detail': true, 'title': '已到港，货物到达目的地（国家/地区）港口'},
    'InTransit_CustomsProcessing': {
        'badgeText': '清关中',
        'detail': true,
        'title': '清关中，货物在海关办理进入     或出口的相关流程中'
    },
    'InTransit_CustomsReleased': {
        'badgeText': '清关完成',
        'detail': true,
        'title': '清关完成，货物在海关完成了进入或出口的流程'
    },
    'InTransit_CustomsRequiringInformation': {
        'badgeText': '需要资料',
        'detail': true,
        'title': '需要资料，在清关中流程中承运人需要提供相关资料才能完成清关'
    },
    'Expired_Other': {'badgeText': '运输过久', 'detail': true, 'title': '运输过久'},
    'AvailableForPickup_Other': {'badgeText': '到达待取', 'detail': true, 'title': '到达待取'},
    'OutForDelivery_Other': {'badgeText': '派送途中', 'detail': true, 'title': '派送途中'},
    'DeliveryFailure_Other': {
        'badgeText': '投递失败',
        'detail': true,
        'title': '投递失败'
    },
    'DeliveryFailure_NoBody': {
        'badgeText': '找不到收件人',
        'detail': true,
        'status': 'error',
        'title': '找不到收件人，派送中的包裹暂时无法联系上收件人，导致投递失败'
    },
    'DeliveryFailure_Security': {
        'badgeText': '投递失败(安全原因)',
        'detail': true,
        'status': 'error',
        'title': '安全原因，派送中发现的包裹安全、清关、费用问题，导致投递失败'
    },
    'DeliveryFailure_Rejected': {
        'badgeText': '拒收',
        'detail': true,
        'status': 'error',
        'title': '拒收，收件人因某些原因拒绝接收包裹，导致投递失败'
    },
    'DeliveryFailure_InvalidAddress': {
        'badgeText': '地址错误',
        'detail': true,
        'title': '地址错误，由于收件人地址不正确，导致投递失败'
    },
    'Delivered_Other': {
        'badgeText': '成功签收',
        'detail': true,
        'status': 'success',
        'title': '成功签收'
    },
    'Exception_Other': {
        'badgeText': '其它情况',
        'detail': true,
        'title': '其它情况'
    },
    'Exception_Returning': {'badgeText': '退件中', 'detail': true, 'title': '退件中，包裹正在送回寄件人的途中'},
    'Exception_Returned': {
        'badgeText': '退件签收',
        'detail': true,
        'status': 'success',
        'title': '退件签收，寄件人已成功到退件'
    },
    'Exception_NoBody': {
        'badgeText': '找不到收件人',
        'detail': true,
        'status': 'error',
        'title': '找不到收件人，在派送之前发现的收件人信息异常'
    },
    'Exception_Security': {
        'badgeText': '安全原因',
        'detail': true,
        'status': 'error',
        'title': '安全原因，在派送之前发现异常，包含安全、清关、费用问题'
    },
    'Exception_Damage': {
        'badgeText': '损坏',
        'detail': true,
        'status': 'error',
        'title': '损坏，在承运过程中发现货物损坏了'
    },
    'Exception_Rejected': {
        'badgeText': '拒收',
        'detail': true,
        'status': 'warning',
        'title': '拒收，在派送之前接收到有收件人拒收情况'
    },
    'Exception_Delayed': {
        'badgeText': '延误',
        'detail': true,
        'status': 'warning',
        'title': '延误，因各种情况导致的能超出原定的运输周期'
    },
    'Exception_Lost': {
        'badgeText': '丢失',
        'detail': true,
        'status': 'error',
        'title': '丢失，因各种情况导致的货物丢失'
    },
    'Exception_Destroyed': {
        'badgeText': '销毁', 'detail': true, 'status': 'error', 'title': '销毁，因各种情况无法完成交付的货物并进行销毁'
    }
    ,
    'Exception_Cancel':
        {
            'badgeText': '取消', 'detail': true, 'status': 'error', 'title': '取消，因为各种情况物流订单被取消了'
        }
}