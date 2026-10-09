import React, { useEffect, useState } from 'react';
import { Alert, Button, Descriptions, Drawer, Input, Select, Space, Spin, Table, Tabs, Typography, message } from 'antd';
import { HistoryOutlined, PrinterOutlined, ReloadOutlined } from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import { PAYMENT_METHODS, printReceipt } from '../common/receiptApi';
import { getSettlementDifferenceDisplay, getSettlementStatus } from '../common/receiptSettlement';
import { money, queryString } from '../common/financeApi';
import { clearFeatureTourFlow, decodeJwtPayload, getCurrentTourUser, readFeatureTourFlow } from '../common/featureTourState';
import FinanceHistoryDrawer from '../components/FinanceHistoryDrawer';
import { getUserRoles } from '../common/roleConfig';
import { COST_QUOTE_RECEIPT_TOUR } from '../common/featureTourConfig';
import { FinancePayments } from './financeWorkspace';
import styles from './receipts.module.css';

const LEGACY_STATUS = { pending: '待审核', approved: '已生效', rejected: '已驳回' };
export function LegacyReceiptHistory() {
    const [messageApi, contextHolder] = message.useMessage();
    const [filters, setFilters] = useState({});
    const [page, setPage] = useState(1);
    const [revision, setRevision] = useState(0);
    const [state, setState] = useState({ items: [], total: 0, loading: true, error: '' });
    const [detailId, setDetailId] = useState(null);
    const [detail, setDetail] = useState({ data: null, loading: false, error: '' });
    const [historyId, setHistoryId] = useState(null);
    const key = queryString({ ...filters, p: page, s: 20 });
    useEffect(() => {
        let active = true;
        const controller = new AbortController();
        setState({ items: [], total: 0, loading: true, error: '' });
        fetch(`${endpoint}/receipts?${key}`, { headers: getSafeHeader(), signal: controller.signal })
            .then(async response => { const result = await response.json(); if (!response.ok || result.code !== 200) throw new Error(result.msg || '读取历史收款失败'); return result; })
            .then(result => { if (active) setState({ items: result.data || [], total: result.total || 0, loading: false, error: '' }); })
            .catch(error => { if (active && error.name !== 'AbortError') setState({ items: [], total: 0, loading: false, error: error.message }); });
        return () => { active = false; controller.abort(); };
    }, [key, revision]);
    useEffect(() => {
        if (!detailId) return undefined;
        let active = true;
        const controller = new AbortController();
        setDetail({ data: null, loading: true, error: '' });
        fetch(`${endpoint}/receipts/${detailId}`, { headers: getSafeHeader(), signal: controller.signal })
            .then(async response => { const result = await response.json(); if (!response.ok || result.code !== 200) throw new Error(result.msg || '读取历史收款明细失败'); return result.data; })
            .then(data => { if (active) setDetail({ data, loading: false, error: '' }); })
            .catch(error => { if (active && error.name !== 'AbortError') setDetail({ data: null, loading: false, error: error.message }); });
        return () => { active = false; controller.abort(); };
    }, [detailId, revision]);
    const change = patch => { setFilters(previous => ({ ...previous, ...patch })); setPage(1); };
    return <>
        {contextHolder}
        <Alert type="info" showIcon message="历史收款仅供查询和打印。原待审核记录由财务在「历史收款清理」处理；新收付款请在收付款记录中登记。" style={{ marginBottom: 16 }} />
        <Space wrap style={{ marginBottom: 16 }}>
            <Input.Search placeholder="历史收款单号 / 客户" allowClear onSearch={q => change({ q })} />
            <Select aria-label="历史收款状态" placeholder="全部状态" allowClear style={{ width: 150 }} onChange={status => change({ status })} options={Object.entries(LEGACY_STATUS).map(([value, label]) => ({ value, label }))} />
            <Button icon={<ReloadOutlined />} onClick={() => setRevision(value => value + 1)}>刷新</Button>
        </Space>
        {state.error && <Alert type="error" message={state.error} action={<Button size="small" onClick={() => setRevision(value => value + 1)}>重试</Button>} style={{ marginBottom: 12 }} />}
        <Table size="small" rowKey="id" loading={state.loading} dataSource={state.items} scroll={{ x: 1000 }} columns={[
            { title: '历史收款单', dataIndex: 'receipt_no', width: 180, render: (value, row) => <Button type="link" style={{ padding: 0 }} onClick={() => setDetailId(row.id)}>{value}</Button> },
            { title: '客户', dataIndex: 'customer_name', width: 160 }, { title: '收款日期', dataIndex: 'receipt_date', width: 120 },
            { title: '金额 / CNY', dataIndex: 'total_amount', align: 'right', width: 130, render: money },
            { title: '状态', dataIndex: 'status', width: 110, render: value => LEGACY_STATUS[value] || value },
            { title: '登记人', dataIndex: 'creator_name', width: 110 }, { title: '审核人', dataIndex: 'reviewer_name', width: 110 },
            { title: '操作', width: 170, fixed: 'right', render: (_, row) => <Space><Button size="small" icon={<PrinterOutlined />} onClick={() => printReceipt(row.id, messageApi)}>打印</Button><Button size="small" icon={<HistoryOutlined />} onClick={() => setHistoryId(row.id)}>历史</Button></Space> },
        ]} pagination={{ current: page, pageSize: 20, total: state.total, showSizeChanger: false, onChange: setPage }} />
        <Drawer title={detail.data?.receipt_no || '历史收款详情'} open={Boolean(detailId)} onClose={() => setDetailId(null)} width="min(800px, 100vw)" destroyOnHidden>
            <Spin spinning={detail.loading}>
                {detail.error && <Alert type="error" message={detail.error} action={<Button onClick={() => setRevision(value => value + 1)}>重试</Button>} />}
                {detail.data && <>
                    <Descriptions column={{ xs: 1, sm: 2 }} items={[
                        { key: 'customer', label: '客户', children: detail.data.customer_name },
                        { key: 'amount', label: '金额', children: `${money(detail.data.total_amount)} CNY` },
                        { key: 'date', label: '收款日期', children: detail.data.receipt_date },
                        { key: 'status', label: '审核状态', children: LEGACY_STATUS[detail.data.status] || detail.data.status },
                        { key: 'method', label: '原收款方式', children: PAYMENT_METHODS.find(item => item.value === detail.data.payment_method)?.label || detail.data.payment_method || '—' },
                        { key: 'settlement', label: '原结清状态', children: getSettlementStatus(detail.data.settlement_status).label },
                        { key: 'creator', label: '登记人 / 时间', children: `${detail.data.creator_name || '—'} / ${detail.data.create_date || '—'}` },
                        { key: 'reviewer', label: '审核人 / 时间', children: `${detail.data.reviewer_name || '—'} / ${detail.data.review_date || '—'}` },
                        { key: 'remark', label: '备注', children: detail.data.remark || '—' },
                        { key: 'review', label: '审核备注', children: detail.data.review_remark || '—' },
                    ]} />
                    <Table rowKey={row => row.id || row.order_uid} size="small" pagination={false} dataSource={detail.data.items || []} scroll={{ x: 780 }} columns={[
                        { title: '原关联订单', dataIndex: 'order_id', render: (value, row) => value || row.order_uid },
                        { title: '原应收', dataIndex: 'receivable_snapshot', align: 'right', render: value => value == null ? '—' : money(value) },
                        { title: '此前已收', dataIndex: 'received_before', align: 'right', render: value => value == null ? '—' : money(value) },
                        { title: '实际收款', dataIndex: 'amount', align: 'right', render: money },
                        { title: '收款后余额', dataIndex: 'remaining_after', align: 'right', render: value => value == null ? '—' : money(value) },
                        { title: '原结清差额', align: 'right', render: (_, row) => { const difference = getSettlementDifferenceDisplay(detail.data, row); return difference.value == null ? '—' : <span title={difference.label}>{money(difference.value)}{detail.data.status === 'pending' ? '（预计）' : ''}</span>; } },
                        { title: '原差价单', dataIndex: 'adjustment_id', render: value => value ? `#${value}` : '—' },
                    ]} />
                </>}
            </Spin>
        </Drawer>
        <FinanceHistoryDrawer open={Boolean(historyId)} onClose={() => setHistoryId(null)} historyUrl={`/receipts/${historyId}/history`} title="历史收款变更记录" />
    </>;
}

export default function Receipts() {
    const location = useLocation();
    const navigate = useNavigate();
    const searchParams = new URLSearchParams(location.search);
    const paymentParam = searchParams.get('payment_id');
    const parsedPaymentId = Number(paymentParam);
    const paymentId = /^\d+$/.test(paymentParam || '') && Number.isSafeInteger(parsedPaymentId) && parsedPaymentId > 0 ? parsedPaymentId : null;
    const hasPaymentLink = searchParams.has('payment_id');
    const { userId } = getCurrentTourUser();
    const roles = getUserRoles(decodeJwtPayload(window.localStorage.getItem('jwt')) || {});
    const [scope, setScope] = useState('mine');
    const [tab, setTab] = useState('entry');
    const canViewAll = roles.some(role => ['admin', 'finance'].includes(role));
    useEffect(() => { if (readFeatureTourFlow(userId)?.campaignId === COST_QUOTE_RECEIPT_TOUR.id) clearFeatureTourFlow(userId); }, [userId]);
    useEffect(() => {
        if (paymentId || (!hasPaymentLink && location.state?.paymentContext)) setTab('entry');
    }, [paymentId, hasPaymentLink, location.key, location.state]);
    const closePaymentLink = () => {
        const params = new URLSearchParams(location.search);
        params.delete('payment_id');
        const search = params.toString();
        navigate({ pathname: location.pathname, search: search ? `?${search}` : '', hash: location.hash }, {
            replace: true, state: location.state,
        });
    };
    return <div className={styles.page}>
        <div className={styles.header}><Typography.Title level={4} className={styles.title}>收付款</Typography.Title></div>
        <Tabs activeKey={tab} onChange={setTab} items={[
            { key: 'entry', label: '收付款记录', children: <>
                <Space wrap style={{ marginBottom: 16 }}><Typography.Text type="secondary">登记客户实际收付款，提交财务确认后独立核销。</Typography.Text>
                    {canViewAll && <Select aria-label="登记人范围" value={scope} onChange={setScope} options={[{ value: 'mine', label: '我登记的收付款' }, { value: 'all', label: '全部收付款' }]} />}
                </Space>
                <FinancePayments business initialFilter={scope === 'mine' && userId ? { created_by_id: userId } : {}} filterRevision={scope === 'mine' ? 1 : 2}
                    initialContext={hasPaymentLink ? undefined : location.state?.paymentContext} navigationToken={location.key}
                    initialPaymentId={paymentId} onDetailClose={closePaymentLink} />
            </> },
            { key: 'list', label: '历史收款（只读）', children: <LegacyReceiptHistory /> },
        ]} />
    </div>;
}
