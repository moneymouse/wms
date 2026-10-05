import React from 'react';
import { DatePicker, Form, Input, InputNumber, Modal, Select, Space, Typography } from 'antd';
import dayjs from 'dayjs';
import { PAYMENT_METHODS } from '../common/receiptApi';
import { amountToCents, SETTLEMENT_OPTIONS } from '../common/receiptSettlement';

const { Text } = Typography;

function ReceiptFields() {
    return (
        <>
            <Form.Item name="receipt_date" label="收款日期" rules={[{ required: true, message: '请选择收款日期' }]}>
                <DatePicker style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="payment_method" label="收款方式" rules={[{ required: true, message: '请选择收款方式' }]}>
                <Select options={PAYMENT_METHODS} />
            </Form.Item>
        </>
    );
}

export default function ReceiptModal({
    open, form, submitting, onSubmit, onCancel, orders, selectedTotal, remainingReceivableCents, children,
}) {
    return (
        <Modal
            title="确认收款信息"
            open={open}
            forceRender
            onOk={onSubmit}
            onCancel={onCancel}
            okText="确认提交"
            cancelText="取消"
            confirmLoading={submitting}
            cancelButtonProps={{ disabled: submitting }}
            closable={!submitting}
            maskClosable={!submitting}
            keyboard={!submitting}
        >
            <Space direction="vertical" style={{ marginBottom: 16 }}>
                <Text>客户：{orders[0]?.customer_name || '-'}</Text>
                <Text>已选 {orders.length} 笔订单</Text>
                <Text strong>本次合计：{selectedTotal.toFixed(2)} CNY</Text>
                <Text>本次收款后剩余应收合计：{(remainingReceivableCents / 100).toFixed(2)} CNY</Text>
            </Space>
            <Form
                form={form}
                layout="vertical"
                disabled={submitting}
                initialValues={{ receipt_date: dayjs(), payment_method: 'cash', remark: '' }}
            >
                {children}
                <ReceiptFields />
                <Form.Item
                    name="settlement_status"
                    label="结清状态"
                    rules={[{ required: true, message: '请选择结清状态' }]}
                    extra="原应收减去已审核实收、已生效结清差额及本次收款后，合计小于30元默认已结清，否则默认未结清；可手动修改。其他待审核收款不参与默认计算，结清在财务审核通过后生效，余额为0的订单仍自动结清。"
                >
                    <Select options={SETTLEMENT_OPTIONS} />
                </Form.Item>
                <Form.Item name="remark" label="备注"><Input.TextArea rows={2} /></Form.Item>
            </Form>
        </Modal>
    );
}

export function AdjustmentReceiptModal({ adjustment, submitting, onSubmit, onCancel, children }) {
    const [form] = Form.useForm();
    return (
        <Modal
            title="登记差价补收"
            open
            onOk={() => onSubmit(form)}
            onCancel={onCancel}
            okText="确认提交"
            cancelText="取消"
            confirmLoading={submitting}
            cancelButtonProps={{ disabled: submitting }}
            closable={!submitting}
            maskClosable={!submitting}
            keyboard={!submitting}
        >
            {children}
            <Space direction="vertical" style={{ marginBottom: 16 }}>
                <Text>客户：{adjustment.customer_name || '-'}</Text>
                <Text>订单：{adjustment.order_id}</Text>
                <Text>报价差价：{Number(adjustment.delta_amount || 0).toFixed(2)} CNY</Text>
                <Text strong>当前可补收：{Number(adjustment.available_amount || 0).toFixed(2)} CNY</Text>
            </Space>
            <Form
                form={form}
                name="adjustmentReceipt"
                layout="vertical"
                disabled={submitting}
                initialValues={{
                    amount: adjustment.available_amount,
                    receipt_date: dayjs(),
                    payment_method: 'cash',
                    remark: '',
                    ...adjustment.copyValues,
                }}
            >
                <Form.Item
                    name="amount"
                    label="本次补收(CNY)"
                    rules={[{
                        validator: (_, value) => Number.isFinite(Number(value))
                            && amountToCents(value) > 0
                            && amountToCents(value) <= amountToCents(adjustment.available_amount)
                            ? Promise.resolve()
                            : Promise.reject(new Error('本次补收必须大于 0 且不超过当前可补收金额')),
                    }]}
                    extra="按实际到账金额登记，可分次补收；财务审核通过后更新差价余额，剩余差价不会自动减免。"
                >
                    <InputNumber precision={2} style={{ width: '100%' }} />
                </Form.Item>
                <ReceiptFields />
                <Form.Item name="remark" label="备注"><Input.TextArea rows={2} /></Form.Item>
            </Form>
        </Modal>
    );
}
