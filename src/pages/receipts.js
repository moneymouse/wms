import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
    Button, Card, Col, DatePicker, Form, Input, InputNumber, Modal, Row, Select, Space,
    Table, Tabs, Tag, Typography, message
} from 'antd';
import { CopyOutlined, PrinterOutlined, ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { Link } from 'react-router-dom';

import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import {
    amountToCents,
    getDefaultSettlementStatus,
    getRemainingReceivableCents,
    getSettlementDifferenceDisplay,
    getSettlementStatus,
    SETTLEMENT_OPTIONS,
} from '../common/receiptSettlement';
import FeatureTour from '../components/FeatureTour';
import { COST_QUOTE_RECEIPT_TOUR, getCostQuoteReceiptChapter } from '../common/featureTourConfig';
import {
    clearFeatureTourFlow,
    getCurrentTourUser,
    readFeatureTourFlow,
    saveFeatureTourFlow,
} from '../common/featureTourState';

const { Title, Text } = Typography;
const PAYMENT_METHODS = [
    { value: 'cash', label: '现金 / Cash' },
    { value: 'bank_transfer', label: '银行转账 / Bank Transfer' },
    { value: 'wechat', label: '微信 / WeChat Pay' },
    { value: 'alipay', label: '支付宝 / Alipay' },
    { value: 'other', label: '其他 / Other' },
];
const STATUS_LABELS = {
    pending: { label: '待审核', color: 'orange' },
    approved: { label: '已生效', color: 'green' },
    rejected: { label: '已驳回', color: 'red' },
};
const receiptEntryTourChapter = getCostQuoteReceiptChapter('receiptEntry');
const receiptEntryTourTargets = {
    basics: '[data-tour="receipt-basics"]',
    orders: '[data-tour="receipt-orders"]',
    submit: '[data-tour="receipt-submit"]',
    records: '[data-tour="receipt-records"]',
};

function getSelectionSignature(keys, amounts, cache) {
    return JSON.stringify([...keys].sort().map(uid => [
        uid, amountToCents(amounts[uid]),
        amountToCents(cache[uid]?.receivable_amount), amountToCents(cache[uid]?.approved_received),
    ]));
}

function base64ToBlob(base64, mimeType) {
    const binary = window.atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return new Blob([bytes], { type: mimeType });
}

async function printReceipt(receiptId, messageApi) {
    const preview = window.open('', '_blank');
    if (!preview) {
        messageApi.warning('浏览器拦截了新窗口，请允许弹窗后重试');
        return;
    }
    preview.document.write('正在生成收款单 PDF...');
    try {
        const response = await fetch(`${endpoint}/receipts/${receiptId}/pdf`, { headers: getSafeHeader() });
        const result = await response.json();
        if (!response.ok || result.code !== 200) throw new Error(result.msg || '生成失败');
        const url = URL.createObjectURL(base64ToBlob(result.data, result.mime_type || 'application/pdf'));
        preview.location.href = url;
        window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (error) {
        preview.close();
        messageApi.error(error.message || '生成收款单失败');
    }
}

export default function Receipts() {
    const [messageApi, contextHolder] = message.useMessage();
    const [form] = Form.useForm();
    const [filters, setFilters] = useState({});
    const [owners, setOwners] = useState([]);
    const [receiptModalOpen, setReceiptModalOpen] = useState(false);
    const ordersRequestId = useRef(0);
    const submitInProgress = useRef(false);
    const settlementSelection = useRef(null);
    const [activeTab, setActiveTab] = useState('entry');
    const [customers, setCustomers] = useState([]);
    const [orders, setOrders] = useState([]);
    const [orderCache, setOrderCache] = useState({});
    const [orderPagination, setOrderPagination] = useState({ current: 1, pageSize: 20, total: 0 });
    const [selectedKeys, setSelectedKeys] = useState([]);
    const [amounts, setAmounts] = useState({});
    const [loadingOrders, setLoadingOrders] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [receipts, setReceipts] = useState([]);
    const [receiptDetails, setReceiptDetails] = useState({});
    const [loadingReceiptDetails, setLoadingReceiptDetails] = useState({});
    const [loadingReceipts, setLoadingReceipts] = useState(false);
    const [receiptPagination, setReceiptPagination] = useState({ current: 1, pageSize: 20, total: 0 });
    const { userId: tourUserId, roles } = getCurrentTourUser();
    const isAdmin = roles.includes('admin');
    const tourFlow = readFeatureTourFlow(tourUserId);
    const continuingReceiptFlow = tourFlow?.campaignId === COST_QUOTE_RECEIPT_TOUR.id
        && ['receipt-navigation', 'receipt-entry'].includes(tourFlow.stage);

    useEffect(() => {
        fetch(`${endpoint}/customer_list`, { headers: getSafeHeader() })
            .then(response => response.json())
            .then(result => {
                if (result.code === 200) setCustomers(result.data || []);
            })
            .catch(() => messageApi.error('获取客户失败'));
    }, [messageApi]);

    useEffect(() => {
        if (!isAdmin) return;
        fetch(`${endpoint}/work/workers?roles=salesperson`, { headers: getSafeHeader() })
            .then(response => response.json())
            .then(result => {
                if (result.code !== 200) throw new Error(result.msg || '获取业务员失败');
                setOwners(result.data || []);
            })
            .catch(error => messageApi.error(error.message || '获取业务员失败'));
    }, [isAdmin, messageApi]);

    const fetchOrders = async (
        nextFilters = filters,
        page = 1,
        pageSize = orderPagination.pageSize,
        resetSelection = true
    ) => {
        const requestId = ++ordersRequestId.current;
        if (resetSelection) {
            setSelectedKeys([]);
            setOrderCache({});
            setAmounts({});
            setOrders([]);
            setOrderPagination({ current: page, pageSize, total: 0 });
        }
        setLoadingOrders(true);
        try {
            const params = new URLSearchParams();
            if (nextFilters.customer_id) params.set('customer_id', nextFilters.customer_id);
            if (nextFilters.dateRange?.[0] && nextFilters.dateRange?.[1]) {
                params.set('date_from', nextFilters.dateRange[0].format('YYYY-MM-DD'));
                params.set('date_to', nextFilters.dateRange[1].format('YYYY-MM-DD'));
            }
            if (isAdmin && nextFilters.owner_id) params.set('owner_id', nextFilters.owner_id);
            params.set('p', page);
            params.set('s', pageSize);
            const query = params.toString();
            const response = await fetch(
                `${endpoint}/receivables/orders${query ? `?${query}` : ''}`,
                { headers: getSafeHeader() }
            );
            const result = await response.json();
            if (requestId !== ordersRequestId.current) return null;
            if (!response.ok || result.code !== 200) throw new Error(result.msg || '获取可收款订单失败');
            const rows = result.data || [];
            setOrders(rows);
            setOrderCache(prev => {
                const currentPage = Object.fromEntries(rows.map(row => [row.uid, row]));
                return resetSelection ? currentPage : { ...prev, ...currentPage };
            });
            setOrderPagination({
                current: result.page || page,
                pageSize: result.page_size || pageSize,
                total: result.total || 0,
            });
            const defaults = {};
            rows.forEach(row => { defaults[row.uid] = Math.max(Number(row.available_amount || 0), 0); });
            setAmounts(prev => resetSelection ? defaults : { ...defaults, ...prev });
            return rows;
        } catch (error) {
            if (requestId !== ordersRequestId.current) return null;
            messageApi.error(error.message || '获取可收款订单失败');
            return null;
        } finally {
            if (requestId === ordersRequestId.current) setLoadingOrders(false);
        }
    };

    // Start without filters; the server enforces the current user's receivable scope.
    useEffect(() => {
        fetchOrders();
        return () => { ordersRequestId.current += 1; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const changeFilters = (changed) => {
        const nextFilters = { ...filters, ...changed };
        setFilters(nextFilters);
        fetchOrders(nextFilters);
    };

    const fetchReceipts = async (
        page = receiptPagination.current,
        pageSize = receiptPagination.pageSize
    ) => {
        setLoadingReceipts(true);
        try {
            const response = await fetch(`${endpoint}/receipts?p=${page}&s=${pageSize}`, { headers: getSafeHeader() });
            const result = await response.json();
            if (!response.ok || result.code !== 200) throw new Error(result.msg || '获取收款单失败');
            setReceipts(result.data || []);
            setReceiptPagination({ current: result.page || page, pageSize: result.page_size || pageSize, total: result.total || 0 });
        } catch (error) {
            messageApi.error(error.message || '获取收款单失败');
        } finally {
            setLoadingReceipts(false);
        }
    };

    useEffect(() => {
        if (activeTab === 'list') fetchReceipts(1, receiptPagination.pageSize);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeTab]);

    const fetchReceiptDetail = async (receiptId, refresh = false) => {
        if (!refresh && receiptDetails[receiptId]) return receiptDetails[receiptId];
        if (refresh) {
            setReceiptDetails(prev => {
                const next = { ...prev };
                delete next[receiptId];
                return next;
            });
        }
        setLoadingReceiptDetails(prev => ({ ...prev, [receiptId]: true }));
        try {
            const response = await fetch(`${endpoint}/receipts/${receiptId}`, { headers: getSafeHeader() });
            const result = await response.json();
            if (!response.ok || result.code !== 200) throw new Error(result.msg || '获取收款单明细失败');
            setReceiptDetails(prev => ({ ...prev, [receiptId]: result.data }));
            return result.data;
        } catch (error) {
            messageApi.error(error.message || '获取收款单明细失败');
            return null;
        } finally {
            setLoadingReceiptDetails(prev => ({ ...prev, [receiptId]: false }));
        }
    };

    const selectedTotal = useMemo(
        () => selectedKeys.reduce((sum, uid) => sum + amountToCents(amounts[uid]), 0) / 100,
        [selectedKeys, amounts]
    );
    const selectedOrders = useMemo(
        () => selectedKeys.map(uid => orderCache[uid]).filter(Boolean),
        [selectedKeys, orderCache]
    );
    const remainingReceivableCents = getRemainingReceivableCents(selectedOrders, amounts);
    const selectionSignature = getSelectionSignature(selectedKeys, amounts, orderCache);

    useEffect(() => {
        if (settlementSelection.current === selectionSignature) return;
        settlementSelection.current = selectionSignature;
        form.setFieldsValue({ settlement_status: getDefaultSettlementStatus(remainingReceivableCents) });
    }, [form, selectionSignature, remainingReceivableCents]);

    const selectedCustomerScope = filters.customer_id || selectedOrders[0]?.customer_id;
    const receiptEntryTourSteps = receiptEntryTourChapter.steps.map(step => ({
        ...step,
        target: () => document.querySelector(receiptEntryTourTargets[step.key]),
    }));

    const handleReceiptTourStepChange = async (nextStep) => {
        const targetTab = receiptEntryTourChapter.steps[nextStep]?.tab;
        if (targetTab && targetTab !== activeTab) setActiveTab(targetTab);
    };

    const submitReceipt = async () => {
        if (submitInProgress.current) return;
        submitInProgress.current = true;
        setSubmitting(true);
        try {
            const values = await form.validateFields();
            if (!selectedKeys.length) {
                messageApi.warning('请至少选择一笔订单');
                return;
            }
            const selectedCustomerIds = new Set(
                selectedOrders.map(order => order.customer_id).filter(Boolean)
            );
            const effectiveCustomerId = selectedCustomerIds.size === 1 ? [...selectedCustomerIds][0] : null;
            if (!effectiveCustomerId || selectedOrders.length !== selectedKeys.length
                || selectedOrders.some(order => order.customer_id !== effectiveCustomerId)) {
                messageApi.warning('同一收款单只能选择同一个客户的订单');
                return;
            }
            const invalidOrder = selectedOrders.find(order => {
                const amount = Number(amounts[order.uid]);
                return !Number.isFinite(amount) || amount <= 0 || amount > Number(order.available_amount || 0);
            });
            if (invalidOrder) {
                messageApi.warning(`订单 ${invalidOrder.order_id} 的本次收款必须大于 0 且不超过可收余额`);
                return;
            }
            const response = await fetch(`${endpoint}/receipts`, {
                method: 'POST',
                headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    customer_id: effectiveCustomerId,
                    receipt_date: values.receipt_date.format('YYYY-MM-DD'),
                    payment_method: values.payment_method,
                    settlement_status: values.settlement_status,
                    remark: values.remark,
                    items: selectedKeys.map(orderUid => ({ order_uid: orderUid, amount: Number(amounts[orderUid] || 0) })),
                }),
            });
            const result = await response.json();
            if (!response.ok || result.code !== 200) throw new Error(result.msg || '提交失败');
            messageApi.success(`收款单 ${result.data.receipt_no} 已提交审核`);
            setReceiptModalOpen(false);
            form.resetFields();
            form.setFieldsValue({ receipt_date: dayjs(), payment_method: 'cash', remark: '' });
            setSelectedKeys([]);
            await printReceipt(result.data.id, messageApi);
            await fetchOrders(filters);
            setActiveTab('list');
        } catch (error) {
            if (error?.errorFields) return;
            messageApi.error(error.message || '提交收款单失败');
        } finally {
            submitInProgress.current = false;
            setSubmitting(false);
        }
    };

    const copyRejectedReceipt = async (receipt) => {
        const receiptDetail = receipt.items ? receipt : await fetchReceiptDetail(receipt.id);
        if (!receiptDetail) return;
        form.setFieldsValue({
            receipt_date: dayjs(),
            payment_method: receiptDetail.payment_method,
            remark: receiptDetail.remark || '',
        });
        const nextFilters = { customer_id: receiptDetail.customer_id };
        setFilters(nextFilters);
        const availableOrders = await fetchOrders(nextFilters);
        if (!availableOrders) return;
        const availableMap = Object.fromEntries(availableOrders.map(row => [row.uid, row]));
        const nextKeys = [];
        const nextAmounts = {};
        (receiptDetail.items || []).forEach(item => {
            const available = availableMap[item.order_uid];
            if (!available) return;
            nextKeys.push(item.order_uid);
            nextAmounts[item.order_uid] = Math.min(Number(item.amount || 0), Number(available.available_amount || 0));
        });
        setSelectedKeys(nextKeys);
        setAmounts(prev => ({ ...prev, ...nextAmounts }));
        settlementSelection.current = getSelectionSignature(nextKeys, nextAmounts, availableMap);
        const copiedStatus = receiptDetail.settlement_status;
        form.setFieldsValue({
            settlement_status: SETTLEMENT_OPTIONS.some(option => option.value === copiedStatus)
                ? copiedStatus
                : getDefaultSettlementStatus(getRemainingReceivableCents(
                    nextKeys.map(uid => availableMap[uid]), nextAmounts
                )),
        });
        setActiveTab('entry');
        messageApi.info(nextKeys.length ? '已复制可重新登记的明细' : '原订单当前没有可收余额');
    };

    const orderColumns = [
        {
            title: '订单号', dataIndex: 'order_id', key: 'order_id', width: 190,
            render: (value, record) => <Link to={`/orders/${record.uid}`}>{value}</Link>,
        },
        {
            title: '订单创建时间', dataIndex: 'create_date', key: 'create_date', width: 180,
            render: value => value && dayjs(value).isValid() ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '-',
        },
        { title: '客户', dataIndex: 'customer_name', key: 'customer_name', width: 150 },
        { title: '报价人', dataIndex: 'quoter_name', key: 'quoter_name', width: 110 },
        {
            title: '计费重量(kg)', dataIndex: 'billing_weight', key: 'billing_weight', width: 130,
            render: value => Number(value || 0).toFixed(0),
        },
        { title: '应收(CNY)', dataIndex: 'receivable_amount', key: 'receivable_amount', width: 120, render: v => Number(v || 0).toFixed(2) },
        { title: '已收', dataIndex: 'approved_received', key: 'approved_received', width: 100, render: v => Number(v || 0).toFixed(2) },
        { title: '待审核占用', dataIndex: 'pending_amount', key: 'pending_amount', width: 120, render: v => Number(v || 0).toFixed(2) },
        {
            title: '本次收款(CNY)', key: 'amount', width: 160,
            render: (_, record) => (
                <InputNumber
                    min={0.01}
                    max={Number(record.available_amount || 0)}
                    precision={2}
                    value={amounts[record.uid]}
                    disabled={!selectedKeys.includes(record.uid)}
                    onChange={value => setAmounts(prev => ({ ...prev, [record.uid]: value }))}
                />
            )
        },
    ];

    const receiptColumns = [
        { title: '收款单号', dataIndex: 'receipt_no', key: 'receipt_no', width: 210 },
        { title: '客户', dataIndex: 'customer_name', key: 'customer_name', width: 160 },
        { title: '收款日期', dataIndex: 'receipt_date', key: 'receipt_date', width: 115 },
        { title: '金额(CNY)', dataIndex: 'total_amount', key: 'total_amount', width: 120, render: v => Number(v || 0).toFixed(2) },
        {
            title: '审核状态', dataIndex: 'status', key: 'status', width: 100,
            render: value => <Tag color={STATUS_LABELS[value]?.color}>{STATUS_LABELS[value]?.label || value}</Tag>
        },
        {
            title: '结清状态', dataIndex: 'settlement_status', key: 'settlement_status', width: 110,
            render: value => {
                const status = getSettlementStatus(value);
                return <Tag color={status.color}>{status.label}</Tag>;
            },
        },
        { title: '创建人', dataIndex: 'creator_name', key: 'creator_name', width: 110 },
        { title: '审核人', dataIndex: 'reviewer_name', key: 'reviewer_name', width: 110, render: v => v || '-' },
        {
            title: '操作', key: 'action', fixed: 'right', width: 190,
            render: (_, record) => (
                <Space>
                    <Button size="small" icon={<PrinterOutlined />} onClick={() => printReceipt(record.id, messageApi)}>打印</Button>
                    {record.status === 'rejected' && (
                        <Button size="small" icon={<CopyOutlined />} onClick={() => copyRejectedReceipt(record)}>复制新建</Button>
                    )}
                </Space>
            )
        },
    ];

    return (
        <div style={{ padding: '8px 16px' }}>
            {contextHolder}
            <div data-tour="receipt-page-title" style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 8 }}>
                <Title level={4} style={{ margin: 0 }}>收款管理 / Payment Receipts</Title>
                <FeatureTour
                    chapter={receiptEntryTourChapter}
                    steps={receiptEntryTourSteps}
                    autoEnabled={false}
                    forceAutoStart={continuingReceiptFlow}
                    onStart={(mode) => {
                        if (mode === 'auto' && continuingReceiptFlow) {
                            saveFeatureTourFlow({
                                userId: tourUserId,
                                campaignId: COST_QUOTE_RECEIPT_TOUR.id,
                                stage: 'receipt-entry',
                            });
                        }
                    }}
                    onStepChange={handleReceiptTourStepChange}
                    onTourEnd={(status, mode) => {
                        if (mode === 'auto' && continuingReceiptFlow) {
                            clearFeatureTourFlow(tourUserId);
                        }
                    }}
                    triggerAriaLabel="打开收款登记操作引导"
                />
            </div>
            <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
                {
                    key: 'entry',
                    label: '收款登记',
                    children: (
                        <>
                            <Card data-tour="receipt-basics" size="small" style={{ marginBottom: 16 }}>
                                <Form layout="vertical">
                                    <Row gutter={16}>
                                        <Col xs={24} md={8}>
                                            <Form.Item label="客户" htmlFor="receipt-customer-filter" style={{ marginBottom: 8 }}>
                                                <Select
                                                    id="receipt-customer-filter"
                                                    allowClear
                                                    showSearch
                                                    optionFilterProp="label"
                                                    placeholder="全部客户"
                                                    value={filters.customer_id}
                                                    options={customers.map(item => ({ value: item.id, label: item.name }))}
                                                    onChange={customerId => changeFilters({ customer_id: customerId })}
                                                />
                                            </Form.Item>
                                        </Col>
                                        <Col xs={24} md={isAdmin ? 8 : 16}>
                                            <Form.Item label="订单日期" htmlFor="receipt-order-date-filter" style={{ marginBottom: 8 }}>
                                                <DatePicker.RangePicker
                                                    id="receipt-order-date-filter"
                                                    aria-label="订单日期"
                                                    value={filters.dateRange || null}
                                                    onChange={dateRange => changeFilters({ dateRange })}
                                                    format="YYYY-MM-DD"
                                                    placeholder={['开始日期', '结束日期']}
                                                    style={{ width: '100%' }}
                                                />
                                            </Form.Item>
                                        </Col>
                                        {isAdmin && (
                                            <Col xs={24} md={8}>
                                                <Form.Item label="业务员" htmlFor="receipt-owner-filter" style={{ marginBottom: 8 }}>
                                                    <Select
                                                        id="receipt-owner-filter"
                                                        allowClear
                                                        showSearch
                                                        optionFilterProp="label"
                                                        placeholder="全部业务员"
                                                        value={filters.owner_id}
                                                        options={owners.map(item => ({ value: item.id, label: item.name }))}
                                                        onChange={ownerId => changeFilters({ owner_id: ownerId })}
                                                    />
                                                </Form.Item>
                                            </Col>
                                        )}
                                    </Row>
                                </Form>
                            </Card>
                            <Card data-tour="receipt-orders" size="small" bodyStyle={{ padding: 0 }} title="未结清订单">
                                <div data-tour="receipt-submit" style={{ padding: 12 }}>
                                    <Space wrap size="middle">
                                        <Button
                                            type="primary"
                                            loading={submitting}
                                            disabled={!selectedKeys.length || loadingOrders}
                                            onClick={() => setReceiptModalOpen(true)}
                                        >生成并提交收款单</Button>
                                        <Text>已选 {selectedKeys.length} 笔订单</Text>
                                        <Text strong>本次合计：{selectedTotal.toFixed(2)} CNY</Text>
                                    </Space>
                                    <div style={{ marginTop: 8 }}>
                                        <Text type="secondary">待审核金额会占用订单可收余额；财务审核通过后计入已收，结清差额不计入收入。</Text>
                                    </div>
                                </div>
                                <Table
                                    rowKey="uid"
                                    loading={loadingOrders}
                                    dataSource={orders}
                                    columns={orderColumns}
                                    rowSelection={{
                                        selectedRowKeys: selectedKeys,
                                        onChange: keys => {
                                            const customerIds = new Set(keys.map(uid => orderCache[uid]?.customer_id));
                                            if (customerIds.size > 1) {
                                                messageApi.warning('同一收款单只能选择同一个客户的订单');
                                                return;
                                            }
                                            setSelectedKeys(keys);
                                        },
                                        preserveSelectedRowKeys: true,
                                        getCheckboxProps: record => ({
                                            disabled: (
                                                !record.customer_id
                                                || Number(record.available_amount || 0) <= 0
                                                || Boolean(
                                                    selectedCustomerScope
                                                    && record.customer_id !== selectedCustomerScope
                                                )
                                            ),
                                        }),
                                    }}
                                    pagination={{
                                        ...orderPagination,
                                        showSizeChanger: false,
                                    }}
                                    onChange={next => fetchOrders(
                                        filters,
                                        next.current,
                                        next.pageSize,
                                        false
                                    )}
                                    scroll={{ x: 'max-content' }}
                                    size="small"
                                />
                            </Card>
                        </>
                    )
                },
                {
                    key: 'list',
                    label: '收款单记录',
                    children: (
                        <Card data-tour="receipt-records" size="small" bodyStyle={{ padding: 0 }}>
                            <div style={{ padding: 12 }}><Button icon={<ReloadOutlined />} onClick={() => fetchReceipts()}>刷新</Button></div>
                            <Table
                                rowKey="id"
                                loading={loadingReceipts}
                                dataSource={receipts}
                                columns={receiptColumns}
                                pagination={{ ...receiptPagination, showSizeChanger: false }}
                                onChange={next => fetchReceipts(next.current, next.pageSize)}
                                expandable={{
                                    expandedRowRender: record => (
                                        <Table
                                            rowKey="id"
                                            size="small"
                                            pagination={false}
                                            loading={Boolean(loadingReceiptDetails[record.id])}
                                            dataSource={receiptDetails[record.id]?.items || []}
                                            columns={[
                                                {
                                                    title: '订单号', dataIndex: 'order_id',
                                                    render: (value, item) => <Link to={`/orders/${item.order_uid}`}>{value}</Link>,
                                                },
                                                { title: '应收', dataIndex: 'receivable_snapshot', render: v => Number(v || 0).toFixed(2) },
                                                { title: '本次收款', dataIndex: 'amount', render: v => Number(v || 0).toFixed(2) },
                                                { title: '可收余额快照', dataIndex: 'remaining_after', render: v => Number(v || 0).toFixed(2) },
                                                {
                                                    title: getSettlementDifferenceDisplay(receiptDetails[record.id] || record).label,
                                                    key: 'settlement_difference',
                                                    render: (_, item) => {
                                                        const { value } = getSettlementDifferenceDisplay(receiptDetails[record.id] || record, item);
                                                        return value == null ? '-' : Number(value).toFixed(2);
                                                    },
                                                },
                                            ]}
                                        />
                                    ),
                                    onExpand: (expanded, record) => {
                                        if (expanded) fetchReceiptDetail(record.id, true);
                                    },
                                }}
                                scroll={{ x: 'max-content' }}
                            />
                        </Card>
                    )
                }
            ]} />
            <Modal
                title="确认收款信息"
                open={receiptModalOpen}
                forceRender
                onOk={submitReceipt}
                onCancel={() => { if (!submitInProgress.current) setReceiptModalOpen(false); }}
                okText="确认提交"
                cancelText="取消"
                confirmLoading={submitting}
                cancelButtonProps={{ disabled: submitting }}
                closable={!submitting}
                maskClosable={!submitting}
                keyboard={!submitting}
            >
                <Space direction="vertical" style={{ marginBottom: 16 }}>
                    <Text>客户：{selectedOrders[0]?.customer_name || '-'}</Text>
                    <Text>已选 {selectedKeys.length} 笔订单</Text>
                    <Text strong>本次合计：{selectedTotal.toFixed(2)} CNY</Text>
                    <Text>本次收款后剩余应收合计：{(remainingReceivableCents / 100).toFixed(2)} CNY</Text>
                </Space>
                <Form
                    form={form}
                    layout="vertical"
                    disabled={submitting}
                    initialValues={{ receipt_date: dayjs(), payment_method: 'cash', remark: '' }}
                >
                    <Form.Item name="receipt_date" label="收款日期" rules={[{ required: true, message: '请选择收款日期' }]}>
                        <DatePicker style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item name="payment_method" label="收款方式" rules={[{ required: true, message: '请选择收款方式' }]}>
                        <Select options={PAYMENT_METHODS} />
                    </Form.Item>
                    <Form.Item
                        name="settlement_status"
                        label="结清状态"
                        rules={[{ required: true, message: '请选择结清状态' }]}
                        extra="原应收减去已审核实收及本次收款后，合计小于30元默认已结清，否则默认未结清；可手动修改。其他待审核收款不参与默认计算，结清在财务审核通过后生效，余额为0的订单仍自动结清。"
                    >
                        <Select options={SETTLEMENT_OPTIONS} />
                    </Form.Item>
                    <Form.Item name="remark" label="备注"><Input.TextArea rows={2} /></Form.Item>
                </Form>
            </Modal>
        </div>
    );
}
