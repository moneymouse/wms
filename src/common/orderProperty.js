const orderProperty = [
    {name: 'order_id', label: '订单号/Tracking Number', width: 200},
    {name: 'customer_name', label: '客户姓名/Customer Name'},
    {name: 'transportation', label: '运输方式/Transportation'},
    {name: 'receiver', label: '收货人/Receiver'},
    {name: 'receiver_phone', label: '收货人电话/Receiver Phone Number'},
    {name: 'mail', label: '收货人邮箱/Mail'},
    {name: 'country', label: '国家/Destination Country'},
    {name: 'province', label: '州,省/State,Province'},
    {name: 'city', label: '城市/City', width: 160},
    {name: 'address', label: '详细地址/Full Address', width: 400, span: 2},
    {name: 'en_name', label: '报关品名/Customs Product Description'},
    {name: 'cn_name', label: '中文品名'},
    {name: 'post_code', label: '海关编码'},
    // {name: 'total_weight', label: '总重量/Weight', width: 160},
    {name: 'zip_code', label: '邮编/Zip Code'},
    {name: 'order_date', label: '创建日期/Date'},
    {name: 'update_date', label: '更新日期/Date'},
    {name: 'tag_all', label: '唛头'}
];
export default orderProperty;