import React, { useEffect, useState } from 'react';
import { Alert, Badge, Button, Card, Checkbox, Collapse, Descriptions, Drawer, Empty, Form, Input, Modal, Select, Space, Spin, Steps, Table, Tabs, Typography, message } from 'antd';
import { CheckCircleOutlined, HistoryOutlined, ReloadOutlined, SwapOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { financeRequest, money, mutationKey } from '../common/financeApi';
import FinanceHistoryDrawer from '../components/FinanceHistoryDrawer';
import styles from './financeWorkspace.module.css';

const { Text, Title } = Typography;
const KIND = { receivable: '期初应收', advance: '期初预收', settled: '零余额接入' };
const STATUS = { current: ['一致', 'success'], reconciliation_required: ['需要核对差异', 'warning'], source_unavailable: ['旧数据暂不可读取', 'error'] };
function useLegacyData(path, params, enabled = true, revision = 0) {
    const [state, setState] = useState({ loading: false, data: null, error: '' });
    const [attempt, setAttempt] = useState(0);
    const key = JSON.stringify(params || {});
    useEffect(() => {
        if (!enabled) return undefined;
        const controller = new AbortController();
        setState({ loading: true, data: null, error: '' });
        financeRequest(path, { params: JSON.parse(key), signal: controller.signal })
            .then(data => { if (!controller.signal.aborted) setState({ loading: false, data, error: '' }); })
            .catch(err => { if (!controller.signal.aborted) setState({ loading: false, data: null, error: err.message }); });
        return () => controller.abort();
    }, [path, key, enabled, revision, attempt]);
    return { ...state, reload: () => setAttempt(value => value + 1) };
}
function Failure({ result }) {
    return result.error ? <Alert type="error" showIcon message={result.error} className={styles.error} action={<Button onClick={result.reload}>重试</Button>} /> : null;
}
function SourceAmounts({ source }) {
    if (!source) return null;
    return <Descriptions size="small" bordered column={2}>
        <Descriptions.Item label="旧订单应收">¥ {money(source.receivable_amount)}</Descriptions.Item>
        <Descriptions.Item label="已审核收款">¥ {money(source.received_amount)}</Descriptions.Item>
        <Descriptions.Item label="结清减免">¥ {money(source.settlement_difference)}</Descriptions.Item>
        <Descriptions.Item label="旧账净余额"><Text strong>¥ {money(source.signed_balance)}</Text></Descriptions.Item>
    </Descriptions>;
}
function Evidence({ source }) {
    const receipts = source?.receipts || [];
    return <Collapse ghost style={{ marginTop: 12 }} items={[{ key: 'evidence', label: '查看原始收费与收款依据', children: <>
        {source?.quote && <Descriptions size="small" column={2} items={[
            { key: 'quote', label: '报价版本', children: source.quote.version_no ?? source.quote.id ?? '—' },
            { key: 'amount', label: '应收金额', children: `¥ ${money(source.receivable_amount)}` },
        ]} />}
        <Table size="small" rowKey={(row, index) => row.receipt_id || row.id || index} dataSource={receipts} pagination={false} scroll={{ x: 450 }} locale={{ emptyText: '没有旧收款明细' }} columns={[
            { title: '原收款单', key: 'number', render: (_, row) => row.receipt_number || row.receipt_no || row.number || row.receipt_id || row.id },
            { title: '状态', dataIndex: 'status', render: value => ({ approved: '已审核', rejected: '已驳回', pending: '待审核' }[value] || value) },
            { title: '金额', dataIndex: 'amount', align: 'right', render: value => `¥ ${money(value)}` },
        ]} />
    </> }]} />;
}

export default function FinanceLegacyMigration({ settings: providedSettings, onChanged, onOpenLedger, initialTab = 'orders', sectionToken = 0 }) {
    const [messageApi, contextHolder] = message.useMessage();
    const [form] = Form.useForm();
    const [reconcileForm] = Form.useForm();
    const [tab, setTab] = useState(initialTab);
    const [revision, setRevision] = useState(0);
    const [ordersQuery, setOrdersQuery] = useState({ p: 1, s: 10, q: '' });
    const [linksQuery, setLinksQuery] = useState({ p: 1, s: 10, q: '', status: '' });
    const [previewUid, setPreviewUid] = useState(null);
    const [previewRevision, setPreviewRevision] = useState(0);
    const [selectedLinkId, setSelectedLinkId] = useState(null);
    const [historyId, setHistoryId] = useState(null);
    const [busy, setBusy] = useState(false);
    const [importError, setImportError] = useState('');
    const [importKey, setImportKey] = useState('');
    const [accountSearch, setAccountSearch] = useState('');
    const [reconcileOpen, setReconcileOpen] = useState(false);
    const [reconcileKey, setReconcileKey] = useState('');
    const [reconcileError, setReconcileError] = useState('');
    const [documentSearch, setDocumentSearch] = useState('');
    const [paymentSearch, setPaymentSearch] = useState('');
    const [revokeOpen, setRevokeOpen] = useState(false);
    const [revokeReason, setRevokeReason] = useState('');
    const [revokeKey, setRevokeKey] = useState('');
    const [revokeError, setRevokeError] = useState('');
    useEffect(() => {
        if (sectionToken) {
            setTab('links');
            setLinksQuery(previous => ({ ...previous, p: 1, status: 'drift' }));
        } else {
            setTab(initialTab);
        }
    }, [initialTab, sectionToken]);
    const fetchedSettings = useLegacyData('/accounting/settings', {}, !providedSettings, revision);
    const settings = providedSettings || fetchedSettings.data;
    const cutoff = settings?.opening_date || dayjs().format('YYYY-MM-DD');
    const eligibleSetup = !!settings?.configured && !settings?.opening_confirmed && cutoff === dayjs().format('YYYY-MM-DD');
    const orders = useLegacyData('/legacy/orders', ordersQuery, tab === 'orders', revision);
    const links = useLegacyData('/legacy/links', linksQuery, tab === 'links', revision);
    const preview = useLegacyData('/legacy/preview', { order_uid: previewUid, cutoff_date: cutoff }, !!previewUid, previewRevision);
    const selectedLink = useLegacyData(`/legacy/links/${selectedLinkId}`, {}, !!selectedLinkId, revision);
    const reconciliationDocuments = useLegacyData('/documents', { partner_type: 'customer', partner_id: selectedLink.data?.customer_id, status: 'posted', s: 200, q: documentSearch }, reconcileOpen && !!selectedLink.data);
    const reconciliationPayments = useLegacyData('/payments', { partner_type: 'customer', partner_id: selectedLink.data?.customer_id, status: 'posted', s: 200, q: paymentSearch }, reconcileOpen && !!selectedLink.data);
    const accounts = useLegacyData('/accounts', { active: 1, s: 200, q: accountSearch }, preview.data?.import_kind === 'advance');
    const refresh = () => setRevision(value => value + 1);
    const openPreview = uid => { setPreviewUid(uid); setPreviewRevision(value => value + 1); setImportKey(mutationKey()); setImportError(''); form.resetFields(); };
    const refreshPreview = () => { setPreviewRevision(value => value + 1); setImportKey(mutationKey()); setImportError(''); form.resetFields(); };
    const doImport = async values => {
        if (busy || !preview.data?.can_import || !eligibleSetup) return;
        setBusy(true); setImportError('');
        try {
            const result = await financeRequest('/legacy/import', { method: 'POST', body: {
                order_uid: preview.data.order_uid, cutoff_date: preview.data.cutoff_date,
                source_hash: preview.data.source_hash, reason: values.reason,
                confirmed: values.confirmed === true,
                ...(values.due_date ? { due_date: values.due_date } : {}),
                ...(preview.data.import_kind === 'advance' ? { account_id: values.account_id } : {}),
                idempotency_key: importKey,
            } });
            messageApi.success('旧账余额已接入，原订单与旧收款记录已保留');
            setPreviewUid(null); setSelectedLinkId(result.id); setTab('links'); refresh(); onChanged?.();
        } catch (err) { setImportError(err.message); } finally { setBusy(false); }
    };
    const reconcile = async values => {
        if (busy || !selectedLink.data) return;
        setBusy(true); setReconcileError('');
        try {
            const row = selectedLink.data;
            await financeRequest(`/legacy/links/${row.id}/acknowledge`, { method: 'POST', body: {
                version: row.version, source_hash: row.current_source_hash, reason: values.reason,
                related_document_ids: values.related_document_ids || [], related_payment_ids: values.related_payment_ids || [],
                idempotency_key: reconcileKey,
            } });
            messageApi.success('差异处理依据已保存，来源核对状态已更新');
            setReconcileOpen(false); refresh(); onChanged?.();
        } catch (err) { setReconcileError(err.message); } finally { setBusy(false); }
    };
    const revoke = async () => {
        if (busy || !selectedLink.data?.can_revoke || !revokeReason.trim()) return;
        setBusy(true); setRevokeError('');
        try {
            const row = selectedLink.data;
            await financeRequest(`/legacy/links/${row.id}/revoke`, { method: 'POST', body: {
                version: row.version, reason: revokeReason.trim(), idempotency_key: revokeKey,
            } });
            messageApi.success('接入已撤销，原期初单据与历史均已保留');
            setRevokeOpen(false); refresh(); onChanged?.();
        } catch (err) { setRevokeError(err.message); } finally { setBusy(false); }
    };
    const recordStatus = row => { if (row.link_status === 'revoked') return <Text type="secondary">已撤销接入</Text>; const [label, status] = STATUS[row.status] || (row.drift ? STATUS.reconciliation_required : STATUS.current); return <Badge status={status} text={label} />; };
    const resultTable = (result, query, setQuery, columns) => <>
        <Failure result={result} /><Table className={styles.table} rowKey={row => row.order_uid || row.id} loading={result.loading} dataSource={result.data?.items || []} scroll={{ x: 760 }}
            pagination={{ current: query.p, pageSize: query.s, total: result.data?.total || 0, showSizeChanger: false }}
            onChange={pagination => setQuery(prev => ({ ...prev, p: pagination.current }))} columns={columns} />
    </>;
    const link = selectedLink.data;
    const requiredDocumentAmount = link?.required_document_amount ?? (Number(link?.delta?.receivable_amount || 0) - Number(link?.delta?.settlement_difference || 0));
    const requiredPaymentAmount = link?.required_payment_amount ?? link?.delta?.received_amount ?? 0;
    const availableDocuments = [...new Map([
        ...(link?.required_documents || []).map(row => ({ ...row, document_type: 'customer_credit', total_amount: row.amount })),
        ...(reconciliationDocuments.data?.items || []).filter(row => !row.is_opening),
    ].map(row => [row.id, row])).values()];
    return <div className={styles.workspace}>
        {contextHolder}
        <div className={styles.toolbar}><Title level={4} style={{ margin: 0 }}>旧订单余额接入</Title><Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button></div>
        <Collapse size="small" ghost style={{ marginBottom: 16 }} items={[{ key: 'scope', label: '接入切换日净余额，历史收款不重复入账', children: <Typography.Paragraph style={{ marginBottom: 0 }}>先核对来源，再把净欠款或预收余额接入人民币账簿。历史收款保留为查证依据，不会作为新到账资金重复入账。接入后旧订单发生变化，会显示差异，由财务核对并通过新账调整处理。</Typography.Paragraph> }]} />
        <Failure result={fetchedSettings} />
        {settings && !eligibleSetup && <Alert className={styles.error} type="warning" showIcon message="当前不能导入期初" description={!settings.configured ? '请先完成建账设置。' : settings.opening_confirmed ? '期初已经确认，不能再导入旧余额；请通过调整单据处理。' : `旧账快照只支持今天切换，建账日 ${cutoff} 与今天不一致。`} />}
        <Card size="small">
            <Tabs activeKey={tab} onChange={setTab} items={[
                { key: 'orders', label: '选择旧订单', children: <>
                    <div className={styles.toolbar}><Input.Search aria-label="搜索旧订单" placeholder="订单号或客户" allowClear onSearch={q => setOrdersQuery(prev => ({ ...prev, q, p: 1 }))} className={styles.search} /><Text type="secondary">切换日期 {cutoff}</Text></div>
                    {resultTable(orders, ordersQuery, setOrdersQuery, [
                        { title: '旧订单', dataIndex: 'order_number', render: value => <Text strong>{value}</Text> },
                        { title: '客户', dataIndex: 'customer_name' },
                        { title: '操作', width: 150, render: (_, row) => <Button onClick={() => openPreview(row.order_uid)} icon={<SwapOutlined />}>预览余额</Button> },
                    ])}
                </> },
                { key: 'links', label: '已接入与差异', children: <>
                    <div className={styles.toolbar}><Space wrap><Input.Search aria-label="搜索接入记录" placeholder="订单号或客户" allowClear onSearch={q => setLinksQuery(prev => ({ ...prev, q, p: 1 }))} /><Select aria-label="差异状态" value={linksQuery.status} onChange={status => setLinksQuery(prev => ({ ...prev, status, p: 1 }))} options={[{ value: '', label: '全部记录' }, { value: 'drift', label: '需要核对' }, { value: 'current', label: '来源一致' }]} /></Space></div>
                    {resultTable(links, linksQuery, setLinksQuery, [
                        { title: '原订单 / 客户', key: 'source', render: (_, row) => <div><Text strong>{row.order_number}</Text><div className={styles.muted}>{row.customer_name}</div></div> },
                        { title: '接入类型', dataIndex: 'import_kind', render: value => KIND[value] || value },
                        { title: '接入金额', dataIndex: 'amount', align: 'right', render: value => `¥ ${money(value)}` },
                        { title: '来源状态', key: 'status', render: (_, row) => recordStatus(row) },
                        { title: '操作', width: 145, render: (_, row) => <Button onClick={() => setSelectedLinkId(row.id)}>{row.drift ? '核对差异' : '查看记录'}</Button> },
                    ])}
                </> },
            ]} />
        </Card>
        <Drawer rootClassName={styles.workspace} title="核对旧订单余额" open={!!previewUid} onClose={() => !busy && setPreviewUid(null)} width="min(780px, 100vw)">
            <Steps size="small" current={preview.data ? 1 : 0} items={[{ title: '读取来源' }, { title: '核对并确认' }, { title: '保存期初' }]} style={{ marginBottom: 24 }} />
            <Failure result={preview} /><Spin spinning={preview.loading}>{preview.data && <>
                <div className={styles.detailTop}><Title level={4}>{preview.data.order_number}</Title><Text>{preview.data.customer_name}</Text><div className={styles.muted}>切换日期 {preview.data.cutoff_date} · 来源读取时间 {preview.data.snapshot_at}</div></div>
                <SourceAmounts source={preview.data.source} /><Evidence source={preview.data.source} />
                <Alert className={styles.error} showIcon type={preview.data.can_import ? 'success' : 'warning'} message={`${KIND[preview.data.import_kind] || '待核对'} · ¥ ${money(preview.data.amount)}`} description={preview.data.notice || '只将核对后的净余额登记为期初，不重新确认历史收入。'} />
                {!!preview.data.blockers?.length && <Alert className={styles.error} type="warning" showIcon message="需先处理以下事项" description={<ul style={{ marginBottom: 0 }}>{preview.data.blockers.map(item => <li key={item}>{item}</li>)}</ul>} />}
                {preview.data.existing_link_id && <Button onClick={() => { setPreviewUid(null); setSelectedLinkId(preview.data.existing_link_id); }}>查看已接入记录</Button>}
                {importError && <Alert className={styles.error} type="error" showIcon message={importError} action={<Button onClick={refreshPreview}>重新读取并核对</Button>} />}
                <Form form={form} layout="vertical" onFinish={doImport} disabled={!preview.data.can_import || !eligibleSetup || busy}>
                    {preview.data.import_kind === 'receivable' && <Form.Item name="due_date" label="经核实的原到期日（可选）" extra={preview.data.due_date_notice || '如有可靠的原账期依据，请填写原到期日；未填写时以切换日作为临时口径。'}><Input type="date" /></Form.Item>}
                    {preview.data.import_kind === 'advance' && <><Failure result={accounts} /><Form.Item name="account_id" label="原预收款对应资金账户" extra="仅用于保留资金来源。银行期初余额须在期初凭证中单独核对，不重复登记到账。" rules={[{ required: true, message: '请选择原收款对应的账户' }]}><Select showSearch filterOption={false} onSearch={setAccountSearch} loading={accounts.loading} options={(accounts.data?.items || []).map(account => ({ value: account.id, label: account.name }))} placeholder="选择资金账户" /></Form.Item></>}
                    <Form.Item name="reason" label="核对依据" rules={[{ required: true, whitespace: true, message: '请填写余额核对依据' }]}><Input.TextArea maxLength={2000} rows={3} placeholder="例如：与客户对账单、旧收据和期初清单逐项核对一致……" /></Form.Item>
                    <Form.Item name="confirmed" valuePropName="checked" rules={[{ validator: (_, value) => value === true ? Promise.resolve() : Promise.reject(new Error('请确认已核对来源及余额')) }]}><Checkbox>我已核对来源和净余额，确认历史收款不会重复入账。</Checkbox></Form.Item>
                    <Space wrap><Button type="primary" htmlType="submit" loading={busy} icon={<CheckCircleOutlined />}>确认接入期初</Button><Button disabled={busy} onClick={refreshPreview}>重新预览</Button></Space>
                </Form>
            </>}</Spin>
        </Drawer>
        <Drawer rootClassName={styles.workspace} title="接入记录与来源核对" open={!!selectedLinkId} onClose={() => setSelectedLinkId(null)} width="min(800px, 100vw)">
            <Failure result={selectedLink} /><Spin spinning={selectedLink.loading}>{link && <>
                <div className={styles.detailTop}><div className={styles.detailHeading}><Title level={4}>{link.order_number}</Title>{recordStatus(link)}</div><Text>{link.customer_name}</Text><div className={styles.muted}>接入时间 {link.imported_at} · 切换日期 {link.cutoff_date}</div></div>
                <Descriptions bordered column={2} size="small"><Descriptions.Item label="新账接入类型">{KIND[link.import_kind]}</Descriptions.Item><Descriptions.Item label="新账期初基线">¥ {money(link.amount)}</Descriptions.Item><Descriptions.Item label="期初账单">{link.document_id || '—'}</Descriptions.Item><Descriptions.Item label="期初预收">{link.payment_id || '—'}</Descriptions.Item></Descriptions>
                {link.link_status === 'revoked' ? <Alert className={styles.error} style={{ marginTop: 16 }} showIcon type="info" message="该接入已撤销，原记录与冲销凭证均保留" description="可以重新读取旧订单余额，核对后再次接入。" /> : link.drift && <Alert className={styles.error} style={{ marginTop: 16 }} showIcon type="warning" message="原订单在接入后发生变化" description="新账期初保持原值。请核对以下差异，必要时在客户账单中创建调整或贷项，并保留核对依据。" />}
                {link.status === 'source_unavailable' && <Alert style={{ marginTop: 16 }} showIcon type="error" message="无法读取当前来源，请恢复来源后再核对" />}
                {!!link.current_preview?.blockers?.length && <Alert style={{ marginTop: 16 }} showIcon type="warning" message="待核对事项" description={<ul>{link.current_preview.blockers.map(item => <li key={item}>{item}</li>)}</ul>} />}
                <Title level={5} className={styles.sectionTitle}>当前旧账余额</Title><SourceAmounts source={link.current_preview?.source} />
                {link.delta && <Table style={{ marginTop: 16 }} size="small" rowKey="field" pagination={false} dataSource={[
                    ['receivable_amount', '旧应收变化'], ['received_amount', '已审收款变化'], ['settlement_difference', '结清减免变化'], ['signed_balance', '净余额变化'],
                ].map(([field, label]) => ({ field, label, value: link.delta[field] }))} columns={[{ title: '与上次核对相比', dataIndex: 'label' }, { title: '变化金额（CNY）', dataIndex: 'value', align: 'right', render: value => <Text type={Number(value) ? 'warning' : 'secondary'}>{Number(value) > 0 ? '+' : ''}{money(value)}</Text> }]} />}
                <div className={styles.detailActions}>
                    {link.drift && link.status !== 'source_unavailable' && link.link_status !== 'revoked' && <Button type="primary" onClick={() => { reconcileForm.resetFields(); reconcileForm.setFieldsValue({ related_document_ids: link.required_document_ids || [] }); setReconcileKey(mutationKey()); setReconcileError(''); setReconcileOpen(true); }}>登记差异处理依据</Button>}
                    {link.link_status === 'revoked' ? <Button type="primary" onClick={() => { setSelectedLinkId(null); openPreview(link.order_uid); }}>重新预览接入</Button> : <Button danger onClick={() => { setRevokeOpen(true); setRevokeReason(''); setRevokeError(''); setRevokeKey(mutationKey()); }}>撤销接入</Button>}
                    {onOpenLedger && <Button onClick={() => { setSelectedLinkId(null); onOpenLedger({ documentId: link.document_id, paymentId: link.payment_id, partnerId: link.customer_id }); }}>前往新账处理</Button>}
                    <Button icon={<HistoryOutlined />} onClick={() => setHistoryId(link.id)}>查看接入历史</Button><Button onClick={selectedLink.reload}>重新核对来源</Button>
                </div>
            </>}{!link && !selectedLink.loading && !selectedLink.error && <Empty />}</Spin>
        </Drawer>
        <Modal title="核对差异并登记处理依据" open={reconcileOpen} onCancel={() => !busy && setReconcileOpen(false)} onOk={() => reconcileForm.submit()} confirmLoading={busy} okText="核对并保存" width={650} destroyOnClose>
            <Alert showIcon type="info" className={styles.error} message="以新账已生效单据作为处理依据" description={`本次需补账单净变化 ¥ ${money(requiredDocumentAmount)}；收款净变化 ¥ ${money(requiredPaymentAmount)}。已包含失效凭据需要补齐的影响，系统会逐项核对金额、客户和依据是否重复。`} />
            {!!link?.required_documents?.length && <Alert type="warning" showIcon className={styles.error} message="以下关联贷项必须纳入本次核对" description={link.required_documents.map(row => `${row.number} · ¥ ${money(row.amount)}`).join('；')} />}
            {reconcileError && <Alert type="error" showIcon className={styles.error} message={reconcileError} />}
            <Failure result={reconciliationDocuments} /><Failure result={reconciliationPayments} />
            <Form form={reconcileForm} layout="vertical" onFinish={reconcile} preserve={false}>
                <Form.Item name="related_document_ids" label="对应的新账单或贷项" rules={Number(requiredDocumentAmount) !== 0 || link?.required_document_ids?.length ? [{ required: true, type: 'array', min: 1, message: '请选择处理应收变化的新账单或贷项' }] : []}>
                    <Select mode="multiple" showSearch filterOption={false} onSearch={setDocumentSearch} loading={reconciliationDocuments.loading} placeholder="选择已生效、非期初的客户账单或贷项" options={availableDocuments.map(row => ({ value: row.id, label: `${row.number} · ${row.document_type === 'customer_credit' ? '贷项' : '账单'} · ¥ ${money(row.total_amount)}` }))} />
                </Form.Item>
                <Form.Item name="related_payment_ids" label="对应的新收款或退款" rules={Number(requiredPaymentAmount) !== 0 ? [{ required: true, type: 'array', min: 1, message: '请选择处理收款变化的新收款或退款' }] : []}>
                    <Select mode="multiple" showSearch filterOption={false} onSearch={setPaymentSearch} loading={reconciliationPayments.loading} placeholder="选择已生效、非期初的客户收款或退款" options={(reconciliationPayments.data?.items || []).filter(row => !row.is_opening).map(row => ({ value: row.id, label: `${row.number} · ${row.direction === 'incoming' ? '收款' : '退款'} · ¥ ${money(row.amount)}` }))} />
                </Form.Item>
                <Form.Item name="reason" label="核对结果与处理说明" rules={[{ required: true, whitespace: true, message: '请填写核对结果与处理说明' }]}><Input.TextArea rows={3} maxLength={2000} /></Form.Item>
            </Form>
        </Modal>
        <Modal title="撤销旧账接入" open={revokeOpen} onCancel={() => !busy && setRevokeOpen(false)} onOk={revoke} confirmLoading={busy} okText="撤销并保留历史" okButtonProps={{ danger: true, disabled: !link?.can_revoke || !revokeReason.trim() }}>
            <Alert type="warning" showIcon className={styles.error} message={`${link?.order_number || ''} · ${KIND[link?.import_kind] || ''} ¥ ${money(link?.amount)}`} description="系统会冲销本次接入产生的期初单据并保留完整历史。原订单及旧收款不变；撤销后需要重新预览、核对才能再次接入。" />
            {!!link?.revoke_blockers?.length && <Alert type="error" showIcon className={styles.error} message="当前不能撤销" description={<ul>{link.revoke_blockers.map(item => <li key={item}>{item}</li>)}</ul>} />}
            {revokeError && <Alert type="error" showIcon className={styles.error} message={revokeError} />}
            <label htmlFor="legacy-revoke-reason">撤销原因</label><Input.TextArea id="legacy-revoke-reason" rows={3} maxLength={2000} value={revokeReason} onChange={event => setRevokeReason(event.target.value)} style={{ marginTop: 8 }} />
        </Modal>
        <FinanceHistoryDrawer open={!!historyId} onClose={() => setHistoryId(null)} historyUrl={historyId ? `/finance/v2/legacy/links/${historyId}/history` : null} title="旧账接入历史" />
    </div>;
}
