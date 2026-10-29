import React, { useEffect, useRef, useState } from 'react';
import useUrlState from '../common/useUrlState';
import dayjs from 'dayjs';
import {
    Alert, Button, Card, Col, DatePicker, Input, Modal, Row, Select, Space, Statistic, Table,
    Typography, message
} from 'antd';
import { PrinterOutlined, ReloadOutlined } from '@ant-design/icons';

import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import FinanceHistoryDrawer from '../components/FinanceHistoryDrawer';
import { getSettlementDifferenceDisplay, getSettlementStatus } from '../common/receiptSettlement';
import FeatureTour from '../components/FeatureTour';
import { COST_QUOTE_RECEIPT_TOUR, getCostQuoteReceiptChapter } from '../common/featureTourConfig';
import {
    clearFeatureTourFlow,
    getCurrentTourUser,
    readFeatureTourFlow,
    saveFeatureTourFlow,
} from '../common/featureTourState';

const dateRangeUrl = {
    encode: value => JSON.stringify(value?.map(date => date.format('YYYY-MM-DD')) ?? null),
    decode: raw => {
        const values = JSON.parse(raw);
        if (values === null) return null;
        if (!Array.isArray(values) || values.length !== 2 || values.some(value => typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || !dayjs(value).isValid() || dayjs(value).format('YYYY-MM-DD') !== value)) throw new Error('Invalid date range');
        return values.map(value => dayjs(value));
    },
};

const { Text } = Typography;
const STATUS = {
    unpaid: { label: '未收', color: 'red' },
    partial: { label: '部分收款', color: 'orange' },
    paid: { label: '已结清', color: 'green' },
    refund_due: { label: '待退款', color: 'blue' },
};
const RECEIPT_STATUS = {
    pending: { label: '待审核', color: 'orange' },
    approved: { label: '已生效', color: 'green' },
    rejected: { label: '已驳回', color: 'red' },
};
const receivableLedgerTourChapter = getCostQuoteReceiptChapter('receivableLedger');
const receiptAuditTourChapter = getCostQuoteReceiptChapter('receiptAudit');
const receivableLedgerTourTargets = {
    filters: '[data-tour="receivable-filters"]',
    totals: '[data-tour="receivable-totals"]',
    ledger: '[data-tour="receivable-ledger"]',
};
const receiptAuditTourTargets = {
    filter: '[data-tour="audit-filter"]',
    details: '[data-tour="audit-table"]',
    review: '[data-tour="audit-review-modal"]',
};

function defaultDateRange() {
    return null;
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

function SettlementTag({ status }) {
    const display = getSettlementStatus(status);
    return <Text>{display.label}</Text>;
}

function ReceiptItems({ receipt, loading = false }) {
    const differenceLabel = getSettlementDifferenceDisplay(receipt || {}, receipt?.items?.[0] || {}).label;
    return <Table
        rowKey="id"
        size="small"
        pagination={false}
        loading={loading}
        dataSource={receipt?.items || []}
        scroll={{ x: 'max-content' }}
        columns={[
            { title: '订单号', dataIndex: 'order_id' },
            { title: '应收', dataIndex: 'receivable_snapshot', render: v => Number(v || 0).toFixed(2) },
            { title: '此前已收', dataIndex: 'received_before', render: v => Number(v || 0).toFixed(2) },
            { title: '本次实收', dataIndex: 'amount', render: v => Number(v || 0).toFixed(2) },
            { title: '可收余额快照', dataIndex: 'remaining_after', render: v => Number(v || 0).toFixed(2) },
            {
                title: differenceLabel,
                key: 'settlement_difference',
                render: (_, item) => {
                    const { value } = getSettlementDifferenceDisplay(receipt, item);
                    return value == null ? '-' : Number(value).toFixed(2);
                },
            },
        ]}
    />;
}

export function ReceivableLedger() {
    const [messageApi, contextHolder] = message.useMessage();
    const [dateRange, setDateRange] = useUrlState('legacyLedgerDates', defaultDateRange, dateRangeUrl);
    const [ledgerPagination, setLedgerPagination] = useUrlState('legacyLedgerPage', { current: 1, pageSize: 20 });
    const [query, setQuery] = useUrlState('legacyLedgerSearch', '');
    const [status, setStatus] = useUrlState('legacyLedgerStatus', undefined);
    const [customerId, setCustomerId] = useUrlState('legacyLedgerCustomer', undefined);
    const [ownerId, setOwnerId] = useUrlState('legacyLedgerOwner', undefined);
    const [customers, setCustomers] = useState([]);
    const [owners, setOwners] = useState([]);
    const [data, setData] = useState({ items: [], totals: {}, total: 0, page: 1, page_size: 20 });
    const [loading, setLoading] = useState(false);
    const ledgerRequest = useRef(0);
    const changeLedgerFilter = setter => value => { setter(value); setLedgerPagination(previous => ({ ...previous, current: 1 })); };
    const { userId: tourUserId } = getCurrentTourUser();
    const tourFlow = readFeatureTourFlow(tourUserId);
    const continuingLedgerFlow = tourFlow?.campaignId === COST_QUOTE_RECEIPT_TOUR.id
        && tourFlow.stage === 'receivable-ledger';
    const receivableLedgerTourSteps = receivableLedgerTourChapter.steps.map(step => ({
        ...step,
        target: () => document.querySelector(receivableLedgerTourTargets[step.key]),
    }));

    useEffect(() => {
        Promise.all([
            fetch(`${endpoint}/customer_list`, { headers: getSafeHeader() }).then(r => r.json()),
            fetch(`${endpoint}/work/workers?roles=salesperson`, { headers: getSafeHeader() }).then(r => r.json()),
        ]).then(([customersResult, ownersResult]) => {
            if (customersResult.code === 200) setCustomers(customersResult.data || []);
            if (ownersResult.code === 200) setOwners(ownersResult.data || []);
        }).catch(() => {});
    }, []);

    const fetchLedger = async (page = ledgerPagination.current, pageSize = ledgerPagination.pageSize) => {
        const requestId = ++ledgerRequest.current;
        setLoading(true);
        try {
            const params = new URLSearchParams({ p: page, s: pageSize });
            if (dateRange?.[0] && dateRange?.[1]) {
                params.set('date_from', dateRange[0].format('YYYY-MM-DD'));
                params.set('date_to', dateRange[1].format('YYYY-MM-DD'));
            }
            if (query.trim()) params.set('q', query.trim());
            if (status) params.set('status', status);
            if (customerId) params.set('customer_id', customerId);
            if (ownerId) params.set('owner_id', ownerId);
            const response = await fetch(`${endpoint}/finance/accounts-receivable?${params}`, { headers: getSafeHeader() });
            const result = await response.json();
            if (requestId !== ledgerRequest.current) return;
            if (!response.ok || result.code !== 200) throw new Error(result.msg || '查询失败');
            setData(result.data || { items: [], totals: {} });
        } catch (error) {
            if (requestId === ledgerRequest.current) messageApi.error(error.message || '查询应收账款失败');
        } finally {
            if (requestId === ledgerRequest.current) setLoading(false);
        }
    };

    // Include opening arrears; a month filter would hide older unpaid orders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    useEffect(() => { fetchLedger(); }, [dateRange, query, status, customerId, ownerId, ledgerPagination]);

    const columns = [
        { title: '订单号', dataIndex: 'order_id', key: 'order_id', width: 200 },
        { title: '客户', dataIndex: 'customer_name', key: 'customer_name', width: 150 },
        { title: '负责人', dataIndex: 'quoter_name', key: 'quoter_name', width: 110 },
        { title: '报价生效', dataIndex: 'effective_date', key: 'effective_date', width: 165 },
        {
            title: '计费重量(kg)', dataIndex: 'billing_weight', key: 'billing_weight', width: 130,
            render: value => Number(value || 0).toFixed(0),
        },
        { title: '应收(CNY)', dataIndex: 'receivable_amount', key: 'receivable_amount', width: 115, render: v => Number(v || 0).toFixed(2) },
        { title: '已收', dataIndex: 'received_amount', key: 'received_amount', width: 105, render: v => Number(v || 0).toFixed(2) },
        { title: '结清差额', dataIndex: 'settlement_difference', key: 'settlement_difference', width: 110, render: v => Number(v || 0).toFixed(2) },
        { title: '未收', dataIndex: 'outstanding_amount', key: 'outstanding_amount', width: 105, render: v => <Text type={Number(v) > 0 ? 'danger' : 'success'}>{Number(v || 0).toFixed(2)}</Text> },
        { title: '应退', dataIndex: 'refund_due', key: 'refund_due', width: 105, render: v => <Text type={Number(v) > 0 ? 'warning' : 'secondary'}>{Number(v || 0).toFixed(2)}</Text> },
        { title: '待审核', dataIndex: 'pending_amount', key: 'pending_amount', width: 105, render: v => Number(v || 0).toFixed(2) },
        {
            title: '状态', dataIndex: 'settlement_status', key: 'settlement_status', width: 105,
            render: v => <Text>{STATUS[v]?.label || v}</Text>
        },
    ];

    return (
        <div>
            {contextHolder}
            <Alert type="info" showIcon style={{ marginBottom: 16 }} message="订单结算参考：此页按实时订单报价及原收款统计；正式账簿与往来对账在财务工作台。" />
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 4 }}>
                <FeatureTour
                    chapter={receivableLedgerTourChapter}
                    steps={receivableLedgerTourSteps}
                    autoEnabled={false}
                    forceAutoStart={continuingLedgerFlow}
                    onTourEnd={(status, mode) => {
                        if (mode === 'auto' && continuingLedgerFlow) {
                            clearFeatureTourFlow(tourUserId);
                        }
                    }}
                    triggerAriaLabel="打开应收账款操作引导"
                />
            </div>
            <Card data-tour="receivable-filters" size="small" style={{ marginBottom: 16 }}>
                <Space wrap>
                    <DatePicker.RangePicker
                        value={dateRange}
                        onChange={changeLedgerFilter(setDateRange)}
                        allowClear
                        format="YYYY-MM-DD"
                        placeholder={['开始日期', '结束日期']}
                    />
                    <Input value={query} onChange={e => changeLedgerFilter(setQuery)(e.target.value)} placeholder="订单号/客户" style={{ width: 190 }} onPressEnter={() => fetchLedger()} />
                    <Select allowClear value={customerId} onChange={changeLedgerFilter(setCustomerId)} placeholder="客户" style={{ width: 160 }} showSearch optionFilterProp="label" options={customers.map(row => ({ value: row.id, label: row.name }))} />
                    <Select allowClear value={ownerId} onChange={changeLedgerFilter(setOwnerId)} placeholder="报价负责人" style={{ width: 160 }} options={owners.map(row => ({ value: row.id, label: row.name }))} />
                    <Select allowClear value={status} onChange={changeLedgerFilter(setStatus)} placeholder="结清状态" style={{ width: 140 }} options={Object.entries(STATUS).map(([value, item]) => ({ value, label: item.label }))} />
                    <Button type="primary" icon={<ReloadOutlined />} onClick={() => fetchLedger()}>查询</Button>
                </Space>
            </Card>
            <Card data-tour="receivable-totals" size="small" style={{ marginBottom: 16 }}>
                <Row gutter={[16, 16]}>
                    <Col role="group" aria-label="区间总应收" xs={12} md={8} xl={{ flex: '1 1 20%' }}><Statistic title="区间总应收" value={Number(data.totals?.receivable_amount || 0).toFixed(2)} suffix="CNY" /></Col>
                    <Col role="group" aria-label="已收账款" xs={12} md={8} xl={{ flex: '1 1 20%' }}><Statistic title="已收账款" value={Number(data.totals?.received_amount || 0).toFixed(2)} suffix="CNY" valueStyle={{ color: '#15803d' }} /></Col>
                    <Col role="group" aria-label="结清差额合计" xs={12} md={8} xl={{ flex: '1 1 20%' }}><Statistic title="结清差额合计" value={Number(data.totals?.settlement_difference || 0).toFixed(2)} suffix="CNY" /></Col>
                    <Col role="group" aria-label="未收账款" xs={12} md={8} xl={{ flex: '1 1 20%' }}><Statistic title="未收账款" value={Number(data.totals?.outstanding_amount || 0).toFixed(2)} suffix="CNY" valueStyle={{ color: '#b91c1c' }} /></Col>
                    <Col role="group" aria-label="待退款" xs={12} md={8} xl={{ flex: '1 1 20%' }}><Statistic title="待退款" value={Number(data.totals?.refund_due || 0).toFixed(2)} suffix="CNY" valueStyle={{ color: '#2563eb' }} /></Col>
                    <Col role="group" aria-label="待审核占用" xs={12} md={8} xl={{ flex: '1 1 20%' }}><Statistic title="待审核占用" value={Number(data.totals?.pending_amount || 0).toFixed(2)} suffix="CNY" /></Col>
                </Row>
            </Card>
            <Card data-tour="receivable-ledger" size="small" bodyStyle={{ padding: 0 }}>
                <Table
                    rowKey="order_uid"
                    loading={loading}
                    dataSource={data.items || []}
                    columns={columns}
                    pagination={{ ...ledgerPagination, total: data.total || 0 }}
                    onChange={next => setLedgerPagination({ current: next.current, pageSize: next.pageSize })}
                    scroll={{ x: 'max-content' }}
                    size="small"
                />
            </Card>
        </div>
    );
}

export function ReceiptAudit() {
    const [messageApi, contextHolder] = message.useMessage();
    const [status, setStatus] = useUrlState('legacyAuditStatus', 'pending');
    const [receiptNoSearch, setReceiptNoSearch] = useUrlState('legacyAuditSearch', '');
    const [auditPagination, setAuditPagination] = useUrlState('legacyAuditPage', { current: 1, pageSize: 20 });
    const [receipts, setReceipts] = useState([]);
    const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 });
    const listRequest = useRef(0);
    const [historyReceipt, setHistoryReceipt] = useState(null);
    const [loading, setLoading] = useState(false);
    const [detailStates, setDetailStates] = useState({});
    const detailRequests = useRef({});
    const [reviewing, setReviewing] = useState(null);
    const [reviewDetail, setReviewDetail] = useState({ data: null, loading: false, error: '' });
    const reviewRequest = useRef(0);
    const [reviewRemark, setReviewRemark] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const { userId: tourUserId } = getCurrentTourUser();
    const tourFlow = readFeatureTourFlow(tourUserId);
    const continuingAuditFlow = tourFlow?.campaignId === COST_QUOTE_RECEIPT_TOUR.id
        && tourFlow.stage === 'receipt-audit';
    const receiptAuditTourSteps = receiptAuditTourChapter.steps.map(step => ({
        ...step,
        target: () => document.querySelector(receiptAuditTourTargets[step.key])
            || document.querySelector('[data-tour="audit-review-action"]')
            || document.querySelector('[data-tour="audit-table"]'),
    }));

    const fetchReceipts = async (page = auditPagination.current, pageSize = auditPagination.pageSize) => {
        const requestId = ++listRequest.current;
        setLoading(true);
        try {
            const params = new URLSearchParams({ p: page, s: pageSize });
            if (status) params.set('status', status);
            if (receiptNoSearch.trim()) params.set('q', receiptNoSearch.trim());
            const response = await fetch(`${endpoint}/receipts?${params}`, { headers: getSafeHeader() });
            const result = await response.json();
            if (requestId !== listRequest.current) return;
            if (!response.ok || result.code !== 200) throw new Error(result.msg || '获取失败');
            setReceipts(result.data || []);
            setPagination({ current: result.page || page, pageSize: result.page_size || pageSize, total: result.total ?? result.data?.length ?? 0 });
        } catch (error) {
            if (requestId !== listRequest.current) return;
            messageApi.error(error.message || '获取收款单失败');
        } finally {
            if (requestId === listRequest.current) setLoading(false);
        }
    };
    // URL changes, including browser navigation, restore the same result set.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    useEffect(() => { fetchReceipts(); }, [status, receiptNoSearch, auditPagination]);

    const fetchReceiptDetail = async (receiptId) => {
        const response = await fetch(`${endpoint}/receipts/${receiptId}`, { headers: getSafeHeader() });
        const result = await response.json();
        if (!response.ok || result.code !== 200) throw new Error(result.msg || '获取收款单明细失败');
        if (result.data?.id !== receiptId || !Array.isArray(result.data?.items)) {
            throw new Error('收款单明细不完整，请重试');
        }
        return result.data;
    };

    const loadExpandedReceipt = async (receiptId) => {
        const requestId = (detailRequests.current[receiptId] || 0) + 1;
        detailRequests.current[receiptId] = requestId;
        setDetailStates(prev => ({ ...prev, [receiptId]: { data: null, loading: true, error: '' } }));
        try {
            const data = await fetchReceiptDetail(receiptId);
            if (detailRequests.current[receiptId] !== requestId) return;
            setDetailStates(prev => ({ ...prev, [receiptId]: { data, loading: false, error: '' } }));
        } catch (error) {
            if (detailRequests.current[receiptId] !== requestId) return;
            setDetailStates(prev => ({ ...prev, [receiptId]: { data: null, loading: false, error: error.message || '获取收款单明细失败' } }));
        }
    };

    const loadReviewDetail = async (receiptId) => {
        const requestId = ++reviewRequest.current;
        setReviewDetail({ data: null, loading: true, error: '' });
        try {
            const data = await fetchReceiptDetail(receiptId);
            if (reviewRequest.current !== requestId) return;
            setReviewDetail({ data, loading: false, error: '' });
        } catch (error) {
            if (reviewRequest.current !== requestId) return;
            setReviewDetail({ data: null, loading: false, error: error.message || '获取收款单明细失败' });
        }
    };

    const openReview = (receipt) => {
        setReviewing(receipt);
        setReviewRemark('');
        // A pending receipt's settlement preview can change after another receipt is reviewed.
        loadReviewDetail(receipt.id);
    };

    const closeReview = () => {
        reviewRequest.current += 1;
        setReviewing(null);
        setReviewDetail({ data: null, loading: false, error: '' });
    };

    const canReview = !!reviewing && reviewDetail.data?.id === reviewing.id
        && reviewDetail.data.status === 'pending' && !reviewDetail.loading && !reviewDetail.error;

    const review = async (action) => {
        if (!canReview || submitting) return;
        if (action === 'reject' && !reviewRemark.trim()) {
            messageApi.warning('驳回时请填写审核意见');
            return;
        }
        setSubmitting(true);
        const requestId = reviewRequest.current;
        try {
            const response = await fetch(`${endpoint}/finance/receipts/${reviewing.id}/review`, {
                method: 'PUT',
                headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ action, review_remark: reviewRemark }),
            });
            const result = await response.json();
            if (!response.ok || result.code !== 200) throw new Error(result.msg || '审核失败');
            messageApi.success('审核完成');
            detailRequests.current[reviewing.id] = (detailRequests.current[reviewing.id] || 0) + 1;
            setDetailStates(prev => ({ ...prev, [reviewing.id]: { data: result.data, loading: false, error: '' } }));
            if (reviewRequest.current === requestId) {
                closeReview();
                setReviewRemark('');
            }
            fetchReceipts(pagination.current);
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

    const handleReceiptAuditTourStepChange = async (nextStep) => {
        const stepKey = receiptAuditTourChapter.steps[nextStep]?.key;
        if (stepKey === 'review') {
            const pendingReceipt = receipts.find(receipt => receipt.status === 'pending');
            if (pendingReceipt) {
                openReview(pendingReceipt);
            }
        } else if (reviewing) {
            closeReview();
        }
    };

    const columns = [
        { title: '收款单号', dataIndex: 'receipt_no', key: 'receipt_no', width: 210 },
        { title: '客户', dataIndex: 'customer_name', key: 'customer_name', width: 150 },
        { title: '收款日期', dataIndex: 'receipt_date', key: 'receipt_date', width: 115 },
        { title: '金额(CNY)', dataIndex: 'total_amount', key: 'total_amount', width: 115, render: v => Number(v || 0).toFixed(2) },
        { title: '创建人', dataIndex: 'creator_name', key: 'creator_name', width: 105 },
        { title: '审核人', dataIndex: 'reviewer_name', key: 'reviewer_name', width: 105, render: v => v || '-' },
        { title: '结清状态', dataIndex: 'settlement_status', key: 'settlement_status', width: 105, render: v => <SettlementTag status={v} /> },
        { title: '审核状态', dataIndex: 'status', key: 'status', width: 95, render: v => <Text type={v === 'rejected' ? 'danger' : undefined}>{RECEIPT_STATUS[v]?.label || v}</Text> },
        {
            title: '操作', key: 'action', fixed: 'right', width: 235,
            render: (_, record) => <Space>
                <Button size="small" icon={<PrinterOutlined />} onClick={() => print(record)}>打印</Button>
                <Button size="small" onClick={() => setHistoryReceipt(record)}>历史</Button>
                {record.status === 'pending' && <Button data-tour="audit-review-action" size="small" type="primary" onClick={() => openReview(record)}>审核</Button>}
            </Space>
        },
    ];

    const reviewingReceipt = reviewDetail.data || reviewing;

    return (
        <div>
            {contextHolder}
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 4 }}>
                <FeatureTour
                    chapter={receiptAuditTourChapter}
                    steps={receiptAuditTourSteps}
                    autoEnabled={false}
                    forceAutoStart={continuingAuditFlow}
                    onStepChange={handleReceiptAuditTourStepChange}
                    onTourEnd={(status, mode) => {
                        closeReview();
                        if (mode !== 'auto' || !continuingAuditFlow) return;
                        if (status === 'completed') {
                            saveFeatureTourFlow({
                                userId: tourUserId,
                                campaignId: COST_QUOTE_RECEIPT_TOUR.id,
                                stage: 'receivable-ledger',
                            });
                        } else {
                            clearFeatureTourFlow(tourUserId);
                        }
                    }}
                    triggerAriaLabel="打开收款审核操作引导"
                />
            </div>
            <Card data-tour="audit-table" size="small" bodyStyle={{ padding: 0 }}>
                <div data-tour="audit-filter" style={{ padding: 12 }}>
                    <Space wrap>
                        <Input.Search
                            allowClear
                            value={receiptNoSearch}
                            onChange={event => { setReceiptNoSearch(event.target.value); setAuditPagination(previous => ({ ...previous, current: 1 })); }}
                            onSearch={() => fetchReceipts()}
                            placeholder="收款单号"
                            enterButton="搜索"
                            style={{ width: 260 }}
                        />
                        <Select value={status} onChange={value => { setStatus(value); setAuditPagination(previous => ({ ...previous, current: 1 })); }} style={{ width: 130 }} options={[{ value: 'pending', label: '待审核' }, { value: 'approved', label: '已生效' }, { value: 'rejected', label: '已驳回' }, { value: '', label: '全部' }]} />
                        <Button icon={<ReloadOutlined />} onClick={() => fetchReceipts(pagination.current)}>刷新</Button>
                    </Space>
                </div>
                <Table
                    rowKey="id"
                    loading={loading}
                    dataSource={receipts}
                    columns={columns}
                    pagination={{ ...pagination, ...auditPagination, showSizeChanger: true, showTotal: total => `共 ${total} 张收款单` }}
                    onChange={next => setAuditPagination({ current: next.current, pageSize: next.pageSize })}
                    scroll={{ x: 'max-content' }}
                    expandable={{
                        onExpand: (expanded, record) => {
                            if (expanded) loadExpandedReceipt(record.id);
                        },
                        expandedRowRender: record => {
                            const detail = detailStates[record.id];
                            if (detail?.error) return <Alert
                                type="error"
                                showIcon
                                message={detail.error}
                                action={<Button size="small" onClick={() => loadExpandedReceipt(record.id)}>重试加载明细</Button>}
                            />;
                            return <ReceiptItems receipt={detail?.data} loading={!detail || detail.loading} />;
                        },
                    }}
                />
            </Card>
            <Modal
                title={reviewing ? `收款审核 - ${reviewing.receipt_no}` : '收款审核'}
                open={!!reviewing}
                width={900}
                onCancel={() => { if (!submitting) closeReview(); }}
                closable={!submitting}
                maskClosable={!submitting}
                keyboard={!submitting}
                footer={[
                    <Button key="reject" danger disabled={!canReview} loading={submitting} onClick={() => review('reject')}>驳回</Button>,
                    <Button key="approve" type="primary" disabled={!canReview} loading={submitting} onClick={() => review('approve')}>审核通过</Button>,
                ]}
            >
                {reviewing && <div data-tour="audit-review-modal">
                    <Space direction="vertical" style={{ width: '100%' }}>
                        <Text>客户：{reviewingReceipt.customer_name}</Text>
                        <Text>实收金额：{Number(reviewingReceipt.total_amount || 0).toFixed(2)} CNY</Text>
                        <Text>创建人：{reviewingReceipt.creator_name}</Text>
                        <Text>结清状态：<SettlementTag status={reviewingReceipt.settlement_status} /></Text>
                        {reviewingReceipt.settlement_status === 'settled' && <Text type="secondary">审核通过后，结清差额不再计入待收，也不计入实际收入。</Text>}
                        {reviewDetail.error ? <Alert
                            type="error"
                            showIcon
                            message={reviewDetail.error}
                            action={<Button onClick={() => loadReviewDetail(reviewing.id)}>重试加载明细</Button>}
                        /> : <ReceiptItems receipt={reviewDetail.data} loading={reviewDetail.loading} />}
                        {reviewDetail.data && reviewDetail.data.status !== 'pending' && <Alert type="warning" showIcon message="该收款单已完成审核，请刷新列表查看最新状态。" />}
                        <Input.TextArea rows={3} value={reviewRemark} disabled={submitting} onChange={e => setReviewRemark(e.target.value)} placeholder="审核意见（驳回时必填）" />
                    </Space>
                </div>}
            </Modal>
            <FinanceHistoryDrawer open={!!historyReceipt} onClose={() => setHistoryReceipt(null)}
                title={historyReceipt ? `${historyReceipt.receipt_no} · 修改历史` : '收款修改历史'}
                historyUrl={historyReceipt ? `/receipts/${historyReceipt.id}/history` : null} />
        </div>
    );
}
