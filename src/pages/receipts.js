import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
    Button, Card, Col, DatePicker, Form, InputNumber, Row, Select, Space,
    Table, Tabs, Tag, Typography, message
} from 'antd';
import { CopyOutlined, PrinterOutlined, ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { Link } from 'react-router-dom';

import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import { createReceipt, printReceipt } from '../common/receiptApi';
import ReceiptModal, { AdjustmentReceiptModal } from '../components/ReceiptModal';
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
    decodeJwtPayload,
    getCurrentTourUser,
    readFeatureTourFlow,
    saveFeatureTourFlow,
} from '../common/featureTourState';

const { Title, Text } = Typography;
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
        amountToCents(cache[uid]?.settlement_difference),
    ]));
}

export default function Receipts() {
    const { userId: tourUserId, roles } = getCurrentTourUser();
    const isAdmin = roles.includes('admin');
    const currentUserName = decodeJwtPayload(window.localStorage.getItem('jwt'))?.name || '我自己';
    const [messageApi, contextHolder] = message.useMessage();
    const [form] = Form.useForm();
    const [filters, setFilters] = useState(() => (isAdmin && tourUserId ? { owner_id: tourUserId } : {}));
    const [owners, setOwners] = useState([]);
    const [receiptModalOpen, setReceiptModalOpen] = useState(false);
    const ordersRequestId = useRef(0);
    const adjustmentsRequestId = useRef(0);
    const receiptsRequestId = useRef(0);
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
    const [adjustments, setAdjustments] = useState([]);
    const [loadingAdjustments, setLoadingAdjustments] = useState(false);
    const [adjustmentPagination, setAdjustmentPagination] = useState({ current: 1, pageSize: 20, total: 0 });
    const [activeAdjustment, setActiveAdjustment] = useState(null);
    const [submitting, setSubmitting] = useState(false);
    const [receipts, setReceipts] = useState([]);
    const [receiptDetails, setReceiptDetails] = useState({});
    const [loadingReceiptDetails, setLoadingReceiptDetails] = useState({});
    const [loadingReceipts, setLoadingReceipts] = useState(false);
    const [receiptPagination, setReceiptPagination] = useState({ current: 1, pageSize: 20, total: 0 });
    const tourFlow = readFeatureTourFlow(tourUserId);
    const continuingReceiptFlow = tourFlow?.campaignId === COST_QUOTE_RECEIPT_TOUR.id
        && ['receipt-navigation', 'receipt-entry'].includes(tourFlow.stage);
    const ownerOptions = useMemo(() => {
        const options = owners.map(item => ({ value: String(item.id), label: item.name }));
        if (tourUserId && !options.some(option => option.value === tourUserId)) {
            options.unshift({ value: tourUserId, label: currentUserName });
        }
        return options;
    }, [owners, tourUserId, currentUserName]);

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

    // Apply the administrator's own scope before the first request.
    useEffect(() => {
        fetchOrders();
        return () => { ordersRequestId.current += 1; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const changeFilters = (changed) => {
        const nextFilters = { ...filters, ...changed };
        setFilters(nextFilters);
        const ordersPromise = fetchOrders(nextFilters);
        if (Object.prototype.hasOwnProperty.call(changed, 'owner_id')) {
            fetchAdjustments(1, adjustmentPagination.pageSize, nextFilters);
            receiptsRequestId.current += 1;
            setReceipts([]);
            if (activeTab !== 'list') setLoadingReceipts(false);
            setReceiptPagination(prev => ({ ...prev, current: 1 }));
            if (activeTab === 'list') fetchReceipts(1, receiptPagination.pageSize, nextFilters);
        }
        return ordersPromise;
    };

    const fetchAdjustments = async (
        page = adjustmentPagination.current,
        pageSize = adjustmentPagination.pageSize,
        nextFilters = filters
    ) => {
        const requestId = ++adjustmentsRequestId.current;
        setLoadingAdjustments(true);
        try {
            const params = new URLSearchParams({ status: 'pending', p: page, s: pageSize });
            if (isAdmin && nextFilters.owner_id) params.set('owner_id', nextFilters.owner_id);
            const response = await fetch(
                `${endpoint}/receivable-adjustments?${params}`,
                { headers: getSafeHeader() }
            );
            const result = await response.json();
            if (requestId !== adjustmentsRequestId.current) return null;
            if (!response.ok || result.code !== 200) throw new Error(result.msg || '获取差价单失败');
            setAdjustments(result.data || []);
            setAdjustmentPagination({
                current: result.page || page,
                pageSize: result.page_size || pageSize,
                total: result.total || 0,
            });
            return result.data || [];
        } catch (error) {
            if (requestId !== adjustmentsRequestId.current) return null;
            messageApi.error(error.message || '获取差价单失败');
            return null;
        } finally {
            if (requestId === adjustmentsRequestId.current) setLoadingAdjustments(false);
        }
    };

    useEffect(() => {
        fetchAdjustments(1, adjustmentPagination.pageSize);
        return () => { adjustmentsRequestId.current += 1; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const fetchReceipts = async (
        page = receiptPagination.current,
        pageSize = receiptPagination.pageSize,
        nextFilters = filters
    ) => {
        const requestId = ++receiptsRequestId.current;
        setLoadingReceipts(true);
        try {
            const params = new URLSearchParams({ p: page, s: pageSize });
            if (isAdmin && nextFilters.owner_id) params.set('owner_id', nextFilters.owner_id);
            const response = await fetch(`${endpoint}/receipts?${params}`, { headers: getSafeHeader() });
            const result = await response.json();
            if (requestId !== receiptsRequestId.current) return;
            if (!response.ok || result.code !== 200) throw new Error(result.msg || '获取收款单失败');
            setReceipts(result.data || []);
            setReceiptPagination({ current: result.page || page, pageSize: result.page_size || pageSize, total: result.total || 0 });
        } catch (error) {
            if (requestId !== receiptsRequestId.current) return;
            messageApi.error(error.message || '获取收款单失败');
        } finally {
            if (requestId === receiptsRequestId.current) setLoadingReceipts(false);
        }
    };

    useEffect(() => {
        if (activeTab === 'list') fetchReceipts(1, receiptPagination.pageSize);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeTab]);

    useEffect(() => () => { receiptsRequestId.current += 1; }, []);

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
            const receipt = await createReceipt({
                customer_id: effectiveCustomerId,
                receipt_date: values.receipt_date.format('YYYY-MM-DD'),
                payment_method: values.payment_method,
                settlement_status: values.settlement_status,
                remark: values.remark,
                items: selectedKeys.map(orderUid => ({ order_uid: orderUid, amount: Number(amounts[orderUid] || 0) })),
            });
            messageApi.success(`收款单 ${receipt.receipt_no} 已提交审核`);
            setReceiptModalOpen(false);
            form.resetFields();
            form.setFieldsValue({ receipt_date: dayjs(), payment_method: 'cash', remark: '' });
            setSelectedKeys([]);
            await printReceipt(receipt.id, messageApi);
            await fetchOrders(filters);
            await fetchAdjustments();
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
        const adjustmentItem = receiptDetail.items?.find(item => item.adjustment_id != null);
        if (adjustmentItem) {
            try {
                const response = await fetch(`${endpoint}/receivable-adjustments/${adjustmentItem.adjustment_id}`, {
                    headers: getSafeHeader(),
                });
                const result = await response.json();
                if (!response.ok || result.code !== 200) throw new Error(result.msg || '获取差价单失败');
                const adjustment = result.data;
                if (adjustment.status !== 'pending' || Number(adjustment.available_amount || 0) <= 0) {
                    messageApi.info(adjustment.collection_blocked_reason || '该差价当前没有可补收余额');
                    return;
                }
                setActiveTab('entry');
                setActiveAdjustment({
                    ...adjustment,
                    copyValues: {
                        amount: Math.min(Number(adjustmentItem.amount), Number(adjustment.available_amount)),
                        payment_method: receiptDetail.payment_method,
                        remark: receiptDetail.remark || '',
                    },
                });
            } catch (error) {
                messageApi.error(error.message || '复制差价收款单失败');
            }
            return;
        }
        form.setFieldsValue({
            receipt_date: dayjs(),
            payment_method: receiptDetail.payment_method,
            remark: receiptDetail.remark || '',
        });
        const availableOrders = await changeFilters({
            customer_id: receiptDetail.customer_id, dateRange: null, owner_id: undefined,
        });
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

    const submitAdjustmentReceipt = async (adjustmentForm) => {
        if (submitInProgress.current) return;
        submitInProgress.current = true;
        setSubmitting(true);
        try {
            const values = await adjustmentForm.validateFields();
            const receipt = await createReceipt({
                customer_id: activeAdjustment.customer_id,
                receipt_date: values.receipt_date.format('YYYY-MM-DD'),
                payment_method: values.payment_method,
                settlement_status: 'unsettled',
                remark: values.remark,
                items: [{
                    order_uid: activeAdjustment.order_uid,
                    amount: Number(values.amount),
                    adjustment_id: activeAdjustment.id,
                }],
            });
            messageApi.success(`差价收款单 ${receipt.receipt_no} 已提交审核`);
            setActiveAdjustment(null);
            await printReceipt(receipt.id, messageApi);
            await fetchOrders(filters);
            await fetchAdjustments();
            setActiveTab('list');
        } catch (error) {
            if (error?.errorFields) return;
            messageApi.error(error.message || '提交差价收款单失败');
        } finally {
            submitInProgress.current = false;
            setSubmitting(false);
        }
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

    const adjustmentColumns = [
        {
            title: '订单号', dataIndex: 'order_id', key: 'order_id', width: 170,
            render: (value, record) => <Link to={`/orders/${record.order_uid}`}>{value}</Link>,
        },
        { title: '客户', dataIndex: 'customer_name', key: 'customer_name', width: 150, render: value => value || '-' },
        { title: '原应收', dataIndex: 'old_receivable', key: 'old_receivable', width: 110, render: value => Number(value || 0).toFixed(2) },
        { title: '新应收', dataIndex: 'new_receivable', key: 'new_receivable', width: 110, render: value => Number(value || 0).toFixed(2) },
        {
            title: '差价', dataIndex: 'delta_amount', key: 'delta_amount', width: 130,
            render: (value, record) => (
                <Typography.Text type={record.direction === 'refund' ? 'success' : 'danger'} strong>
                    {Number(value || 0) > 0 ? '+' : ''}{Number(value || 0).toFixed(2)}
                </Typography.Text>
            ),
        },
        {
            title: '处理方向', dataIndex: 'direction', key: 'direction', width: 110,
            render: value => value === 'refund'
                ? <Tag color="green">待退款</Tag>
                : <Tag color="orange">待补收</Tag>,
        },
        { title: '已补收', dataIndex: 'approved_received', key: 'approved_received', width: 110, render: value => Number(value || 0).toFixed(2) },
        { title: '待审核占用', dataIndex: 'pending_amount', key: 'pending_amount', width: 120, render: value => Number(value || 0).toFixed(2) },
        { title: '可补收(CNY)', dataIndex: 'available_amount', key: 'available_amount', width: 130, render: value => Number(value || 0).toFixed(2) },
        { title: '报价人', dataIndex: 'quoter_name', key: 'quoter_name', width: 110, render: value => value || '-' },
        { title: '生成时间', dataIndex: 'create_date', key: 'create_date', width: 170 },
        {
            title: '操作', key: 'action', fixed: 'right', width: 230,
            render: (_, record) => record.direction === 'refund'
                ? <Text type="secondary">退款需财务处理</Text>
                : (
                    <Space direction="vertical" size={0}>
                        <Button
                            size="small"
                            type="primary"
                            disabled={submitting || loadingAdjustments || !record.customer_id || Number(record.available_amount || 0) <= 0}
                            onClick={() => setActiveAdjustment(record)}
                        >登记补收</Button>
                        {(!record.customer_id || Number(record.available_amount || 0) <= 0) && (
                            <Text type="secondary">
                                {record.collection_blocked_reason || (!record.customer_id
                                    ? '请先关联客户'
                                    : Number(record.pending_amount || 0) > 0 ? '差价收款单待审核' : '当前无可补收余额')}
                            </Text>
                        )}
                    </Space>
                ),
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
            {isAdmin && (
                <Card size="small" style={{ marginBottom: 8 }}>
                    <Form layout="vertical">
                        <Form.Item label="业务员" htmlFor="receipt-owner-filter" style={{ marginBottom: 0, maxWidth: 360 }}>
                            <Select
                                id="receipt-owner-filter"
                                allowClear
                                showSearch
                                optionFilterProp="label"
                                placeholder="全部业务员"
                                value={filters.owner_id}
                                options={ownerOptions}
                                onChange={ownerId => changeFilters({ owner_id: ownerId })}
                            />
                        </Form.Item>
                    </Form>
                </Card>
            )}
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
                                        <Col xs={24} md={16}>
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
                                    </Row>
                                </Form>
                            </Card>
                            <Card data-tour="receipt-orders" size="small" styles={{ body: { padding: 0 } }} style={{ marginBottom: 16 }} title="未结清订单">
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
                            <Card
                                size="small"
                                title="待处理差价"
                                extra={<Button size="small" icon={<ReloadOutlined />} onClick={() => fetchAdjustments()}>刷新</Button>}
                                styles={{ body: { padding: 0 } }}
                            >
                                <div style={{ padding: '8px 12px' }}>
                                    <Text type="secondary">重报价生效后生成；待补收可登记收款单，财务审核通过后计入实收并更新差价余额。待退款需财务处理，不代表现金已经收取或退还。</Text>
                                </div>
                                <Table
                                    rowKey="id"
                                    loading={loadingAdjustments}
                                    dataSource={adjustments}
                                    columns={adjustmentColumns}
                                    pagination={{ ...adjustmentPagination, showSizeChanger: false }}
                                    onChange={next => fetchAdjustments(next.current, next.pageSize)}
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
                        <Card data-tour="receipt-records" size="small" styles={{ body: { padding: 0 } }}>
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
            {activeAdjustment && (
                <AdjustmentReceiptModal
                    key={activeAdjustment.id}
                    adjustment={activeAdjustment}
                    submitting={submitting}
                    onSubmit={submitAdjustmentReceipt}
                    onCancel={() => { if (!submitInProgress.current) setActiveAdjustment(null); }}
                />
            )}
            <ReceiptModal
                open={receiptModalOpen}
                form={form}
                submitting={submitting}
                onSubmit={submitReceipt}
                onCancel={() => { if (!submitInProgress.current) setReceiptModalOpen(false); }}
                orders={selectedOrders}
                selectedTotal={selectedTotal}
                remainingReceivableCents={remainingReceivableCents}
            />
        </div>
    );
}
