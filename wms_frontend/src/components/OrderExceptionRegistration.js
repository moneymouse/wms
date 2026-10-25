import React, { useEffect, useRef, useState } from 'react';
import { Alert, Button, Form, Input, Modal, Select, Space, Typography } from 'antd';
import { exceptionSubmission, fetchExceptionOrderCargos, registerOrderException, searchExceptionOrders } from '../common/orderExceptionApi';

export const exceptionCargoLabel = cargo => [cargo.transfer_id || cargo.origin_id, cargo.waybill_id].filter(Boolean).join(' / ') || `包裹 ${cargo.cargo_uid || cargo.uid}`;

export default function OrderExceptionRegistration({ open, onCancel, onCreated, order }) {
    const [form] = Form.useForm();
    const [orders, setOrders] = useState([]);
    const [cargos, setCargos] = useState([]);
    const [search, setSearch] = useState('');
    const [query, setQuery] = useState('');
    const [orderLoading, setOrderLoading] = useState(false);
    const [cargoLoading, setCargoLoading] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState('');
    const [cargoError, setCargoError] = useState('');
    const [orderError, setOrderError] = useState('');
    const submission = useRef(null);
    const submitLock = useRef(false);
    const selectedOrder = Form.useWatch('order_uid', form);
    const fixedOrderUid = order?.uid;

    useEffect(() => {
        if (!open) return;
        form.resetFields();
        form.setFieldsValue({ order_uid: fixedOrderUid, cargo_uid: undefined });
        setOrders([]);
        setSearch(''); setQuery(''); setError(''); setCargoError(''); setOrderError('');
        submission.current = null;
    }, [open, fixedOrderUid, form]);

    // Late order metadata may update its label without replacing the draft.
    useEffect(() => {
        if (open && order) setOrders([order]);
    }, [open, order, form]);

    useEffect(() => {
        if (!open || order) return;
        const controller = new AbortController();
        setOrderLoading(true); setOrderError('');
        searchExceptionOrders(query, { signal: controller.signal }).then(data => {
            if (!controller.signal.aborted) setOrders(data);
        }).catch(cause => {
            if (!controller.signal.aborted) setOrderError(cause.message);
        }).finally(() => { if (!controller.signal.aborted) setOrderLoading(false); });
        return () => controller.abort();
    }, [open, order, query]);

    useEffect(() => {
        setCargos([]); setCargoError('');
        if (!open || !selectedOrder) { setCargoLoading(false); return; }
        const controller = new AbortController();
        setCargoLoading(true);
        fetchExceptionOrderCargos(selectedOrder, { signal: controller.signal }).then(data => {
            if (!controller.signal.aborted) setCargos(data);
        }).catch(cause => {
            if (!controller.signal.aborted) setCargoError(cause.message);
        }).finally(() => { if (!controller.signal.aborted) setCargoLoading(false); });
        return () => controller.abort();
    }, [open, selectedOrder]);

    const submit = async () => {
        if (submitLock.current) return;
        let values;
        try { values = await form.validateFields(); } catch { return; }
        if (submitLock.current) return;
        submitLock.current = true; setSubmitting(true); setError('');
        try {
            const body = { order_uid: values.order_uid, ...(values.cargo_uid ? { cargo_uid: values.cargo_uid } : {}), reason: values.reason.trim() };
            const created = await registerOrderException(exceptionSubmission(submission, body));
            submission.current = null;
            onCreated?.(created);
        } catch (cause) { setError(cause.message); }
        finally { submitLock.current = false; setSubmitting(false); }
    };

    return <Modal title="登记异常" open={open} onCancel={submitting ? undefined : onCancel}
        maskClosable={!submitting} closable={!submitting} destroyOnClose
        footer={<Space><Button aria-label="取消" disabled={submitting} onClick={onCancel}>取消</Button>
            <Button aria-label="提交异常" type="primary" loading={submitting} onClick={submit}>提交异常</Button></Space>}>
        <Typography.Paragraph type="secondary">填写异常理由后，将通知订单对应业务员。未选择包裹时登记整张订单。</Typography.Paragraph>
        {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
        {orderError && <Alert type="error" showIcon message={orderError} style={{ marginBottom: 16 }} />}
        <Form form={form} layout="vertical" disabled={submitting}>
            {!order && <Form.Item label="查找订单"><Input.Search aria-label="查找订单" placeholder="订单号、原单号或转单号"
                value={search} onChange={event => setSearch(event.target.value)} onSearch={value => setQuery(value.trim())} enterButton="查找" /></Form.Item>}
            <Form.Item label="订单" name="order_uid" rules={[{ required: true, message: '请选择订单' }]}>
                <Select aria-label="异常订单" placeholder="选择订单" disabled={Boolean(order) || submitting} loading={orderLoading}
                    options={orders.map(item => ({ value: item.uid, label: item.order_id || item.uid }))}
                    onChange={() => form.setFieldValue('cargo_uid', undefined)} />
            </Form.Item>
            <Form.Item label="包裹（可选）" name="cargo_uid" extra={cargoError ? <Typography.Text type="danger">{cargoError}；仍可登记整张订单。</Typography.Text> : '不选择表示整张订单'}>
                <Select aria-label="异常包裹" allowClear placeholder="整张订单" disabled={!selectedOrder || cargoLoading || submitting}
                    loading={cargoLoading} options={cargos.map(cargo => ({ value: cargo.uid, label: exceptionCargoLabel(cargo) }))} />
            </Form.Item>
            <Form.Item label="异常理由" name="reason" rules={[{ required: true, whitespace: true, message: '请填写异常理由' }]}>
                <Input.TextArea aria-label="异常理由" rows={4} maxLength={2000} showCount />
            </Form.Item>
        </Form>
    </Modal>;
}
