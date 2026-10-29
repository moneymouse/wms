import React, { useEffect, useRef, useState } from 'react';
import useUrlState from '../common/useUrlState';
import { Alert, Button, DatePicker, Descriptions, Form, Input, InputNumber, Modal, Select, Space, Table, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import dayjs from 'dayjs';
import { financeRequest, money, mutationKey, queryString } from '../common/financeApi';
import { amountToCents } from '../common/receiptSettlement';

const { Text } = Typography;
function useOrders(params, revision = 0) {
    const key = queryString(params);
    const [state, setState] = useState({ key: '', data: null, error: '', loading: true });
    const identity = `${key}|${revision}`;
    useEffect(() => {
        let active = true;
        const controller = new AbortController();
        setState({ key: identity, data: null, error: '', loading: true });
        financeRequest('/order-settlements', { params: Object.fromEntries(new URLSearchParams(key)), signal: controller.signal })
            .then(data => { if (active) setState({ key: identity, data, error: '', loading: false }); })
            .catch(error => { if (active && error.name !== 'AbortError') setState({ key: identity, data: null, error: error.message, loading: false }); });
        return () => { active = false; controller.abort(); };
    }, [identity, key]);
    return state.key === identity ? state : { data: null, error: '', loading: true };
}
const cashColumn = (title, dataIndex) => ({ title, dataIndex, align: 'right', width: 130, render: value => money(value) });
const orderColumn = { title: '订单', dataIndex: 'order_number', width: 170, render: (value, row) => <Link to={`/orders/${row.order_uid}`}>{value || row.order_uid}</Link> };
function OrderReferences({ row }) {
    return <Descriptions size="small" column={1} items={[
        { key: 'legacy', label: '历史结算净额', children: `${money(row.legacy_settled_amount)} CNY` },
        { key: 'blockers', label: '办理提示', children: row.blockers?.join('；') || '可由财务确认报价并核销' },
        { key: 'docs', label: '已入账账单', children: row.documents?.map(doc => `${doc.number}（${money(doc.total_amount)}，未结 ${money(doc.residual_amount)}）`).join('；') || '尚未入账' },
    ]} />;
}

export function OrderAllocationDialog({ payment, onClose, onSuccess }) {
    const [form] = Form.useForm();
    const [query, setQuery] = useUrlState(`allocationSearch-${payment.id}`, '');
    const [page, setPage] = useUrlState(`allocationPage-${payment.id}`, 1, { validate: value => Number.isSafeInteger(value) && value > 0 });
    const [revision, setRevision] = useState(0);
    const [packingOnly, setPackingOnly] = useUrlState(`allocationPacking-${payment.id}`, Boolean(payment.reference_packing_boxes?.length));
    const [selected, setSelected] = useState({});
    const [error, setError] = useState('');
    const [saving, setSaving] = useState(false);
    const savingRef = useRef(false);
    const keyRef = useRef(mutationKey());
    const result = useOrders({ partner_id: payment.partner_id, ...(packingOnly ? { payment_id: payment.id } : {}), q: query, p: page, s: 20 }, revision);
    const refundable = payment.direction === 'outgoing';
    const available = amountToCents(payment.available_amount ?? payment.unallocated_amount);
    const balance = row => amountToCents(refundable ? row.refundable_amount : row.receivable_balance);
    const total = Object.values(selected).reduce((sum, row) => sum + amountToCents(row.amount), 0);
    const refresh = () => { setSelected({}); setRevision(value => value + 1); };
    const save = async () => {
        if (savingRef.current) return;
        savingRef.current = true; setSaving(true); setError('');
        try {
            const values = await form.validateFields();
            const rows = Object.values(selected);
            if (!rows.length) throw new Error('请选择实际核销的订单');
            if (rows.some(row => amountToCents(row.amount) <= 0 || amountToCents(row.amount) > balance(row))) throw new Error('每笔核销金额必须大于 0 且不超过订单可核销余额');
            if (total > available) throw new Error('核销合计不能超过收付款可用余额');
            await financeRequest('/order-allocations', { method: 'POST', body: {
                payment_id: payment.id, version: payment.version, idempotency_key: keyRef.current,
                packing_only: packingOnly,
                allocation_date: values.allocation_date.format('YYYY-MM-DD'), reason: values.reason || '',
                allocations: rows.map(row => ({ order_uid: row.order_uid, amount: (amountToCents(row.amount) / 100).toFixed(2), source_hash: row.source_hash })),
            } });
            onSuccess(); onClose();
        } catch (err) { if (!err.errorFields) setError(err.message); }
        finally { savingRef.current = false; setSaving(false); }
    };
    return <Modal title={`核销订单 · ${payment.number}`} open width={1000} onCancel={() => { if (!saving) onClose(); }} onOk={save} okText="确认订单核销" cancelText="取消" confirmLoading={saving} cancelButtonProps={{ disabled: saving }} maskClosable={!saving} closable={!saving} keyboard={!saving}>
        <Typography.Paragraph>客户：{payment.partner_name} · 可核销 {money(available / 100)} CNY。选择本次实际抵扣的订单并确认金额；同一订单的多箱货只列一次。</Typography.Paragraph>
        <Alert type="info" showIcon message={refundable ? '按当前报价核对订单应退金额，确认后核销客户付款。仅可按今天的报价快照办理。' : '确认后按当前报价生成或调整订单应收账单，再核销本次收款。仅可按今天的报价快照办理。'} style={{ marginBottom: 16 }} />
        {(error || result.error) && <Alert type="error" showIcon message={error || result.error} action={<Button size="small" disabled={saving} onClick={refresh}>刷新订单</Button>} style={{ marginBottom: 12 }} />}
        {packingOnly && result.data?.unresolved_packing_boxes?.length > 0 && <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="以下箱子尚不能核销，可先处理已分配的订单"
            description={result.data.unresolved_packing_boxes.map(row => `${row.list_number} / 箱 ${row.box_number ?? row.box_uid}：${row.reason}`).join('；')} />}
        <Space wrap style={{ marginBottom: 12 }}><Input.Search value={query} onChange={event => { setQuery(event.target.value); setPage(1); setSelected({}); }} aria-label="核销订单搜索" placeholder="搜索订单号" onSearch={value => { setQuery(value); setPage(1); setSelected({}); }} disabled={saving} /><Button icon={<ReloadOutlined />} disabled={saving} onClick={refresh}>刷新</Button><Text>已选 {Object.keys(selected).length} 单 / {money(total / 100)} CNY</Text></Space>
        {payment.reference_packing_boxes?.length > 0 && <Select aria-label="核销订单范围" value={packingOnly ? 'packing' : 'all'} disabled={saving} style={{ width: 220, marginBottom: 12 }}
            options={[{ value: 'packing', label: '备注箱子当前所属订单' }, { value: 'all', label: '此客户的全部订单' }]}
            onChange={value => { setPackingOnly(value === 'packing'); setPage(1); setSelected({}); }} />}
        <Table size="small" rowKey="order_uid" loading={result.loading} dataSource={result.data?.items || []} scroll={{ x: 780 }} expandable={{ expandedRowRender: row => <OrderReferences row={row} /> }}
            rowSelection={{ selectedRowKeys: Object.keys(selected), preserveSelectedRowKeys: true,
                getCheckboxProps: row => ({ disabled: saving || !row.can_allocate || balance(row) <= 0 }),
                onChange: (keys, rows) => setSelected(previous => Object.fromEntries(keys.map(key => {
                    const row = previous[key] || rows.find(item => item.order_uid === key);
                    return [key, { ...row, amount: previous[key]?.amount ?? (balance(row) / 100).toFixed(2) }];
                }))),
            }} columns={[orderColumn, cashColumn('当前报价 / CNY', 'receivable_amount'), cashColumn(refundable ? '可退 / CNY' : '待收 / CNY', refundable ? 'refundable_amount' : 'receivable_balance'),
                { title: '本次核销 / CNY', width: 170, fixed: 'right', align: 'right', render: (_, row) => <InputNumber aria-label={`${row.order_number} 订单核销金额`} stringMode precision={2} min={0.01} max={balance(row) / 100} disabled={saving || !selected[row.order_uid]} value={selected[row.order_uid]?.amount} onChange={amount => setSelected(previous => ({ ...previous, [row.order_uid]: { ...previous[row.order_uid], amount } }))} style={{ width: '100%' }} /> },
            ]} pagination={{ current: page, pageSize: 20, total: result.data?.total || 0, showSizeChanger: false, onChange: setPage }} />
        <Form form={form} layout="vertical" disabled={saving} initialValues={{ allocation_date: dayjs() }}>
            <Form.Item name="allocation_date" label="核销日期" rules={[{ required: true }]}><DatePicker disabledDate={date => !date.isSame(dayjs(), 'day')} /></Form.Item>
            <Form.Item name="reason" label="核销说明"><Input.TextArea rows={2} maxLength={1000} /></Form.Item>
        </Form>
    </Modal>;
}

export default function FinanceOrderSettlements() {
    const [query, setQuery] = useUrlState('orderSettlementSearch', '');
    const [partnerId, setPartnerId] = useUrlState('orderSettlementCustomer', undefined);
    const [partnerQuery, setPartnerQuery] = useState('');
    const [partners, setPartners] = useState([]);
    const [partnerError, setPartnerError] = useState('');
    const [page, setPage] = useUrlState('orderSettlementPage', 1, { validate: value => Number.isSafeInteger(value) && value > 0 });
    const [revision, setRevision] = useState(0);
    const [syncing, setSyncing] = useState(null);
    const [saving, setSaving] = useState(false);
    const savingRef = useRef(false);
    const keyRef = useRef(mutationKey());
    const [error, setError] = useState('');
    const [form] = Form.useForm();
    const result = useOrders({ partner_id: partnerId, q: query, p: page, s: 20 }, revision);
    useEffect(() => {
        let active = true;
        const controller = new AbortController();
        setPartnerError('');
        financeRequest('/partners', { params: { partner_type: 'customer', q: partnerQuery }, signal: controller.signal })
            .then(data => { if (active) setPartners(data.items || []); })
            .catch(err => { if (active && err.name !== 'AbortError') setPartnerError(err.message); });
        return () => { active = false; controller.abort(); };
    }, [partnerQuery, revision]);
    const sync = async () => {
        if (savingRef.current) return;
        savingRef.current = true; setSaving(true); setError('');
        try {
            const values = await form.validateFields();
            await financeRequest(`/order-settlements/${encodeURIComponent(syncing.order_uid)}/sync`, { method: 'POST', body: { source_hash: syncing.source_hash, document_date: values.document_date.format('YYYY-MM-DD'), reason: values.reason.trim(), idempotency_key: keyRef.current } });
            setSyncing(null); setRevision(value => value + 1);
        } catch (err) { if (!err.errorFields) setError(err.message); }
        finally { savingRef.current = false; setSaving(false); }
    };
    return <>
        <Typography.Paragraph type="secondary">按订单当前有效报价核对应收与应退。收付款独立登记；财务确认报价或核销时，生成对应账单并保留快照。历史订单净余额请在「会计与月结 → 旧订单接入」核对。</Typography.Paragraph>
        <Space wrap style={{ marginBottom: 16 }}>
            <Input.Search value={query} onChange={event => { setQuery(event.target.value); setPage(1); }} placeholder="搜索订单号 / 客户" allowClear onSearch={value => { setQuery(value); setPage(1); }} />
            <Select aria-label="订单应收客户" placeholder="全部客户" showSearch filterOption={false} allowClear style={{ width: 220 }} value={partnerId} onSearch={setPartnerQuery} onChange={value => { setPartnerId(value); setPage(1); }} options={partners.map(row => ({ value: row.id, label: row.name }))} />
            <Button icon={<ReloadOutlined />} onClick={() => setRevision(value => value + 1)}>刷新</Button>
        </Space>
        {(result.error || partnerError) && <Alert type="error" showIcon message={result.error || partnerError} action={<Button size="small" onClick={() => setRevision(value => value + 1)}>重试</Button>} style={{ marginBottom: 12 }} />}
        <Table size="small" rowKey="order_uid" loading={result.loading} dataSource={result.data?.items || []} scroll={{ x: 1150 }} expandable={{ expandedRowRender: row => <OrderReferences row={row} /> }} columns={[
            orderColumn, { title: '客户', dataIndex: 'customer_name', width: 140 }, cashColumn('当前应收 / CNY', 'receivable_amount'), cashColumn('已核销 / CNY', 'allocated_amount'), cashColumn('待补收 / CNY', 'receivable_balance'), cashColumn('待退 / CNY', 'refundable_amount'), cashColumn('报价变动 / CNY', 'sync_delta'),
            { title: '操作', fixed: 'right', width: 130, render: (_, row) => <Button type="link" size="small" disabled={!row.can_allocate} onClick={() => { setSyncing(row); setError(''); keyRef.current = mutationKey(); form.resetFields(); }}>确认当前报价</Button> },
        ]} pagination={{ current: page, pageSize: 20, total: result.data?.total || 0, showSizeChanger: false, showTotal: total => `共 ${total} 个订单`, onChange: setPage }} />
        <Modal title={`确认当前报价 · ${syncing?.order_number || ''}`} open={Boolean(syncing)} onOk={sync} onCancel={() => { if (!saving) setSyncing(null); }} okText="确认入账" cancelText="取消" confirmLoading={saving} cancelButtonProps={{ disabled: saving }} maskClosable={!saving} closable={!saving} keyboard={!saving}>
            {error && <Alert type="error" message={error} style={{ marginBottom: 12 }} />}
            <Typography.Paragraph>当前应收 {money(syncing?.receivable_amount)} CNY，较已入账应收变化 {money(syncing?.sync_delta)} CNY。确认将生成相应应收账单或贷项，不登记新资金。</Typography.Paragraph>
            <Form form={form} layout="vertical" disabled={saving} initialValues={{ document_date: dayjs() }}>
                <Form.Item name="document_date" label="入账日期" rules={[{ required: true }]}><DatePicker disabledDate={date => !date.isSame(dayjs(), 'day')} /></Form.Item>
                <Form.Item name="reason" label="确认说明" rules={[{ required: true, whitespace: true, message: '请填写确认说明' }]}><Input.TextArea rows={3} maxLength={1000} /></Form.Item>
            </Form>
        </Modal>
    </>;
}
