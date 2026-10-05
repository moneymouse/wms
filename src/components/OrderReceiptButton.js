import React, { useEffect, useRef, useState } from 'react';
import { Button, Form, InputNumber, Select, Typography } from 'antd';
import { DollarOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import { createReceipt, printReceipt } from '../common/receiptApi';
import { amountToCents, getDefaultSettlementStatus, getRemainingReceivableCents } from '../common/receiptSettlement';
import ReceiptModal, { AdjustmentReceiptModal } from './ReceiptModal';

export default function OrderReceiptButton({ orderUid, messageApi, onSuccess }) {
    const [form] = Form.useForm();
    const [order, setOrder] = useState(null);
    const [loading, setLoading] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [adjustments, setAdjustments] = useState([]);
    const [activeAdjustment, setActiveAdjustment] = useState(null);
    const opening = useRef(false);
    const submittingRef = useRef(false);
    const amount = Form.useWatch('amount', form);
    const remainingReceivableCents = getRemainingReceivableCents(
        order ? [order] : [], order ? { [order.uid]: amount } : {}
    );

    useEffect(() => {
        if (order) form.setFieldsValue({ settlement_status: getDefaultSettlementStatus(remainingReceivableCents) });
    }, [form, order, remainingReceivableCents]);

    const openReceipt = async () => {
        if (opening.current || submittingRef.current) return;
        opening.current = true;
        setLoading(true);
        try {
            const params = new URLSearchParams({ order_uid: orderUid });
            const response = await fetch(`${endpoint}/receivables/orders?${params}`, { headers: getSafeHeader() });
            const result = await response.json();
            if (!response.ok || result.code !== 200) throw new Error(result.msg || '获取可收款订单失败');
            const collectible = (result.data || []).find(row => String(row.uid) === String(orderUid));
            if (collectible && Number(collectible.available_amount) > 0) {
                form.resetFields();
                form.setFieldsValue({
                    amount: Number(collectible.available_amount),
                    receipt_date: dayjs(), payment_method: 'cash', remark: '',
                });
                setOrder(collectible);
                return;
            }
            params.set('status', 'pending');
            params.set('s', '200');
            const adjustmentResponse = await fetch(`${endpoint}/receivable-adjustments?${params}`, { headers: getSafeHeader() });
            const adjustmentResult = await adjustmentResponse.json();
            if (!adjustmentResponse.ok || adjustmentResult.code !== 200) {
                throw new Error(adjustmentResult.msg || '获取差价单失败');
            }
            const availableAdjustments = (adjustmentResult.data || []).filter(row => (
                String(row.order_uid) === String(orderUid) && Number(row.available_amount) > 0
            ));
            if (availableAdjustments.length) {
                setAdjustments(availableAdjustments);
                setActiveAdjustment(availableAdjustments[0]);
            } else {
                messageApi.info('当前订单没有可收余额');
                await onSuccess();
            }
        } catch (error) {
            messageApi.error(error.message || '获取可收款订单失败');
        } finally {
            opening.current = false;
            setLoading(false);
        }
    };

    const submitReceipt = async (adjustmentForm) => {
        if (submittingRef.current) return;
        submittingRef.current = true;
        setSubmitting(true);
        try {
            const values = await (adjustmentForm || form).validateFields();
            const source = activeAdjustment || order;
            if (!source?.customer_id) {
                messageApi.warning('请先关联订单客户后再收款');
                return;
            }
            const receipt = await createReceipt({
                customer_id: source.customer_id,
                receipt_date: values.receipt_date.format('YYYY-MM-DD'),
                payment_method: values.payment_method,
                settlement_status: activeAdjustment ? 'unsettled' : values.settlement_status,
                remark: values.remark,
                items: [{
                    order_uid: orderUid,
                    amount: Number(values.amount),
                    ...(activeAdjustment ? { adjustment_id: activeAdjustment.id } : {}),
                }],
            });
            messageApi.success(`收款单 ${receipt.receipt_no} 已提交审核`);
            setOrder(null);
            setActiveAdjustment(null);
            form.resetFields();
            await printReceipt(receipt.id, messageApi);
            await onSuccess();
        } catch (error) {
            if (!error?.errorFields) messageApi.error(error.message || '提交收款单失败');
        } finally {
            submittingRef.current = false;
            setSubmitting(false);
        }
    };

    return (
        <>
            <Button size="middle" type="primary" icon={<DollarOutlined />} loading={loading}
                disabled={submitting} onClick={openReceipt}>收款</Button>
            <ReceiptModal
                open={Boolean(order)}
                form={form}
                submitting={submitting}
                onSubmit={() => submitReceipt()}
                onCancel={() => { if (!submittingRef.current) setOrder(null); }}
                orders={order ? [order] : []}
                selectedTotal={amountToCents(amount) / 100}
                remainingReceivableCents={remainingReceivableCents}
            >
                <Typography.Paragraph>订单：{order?.order_id}</Typography.Paragraph>
                <Typography.Paragraph>
                    可收余额：{Number(order?.available_amount || 0).toFixed(2)} CNY
                    {' '}（已收 {Number(order?.approved_received || 0).toFixed(2)}，待审核占用 {Number(order?.pending_amount || 0).toFixed(2)}）
                </Typography.Paragraph>
                <Form.Item name="amount" label="本次收款(CNY)" rules={[{
                    validator: (_, value) => Number.isFinite(Number(value))
                        && amountToCents(value) > 0
                        && amountToCents(value) <= amountToCents(order?.available_amount)
                        ? Promise.resolve()
                        : Promise.reject(new Error('本次收款必须大于 0 且不超过可收余额')),
                }]}>
                    <InputNumber precision={2} style={{ width: '100%' }} />
                </Form.Item>
            </ReceiptModal>
            {activeAdjustment && (
                <AdjustmentReceiptModal
                    key={activeAdjustment.id}
                    adjustment={activeAdjustment}
                    submitting={submitting}
                    onSubmit={submitReceipt}
                    onCancel={() => { if (!submittingRef.current) setActiveAdjustment(null); }}
                >
                    {adjustments.length > 1 && (
                        <Select
                            aria-label="差价单"
                            style={{ width: '100%', marginBottom: 16 }}
                            disabled={submitting}
                            value={activeAdjustment.id}
                            options={adjustments.map(item => ({ value: item.id, label: `差价单 #${item.id}（可补收 ${Number(item.available_amount).toFixed(2)} CNY）` }))}
                            onChange={id => setActiveAdjustment(adjustments.find(item => item.id === id))}
                        />
                    )}
                </AdjustmentReceiptModal>
            )}
        </>
    );
}
