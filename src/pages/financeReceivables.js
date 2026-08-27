import React, { useEffect, useMemo, useState } from 'react';
import {
    Button, Card, Col, Input, Modal, Row, Select, Space, Statistic, Table, Tag,
    Typography, message
} from 'antd';
import { PrinterOutlined, ReloadOutlined } from '@ant-design/icons';

import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';

const { Text } = Typography;
const STATUS = {
    unpaid: { label: '未收', color: 'red' },
    partial: { label: '部分收款', color: 'orange' },
    paid: { label: '已结清', color: 'green' },
};
const RECEIPT_STATUS = {
    pending: { label: '待审核', color: 'orange' },
    approved: { label: '已生效', color: 'green' },
    rejected: { label: '已驳回', color: 'red' },
};

function today() {
    const date = new Date();
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function openPdfData(result, messageApi) {
    const binary = window.atob(result.data);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([bytes], { type: result.mime_type || 'application/pdf' }));
    const preview = window.open(url, '_blank');
    if (!preview) messageApi.warning('浏览器拦截了新窗口');
    window.setTimeout(() => URL.revokeObjectURL(url), 60000);
}

export function ReceivableLedger() {
    const [messageApi, contextHolder] = message.useMessage();
    const [asOf, setAsOf] = useState(today());
    const [query, setQuery] = useState('');
    const [status, setStatus] = useState(undefined);
    const [customerId, setCustomerId] = useState(undefined);
    const [ownerId, setOwnerId] = useState(undefined);
    const [customers, setCustomers] = useState([]);
    const [owners, setOwners] = useState([]);
    const [data, setData] = useState({ items: [], totals: {}, total: 0, page: 1, page_size: 20 });
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        Promise.all([
            fetch(`${endpoint}/customer_list`, { headers: getSafeHeader() }).then(r => r.json()),
            fetch(`${endpoint}/work/workers?roles=salesperson`, { headers: getSafeHeader() }).then(r => r.json()),
        ]).then(([customersResult, ownersResult]) => {
            if (customersResult.code === 200) setCustomers(customersResult.data || []);
            if (ownersResult.code === 200) setOwners(ownersResult.data || []);
        }).catch(() => {});
    }, []);

    const fetchLedger = async (page = 1, pageSize = data.page_size || 20) => {
        setLoading(true);
        try {
            const params = new URLSearchParams({ as_of: asOf, p: page, s: pageSize });
            if (query.trim()) params.set('q', query.trim());
            if (status) params.set('status', status);
            if (customerId) params.set('customer_id', customerId);
            if (ownerId) params.set('owner_id', ownerId);
            const response = await fetch(`${endpoint}/finance/accounts-receivable?${params}`, { headers: getSafeHeader() });
            const result = await response.json();
            if (!response.ok || result.code !== 200) throw new Error(result.msg || '查询失败');
            setData(result.data || { items: [], totals: {} });
        } catch (error) {
            messageApi.error(error.message || '查询应收账款失败');
        } finally {
            setLoading(false);
        }
    };

    // Initial ledger query uses the default cutoff and filters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    useEffect(() => { fetchLedger(); }, []);

    const columns = [
        { title: '订单号', dataIndex: 'order_id', key: 'order_id', width: 200 },
        { title: '客户', dataIndex: 'customer_name', key: 'customer_name', width: 150 },
        { title: '负责人', dataIndex: 'quoter_name', key: 'quoter_name', width: 110 },
        { title: '报价生效', dataIndex: 'effective_date', key: 'effective_date', width: 165 },
        { title: '重量(kg)', dataIndex: 'weight_snapshot', key: 'weight_snapshot', width: 105, render: v => Number(v || 0).toFixed(3) },
        { title: '应收(CNY)', dataIndex: 'receivable_amount', key: 'receivable_amount', width: 115, render: v => Number(v || 0).toFixed(2) },
        { title: '已收', dataIndex: 'received_amount', key: 'received_amount', width: 105, render: v => Number(v || 0).toFixed(2) },
        { title: '未收', dataIndex: 'outstanding_amount', key: 'outstanding_amount', width: 105, render: v => <Text type={Number(v) > 0 ? 'danger' : 'success'}>{Number(v || 0).toFixed(2)}</Text> },
        { title: '待审核', dataIndex: 'pending_amount', key: 'pending_amount', width: 105, render: v => Number(v || 0).toFixed(2) },
        {
            title: '状态', dataIndex: 'settlement_status', key: 'settlement_status', width: 105,
            render: v => <Tag color={STATUS[v]?.color}>{STATUS[v]?.label || v}</Tag>
        },
        { title: '报价状态', dataIndex: 'quote_stale', key: 'quote_stale', width: 105, render: v => v ? <Tag color="orange">待重报</Tag> : <Tag color="green">有效</Tag> },
    ];

    return (
        <div>
            {contextHolder}
            <Card size="small" style={{ marginBottom: 16 }}>
                <Space wrap>
                    <Input type="date" value={asOf} onChange={e => setAsOf(e.target.value)} style={{ width: 150 }} />
                    <Input value={query} onChange={e => setQuery(e.target.value)} placeholder="订单号/客户" style={{ width: 190 }} onPressEnter={() => fetchLedger()} />
                    <Select allowClear value={customerId} onChange={setCustomerId} placeholder="客户" style={{ width: 160 }} showSearch optionFilterProp="label" options={customers.map(row => ({ value: row.id, label: row.name }))} />
                    <Select allowClear value={ownerId} onChange={setOwnerId} placeholder="报价负责人" style={{ width: 160 }} options={owners.map(row => ({ value: row.id, label: row.name }))} />
                    <Select allowClear value={status} onChange={setStatus} placeholder="结清状态" style={{ width: 140 }} options={Object.entries(STATUS).map(([value, item]) => ({ value, label: item.label }))} />
                    <Button type="primary" icon={<ReloadOutlined />} onClick={() => fetchLedger()}>查询</Button>
                </Space>
            </Card>
            <Card size="small" style={{ marginBottom: 16 }}>
                <Row gutter={[16, 16]}>
                    <Col xs={12} md={6}><Statistic title="应收账款" value={Number(data.totals?.receivable_amount || 0).toFixed(2)} suffix="CNY" /></Col>
                    <Col xs={12} md={6}><Statistic title="已收账款" value={Number(data.totals?.received_amount || 0).toFixed(2)} suffix="CNY" valueStyle={{ color: '#15803d' }} /></Col>
                    <Col xs={12} md={6}><Statistic title="未收账款" value={Number(data.totals?.outstanding_amount || 0).toFixed(2)} suffix="CNY" valueStyle={{ color: '#b91c1c' }} /></Col>
                    <Col xs={12} md={6}><Statistic title="待审核占用" value={Number(data.totals?.pending_amount || 0).toFixed(2)} suffix="CNY" /></Col>
                </Row>
            </Card>
            <Card size="small" bodyStyle={{ padding: 0 }}>
                <Table
                    rowKey="order_uid"
                    loading={loading}
                    dataSource={data.items || []}
                    columns={columns}
                    pagination={{ current: data.page || 1, pageSize: data.page_size || 20, total: data.total || 0 }}
                    onChange={next => fetchLedger(next.current, next.pageSize)}
                    scroll={{ x: 'max-content' }}
                    size="small"
                />
            </Card>
        </div>
    );
}

export function ReceiptAudit() {
    const [messageApi, contextHolder] = message.useMessage();
    const [status, setStatus] = useState('pending');
    const [receipts, setReceipts] = useState([]);
    const [loading, setLoading] = useState(false);
    const [reviewing, setReviewing] = useState(null);
    const [reviewRemark, setReviewRemark] = useState('');
    const [submitting, setSubmitting] = useState(false);

    const fetchReceipts = async () => {
        setLoading(true);
        try {
            const params = new URLSearchParams({ p: 1, s: 200 });
            if (status) params.set('status', status);
            const response = await fetch(`${endpoint}/receipts?${params}`, { headers: getSafeHeader() });
            const result = await response.json();
            if (!response.ok || result.code !== 200) throw new Error(result.msg || '获取失败');
            setReceipts(result.data || []);
        } catch (error) {
            messageApi.error(error.message || '获取收款单失败');
        } finally {
            setLoading(false);
        }
    };
    // Status is the only input that should automatically refresh this list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    useEffect(() => { fetchReceipts(); }, [status]);

    const review = async (action) => {
        if (action === 'reject' && !reviewRemark.trim()) {
            messageApi.warning('驳回时请填写审核意见');
            return;
        }
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/finance/receipts/${reviewing.id}/review`, {
                method: 'PUT',
                headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ action, review_remark: reviewRemark }),
            });
            const result = await response.json();
            if (!response.ok || result.code !== 200) throw new Error(result.msg || '审核失败');
            messageApi.success('审核完成');
            setReviewing(null);
            setReviewRemark('');
            fetchReceipts();
        } catch (error) {
            messageApi.error(error.message || '审核失败');
        } finally {
            setSubmitting(false);
        }
    };

    const print = async (receipt) => {
        try {
            const response = await fetch(`${endpoint}/receipts/${receipt.id}/pdf`, { headers: getSafeHeader() });
            const result = await response.json();
            if (!response.ok || result.code !== 200) throw new Error(result.msg || '生成失败');
            openPdfData(result, messageApi);
        } catch (error) {
            messageApi.error(error.message || '生成收款单失败');
        }
    };

    const columns = useMemo(() => [
        { title: '收款单号', dataIndex: 'receipt_no', key: 'receipt_no', width: 210 },
        { title: '客户', dataIndex: 'customer_name', key: 'customer_name', width: 150 },
        { title: '收款日期', dataIndex: 'receipt_date', key: 'receipt_date', width: 115 },
        { title: '金额(CNY)', dataIndex: 'total_amount', key: 'total_amount', width: 115, render: v => Number(v || 0).toFixed(2) },
        { title: '创建人', dataIndex: 'creator_name', key: 'creator_name', width: 105 },
        { title: '审核人', dataIndex: 'reviewer_name', key: 'reviewer_name', width: 105, render: v => v || '-' },
        { title: '状态', dataIndex: 'status', key: 'status', width: 95, render: v => <Tag color={RECEIPT_STATUS[v]?.color}>{RECEIPT_STATUS[v]?.label || v}</Tag> },
        {
            title: '操作', key: 'action', fixed: 'right', width: 160,
            render: (_, record) => <Space>
                <Button size="small" icon={<PrinterOutlined />} onClick={() => print(record)}>打印</Button>
                {record.status === 'pending' && <Button size="small" type="primary" onClick={() => { setReviewing(record); setReviewRemark(''); }}>审核</Button>}
            </Space>
        },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    ], []);

    return (
        <div>
            {contextHolder}
            <Card size="small" bodyStyle={{ padding: 0 }}>
                <div style={{ padding: 12 }}>
                    <Space>
                        <Select value={status} onChange={setStatus} style={{ width: 130 }} options={[{ value: 'pending', label: '待审核' }, { value: 'approved', label: '已生效' }, { value: 'rejected', label: '已驳回' }, { value: '', label: '全部' }]} />
                        <Button icon={<ReloadOutlined />} onClick={fetchReceipts}>刷新</Button>
                    </Space>
                </div>
                <Table
                    rowKey="id"
                    loading={loading}
                    dataSource={receipts}
                    columns={columns}
                    pagination={{ pageSize: 20 }}
                    scroll={{ x: 'max-content' }}
                    expandable={{ expandedRowRender: record => <Table rowKey="id" size="small" pagination={false} dataSource={record.items || []} columns={[
                        { title: '订单号', dataIndex: 'order_id' },
                        { title: '应收', dataIndex: 'receivable_snapshot', render: v => Number(v || 0).toFixed(2) },
                        { title: '此前已收', dataIndex: 'received_before', render: v => Number(v || 0).toFixed(2) },
                        { title: '本次收款', dataIndex: 'amount', render: v => Number(v || 0).toFixed(2) },
                        { title: '收款后余额', dataIndex: 'remaining_after', render: v => Number(v || 0).toFixed(2) },
                    ]} /> }}
                />
            </Card>
            <Modal
                title={reviewing ? `收款审核 - ${reviewing.receipt_no}` : '收款审核'}
                open={!!reviewing}
                onCancel={() => setReviewing(null)}
                footer={[
                    <Button key="reject" danger loading={submitting} onClick={() => review('reject')}>驳回</Button>,
                    <Button key="approve" type="primary" loading={submitting} onClick={() => review('approve')}>审核通过</Button>,
                ]}
            >
                {reviewing && <Space direction="vertical" style={{ width: '100%' }}>
                    <Text>客户：{reviewing.customer_name}</Text>
                    <Text>收款金额：{Number(reviewing.total_amount || 0).toFixed(2)} CNY</Text>
                    <Text>创建人：{reviewing.creator_name}</Text>
                    <Input.TextArea rows={3} value={reviewRemark} onChange={e => setReviewRemark(e.target.value)} placeholder="审核意见（驳回时必填）" />
                </Space>}
            </Modal>
        </div>
    );
}
