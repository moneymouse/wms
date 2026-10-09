const EXPORT_FIELDS = [
  { value: 'order_id', label: '订单号' },
  { value: 'transfer_id', label: '原单号' },
  { value: 'waybill_id', label: '转单号（运单号）' },
  { value: 'receiver', label: '收货人' },
  { value: 'receiver_phone', label: '收货人电话' },
  { value: 'country', label: '国家' },
  { value: 'province', label: '州,省' },
  { value: 'city', label: '城市' },
  { value: 'address', label: '详细地址' },
  { value: 'zip_code', label: '邮编' },
  { value: 'mail', label: '收货人邮箱' },
  { value: 'transportation', label: '运输方式' },
  { value: 'weight', label: '重量(KG)' },
  { value: 'real_en_name', label: '英文品名' },
  { value: 'cn_name', label: '中文品名' },
  { value: 'price', label: '申报价值' },
  { value: 'count', label: '申报数量(件)' },
  { value: 'post_code', label: '海关编码' },
  { value: 'customer_name', label: '客户姓名' },
];

export default EXPORT_FIELDS;
