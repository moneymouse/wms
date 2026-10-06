import React, { useState } from 'react';
import { Button, message } from 'antd';
import { DollarOutlined } from '@ant-design/icons';
import { PaymentEditor } from '../pages/financeWorkspace';

export default function OrderReceiptButton({ orderUid, orderNumber, customerId, customerName }) {
    const [open, setOpen] = useState(false);
    const [messageApi, contextHolder] = message.useMessage();
    return <>
        {contextHolder}
        <Button icon={<DollarOutlined aria-hidden />} onClick={() => setOpen(true)}>登记收付款</Button>
        {open && <PaymentEditor open business modal
            initialContext={{ customerId, customerName, orderUid, orderNumber }}
            onClose={() => setOpen(false)}
            onSaved={payment => messageApi.success(payment.status === 'pending' ? '收付款已提交' : '收付款已保存')} />}
    </>;
}
