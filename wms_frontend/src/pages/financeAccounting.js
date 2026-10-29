import React, { useCallback, useContext, useEffect, useRef, useState } from 'react';
import useUrlState from '../common/useUrlState';
import { UNSAFE_LocationContext } from 'react-router-dom';
import { Alert, Button, Checkbox, DatePicker, Descriptions, Drawer, Form, Input, InputNumber, Modal, Select, Space, Spin, Table, Tabs, Typography, Upload, message } from 'antd';
import { DownloadOutlined, HistoryOutlined, PlusOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import * as XLSX from 'xlsx';
import { financeRequest, money, mutationKey, queryString } from '../common/financeApi';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import { getCurrentTourUser } from '../common/featureTourState';
import FinanceHistoryDrawer from '../components/FinanceHistoryDrawer';
import FinanceRevenue from './financeRevenue';
import FinanceLegacyMigration from './financeLegacyMigration';
import styles from './financeAccounting.module.css';

const dateRangeUrl = {
    encode: value => JSON.stringify(value?.map(date => date.format('YYYY-MM-DD')) ?? null),
    decode: raw => {
        const values = JSON.parse(raw);
        if (values === null) return null;
        if (!Array.isArray(values) || values.length !== 2 || values.some(value => typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || !dayjs(value).isValid() || dayjs(value).format('YYYY-MM-DD') !== value)) throw new Error('Invalid date range');
        return values.map(value => dayjs(value));
    },
};

const { Text, Title } = Typography;
const api = (path, options) => financeRequest(`/accounting${path}`, options);
const today = () => dayjs().format('YYYY-MM-DD');
const TYPES = { asset: '资产', liability: '负债', equity: '权益', revenue: '收入', expense: '费用' };
const STATUS = { draft: '草稿', posted: '已过账', cancelled: '已作废', reversed: '已冲销' };
const ACTIONS = { operating: '经营活动', investing: '投资活动', financing: '筹资活动', transfer: '内部调拨' };

function useData(path, params = {}, revision = 0, enabled = true) {
    const key = JSON.stringify(params);
    const identity = `${path}?${key}`;
    const [state, setState] = useState({ loading: true, data: null, error: '', identity });
    const [attempt, setAttempt] = useState(0);
    useEffect(() => {
        if (!enabled) return undefined;
        const controller = new AbortController();
        setState(previous => ({ ...previous, identity, data: previous.identity === identity ? previous.data : null, loading: true, error: '' }));
        api(path, { params: JSON.parse(key), signal: controller.signal }).then(data => {
            if (!controller.signal.aborted) setState({ loading: false, data, error: '', identity });
        }).catch(error => {
            if (!controller.signal.aborted) setState({ loading: false, data: null, error: error.message, identity });
        });
        return () => controller.abort();
    }, [path, key, identity, revision, attempt, enabled]);
    return { ...(state.identity === identity ? state : { loading: enabled, data: null, error: '' }), reload: () => setAttempt(value => value + 1) };
}
function Failure({ result }) {
    return result.error ? <Alert className={styles.error} type="error" showIcon message={result.error} action={<Button onClick={result.reload}>重试</Button>} /> : null;
}
function Panel({ title, extra, children }) {
    return <section className={styles.panel}><div className={styles.panelHead}><Title level={5} className={styles.panelTitle}>{title}</Title>{extra}</div><div className={styles.panelBody}>{children}</div></section>;
}
function Amount({ value }) { return <span className={styles.amount}>{money(value)}</span>; }
function useAction(onSuccess) {
    const [pending, setPending] = useState(false);
    const pendingRef = useRef(false);
    const [messageApi, contextHolder] = message.useMessage();
    const run = async operation => {
        if (pendingRef.current) return;
        pendingRef.current = true; setPending(true);
        try { const result = await operation(); onSuccess?.(result); return result; }
        catch (error) { if (!error.errorFields) messageApi.error(error.message || '操作失败'); return undefined; }
        finally { pendingRef.current = false; setPending(false); }
    };
    return { pending, run, contextHolder };
}

export function AccountingSetup({ settings, onSaved }) {
    const [form] = Form.useForm();
    const action = useAction(onSaved);
    useEffect(() => { form.setFieldsValue({ company_name: settings?.company_name || '', opening_date: settings?.opening_date || today(), revenue_policy: settings?.revenue_policy || 'deferred' }); }, [settings, form]);
    return <Panel title={settings?.configured ? '账簿设置' : '开始建账'} extra={<Text type="secondary">人民币 · CNY</Text>}>
        {action.contextHolder}
        <Typography.Paragraph type="secondary" className={styles.subtitle}>设置账簿主体、建账日期和收入确认方式，再开放会计期间。</Typography.Paragraph>
        <Form form={form} layout="vertical" className={styles.setupForm} onFinish={values => action.run(() => api('/settings', { method: 'PUT', body: { ...values, version: settings?.version } }))}>
            <div className={styles.formGrid}><Form.Item name="company_name" label="账簿主体" rules={[{ required: true, message: '请输入公司名称' }]}><Input placeholder="公司名称" maxLength={200} /></Form.Item>
                <Form.Item name="opening_date" label="建账日期" rules={[{ required: true }]}><Input type="date" /></Form.Item></div>
            <Form.Item name="revenue_policy" label="收入确认方式" extra="请按实际合同和财务政策选择；有生效凭证后不可直接切换。">
                    <Select options={[{ value: 'deferred', label: '先记待履约收入，完成服务后分次确认收入' }, { value: 'invoice', label: '确认服务账单时确认收入' }]} />
            </Form.Item><Button type="primary" htmlType="submit" loading={action.pending}>{settings?.configured ? '保存账簿设置' : '建立账簿与初始科目'}</Button>
        </Form>
    </Panel>;
}

export function OpeningConfirmation({ settings, onChanged }) {
    const [open, setOpen] = useState(false);
    const [reason, setReason] = useState('');
    const [checked, setChecked] = useState(false);
    const action = useAction(() => { setOpen(false); onChanged(); });
    return <>{action.contextHolder}<div className={styles.openingNotice}><Space wrap>
        <Text type={settings.opening_confirmed ? 'secondary' : 'warning'}>{settings.opening_confirmed ? '期初余额已确认' : '期初尚未核对，报表为待核对口径'}</Text>
        {!settings.opening_confirmed && <Button size="small" type="link" onClick={() => { setChecked(false); setReason(''); setOpen(true); }}>核对期初</Button>}
    </Space></div>
        <Modal cancelText="取消" open={open} title="确认期初余额" closable={!action.pending} maskClosable={!action.pending} keyboard={!action.pending} cancelButtonProps={{ disabled: action.pending }} onCancel={() => { if (!action.pending) setOpen(false); }} okText="确认核对完成" confirmLoading={action.pending} okButtonProps={{ disabled: !checked || !reason.trim() }} onOk={() => checked && reason.trim() && action.run(() => api('/opening-confirmation', { method: 'POST', body: { version: settings.version, reason } }))}>
            <p>此操作确认账簿期初资料完整。请先完成期初凭证和往来余额的核对。</p>
            <Input.TextArea disabled={action.pending} aria-label="期初核对依据" placeholder="核对依据、账册来源和差异处理结果" value={reason} onChange={event => setReason(event.target.value)} rows={3} />
            <Checkbox disabled={action.pending} style={{ marginTop: 16 }} checked={checked} onChange={event => setChecked(event.target.checked)}>已核对全部期初余额（零余额也已确认）</Checkbox>
        </Modal></>;
}

export function AccountingPeriods({ revision, onChanged }) {
    const [historyPeriod, setHistoryPeriod] = useState(null);
    const canReopen = getCurrentTourUser().roles.includes('admin');
    const result = useData('/periods', {}, revision);
    const [creating, setCreating] = useState(false);
    const [selected, setSelected] = useState(null);
    const [reason, setReason] = useState('');
    const [form] = Form.useForm();
    const checks = useData(`/periods/${selected?.id}/checks`, {}, selected?.version || 0, !!selected);
    const action = useAction(() => { setCreating(false); setSelected(null); result.reload(); onChanged(); });
    return <Panel title="会计期间" extra={<Button icon={<PlusOutlined />} onClick={() => { form.setFieldsValue({ name: dayjs().format('YYYY年MM月'), date_from: dayjs().startOf('month').format('YYYY-MM-DD'), date_to: dayjs().endOf('month').format('YYYY-MM-DD') }); setCreating(true); }}>开放期间</Button>}>
        {action.contextHolder}<Failure result={result} />
        <Table rowKey="id" size="small" loading={result.loading} dataSource={result.data || []} pagination={{ pageSize: 12 }} scroll={{ x: 700 }} columns={[
            { title: '期间', dataIndex: 'name' }, { title: '开始', dataIndex: 'date_from' }, { title: '结束', dataIndex: 'date_to' },
            { title: '状态', dataIndex: 'status', render: value => <Text type={value === 'open' ? undefined : 'secondary'}>{value === 'open' ? '开放中' : '已关账'}</Text> },
            { title: '操作', render: (_, row) => <Space wrap>{row.status === 'closed' && !canReopen ? <Text type="secondary">重开需管理员</Text> : <Button type="link" disabled={action.pending} onClick={() => { setSelected(row); setReason(''); }}>{row.status === 'open' ? '检查与关账' : '重开期间'}</Button>}<Button type="link" icon={<HistoryOutlined aria-hidden />} onClick={() => setHistoryPeriod(row)}>历史</Button></Space> },
        ]} />
        <Modal cancelText="取消" okText="开放期间" title="开放会计期间" open={creating} closable={!action.pending} maskClosable={!action.pending} keyboard={!action.pending} cancelButtonProps={{ disabled: action.pending }} onCancel={() => { if (!action.pending) setCreating(false); }} confirmLoading={action.pending} onOk={() => action.run(async () => api('/periods', { method: 'POST', body: await form.validateFields() }))}>
            <Form form={form} layout="vertical" disabled={action.pending}><Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item><div className={styles.formGrid}>
                <Form.Item name="date_from" label="开始日期" rules={[{ required: true }]}><Input type="date" /></Form.Item><Form.Item name="date_to" label="结束日期" rules={[{ required: true }]}><Input type="date" /></Form.Item></div></Form>
        </Modal>
        <Drawer title={`${selected?.name || ''} · 期间检查`} open={!!selected} onClose={() => { if (!action.pending) setSelected(null); }} closable={!action.pending} maskClosable={!action.pending} width="min(540px, 100vw)">
            <Failure result={checks} /><Spin spinning={checks.loading}>
                {checks.data?.checks?.map(item => <Alert key={item.key} style={{ marginBottom: 12 }} showIcon type={item.passed ? 'success' : 'warning'} message={item.label} description={item.passed ? '检查通过' : `待处理 ${item.count} 项`} />)}
            </Spin>
            {selected?.status === 'closed' && <Alert type="warning" message="重开期间仅管理员可执行，需记录更正依据。" showIcon style={{ marginBottom: 16 }} />}
            <Input.TextArea disabled={action.pending} aria-label="期间操作依据" placeholder="填写关账或重开依据" value={reason} onChange={event => setReason(event.target.value)} rows={3} />
            <Button type="primary" danger={selected?.status === 'closed'} loading={action.pending} style={{ marginTop: 16 }} disabled={!reason.trim() || (selected?.status === 'closed' && !canReopen) || checks.loading || !!checks.error || (selected?.status === 'open' && !checks.data?.can_close)}
                onClick={() => action.run(() => api(`/periods/${selected.id}/${selected.status === 'open' ? 'close' : 'reopen'}`, { method: 'POST', body: { version: selected.version, reason } }))}>{selected?.status === 'open' ? '确认关账' : '重开期间'}</Button>
        </Drawer>
        <FinanceHistoryDrawer open={!!historyPeriod} onClose={() => setHistoryPeriod(null)} title={`${historyPeriod?.name || ''} · 期间历史`} historyUrl={historyPeriod ? `/finance/v2/accounting/periods/${historyPeriod.id}/history` : null} />
    </Panel>;
}

async function loadFundAccounts(signal) {
    const items = [];
    let page = 1;
    while (!signal.aborted) {
        const data = await financeRequest('/accounts', { params: { p: page, s: 200 }, signal });
        const batch = data.items || [];
        items.push(...batch);
        if (!batch.length || items.length >= Number(data.total || 0)) break;
        page += 1;
    }
    return items;
}

export function JournalEditor({ open, onClose, onSaved }) {
    const [form] = Form.useForm();
    const chart = useData('/accounts');
    const [funds, setFunds] = useState([]);
    const [fundError, setFundError] = useState('');
    const [fundAttempt, setFundAttempt] = useState(0);
    const [fundLoading, setFundLoading] = useState(true);
    const key = useRef(mutationKey());
    const action = useAction(onSaved);
    const draftLines = Form.useWatch('lines', form) || [];
    const totals = draftLines.reduce((sum, line) => ({ debit: sum.debit + Math.round(Number(line?.debit || 0) * 100), credit: sum.credit + Math.round(Number(line?.credit || 0) * 100) }), { debit: 0, credit: 0 });
    useEffect(() => {
        const controller = new AbortController(); setFundLoading(true); setFundError('');
        loadFundAccounts(controller.signal).then(data => { if (!controller.signal.aborted) setFunds(data); })
            .catch(error => { if (!controller.signal.aborted) setFundError(error.message); })
            .finally(() => { if (!controller.signal.aborted) setFundLoading(false); });
        return () => controller.abort();
    }, [fundAttempt]);
    const save = () => action.run(async () => {
        const values = await form.validateFields();
        const lines = values.lines || [];
        if (lines.length < 2 || lines.some(line => {
            const debit = Number(line.debit || 0), credit = Number(line.credit || 0);
            return !Number.isFinite(debit) || !Number.isFinite(credit) || debit < 0 || credit < 0 || !((debit > 0 && credit === 0) || (credit > 0 && debit === 0));
        })) throw new Error('每条分录必须且只能填写一方正金额，至少保留两条分录');
        const debit = lines.reduce((sum, line) => sum + Math.round(Number(line.debit || 0) * 100), 0);
        const credit = lines.reduce((sum, line) => sum + Math.round(Number(line.credit || 0) * 100), 0);
        if (debit !== credit) throw new Error('借贷金额不平衡，请核对后再保存');
        return api('/entries', { method: 'POST', body: { ...values, idempotency_key: key.current } });
    });
    return <Modal cancelText="取消" open={open} title="录入记账凭证" width="min(950px, 100vw)" onCancel={() => { if (!action.pending) onClose(); }}
        closable={!action.pending} maskClosable={!action.pending} keyboard={!action.pending} cancelButtonProps={{ disabled: action.pending }}
        confirmLoading={action.pending} okButtonProps={{ disabled: chart.loading || !!chart.error || fundLoading || !!fundError }} okText="保存草稿" onOk={save}>
        {action.contextHolder}<Failure result={chart} />{fundError && <Alert type="error" message={fundError} action={<Button onClick={() => setFundAttempt(value => value + 1)}>重试资金账户</Button>} />}
        <Form form={form} layout="vertical" disabled={action.pending} initialValues={{ entry_date: today(), kind: 'manual', cashflow_activity: 'operating', lines: [{ debit: '0', credit: '0' }, { debit: '0', credit: '0' }] }}>
            <div className={styles.formGrid}><Form.Item name="entry_date" label="记账日期" rules={[{ required: true }]}><Input type="date" /></Form.Item><Form.Item name="kind" label="凭证类型"><Select options={[{ value: 'manual', label: '普通凭证' }, { value: 'opening', label: '期初凭证（仅建账日）' }]} /></Form.Item></div>
            <Form.Item name="description" label="摘要" rules={[{ required: true, whitespace: true }]}><Input placeholder="业务事项、依据或凭证编号" /></Form.Item>
            <Form.Item name="cashflow_activity" label="资金流类别"><Select options={Object.entries(ACTIONS).map(([value, label]) => ({ value, label }))} /></Form.Item>
            <Alert style={{ marginBottom: 16 }} type="info" showIcon message="应收应付由账单和收付款生成；现金、银行分录须关联资金账户。" />
            <Form.List name="lines">{(fields, { add, remove }) => <>{fields.map(field => <div className={styles.lineForm} key={field.key}><div className={styles.formGrid}>
                <Form.Item name={[field.name, 'account_code']} label={`第 ${field.name + 1} 行科目`} rules={[{ required: true }]}><Select showSearch optionFilterProp="label" onChange={() => form.setFieldValue(['lines', field.name, 'fund_account_id'], undefined)} options={(chart.data || []).filter(row => !['1122', '2202', '2203'].includes(row.code)).map(row => ({ value: row.code, label: `${row.code} ${row.name}` }))} /></Form.Item>
                <Form.Item noStyle shouldUpdate={(before, after) => before.lines?.[field.name]?.account_code !== after.lines?.[field.name]?.account_code}>{() => {
                    const code = form.getFieldValue(['lines', field.name, 'account_code']);
                    const needsFund = ['1001', '1002'].includes(code);
                    return <Form.Item name={[field.name, 'fund_account_id']} label={`第 ${field.name + 1} 行资金账户`} rules={needsFund ? [{ required: true, message: '现金或银行分录必须选择相应的资金账户' }] : []}>
                        <Select allowClear disabled={!needsFund || action.pending} showSearch optionFilterProp="label" placeholder={needsFund ? '选择对应资金账户' : '该科目不使用资金账户'} options={funds.filter(row => row.active && (code === '1001' ? row.account_type === 'cash' : row.account_type !== 'cash')).map(row => ({ value: row.id, label: row.name }))} />
                    </Form.Item>;
                }}</Form.Item>
                <Form.Item name={[field.name, 'debit']} label="借方"><InputNumber aria-label={`第 ${field.name + 1} 行借方`} min={0} precision={2} stringMode /></Form.Item><Form.Item name={[field.name, 'credit']} label="贷方"><InputNumber aria-label={`第 ${field.name + 1} 行贷方`} min={0} precision={2} stringMode /></Form.Item>
            </div><Button size="small" danger disabled={fields.length < 3 || action.pending} onClick={() => remove(field.name)}>删除分录</Button></div>)}<Button disabled={action.pending || fields.length >= 200} onClick={() => add({ debit: '0', credit: '0' })} icon={<PlusOutlined />}>增加分录</Button></>}</Form.List>
            <div className={styles.formSummary}><span>借方 {money(totals.debit / 100)}</span><span>贷方 {money(totals.credit / 100)}</span><Text type={totals.debit === totals.credit ? 'success' : 'danger'}>{totals.debit === totals.credit ? '借贷平衡' : `差额 ${money((totals.debit - totals.credit) / 100)}`}</Text></div>
        </Form>
    </Modal>;
}

export function AccountingJournals({ revision, onChanged }) {
    const [page, setPage] = useUrlState('journalPage', 1, { validate: value => Number.isSafeInteger(value) && value > 0 });
    const [query, setQuery] = useUrlState('journalSearch', '');
    const [status, setStatus] = useUrlState('journalStatus', '');
    const [selected, setSelected] = useState(null);
    const [creating, setCreating] = useState(false);
    const [history, setHistory] = useState(false);
    const [reason, setReason] = useState('');
    const [reversalDate, setReversalDate] = useState(today());
    const result = useData('/entries', { p: page, s: 20, q: query, status }, revision);
    const action = useAction(() => { setSelected(null); result.reload(); onChanged(); });
    const columns = [
        { title: '凭证号', dataIndex: 'number', render: (value, row) => <Button type="link" onClick={() => { setSelected(row); setReason(''); setReversalDate(today()); setHistory(false); }}>{value}</Button> },
        { title: '记账日期', dataIndex: 'entry_date', width: 115 }, { title: '摘要', dataIndex: 'description' },
        { title: '借方 / CNY', dataIndex: 'total_debit', align: 'right', render: value => <Amount value={value} /> },
        { title: '贷方 / CNY', dataIndex: 'total_credit', align: 'right', render: value => <Amount value={value} /> },
        { title: '状态', dataIndex: 'status', width: 90, render: value => <Text type={value === 'cancelled' || value === 'reversed' ? 'secondary' : undefined}>{STATUS[value] || value}</Text> },
    ];
    return <Panel title="记账凭证" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>录入凭证</Button>}>
        {action.contextHolder}<Space wrap style={{ marginBottom: 16 }}><Input.Search value={query} onChange={event => { setQuery(event.target.value); setPage(1); }} placeholder="凭证号 / 摘要" allowClear onSearch={value => { setQuery(value); setPage(1); }} />
            <Select aria-label="凭证状态" value={status} onChange={value => { setStatus(value); setPage(1); }} style={{ width: 140 }} options={[{ value: '', label: '全部状态' }, ...Object.entries(STATUS).map(([value, label]) => ({ value, label }))]} /></Space>
        <Failure result={result} /><Table rowKey="id" loading={result.loading} columns={columns} dataSource={result.data?.items || []} scroll={{ x: 900 }} pagination={{ current: page, pageSize: 20, total: result.data?.total || 0, onChange: setPage, showSizeChanger: false }} />
        {creating && <JournalEditor open onClose={() => setCreating(false)} onSaved={() => { setCreating(false); result.reload(); onChanged(); }} />}
        <Drawer title={selected?.number} open={!!selected} onClose={() => { if (!action.pending) { setSelected(null); setHistory(false); } }} closable={!action.pending} maskClosable={!action.pending} width="min(960px, 100vw)">
            {selected && <><Descriptions column={2} items={[{ key: 'date', label: '记账日期', children: selected.entry_date }, { key: 'status', label: '状态', children: STATUS[selected.status] }, { key: 'desc', label: '摘要', span: 2, children: selected.description }]} />
                <Table rowKey="id" size="small" pagination={false} dataSource={selected.lines} scroll={{ x: 550 }} columns={[
                    { title: '科目', render: (_, row) => `${row.account_code} ${row.account_name}` }, { title: '往来', dataIndex: 'partner_name' },
                    { title: '借方', dataIndex: 'debit', align: 'right', render: value => <Amount value={value} /> }, { title: '贷方', dataIndex: 'credit', align: 'right', render: value => <Amount value={value} /> },
                ]} />
                <Space wrap style={{ marginTop: 20 }}><Button icon={<HistoryOutlined />} onClick={() => setHistory(true)}>修改历史</Button>
                    {selected.status === 'draft' && !selected.source_type && <Button type="primary" loading={action.pending} onClick={() => action.run(() => api(`/entries/${selected.id}/post`, { method: 'POST', body: { version: selected.version } }))}>确认过账</Button>}</Space>
                {selected.source_type && <Alert style={{ marginTop: 16 }} type="info" showIcon message="该凭证由业务单据生成，更正请回到来源账单或收付款。" />}
                {!selected.source_type && ['draft', 'posted'].includes(selected.status) && <div style={{ marginTop: 22 }}>
                    <Input.TextArea disabled={action.pending} aria-label="凭证更正原因" value={reason} onChange={event => setReason(event.target.value)} placeholder="填写作废或冲销原因" rows={3} />
                    {selected.status === 'posted' && <Input disabled={action.pending} aria-label="冲销记账日期" type="date" value={reversalDate} onChange={event => setReversalDate(event.target.value)} style={{ width: 180, margin: '12px 8px 12px 0' }} />}
                    <Button danger disabled={!reason.trim() || (selected.status === 'posted' && !reversalDate)} loading={action.pending} onClick={() => action.run(() => api(`/entries/${selected.id}/${selected.status === 'draft' ? 'cancel' : 'reverse'}`, { method: 'POST', body: { version: selected.version, reason, entry_date: reversalDate } }))}>{selected.status === 'draft' ? '作废草稿' : '生成冲销凭证'}</Button>
                </div>}
                <FinanceHistoryDrawer open={history} onClose={() => setHistory(false)} title={`${selected.number} · 历史`} historyUrl={`/finance/v2/accounting/entries/${selected.id}/history`} />
            </>}
        </Drawer>
    </Panel>;
}

const REPORT_VIEWS = [
    { value: 'trial', label: '试算平衡表' },
    { value: 'profit', label: '利润表' },
    { value: 'balance', label: '资产负债表' },
    { value: 'cash', label: '资金流' },
    { value: 'ledger', label: '科目明细' },
];

export function AccountingReports({ revision }) {
    const [range, setRange] = useUrlState('reportDates', () => [dayjs().startOf('month'), dayjs()], { ...dateRangeUrl, validate: value => Array.isArray(value) && value.length === 2 });
    const [ledgerPage, setLedgerPage] = useUrlState('reportLedgerPage', 1, { validate: value => Number.isSafeInteger(value) && value > 0 });
    const [account, setAccount] = useUrlState('reportAccount', undefined, { decode: raw => raw });
    const [reportTab, setReportTab] = useUrlState('reportView', 'trial', { validate: value => REPORT_VIEWS.some(view => view.value === value) });
    const params = { date_from: range[0].format('YYYY-MM-DD'), date_to: range[1].format('YYYY-MM-DD'), account_code: account };
    const result = useData('/reports', params, revision);
    const action = useAction();
    const report = result.data;
    const download = () => !result.loading && report && action.run(async () => {
        const response = await fetch(`${endpoint}/finance/v2/accounting/reports/export?${queryString(params)}`, { headers: getSafeHeader() });
        if (!response.ok) throw new Error('报表导出失败');
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement('a'); link.href = url; link.download = '试算平衡表.csv'; link.click();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    const baseColumns = [{ title: '科目代码', dataIndex: 'code', width: 130 }, { title: '科目名称', dataIndex: 'name' }];
    const amountColumn = (title, dataIndex) => ({ title, dataIndex, align: 'right', width: 150, render: value => <Amount value={value} /> });
    const summary = (rows, columns) => <Table.Summary>{rows.map(([label, value]) => <Table.Summary.Row key={label}>
        <Table.Summary.Cell index={0} colSpan={columns - 1}><Text strong>{label}</Text></Table.Summary.Cell>
        <Table.Summary.Cell index={columns - 1} align="right"><Text strong>{money(value)}</Text></Table.Summary.Cell>
    </Table.Summary.Row>)}</Table.Summary>;
    return <section className={styles.panel}>
        {action.contextHolder}
        <div className={styles.toolbar}>
            <Space wrap>
                <Select aria-label="报表类型" value={reportTab} onChange={value => { setReportTab(value); setLedgerPage(1); }} options={REPORT_VIEWS} style={{ width: 160 }} />
                <DatePicker.RangePicker aria-label="报表期间" value={range} allowClear={false} onChange={value => { setRange(value); setLedgerPage(1); }} />
                {reportTab === 'ledger' && <Select aria-label="报表科目筛选" allowClear showSearch optionFilterProp="label" style={{ width: 240, maxWidth: '100%' }} placeholder="全部科目" value={account} onChange={value => { setAccount(value); setLedgerPage(1); }} options={(report?.trial_balance || []).map(row => ({ value: row.code, label: `${row.code} ${row.name}` }))} />}
            </Space>
            <Button icon={<DownloadOutlined />} disabled={!report || result.loading || !!result.error} loading={action.pending} onClick={download}>导出试算表</Button>
        </div>
        <Failure result={result} />
        <Spin spinning={result.loading}>{report && <>
            <div className={styles.reportHeading}>
                <div><Title level={4} className={styles.panelTitle}>{REPORT_VIEWS.find(item => item.value === reportTab)?.label}</Title><Text type="secondary">{report.date_from || params.date_from} 至 {report.date_to || params.date_to} · 人民币元</Text></div>
                <Text type={report.opening_confirmed ? 'secondary' : 'warning'}>{report.opening_confirmed ? '已过账账簿' : '期初待核对'}</Text>
            </div>
            {report.notice && <Typography.Paragraph type="secondary" className={styles.footnote}>{report.notice}</Typography.Paragraph>}
            {reportTab === 'trial' && <>
                <Table rowKey="code" size="small" dataSource={report.trial_balance} scroll={{ x: 850 }} columns={[...baseColumns, amountColumn('期初余额', 'opening'), amountColumn('本期借方', 'debit'), amountColumn('本期贷方', 'credit'), amountColumn('期末余额', 'closing')]} pagination={false}
                    summary={() => <Table.Summary.Row><Table.Summary.Cell index={0} colSpan={3}><Text strong>本期借贷合计</Text></Table.Summary.Cell><Table.Summary.Cell index={3} align="right"><Text strong>{money(report.total_debit)}</Text></Table.Summary.Cell><Table.Summary.Cell index={4} align="right"><Text strong>{money(report.total_credit)}</Text></Table.Summary.Cell><Table.Summary.Cell index={5} /></Table.Summary.Row>} />
                <Typography.Paragraph type="secondary" className={styles.footnote}>借方余额为正，贷方余额为负。</Typography.Paragraph>
            </>}
            {reportTab === 'profit' && <Table rowKey="code" size="small" scroll={{ x: 580 }} dataSource={report.profit_loss.items} columns={[...baseColumns, { title: '类别', dataIndex: 'account_type', render: value => TYPES[value] }, amountColumn('本期金额', 'amount')]} pagination={false}
                summary={() => summary([['收入合计', report.profit_loss.revenue], ['费用合计', report.profit_loss.expense], ['本期利润', report.profit_loss.profit]], 4)} />}
            {reportTab === 'balance' && <Table rowKey="code" scroll={{ x: 620 }} size="small" pagination={false} dataSource={report.balance_sheet.items.filter(row => ['asset', 'liability', 'equity'].includes(row.account_type))} columns={[...baseColumns, { title: '类别', dataIndex: 'account_type', render: value => TYPES[value] }, amountColumn('期末余额（借正贷负）', 'closing')]}
                summary={() => summary([['资产合计', report.balance_sheet.assets], ['负债合计', report.balance_sheet.liabilities], ['权益账面余额', report.balance_sheet.equity], ['尚未结转损益', report.balance_sheet.unclosed_profit], ['资产负债校验差', report.balance_sheet.difference]], 4)} />}
            {reportTab === 'cash' && <><Table rowKey="activity" size="small" pagination={false} dataSource={Object.entries(report.cashflow).map(([activity, amount]) => ({ activity, amount }))} columns={[{ title: '类别', dataIndex: 'activity', render: value => ({ ...ACTIONS, opening: '期初余额录入' })[value] || value }, amountColumn('净流入 / CNY', 'amount')]} />
                <Typography.Paragraph type="secondary" className={styles.footnote}>按凭证资金流类别归集；期初和内部调拨单列。</Typography.Paragraph></>}
            {reportTab === 'ledger' && <Table rowKey="line_id" dataSource={report.ledger} size="small" scroll={{ x: 900 }} columns={[{ title: '日期', dataIndex: 'entry_date', width: 110 }, { title: '凭证号', dataIndex: 'entry_number', width: 170 }, { title: '科目', dataIndex: 'account_name' }, { title: '摘要', dataIndex: 'description' }, amountColumn('借方', 'debit'), amountColumn('贷方', 'credit')]} pagination={{ current: ledgerPage, pageSize: 20, onChange: setLedgerPage, showSizeChanger: false }} />}
        </>}</Spin>
    </section>;
}

export async function readBankImportFile(file) {
    if (file.size > 5 * 1024 * 1024) throw new Error('文件不能超过 5 MB，请拆分后导入');
    const workbook = XLSX.read(await file.arrayBuffer(), { type: 'array', cellDates: true, sheetRows: 1002 });
    const sheet = workbook.Sheets[workbook.SheetNames[0]];
    if (!sheet) throw new Error('文件没有可读取的工作表');
    const fullRange = sheet['!fullref'] || sheet['!ref'];
    if (fullRange && XLSX.utils.decode_range(fullRange).e.r > 1000) throw new Error('每次最多导入 1000 行，请拆分文件');
    const values = XLSX.utils.sheet_to_json(sheet, { defval: '' });
    if (!values.length || values.length > 1000) throw new Error('请提供 1 至 1000 行银行流水');
    return values.map(row => ({
        transaction_date: (row.transaction_date || row['日期']) instanceof Date ? dayjs(row.transaction_date || row['日期']).format('YYYY-MM-DD') : String(row.transaction_date || row['日期'] || '').trim(),
        amount: String(row.amount ?? row['金额'] ?? ''), reference: String(row.reference || row['流水号'] || ''), description: String(row.description || row['说明'] || ''),
    }));
}

export function BankReconciliation({ revision, onChanged }) {
    const [historyTransaction, setHistoryTransaction] = useState(null);
    const [funds, setFunds] = useState([]);
    const [account, setAccount] = useUrlState('bankAccount', undefined);
    const [page, setPage] = useUrlState('bankPage', 1, { validate: value => Number.isSafeInteger(value) && value > 0 });
    const [preview, setPreview] = useState(null);
    const [selected, setSelected] = useState(null);
    const [paymentId, setPaymentId] = useState(undefined);
    const [payments, setPayments] = useState([]);
    const [paymentQuery, setPaymentQuery] = useState('');
    const [paymentPage, setPaymentPage] = useState(1);
    const [paymentTotal, setPaymentTotal] = useState(0);
    const [paymentsLoading, setPaymentsLoading] = useState(false);
    const [paymentError, setPaymentError] = useState('');
    const [paymentAttempt, setPaymentAttempt] = useState(0);
    const [reason, setReason] = useState('');
    const [loadError, setLoadError] = useState('');
    const [fundAttempt, setFundAttempt] = useState(0);
    const importGeneration = useRef(0);
    const accountRef = useRef(account); accountRef.current = account;
    const result = useData('/bank-transactions', { account_id: account, p: page, s: 20 }, revision);
    const action = useAction(() => { result.reload(); onChanged?.(); });
    const previewAction = useAction();
    useEffect(() => {
        const controller = new AbortController(); setLoadError('');
        loadFundAccounts(controller.signal).then(data => { if (!controller.signal.aborted) setFunds(data); })
            .catch(error => { if (!controller.signal.aborted) setLoadError(error.message); });
        return () => controller.abort();
    }, [revision, fundAttempt]);
    useEffect(() => () => { importGeneration.current += 1; }, []);
    useEffect(() => {
        if (selected?.status !== 'unmatched') return undefined;
        const controller = new AbortController(); setPaymentsLoading(true); setPaymentError('');
        financeRequest('/payments', { params: { q: paymentQuery, status: 'posted', account_id: selected.account_id, direction: Number(selected.amount) > 0 ? 'incoming' : 'outgoing', p: paymentPage, s: 50 }, signal: controller.signal })
            .then(data => {
                if (controller.signal.aborted) return;
                const candidates = (data.items || []).filter(row => !row.is_opening && Number(row.account_id) === Number(selected.account_id) && Math.round(Number(row.amount) * (row.direction === 'incoming' ? 1 : -1) * 100) === Math.round(Number(selected.amount) * 100));
                setPayments(previous => paymentPage === 1 ? candidates : [...previous, ...candidates].filter((row, index, all) => all.findIndex(item => item.id === row.id) === index));
                setPaymentTotal(data.total || 0);
            }).catch(error => { if (!controller.signal.aborted) setPaymentError(error.message); })
            .finally(() => { if (!controller.signal.aborted) setPaymentsLoading(false); });
        return () => controller.abort();
    }, [selected, paymentQuery, paymentPage, paymentAttempt]);
    const openMatch = row => {
        setSelected(row); setPaymentId(undefined); setReason(''); setPayments([]); setPaymentQuery(''); setPaymentPage(1); setPaymentTotal(0); setPaymentError('');
    };
    const changeAccount = value => {
        importGeneration.current += 1; setAccount(value); setPage(1); setPreview(null); setSelected(null); setPaymentId(undefined); setPayments([]);
    };
    const upload = file => {
        const generation = ++importGeneration.current;
        const selectedAccount = account;
        setPreview(null);
        previewAction.run(async () => {
            if (!selectedAccount) throw new Error('请先选择资金账户');
            const rows = await readBankImportFile(file);
            if (generation !== importGeneration.current || selectedAccount !== accountRef.current) return;
            const data = await api('/bank-transactions/preview', { method: 'POST', body: { account_id: selectedAccount, rows } });
            if (generation !== importGeneration.current || selectedAccount !== accountRef.current) return;
            setPreview({ ...data, account_id: selectedAccount, account_name: funds.find(row => row.id === selectedAccount)?.name, rows });
        });
        return false;
    };
    const importPreview = () => action.run(async () => {
        if (!preview?.rows?.length || preview.account_id !== accountRef.current) throw new Error('资金账户已变化，请重新预览文件');
        await api('/bank-transactions/import', { method: 'POST', body: { account_id: preview.account_id, rows: preview.rows } });
        setPreview(null);
    });
    const canImport = account && funds.find(row => row.id === account)?.active;
    const closePreview = () => { if (!action.pending) { importGeneration.current += 1; setPreview(null); } };
    return <Panel title="银行对账" extra={<Space wrap><Select aria-label="银行流水资金账户" showSearch optionFilterProp="label" style={{ width: 200 }} value={account} placeholder="选择资金账户" disabled={action.pending} onChange={changeAccount} options={funds.map(row => ({ value: row.id, label: `${row.name}${row.active ? '' : '（已停用）'}` }))} />
        <Upload accept=".csv,.xlsx,.xls" showUploadList={false} beforeUpload={upload} disabled={!canImport || action.pending || previewAction.pending}><Button icon={<UploadOutlined />} disabled={!canImport || action.pending} loading={previewAction.pending}>导入流水</Button></Upload></Space>}>
        {action.contextHolder}{previewAction.contextHolder}<p className={styles.footnote}>导入首张表，每次最多 5 MB、1000 行；列名：日期、金额、流水号、说明。日期格式 YYYY-MM-DD，收入为正，支出为负。预览校验后才保存。</p>
        {loadError && <Alert type="error" message={loadError} action={<Button onClick={() => setFundAttempt(value => value + 1)}>重试资金账户</Button>} />}<Failure result={result} />
        <Table rowKey="id" size="small" dataSource={result.data?.items || []} loading={result.loading} scroll={{ x: 750 }} columns={[
            { title: '交易日期', dataIndex: 'transaction_date' }, { title: '流水号', dataIndex: 'reference' }, { title: '说明', dataIndex: 'description' },
            { title: '金额 / CNY', dataIndex: 'amount', align: 'right', render: value => <Amount value={value} /> },
            { title: '状态', dataIndex: 'status', render: value => <Text type={value === 'matched' ? 'secondary' : 'warning'}>{value === 'matched' ? '已匹配' : '待核对'}</Text> },
            { title: '操作', render: (_, row) => <Space wrap><Button type="link" disabled={action.pending} onClick={() => openMatch(row)}>{row.status === 'matched' ? '撤销匹配' : '匹配收付款'}</Button><Button type="link" icon={<HistoryOutlined aria-hidden />} onClick={() => setHistoryTransaction(row)}>历史</Button></Space> },
        ]} pagination={{ current: page, pageSize: 20, total: result.data?.total || 0, onChange: setPage, showSizeChanger: false }} />
        <Modal cancelText="取消" title={`导入预览 · ${preview?.account_name || ''}`} open={!!preview} width="min(800px, 100vw)" onCancel={closePreview} confirmLoading={action.pending} okText="确认导入"
            closable={!action.pending} maskClosable={!action.pending} keyboard={!action.pending} cancelButtonProps={{ disabled: action.pending }} onOk={importPreview}>
            <Alert type="info" message={`共 ${preview?.items?.length || 0} 行，其中 ${preview?.duplicates || 0} 行已存在，将跳过。`} />
            <Table rowKey="row" size="small" scroll={{ x: 570 }} dataSource={preview?.items || []} columns={[{ title: '行', dataIndex: 'row' }, { title: '日期', dataIndex: 'transaction_date' }, { title: '流水号', dataIndex: 'reference' }, { title: '金额', dataIndex: 'amount' }, { title: '重复', dataIndex: 'duplicate', render: value => value ? '跳过' : '新增' }]} pagination={{ pageSize: 10 }} />
        </Modal>
        <Modal cancelText="取消" okText={selected?.status === 'matched' ? '确认撤销' : '确认匹配'} title={selected?.status === 'matched' ? '撤销银行匹配' : '匹配已生效收付款'} open={!!selected} onCancel={() => { if (!action.pending) setSelected(null); }}
            closable={!action.pending} maskClosable={!action.pending} keyboard={!action.pending} cancelButtonProps={{ disabled: action.pending }} confirmLoading={action.pending}
            okButtonProps={{ disabled: selected?.status === 'matched' ? !reason.trim() : !paymentId || paymentsLoading || !!paymentError }}
            onOk={() => action.run(async () => {
                if (!selected || (selected.status === 'matched' ? !reason.trim() : !paymentId || paymentsLoading || paymentError)) return;
                await api(`/bank-transactions/${selected.id}/${selected.status === 'matched' ? 'unmatch' : 'match'}`, { method: 'POST', body: { version: selected.version, payment_id: paymentId, reason } }); setSelected(null);
            })}>
            <p>{selected?.reference} · <Amount value={selected?.amount} /> CNY</p>
            {paymentError && <Alert type="error" message={paymentError} action={<Button onClick={() => setPaymentAttempt(value => value + 1)}>重试候选收付款</Button>} />}
            {selected?.status === 'matched' ? <Input.TextArea disabled={action.pending} aria-label="撤销匹配原因" placeholder="填写撤销匹配原因" value={reason} onChange={event => setReason(event.target.value)} /> : <>
                <Select aria-label="匹配收付款候选" disabled={action.pending} loading={paymentsLoading} style={{ width: '100%' }} showSearch filterOption={false}
                    onSearch={value => { setPaymentQuery(value); setPaymentPage(1); setPaymentId(undefined); setPayments([]); }} placeholder="搜索收付款编号 / 往来单位" value={paymentId} onChange={setPaymentId}
                    options={payments.map(row => ({ value: row.id, label: `${row.number} · ${row.partner_name} · ${money(row.amount)}` }))}
                    notFoundContent={paymentsLoading ? <Spin size="small" /> : '没有已加载的同账户、同方向、同金额收付款'} />
                <Space wrap style={{ marginTop: 12 }}><Text type="secondary">已加载 {Math.min(paymentPage * 50, paymentTotal)} / {paymentTotal} 笔资金记录，{payments.length} 笔金额匹配。</Text>
                    {paymentPage * 50 < paymentTotal && <Button size="small" disabled={action.pending || paymentsLoading || !!paymentError} onClick={() => setPaymentPage(value => value + 1)}>加载更多收付款</Button>}</Space>
            </>}
        </Modal>
        <FinanceHistoryDrawer open={!!historyTransaction} onClose={() => setHistoryTransaction(null)} title={`${historyTransaction?.reference || ''} · 银行流水历史`} historyUrl={historyTransaction ? `/finance/v2/accounting/bank-transactions/${historyTransaction.id}/history` : null} />
    </Panel>;
}

function ChartOfAccounts({ revision }) {
    const result = useData('/accounts', {}, revision);
    const [open, setOpen] = useState(false);
    const [form] = Form.useForm();
    const action = useAction(() => { setOpen(false); result.reload(); form.resetFields(); });
    return <Panel title="会计科目" extra={<Button icon={<PlusOutlined />} onClick={() => setOpen(true)}>新增科目</Button>}>
        {action.contextHolder}<Failure result={result} /><Table rowKey="code" size="small" loading={result.loading} dataSource={result.data || []} columns={[{ title: '科目代码', dataIndex: 'code' }, { title: '名称', dataIndex: 'name' }, { title: '类别', dataIndex: 'account_type', render: value => TYPES[value] }, { title: '属性', dataIndex: 'system', render: value => value ? '基础科目' : '自定义科目' }]} pagination={{ pageSize: 15 }} />
        <Modal cancelText="取消" okText="保存" title="新增会计科目" open={open} closable={!action.pending} maskClosable={!action.pending} keyboard={!action.pending} cancelButtonProps={{ disabled: action.pending }} onCancel={() => { if (!action.pending) setOpen(false); }} confirmLoading={action.pending} onOk={() => action.run(async () => api('/accounts', { method: 'POST', body: await form.validateFields() }))}>
            <Form layout="vertical" form={form} disabled={action.pending}><Form.Item name="code" label="科目代码" rules={[{ required: true }, { pattern: /^\d+$/, message: '请输入数字代码' }]}><Input /></Form.Item><Form.Item name="name" label="科目名称" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="account_type" label="科目类别" rules={[{ required: true }]}><Select options={Object.entries(TYPES).map(([value, label]) => ({ value, label }))} /></Form.Item></Form>
        </Modal>
    </Panel>;
}

export default function FinanceAccounting({ onOpenLedger, initialTab = 'periods', sectionToken = 0 }) {
    const [revision, setRevision] = useState(0);
    const [tab, setTab] = useUrlState('accountingTab', 'periods');
    const locationContext = useContext(UNSAFE_LocationContext);
    const hadInitialTab = useRef(new URLSearchParams(locationContext?.location.search).has('accountingTab'));
    useEffect(() => {
        if (sectionToken || (!hadInitialTab.current && initialTab !== 'periods')) setTab(initialTab);
    }, [initialTab, sectionToken, setTab]);
    const settings = useData('/settings', {}, revision);
    const changed = useCallback(() => setRevision(value => value + 1), []);
    if (settings.loading && !settings.data) return <Spin tip="加载账簿设置…"><div style={{ minHeight: 120 }} /></Spin>;
    if (settings.error) return <Failure result={settings} />;
    if (!settings.data?.configured) return <AccountingSetup settings={settings.data} onSaved={changed} />;
    return <div className={styles.accounting}>
        <div className={styles.toolbar}><Space wrap size={16}><Text strong>{settings.data.company_name}</Text><Text type="secondary">建账日 {settings.data.opening_date}</Text><Text type="secondary">CNY</Text></Space><Button icon={<ReloadOutlined />} onClick={changed}>刷新账簿</Button></div>
        <OpeningConfirmation settings={settings.data} onChanged={changed} />
        <Tabs className={styles.sectionNav} size="small" activeKey={tab} onChange={setTab} items={[
            { key: 'periods', label: '期间与关账', children: <AccountingPeriods revision={revision} onChanged={changed} /> },
            { key: 'journals', label: '记账凭证', children: <AccountingJournals revision={revision} onChanged={changed} /> },
            { key: 'revenue', label: '履约与收入', children: <FinanceRevenue /> },
            { key: 'migration', label: '旧订单接入', children: <FinanceLegacyMigration initialTab={sectionToken ? 'links' : 'orders'} sectionToken={sectionToken} settings={settings.data} onChanged={changed} onOpenLedger={onOpenLedger} /> },
            { key: 'bank', label: '银行对账', children: <BankReconciliation revision={revision} onChanged={changed} /> },
            { key: 'reports', label: '账簿与报表', children: <AccountingReports revision={revision} /> },
            { key: 'chart', label: '会计科目', children: <ChartOfAccounts revision={revision} /> },
            { key: 'setup', label: '账簿设置', children: <AccountingSetup settings={settings.data} onSaved={changed} /> },
        ]} />
    </div>;
}
