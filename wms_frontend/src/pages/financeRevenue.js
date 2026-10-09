import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Badge, Button, Card, DatePicker, Descriptions, Drawer, Empty, Form, Input, InputNumber, Modal, Pagination, Select, Space, Spin, Table, Typography, message } from 'antd';
import { CheckCircleOutlined, HistoryOutlined, ReloadOutlined, RollbackOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import FinanceHistoryDrawer from '../components/FinanceHistoryDrawer';
import styles from './financeRevenue.module.css';

const { Title, Text } = Typography;
const amount = value => Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const requestKey = () => window.crypto?.randomUUID?.() || `revenue-${Date.now()}-${Math.random().toString(36).slice(2)}`;
async function api(path, options = {}) {
    const response = await fetch(`${endpoint}/finance/v2/revenue${path}`, { ...options, headers: { ...getSafeHeader(), 'Content-Type': 'application/json' } });
    const result = await response.json();
    if (!response.ok || result.code !== 200) throw new Error(result.msg || '收入确认请求失败');
    return result.data;
}

export default function FinanceRevenue() {
    const [messageApi, contextHolder] = message.useMessage();
    const [form] = Form.useForm();
    const [filters, setFilters] = useState({ p: 1, s: 15, open_only: 'true', q: '' });
    const [data, setData] = useState({ items: [], total: 0 });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [refresh, setRefresh] = useState(0);
    const [invoice, setInvoice] = useState(null);
    const [detailId, setDetailId] = useState(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailError, setDetailError] = useState('');
    const [command, setCommand] = useState(null);
    const [busy, setBusy] = useState(false);
    const [historyOpen, setHistoryOpen] = useState(false);
    const reload = useCallback(() => setRefresh(value => value + 1), []);
    useEffect(() => {
        const controller = new AbortController();
        setLoading(true); setError('');
        api(`?${new URLSearchParams(filters)}`, { signal: controller.signal })
            .then(result => { if (!controller.signal.aborted) setData(result); })
            .catch(err => { if (!controller.signal.aborted) { setError(err.message); setData({ items: [], total: 0 }); } })
            .finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => controller.abort();
    }, [filters, refresh]);
    useEffect(() => {
        if (!detailId) return undefined;
        const controller = new AbortController();
        setInvoice(null); setDetailLoading(true); setDetailError('');
        api(`/${detailId}`, { signal: controller.signal })
            .then(result => { if (!controller.signal.aborted) setInvoice(result); })
            .catch(err => { if (!controller.signal.aborted) setDetailError(err.message); })
            .finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
        return () => controller.abort();
    }, [detailId, refresh]);
    const openCommand = (kind, row) => {
        setCommand({ kind, row, key: requestKey() });
        form.resetFields();
        form.setFieldsValue({ amount: kind === 'recognize' ? row.deferred_amount : undefined, date: dayjs() });
    };
    const save = async values => {
        if (busy || !command) return;
        setBusy(true);
        try {
            const recognizing = command.kind === 'recognize';
            const result = await api(recognizing ? `/${command.row.id}/recognize` : `/entries/${command.row.id}/reverse`, {
                method: 'POST', body: JSON.stringify({ version: command.row.version,
                    idempotency_key: command.key, amount: values.amount,
                    [recognizing ? 'recognition_date' : 'reversal_date']: values.date.format('YYYY-MM-DD'), reason: values.reason }),
            });
            messageApi.success(recognizing ? '履约收入已确认，凭证和历史已同步保存' : '收入确认已撤销，原始凭证保留');
            setCommand(null); setInvoice(result.invoice); reload();
        } catch (err) { messageApi.error(err.message); } finally { setBusy(false); }
    };
    return <div className={styles.page}>
        {contextHolder}
        <div className={styles.header}><Space direction="vertical" size={4}><Title level={4} style={{ margin: 0 }}>履约收入确认</Title><Text type="secondary">按已完成服务确认收入，并关联账单、履约依据和会计凭证。</Text></Space><Button icon={<ReloadOutlined />} onClick={reload}>刷新</Button></div>
        {data.revenue_policy === 'invoice' ? <Alert showIcon type="info" className={styles.notice} message="当前账簿按账单确认收入" description="客户账单生效时已确认收入，此处无需再次确认。" /> : <Alert showIcon type="info" className={styles.notice} message="按履约事实确认未税收入" description="可分次确认。客户收款、账单核销与收入确认分别记录；贷项会先冲减待履约金额，再冲减已确认收入。" />}
        <Card size="small">
            <Space wrap className={styles.filters}><Input.Search aria-label="搜索待履约账单" placeholder="账单号或客户" allowClear onSearch={q => setFilters(prev => ({ ...prev, p: 1, q }))} style={{ width: 280, maxWidth: '100%' }} /><Select aria-label="履约筛选" value={filters.open_only} onChange={value => setFilters(prev => ({ ...prev, p: 1, open_only: value }))} options={[{ value: 'true', label: '待履约账单' }, { value: 'false', label: '全部客户账单' }]} /><Text type="secondary">共 {data.total} 张 · 人民币</Text></Space>
            {error && <Alert showIcon type="error" message={error} action={<Button onClick={reload}>重试</Button>} />}
            <Table rowKey="id" dataSource={data.items || []} loading={loading} pagination={false} scroll={{ x: 830 }} locale={{ emptyText: <Empty description="当前筛选下没有待处理账单" /> }} columns={[
                { title: '账单 / 客户', key: 'invoice', width: 250, render: (_, row) => <div><Button type="link" className={styles.link} onClick={() => setDetailId(row.id)}>{row.number}</Button><div><Text type="secondary">{row.partner_name}</Text></div></div> },
                { title: '账单日期', dataIndex: 'document_date', width: 120 },
                { title: '原单未税金额', dataIndex: 'subtotal', align: 'right', render: amount },
                { title: '已确认收入', dataIndex: 'recognized_amount', align: 'right', render: value => <Text>{amount(value)}</Text> },
                { title: '待履约金额', dataIndex: 'deferred_amount', align: 'right', render: value => <Text strong>{amount(value)}</Text> },
                { title: '操作', key: 'actions', width: 190, render: (_, row) => <Space><Button type="primary" size="small" disabled={Number(row.deferred_amount) <= 0 || data.revenue_policy !== 'deferred'} onClick={() => openCommand('recognize', row)}>确认收入</Button><Button size="small" onClick={() => setDetailId(row.id)}>记录</Button></Space> },
            ]} />
            <Pagination className={styles.pagination} current={filters.p} pageSize={filters.s} total={data.total} showSizeChanger={false} onChange={p => setFilters(prev => ({ ...prev, p }))} />
        </Card>
        <Drawer title="账单履约与收入记录" open={!!detailId} onClose={() => { setDetailId(null); setHistoryOpen(false); }} width="min(820px, 100vw)">
            <Spin spinning={detailLoading}>{detailError && <Alert type="error" showIcon message={detailError} action={<Button onClick={reload}>重试</Button>} />}{invoice && <>
                <Title level={4}>{invoice.number}</Title><Text type="secondary">{invoice.partner_name}</Text>
                <Descriptions bordered size="small" column={2} className={styles.summary}><Descriptions.Item label="原单未税金额">¥ {amount(invoice.subtotal)}</Descriptions.Item><Descriptions.Item label="账单日期">{invoice.document_date}</Descriptions.Item><Descriptions.Item label="已确认收入">¥ {amount(invoice.recognized_amount)}</Descriptions.Item><Descriptions.Item label="待履约金额">¥ {amount(invoice.deferred_amount)}</Descriptions.Item></Descriptions>
                <Space className={styles.detailActions}><Button type="primary" icon={<CheckCircleOutlined />} disabled={Number(invoice.deferred_amount) <= 0} onClick={() => openCommand('recognize', invoice)}>确认履约收入</Button><Button icon={<HistoryOutlined />} onClick={() => setHistoryOpen(true)}>完整变更历史</Button></Space>
                <Table size="small" rowKey="id" dataSource={invoice.entries || []} pagination={false} scroll={{ x: 660 }} locale={{ emptyText: '暂无履约确认记录' }} columns={[
                    { title: '确认日期', dataIndex: 'entry_date', width: 110 }, { title: '凭证 / 依据', dataIndex: 'description' },
                    { title: '确认金额', dataIndex: 'recognized_amount', align: 'right', render: amount, width: 110 },
                    { title: '状态', dataIndex: 'status', width: 95, render: status => <Badge status={status === 'posted' ? 'success' : 'default'} text={status === 'posted' ? '已确认' : '已撤销'} /> },
                    { title: '操作', key: 'action', width: 80, render: (_, row) => row.status === 'posted' && <Button size="small" icon={<RollbackOutlined />} onClick={() => openCommand('reverse', row)}>撤销</Button> },
                ]} />
            </>}</Spin>
        </Drawer>
        <Modal title={command?.kind === 'recognize' ? '确认履约收入' : '撤销收入确认'} open={!!command} onCancel={() => !busy && setCommand(null)} onOk={() => form.submit()} confirmLoading={busy} okText={command?.kind === 'recognize' ? '确认并生成凭证' : '撤销并生成冲销凭证'} destroyOnClose>
            <Alert type={command?.kind === 'recognize' ? 'info' : 'warning'} showIcon className={styles.notice} message={command?.kind === 'recognize' ? `${command?.row.number} · 待履约 ¥ ${amount(command?.row.deferred_amount)}` : `撤销确认 ¥ ${amount(command?.row.recognized_amount)}`} description={command?.kind === 'recognize' ? '仅确认已完成服务对应的未税金额，请填写可以核验的履约依据。' : '原记录保留。存在后续贷项时，系统会检查撤销是否导致负收入。'} />
            <Form form={form} layout="vertical" onFinish={save} preserve={false}>
                {command?.kind === 'recognize' && <Form.Item name="amount" label="本次确认金额（CNY，未税）" rules={[{ required: true, message: '请输入确认金额' }]}><InputNumber stringMode precision={2} min="0.01" max={command?.row.deferred_amount} style={{ width: '100%' }} /></Form.Item>}
                <Form.Item name="date" label={command?.kind === 'recognize' ? '履约日期' : '撤销日期'} rules={[{ required: true, message: '请选择日期' }]}><DatePicker style={{ width: '100%' }} /></Form.Item>
                <Form.Item name="reason" label={command?.kind === 'recognize' ? '履约依据' : '撤销原因'} rules={[{ required: true, whitespace: true, message: '请填写依据或原因' }]}><Input.TextArea rows={3} maxLength={2000} placeholder="例如：客户已确认签收，回执编号……" /></Form.Item>
            </Form>
        </Modal>
        <FinanceHistoryDrawer open={historyOpen} onClose={() => setHistoryOpen(false)} historyUrl={invoice ? `/finance/v2/documents/${invoice.id}/history` : null} title={`${invoice?.number || ''} 变更历史`} />
    </div>;
}
