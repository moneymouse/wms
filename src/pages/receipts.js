import React, { useEffect, useMemo, useState } from 'react';
import {
    Button, Card, Col, DatePicker, Form, Input, InputNumber, Row, Select, Space,
    Statistic, Table, Tabs, Tag, Typography, message
} from 'antd';
import { CopyOutlined, PrinterOutlined, ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { useNavigate } from 'react-router-dom';

import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
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
    const navigate = useNavigate();
    const [messageApi, contextHolder] = message.useMessage();
    const [form] = Form.useForm();
    const [activeTab, setActiveTab] = useState('entry');
    const [customers, setCustomers] = useState([]);
    const [orders, setOrders] = useState([]);
    const [selectedKeys, setSelectedKeys] = useState([]);
    const [amounts, setAmounts] = useState({});
    const [loadingOrders, setLoadingOrders] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [receipts, setReceipts] = useState([]);
    const [loadingReceipts, setLoadingReceipts] = useState(false);
    const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 });
    const { userId: tourUserId, roles: tourUserRoles } = getCurrentTourUser();
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
        form.setFieldsValue({
            receipt_date: dayjs(),
            payment_method: 'cash',
            remark: '',
        });
    }, [form, messageApi]);

    const fetchOrders = async (customerId) => {
        if (!customerId) {
            setOrders([]);
            return [];
        }
        setLoadingOrders(true);
        try {
            const response = await fetch(`${endpoint}/receivables/orders?customer_id=${customerId}`, { headers: getSafeHeader() });
            const result = await response.json();
            if (!response.ok || result.code !== 200) throw new Error(result.msg || '获取可收款订单失败');
            const rows = result.data || [];
            setOrders(rows);
            const defaults = {};
            rows.forEach(row => { defaults[row.uid] = Number(row.available_amount || 0); });
            setAmounts(defaults);
            setSelectedKeys([]);
            return rows;
        } catch (error) {
            messageApi.error(error.message || '获取可收款订单失败');
            return [];
        } finally {
            setLoadingOrders(false);
        }
    };

    const fetchReceipts = async (page = pagination.current, pageSize = pagination.pageSize) => {
        setLoadingReceipts(true);
        try {
            const response = await fetch(`${endpoint}/receipts?p=${page}&s=${pageSize}`, { headers: getSafeHeader() });
            const result = await response.json();
            if (!response.ok || result.code !== 200) throw new Error(result.msg || '获取收款单失败');
            setReceipts(result.data || []);
            setPagination({ current: result.page || page, pageSize: result.page_size || pageSize, total: result.total || 0 });
        } catch (error) {
            messageApi.error(error.message || '获取收款单失败');
        } finally {
            setLoadingReceipts(false);
        }
    };

    useEffect(() => {
        if (activeTab === 'list') fetchReceipts(1, pagination.pageSize);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeTab]);

    const selectedTotal = useMemo(
        () => selectedKeys.reduce((sum, uid) => sum + Number(amounts[uid] || 0), 0),
        [selectedKeys, amounts]
    );
    const receiptEntryTourSteps = receiptEntryTourChapter.steps.map(step => ({
        ...step,
        target: () => document.querySelector(receiptEntryTourTargets[step.key]),
    }));

    const handleReceiptTourStepChange = async (nextStep) => {
        const targetTab = receiptEntryTourChapter.steps[nextStep]?.tab;
        if (targetTab && targetTab !== activeTab) setActiveTab(targetTab);
    };

    const submitReceipt = async () => {
        try {
            const values = await form.validateFields();
            if (!selectedKeys.length) {
                messageApi.warning('请至少选择一笔订单');
                return;
            }
            setSubmitting(true);
            const response = await fetch(`${endpoint}/receipts`, {
                method: 'POST',
                headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    customer_id: values.customer_id,
                    receipt_date: values.receipt_date.format('YYYY-MM-DD'),
                    payment_method: values.payment_method,
                    remark: values.remark,
                    items: selectedKeys.map(orderUid => ({ order_uid: orderUid, amount: Number(amounts[orderUid] || 0) })),
                }),
            });
            const result = await response.json();
            if (!response.ok || result.code !== 200) throw new Error(result.msg || '提交失败');
            messageApi.success(`收款单 ${result.data.receipt_no} 已提交审核`);
            await printReceipt(result.data.id, messageApi);
            await fetchOrders(values.customer_id);
            setActiveTab('list');
        } catch (error) {
            if (error?.errorFields) return;
            messageApi.error(error.message || '提交收款单失败');
        } finally {
            setSubmitting(false);
        }
    };

    const copyRejectedReceipt = async (receipt) => {
        form.setFieldsValue({
            customer_id: receipt.customer_id,
            receipt_date: dayjs(),
            payment_method: receipt.payment_method,
            remark: receipt.remark,
        });
        const availableOrders = await fetchOrders(receipt.customer_id);
        const availableMap = Object.fromEntries(availableOrders.map(row => [row.uid, row]));
        const nextKeys = [];
        const nextAmounts = {};
        (receipt.items || []).forEach(item => {
            const available = availableMap[item.order_uid];
            if (!available) return;
            nextKeys.push(item.order_uid);
            nextAmounts[item.order_uid] = Math.min(Number(item.amount || 0), Number(available.available_amount || 0));
        });
        setSelectedKeys(nextKeys);
        setAmounts(prev => ({ ...prev, ...nextAmounts }));
        setActiveTab('entry');
        messageApi.info(nextKeys.length ? '已复制可重新登记的明细' : '原订单当前没有可收余额');
    };

    const orderColumns = [
        { title: '订单号', dataIndex: 'order_id', key: 'order_id', width: 190 },
        { title: '报价人', dataIndex: 'quoter_name', key: 'quoter_name', width: 110 },
        { title: '计费重量(kg)', dataIndex: 'weight_snapshot', key: 'weight_snapshot', width: 130, render: v => Number(v || 0).toFixed(3) },
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
            title: '状态', dataIndex: 'status', key: 'status', width: 100,
            render: value => <Tag color={STATUS_LABELS[value]?.color}>{STATUS_LABELS[value]?.label || value}</Tag>
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
                            if (status === 'completed' && tourUserRoles.includes('admin')) {
                                saveFeatureTourFlow({
                                    userId: tourUserId,
                                    campaignId: COST_QUOTE_RECEIPT_TOUR.id,
                                    stage: 'receipt-audit',
                                });
                                navigate('/finance', {
                                    state: { featureTourCampaign: COST_QUOTE_RECEIPT_TOUR.id },
                                });
                            } else {
                                clearFeatureTourFlow(tourUserId);
                            }
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
                                <Form form={form} layout="vertical">
                                    <Row gutter={16}>
                                        <Col xs={24} md={8}>
                                            <Form.Item name="customer_id" label="客户" rules={[{ required: true, message: '请选择客户' }]}>
                                                <Select
                                                    showSearch
                                                    optionFilterProp="label"
                                                    options={customers.map(item => ({ value: item.id, label: item.name }))}
                                                    onChange={fetchOrders}
                                                />
                                            </Form.Item>
                                        </Col>
                                        <Col xs={24} md={6}>
                                            <Form.Item name="receipt_date" label="收款日期" rules={[{ required: true }]}>
                                                <DatePicker style={{ width: '100%' }} />
                                            </Form.Item>
                                        </Col>
                                        <Col xs={24} md={6}>
                                            <Form.Item name="payment_method" label="付款方式" rules={[{ required: true }]}>
                                                <Select options={PAYMENT_METHODS} />
                                            </Form.Item>
                                        </Col>
                                        <Col xs={24} md={4}>
                                            <Statistic title="本次合计" value={selectedTotal.toFixed(2)} suffix="CNY" />
                                        </Col>
                                    </Row>
                                    <Form.Item name="remark" label="备注"><Input.TextArea rows={2} /></Form.Item>
                                </Form>
                            </Card>
                            <Card data-tour="receipt-orders" size="small" bodyStyle={{ padding: 0 }} title="选择未结清订单">
                                <Table
                                    rowKey="uid"
                                    loading={loadingOrders}
                                    dataSource={orders}
                                    columns={orderColumns}
                                    rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
                                    pagination={{ pageSize: 20 }}
                                    scroll={{ x: 'max-content' }}
                                    size="small"
                                />
                            </Card>
                            <Space data-tour="receipt-submit" style={{ marginTop: 16 }}>
                                <Button type="primary" loading={submitting} disabled={!selectedKeys.length} onClick={submitReceipt}>生成并提交收款单</Button>
                                <Text type="secondary">待审核金额会占用订单可收余额；财务审核通过后计入已收。</Text>
                            </Space>
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
                                pagination={pagination}
                                onChange={next => fetchReceipts(next.current, next.pageSize)}
                                expandable={{
                                    expandedRowRender: record => (
                                        <Table
                                            rowKey="id"
                                            size="small"
                                            pagination={false}
                                            dataSource={record.items || []}
                                            columns={[
                                                { title: '订单号', dataIndex: 'order_id' },
                                                { title: '应收', dataIndex: 'receivable_snapshot', render: v => Number(v || 0).toFixed(2) },
                                                { title: '本次收款', dataIndex: 'amount', render: v => Number(v || 0).toFixed(2) },
                                                { title: '收款后余额', dataIndex: 'remaining_after', render: v => Number(v || 0).toFixed(2) },
                                            ]}
                                        />
                                    )
                                }}
                                scroll={{ x: 'max-content' }}
                            />
                        </Card>
                    )
                }
            ]} />
        </div>
    );
}
