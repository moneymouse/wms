import React, { useState } from 'react';
import { Button, message } from 'antd';
import { DollarOutlined } from '@ant-design/icons';
import { PaymentEditor } from '../pages/financeWorkspace';

const MAX_REFERENCE_BOXES = 500;

export default function PackingListReceiptButton({ packingList, selectedBoxUids = [] }) {
    const [context, setContext] = useState(null);
    const [messageApi, contextHolder] = message.useMessage();
    const open = () => {
        if (!packingList?.uid) return;
        const selected = new Set(selectedBoxUids.map(String));
        const boxes = (packingList.boxes || []).filter(box => !selected.size || selected.has(String(box.uid)));
        if (selected.size && boxes.length > MAX_REFERENCE_BOXES) {
            messageApi.warning('每笔收付款最多备注 500 箱，请减少勾选后重试');
            return;
        }
        const referenceBoxes = boxes.length > MAX_REFERENCE_BOXES ? [] : boxes.map(box => ({
            box_uid: String(box.uid), packing_list_uid: packingList.uid,
            list_number: packingList.list_number || packingList.mark || packingList.uid,
            box_number: box.box_number, transfer_id: box.transfer_id, item_name: box.item_name,
            weight: box.weight, customer_id: packingList.customer_id ?? null, target_order_uid: box.target_order_uid,
        }));
        setContext({
            packingListUid: packingList.uid, customerId: packingList.customer_id ?? undefined, customerName: packingList.customer_name,
            referenceBoxUids: referenceBoxes.map(box => box.box_uid), referencePackingBoxes: referenceBoxes,
            referenceNote: boxes.length > MAX_REFERENCE_BOXES
                ? `当前装箱单有 ${boxes.length} 箱，超过每笔 500 箱的备注上限。请在下方装箱单备注中选择需要备注的箱子。`
                : `来自装箱单 ${packingList.list_number || packingList.mark || packingList.uid}，已预选${selected.size ? '当前勾选的' : '全部'} ${referenceBoxes.length} 箱，可在表单中调整。`,
        });
    };
    return <>
        {contextHolder}
        <Button icon={<DollarOutlined aria-hidden />} onClick={open}>登记收付款</Button>
        {context && <PaymentEditor open business modal initialContext={context}
            onClose={() => setContext(null)}
            onSaved={payment => messageApi.success(payment.status === 'pending' ? '收付款已提交' : '收付款已保存')} />}
    </>;
}
