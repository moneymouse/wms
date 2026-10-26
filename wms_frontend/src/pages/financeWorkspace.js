import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
    Alert, Button, Card, Checkbox, Col, DatePicker, Descriptions, Divider, Drawer, Empty, Form, Grid, Input, InputNumber,
    List, Modal, Row, Select, Space, Spin, Statistic, Switch, Table, Tabs, Typography, message,
} from 'antd';
import {
    ArrowDownOutlined, ArrowUpOutlined, CheckCircleOutlined,
    DeleteOutlined, HistoryOutlined,
    PlusOutlined, PrinterOutlined, ReloadOutlined, SwapOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { Link } from 'react-router-dom';
import FinanceHistoryDrawer from '../components/FinanceHistoryDrawer';
import PaymentOrderPicker from '../components/PaymentOrderPicker';
import PaymentPackingBoxPicker from '../components/PaymentPackingBoxPicker';
import FinanceAccounting from './financeAccounting';
import FinancePartnerStatement from './financePartnerStatement';
import {
    FINANCE_DOCUMENT_TYPES, FINANCE_STATUS, financeRequest, money, mutationKey,
    paymentTargetType, printFinancePayment, queryString,
} from '../common/financeApi';
import styles from './financeWorkspace.module.css';
import { getCurrentTourUser } from '../common/featureTourState';
import { OrderAllocationDialog } from './financeOrderSettlements';

const { Title, Text } = Typography;
const DOCUMENT_OPTIONS = Object.entries(FINANCE_DOCUMENT_TYPES).map(([value, item]) => ({ value, label: item.label }));
const STATUS_OPTIONS = ['draft', 'posted', 'cancelled'].map(value => ({ value, label: FINANCE_STATUS[value].label }));
const PARTNERS = [{ value: 'customer', label: '客户' }, { value: 'vendor', label: '供应商' }];
const emptyList = { items: [], total: 0, page: 1, page_size: 20 };
const required = label => [{ required: true, message: `请填写${label}` }];
const isCredit = document => document?.document_type?.endsWith('_credit');
const isOverdue = row => row.status === 'posted' && Number(row.residual_amount) > 0 && row.due_date && dayjs(row.due_date).isBefore(dayjs().startOf('day'));

export function StatusTag({ status }) {
    return <Text type={['draft', 'cancelled'].includes(status) ? 'secondary' : status === 'reversed' ? 'danger' : undefined}>{FINANCE_STATUS[status]?.label || status || '—'}</Text>;
}
function Currency({ value, strong = false }) {
    return <Text strong={strong} className={styles.amount}>{value === undefined || value === null ? '—' : money(value)}</Text>;
}
function ErrorNotice({ error, retry }) {
    return error ? <Alert className={styles.error} type="error" showIcon message={error} action={retry && <Button size="small" onClick={retry}>重试</Button>} /> : null;
}
function Panel({ title, extra, children }) {
    if (!title) return <div className={styles.panel}>{children}</div>;
    return <Card size="small" title={title} extra={extra} className={styles.panel} styles={{ body: { padding: 0 } }}>{children}</Card>;
}

// A request generation prevents a slow older filter request from replacing a newer one.
function useFinanceData(path, params = {}, revision = 0) {
    const [result, setResult] = useState({ identity: '', data: null, error: '', loading: false });
    const [retry, setRetry] = useState(0);
    const key = queryString(params);
    const identity = JSON.stringify([path, key, revision, retry]);
    useEffect(() => {
        if (!path) return undefined;
        let active = true;
        const controller = new AbortController();
        setResult({ identity, data: null, error: '', loading: true });
        financeRequest(path, { params: Object.fromEntries(new URLSearchParams(key)), signal: controller.signal })
            .then(data => { if (active) setResult({ identity, data, error: '', loading: false }); })
            .catch(err => { if (active && err.name !== 'AbortError') setResult({ identity, data: null, error: err.message, loading: false }); });
        return () => { active = false; controller.abort(); };
    }, [path, key, identity]);
    return { ...(path && result.identity === identity ? result : { data: null, error: '', loading: Boolean(path) }), reload: () => setRetry(value => value + 1) };
}

function PartnerSelect({ partnerType, value, onChange, disabled }) {
    const [query, setQuery] = useState('');
    const result = useFinanceData('/partners', { partner_type: partnerType, q: query });
    const rows = result.data?.items || [];
    return <Select aria-label={partnerType === 'vendor' ? '供应商' : '客户'} showSearch allowClear
        value={value} onChange={onChange} disabled={disabled} filterOption={false} onSearch={setQuery}
        loading={result.loading} placeholder={partnerType === 'vendor' ? '搜索供应商' : '搜索客户'}
        options={rows.map(row => ({ value: row.id, label: row.name }))}
        notFoundContent={result.error ? <Text type="danger">{result.error}</Text> : result.loading ? <Spin size="small" /> : '暂无往来单位'} />;
}

function DocumentSelect({ documentType, partnerId, value, onChange }) {
    const [query, setQuery] = useState('');
    const result = useFinanceData(partnerId ? '/documents' : null, { document_type: documentType, partner_id: partnerId, status: 'posted', q: query, s: 100 });
    return <Select showSearch value={value} onChange={onChange} filterOption={false} onSearch={setQuery}
        disabled={!partnerId} loading={result.loading} placeholder="搜索原账单号或参考号"
        options={(result.data?.items || []).map(row => ({ value: row.id, label: `${row.number} · ¥${money(row.total_amount)}${row.order_managed ? '（订单账单，请在订单应收办理）' : ''}`, disabled: Boolean(row.order_managed) }))}
        notFoundContent={result.error || '没有匹配的已生效账单'} />;
}

export function DocumentEditor({ open, document, initialType = 'customer_invoice', onClose, onSaved }) {
    const [form] = Form.useForm();
    const [saving, setSaving] = useState(false);
    const savingRef = useRef(false);
    const keyRef = useRef(mutationKey());
    const [error, setError] = useState('');
    const documentType = Form.useWatch('document_type', form) || initialType;
    const partnerId = Form.useWatch('partner_id', form);
    const lines = Form.useWatch('lines', form) || [];
    const credit = documentType.endsWith('_credit');
    useEffect(() => {
        if (!open) return;
        setError(''); keyRef.current = mutationKey(); form.resetFields();
        form.setFieldsValue(document ? {
            ...document, document_date: dayjs(document.document_date), due_date: document.due_date ? dayjs(document.due_date) : null,
        } : { document_type: initialType, document_date: dayjs(), lines: [{ description: '', quantity: 1, unit_price: 0, tax_rate: 0 }] });
    }, [document, form, initialType, open]);
    const save = async () => {
        if (savingRef.current) return;
        try {
            const values = await form.validateFields();
            if (!values.lines?.length) { setError('请至少添加一条账单明细'); return; }
            savingRef.current = true; setSaving(true); setError('');
            const body = {
                ...values, is_opening: !credit && Boolean(values.is_opening),
                document_date: values.document_date.format('YYYY-MM-DD'),
                due_date: values.due_date?.format('YYYY-MM-DD') || null,
                lines: values.lines.map(line => ({ description: line.description, quantity: line.quantity, unit_price: line.unit_price, tax_rate: line.tax_rate || 0, ...(line.order_uid ? { order_uid: line.order_uid } : {}) })),
                ...(document ? { version: document.version } : { idempotency_key: keyRef.current }),
            };
            const saved = await financeRequest(document ? `/documents/${document.id}` : '/documents', { method: document ? 'PATCH' : 'POST', body });
            onSaved(saved); onClose();
        } catch (err) { if (!err.errorFields) setError(err.message); }
        finally { savingRef.current = false; setSaving(false); }
    };
    const estimated = lines.reduce((sum, line) => sum + Number(line?.quantity || 0) * Number(line?.unit_price || 0) * (1 + Number(line?.tax_rate || 0) / 100), 0);
    return <Drawer title={document ? `编辑草稿 · ${document.number}` : '新建财务账单'} open={open} width="min(900px, 100vw)"
        onClose={() => { if (!saving) onClose(); }} closable={!saving} maskClosable={!saving}
        extra={<Button type="primary" loading={saving} onClick={save}>保存草稿</Button>} destroyOnHidden>
        <ErrorNotice error={error} />
        <Form form={form} layout="vertical" disabled={saving} preserve={false}>
            <div className={styles.formGrid}>
                <Form.Item name="document_type" label="账单类型" rules={required('账单类型')}>
                    <Select options={DOCUMENT_OPTIONS} disabled={Boolean(document)} onChange={() => form.setFieldsValue({ partner_id: undefined, original_document_id: undefined, is_opening: false })} />
                </Form.Item>
                <Form.Item name="partner_id" label={FINANCE_DOCUMENT_TYPES[documentType]?.partner === 'vendor' ? '供应商' : '客户'} rules={required('往来单位')}>
                    <PartnerSelect partnerType={FINANCE_DOCUMENT_TYPES[documentType]?.partner || 'customer'} onChange={() => form.setFieldsValue({ original_document_id: undefined })} />
                </Form.Item>
                <Form.Item name="document_date" label="账单日期" rules={required('账单日期')}><DatePicker /></Form.Item>
                <Form.Item name="due_date" label="到期日"><DatePicker /></Form.Item>
                {credit && <Form.Item name="original_document_id" label="原账单" rules={required('原账单')}>
                    <DocumentSelect documentType={documentType === 'customer_credit' ? 'customer_invoice' : 'vendor_bill'} partnerId={partnerId} />
                </Form.Item>}
                <Form.Item name="reference" label="业务参考号"><Input placeholder="合同号、外部账单号等" maxLength={200} /></Form.Item>
            </div>
            {!credit && <Form.Item name="is_opening" valuePropName="checked" extra="用于建账日前的历史往来余额。日期必须为建账日，且仅在期初确认前可登记；金额不计入本期收入或成本。"><Checkbox>期初账单</Checkbox></Form.Item>}
            {credit && <Alert type="info" showIcon message="贷项用于调减原账单；生效后可抵扣未结账单，或办理实际退款。" style={{ marginBottom: 18 }} />}
            <Title level={5}>费用明细</Title>
            <Form.List name="lines">{(fields, { add, remove }) => <>
                {fields.map(field => <div key={field.key} className={styles.lineForm}>
                    <div className={styles.lineGrid}>
                        <Form.Item name={[field.name, 'description']} label="费用说明" rules={required('费用说明')}><Input maxLength={300} /></Form.Item>
                        <Form.Item name={[field.name, 'quantity']} label="数量" rules={required('数量')}><InputNumber min={0.0001} precision={4} /></Form.Item>
                        <Form.Item name={[field.name, 'unit_price']} label="单价 / CNY" rules={required('单价')}><InputNumber min={0} precision={4} /></Form.Item>
                        <Form.Item name={[field.name, 'tax_rate']} label="税率 %"><InputNumber min={0} max={100} precision={2} /></Form.Item>
                        <Button type="text" danger aria-label={`删除第 ${field.name + 1} 行`} icon={<DeleteOutlined />} disabled={fields.length === 1} style={{ marginTop: 30 }} onClick={() => remove(field.name)} />
                    </div>
                </div>)}
                <Button icon={<PlusOutlined />} onClick={() => add({ description: '', quantity: 1, unit_price: 0, tax_rate: 0 })}>添加费用</Button>
            </>}</Form.List>
            <div className={styles.formSummary}><span>含税合计（预估）</span><strong>¥ {money(estimated)}</strong></div>
            <Form.Item name="memo" label="备注"><Input.TextArea rows={3} maxLength={2000} /></Form.Item>
            <Text type="secondary">保存为草稿后可继续修改。确认生效将生成会计凭证，金额和明细随即锁定。</Text>
        </Form>
    </Drawer>;
}

function PaymentLookup({ path, params = {}, value, onChange, multiple = false, selectedOptions = [], disabled, placeholder, ariaLabel }) {
    const [query, setQuery] = useState('');
    const [page, setPage] = useState(1);
    const [options, setOptions] = useState([]);
    const paramsKey = queryString(params);
    const result = useFinanceData(disabled ? null : path, { ...params, q: query, p: page, s: 30 });
    useEffect(() => { setQuery(''); setPage(1); setOptions([]); }, [path, paramsKey]);
    useEffect(() => {
        if (!result.data) return;
        const next = (result.data.items || []).map(row => ({ value: row.order_uid || row.uid || row.id, label: row.order_number || row.order_id || row.name }));
        setOptions(previous => page === 1 ? next : [...previous, ...next].filter((row, index, all) => all.findIndex(item => item.value === row.value) === index));
    }, [result.data, page]);
    const currentValues = multiple ? value || [] : [value];
    const allOptions = [...options, ...selectedOptions.filter(item => currentValues.includes(item.value))].filter((row, index, all) => all.findIndex(item => String(item.value) === String(row.value)) === index);
    return <>
        <Select aria-label={ariaLabel} showSearch allowClear mode={multiple ? 'multiple' : undefined} value={value} onChange={onChange} disabled={disabled} loading={result.loading}
            filterOption={false} onSearch={text => { setQuery(text); setPage(1); setOptions([]); }} options={allOptions} placeholder={placeholder}
            popupRender={menu => <>{menu}{page * 30 < Number(result.data?.total || 0) && <Button block type="text" loading={result.loading} onMouseDown={event => event.preventDefault()} onClick={() => setPage(current => current + 1)}>加载更多</Button>}</>}
            notFoundContent={result.error || (result.loading ? <Spin size="small" /> : '没有匹配项')} />
        {result.error && <Text type="danger" role="alert">{result.error}<Button type="link" size="small" onClick={result.reload}>重试</Button></Text>}
    </>;
}

export function PaymentEditor({ open, payment, direction = 'incoming', business = false, modal = false, initialContext, onClose, onSaved }) {
    const [form] = Form.useForm();
    const [saving, setSaving] = useState(false);
    const savingRef = useRef(false);
    const keyRef = useRef(mutationKey());
    const workingPayment = useRef(payment || null);
    const [error, setError] = useState('');
    const [remarksTab, setRemarksTab] = useState('packing');
    const partnerType = Form.useWatch('partner_type', form) || 'customer';
    const partnerId = Form.useWatch('partner_id', form);
    const referenceOrderUids = Form.useWatch('reference_order_uids', form) || [];
    const referenceBoxUids = Form.useWatch('reference_box_uids', form) || [];
    const selectedDirection = Form.useWatch('direction', form) || direction;
    const openingAllowed = !business && ((partnerType === 'customer' && selectedDirection === 'incoming') || (partnerType === 'vendor' && selectedDirection === 'outgoing'));
    const [accountQuery, setAccountQuery] = useState('');
    const accounts = useFinanceData(open ? (business ? '/payment-options/accounts' : '/accounts') : null, { s: 100, active: 1, q: accountQuery });
    const contextKey = JSON.stringify(initialContext || {});
    useEffect(() => {
        if (!open) return;
        const context = JSON.parse(contextKey);
        const orderUids = payment
            ? payment.reference_order_uids || (payment.reference_orders || []).map(row => row.order_uid)
            : context.customerId && context.orderUid ? [context.orderUid] : [];
        const boxUids = payment
            ? payment.reference_box_uids || (payment.reference_packing_boxes || []).map(row => row.box_uid)
            : context.referenceBoxUids || (context.referencePackingBoxes || []).map(row => row.box_uid);
        setRemarksTab(boxUids.length || !orderUids.length ? 'packing' : 'orders');
        setError(''); keyRef.current = mutationKey(); workingPayment.current = payment || null; form.resetFields();
        form.setFieldsValue(payment ? {
            ...payment, payment_date: dayjs(payment.payment_date), reference_order_uids: orderUids,
            reference_box_uids: boxUids,
        } : {
            direction, partner_type: business ? 'customer' : direction === 'incoming' ? 'customer' : 'vendor', payment_date: dayjs(),
            partner_id: context.customerId ? Number(context.customerId) : undefined,
            reference_order_uids: orderUids,
            reference_box_uids: boxUids,
        });
    }, [business, contextKey, direction, form, open, payment]);
    const save = async submit => {
        if (savingRef.current) return;
        savingRef.current = true; setSaving(true); setError('');
        try {
            const values = await form.validateFields();
            const current = workingPayment.current;
            const body = { ...values, partner_type: business ? 'customer' : values.partner_type, is_opening: openingAllowed && Boolean(values.is_opening),
                reference_order_uids: values.reference_order_uids || [], reference_box_uids: values.reference_box_uids || [], payment_date: values.payment_date.format('YYYY-MM-DD'),
                ...(current ? { version: current.version } : { idempotency_key: keyRef.current }) };
            const saved = await financeRequest(current ? `/payments/${current.id}` : '/payments', { method: current ? 'PATCH' : 'POST', body });
            workingPayment.current = saved;
            if (submit) {
                try {
                    const submitted = await financeRequest(`/payments/${saved.id}/submit`, { method: 'POST', body: { version: saved.version, idempotency_key: mutationKey() } });
                    workingPayment.current = submitted; onSaved(submitted); onClose();
                } catch (err) { setError(`草稿 ${saved.number} 已保存，提交失败：${err.message}`); }
            } else { onSaved(saved); onClose(); }
        } catch (err) { if (!err.errorFields) setError(err.message); }
        finally { savingRef.current = false; setSaving(false); }
    };
    const partnerLabel = business || partnerType === 'customer' ? '客户' : '供应商';
    const selectedPartnerOptions = [{ value: payment?.partner_id || Number(initialContext?.customerId), label: payment?.partner_name || initialContext?.customerName }].filter(row => row.value && row.label);
    const selectedOrders = payment?.reference_orders
        || (initialContext?.orderUid ? [{ order_uid: initialContext.orderUid, order_number: initialContext.orderNumber || initialContext.orderUid }] : []);
    const selectedBoxes = payment?.reference_packing_boxes || initialContext?.referencePackingBoxes || [];
    const changeCustomer = nextCustomerId => {
        const eligibleContextBoxes = initialContext?.packingListUid && nextCustomerId
            ? referenceBoxUids.filter(uid => selectedBoxes.some(box => String(box.box_uid) === String(uid)
                && (box.customer_id == null || String(box.customer_id) === String(nextCustomerId)))) : [];
        form.setFieldsValue({ reference_order_uids: [], reference_box_uids: eligibleContextBoxes });
    };
    const close = () => { if (!saving) { if (workingPayment.current && workingPayment.current !== payment) onSaved(workingPayment.current); onClose(); } };
    const actions = <Space>
        {modal && <Button autoInsertSpace={false} disabled={saving} onClick={close}>取消</Button>}
        <Button autoInsertSpace={false} disabled={saving} onClick={() => save(false)}>保存</Button>
        {business && <Button autoInsertSpace={false} type="primary" loading={saving} onClick={() => save(true)}>提交</Button>}
    </Space>;
    const content = <>
        <ErrorNotice error={error || accounts.error} retry={accounts.error ? accounts.reload : undefined} />
        <Typography.Paragraph type="secondary">按实际收付款登记，可备注装箱单的箱子。暂未分配订单也可登记；分配后财务可依据箱子所属订单核销。</Typography.Paragraph>
        {initialContext?.referenceNote && <Alert type="info" showIcon message={initialContext.referenceNote} style={{ marginBottom: 16 }} />}
        <Form form={form} layout="vertical" disabled={saving} preserve={false}>
            <Row gutter={16}>
                <Col xs={24} sm={12}><Form.Item name="direction" label="资金方向" rules={required('资金方向')}><Select onChange={() => form.setFieldsValue({ is_opening: false })} options={[{ value: 'incoming', label: '收款' }, { value: 'outgoing', label: '付款' }]} /></Form.Item></Col>
                {!business && <Col xs={24} sm={12}><Form.Item name="partner_type" label="往来类型" rules={required('往来类型')}><Select options={PARTNERS} onChange={value => {
                    form.setFieldsValue({ partner_id: undefined, reference_order_uids: [], reference_box_uids: [], is_opening: false });
                    if (value === 'vendor') setRemarksTab('packing');
                }} /></Form.Item></Col>}
                <Col xs={24} sm={12}><Form.Item name="partner_id" label={partnerLabel} rules={required(partnerLabel)}>
                    {business ? <PaymentLookup path="/payment-options/customers" ariaLabel="收付款客户" placeholder="搜索客户" selectedOptions={selectedPartnerOptions} onChange={changeCustomer} />
                        : <PartnerSelect partnerType={partnerType} onChange={() => form.setFieldsValue({ reference_order_uids: [], reference_box_uids: [] })} />}
                </Form.Item></Col>
                <Col xs={24} sm={12}><Form.Item name="account_id" label="收付款账户" rules={required('收付款账户')}><Select showSearch filterOption={false} onSearch={setAccountQuery} loading={accounts.loading} placeholder="选择银行或现金账户" options={(accounts.data?.items || accounts.data || []).filter(row => row.active !== false).map(row => ({ value: row.id, label: row.name }))} /></Form.Item></Col>
                <Col xs={24} sm={12}><Form.Item name="payment_date" label="收付款日期" rules={required('收付款日期')}><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
                <Col xs={24} sm={12}><Form.Item name="amount" label="金额(CNY)" rules={[...required('金额'), { validator: (_, value) => Number.isFinite(Number(value)) && Number(value) > 0 ? Promise.resolve() : Promise.reject(new Error('金额必须大于 0')) }]}><InputNumber min={0.01} precision={2} stringMode style={{ width: '100%' }} /></Form.Item></Col>
                <Col xs={24} sm={12}><Form.Item name="reference" label="流水号 / 支付参考号"><Input maxLength={200} /></Form.Item></Col>
            </Row>
            {openingAllowed && <Form.Item name="is_opening" valuePropName="checked" extra="用于历史预收 / 预付余额，仅在建账日且期初确认前录入；不计入本期资金流水。"><Checkbox>期初预收 / 预付</Checkbox></Form.Item>}
            <Form.Item name="memo" label="文字备注（可不填）" preserve><Input.TextArea aria-label="文字备注" rows={4} maxLength={2000} showCount placeholder="填写收付款补充说明" /></Form.Item>
            <div className={styles.paymentRemarks}>
                <Text type="secondary">{partnerType === 'vendor' ? '供应商收付款可填写文字备注。' : '可同时备注订单、装箱单和文字说明。'}</Text>
                <Tabs activeKey={remarksTab} onChange={setRemarksTab} destroyOnHidden={false} items={[
                    {
                        key: 'packing', label: `装箱单备注${referenceBoxUids.length ? `（${referenceBoxUids.length} 箱）` : ''}`,
                        disabled: partnerType === 'vendor' || saving, forceRender: true,
                        children: <Form.Item name="reference_box_uids" label="选择装箱单并展开勾选箱子（可不选）" preserve extra="未分配到订单的箱子也可备注。" rules={[{ validator: (_, value) => (value || []).length <= 500 ? Promise.resolve() : Promise.reject(new Error('每笔收付款最多备注 500 箱，请减少选择')) }]}>
                            <PaymentPackingBoxPicker customerId={partnerId} disabled={!partnerId || saving || partnerType === 'vendor' || remarksTab !== 'packing'} selectedBoxes={selectedBoxes}
                                packingListUid={initialContext?.packingListUid} retainEligibleOnCustomerChange={Boolean(initialContext?.packingListUid)} />
                        </Form.Item>,
                    },
                    {
                        key: 'orders', label: `订单备注${referenceOrderUids.length ? `（${referenceOrderUids.length}）` : ''}`,
                        disabled: partnerType === 'vendor' || saving, forceRender: true,
                        children: <Form.Item name="reference_order_uids" label="选择订单（可不选）" preserve extra="所选订单仅作为本次收付款的备注。">
                            <PaymentOrderPicker customerId={partnerId} disabled={!partnerId || saving || partnerType === 'vendor' || remarksTab !== 'orders'} selectedOrders={selectedOrders} />
                        </Form.Item>,
                    },
                ]} />
            </div>
        </Form>
    </>;
    const title = payment ? `编辑收付款 · ${payment.number}` : '登记收付款';
    return modal ? <Modal title={title} open={open} width="min(1100px, calc(100vw - 32px))" centered
        onCancel={close} footer={actions} maskClosable={!saving} closable={!saving} keyboard={!saving} destroyOnHidden
        styles={{ body: { maxHeight: 'calc(100vh - 200px)', overflowY: 'auto' } }}>{content}</Modal>
        : <Drawer title={title} open={open} width="min(1100px, 100vw)"
            onClose={close} maskClosable={!saving} closable={!saving} keyboard={!saving} destroyOnHidden extra={actions}>{content}</Drawer>;
}

function ActionDialog({ action, onClose, onSuccess }) {
    const [form] = Form.useForm();
    const [saving, setSaving] = useState(false);
    const savingRef = useRef(false);
    const [error, setError] = useState('');
    const keyRef = useRef(mutationKey());
    const needsReason = !['post', 'submit'].includes(action?.action);
    useEffect(() => { if (action) { form.resetFields(); setError(''); keyRef.current = mutationKey(); } }, [action, form]);
    const execute = async () => {
        if (savingRef.current) return;
        savingRef.current = true; setSaving(true); setError('');
        try {
            const values = await form.validateFields();
            const date = values.date?.format('YYYY-MM-DD');
            const body = {
                version: action.record.version, idempotency_key: keyRef.current,
                ...(values.reason ? { reason: values.reason.trim() } : {}),
                ...(date ? { [action.entity === 'documents' ? 'document_date' : action.entity === 'allocations' ? 'reversal_date' : 'payment_date']: date } : {}),
            };
            await financeRequest(`/${action.entity}/${action.record.id}/${action.action}`, { method: 'POST', body });
            onSuccess(); onClose();
        } catch (err) { if (!err.errorFields) setError(err.message); }
        finally { savingRef.current = false; setSaving(false); }
    };
    return <Modal cancelText="取消" title={action?.label} open={Boolean(action)} onCancel={() => { if (!saving) onClose(); }} onOk={execute}
        okText={action?.label} okButtonProps={{ autoInsertSpace: false }} confirmLoading={saving} cancelButtonProps={{ disabled: saving }} closable={!saving} maskClosable={!saving} keyboard={!saving} destroyOnHidden>
        <ErrorNotice error={error} />
        <Typography.Paragraph>{action?.description}</Typography.Paragraph>
        <Form form={form} layout="vertical" disabled={saving} initialValues={{ date: dayjs() }}>
            {action?.action === 'reverse' && <Form.Item name="date" label="冲销日期" rules={required('冲销日期')}><DatePicker style={{ width: '100%' }} /></Form.Item>}
            {needsReason && <Form.Item name="reason" label="操作原因" rules={[{ required: true, whitespace: true, message: '请填写原因，供后续审计核对' }]}><Input.TextArea rows={3} maxLength={1000} /></Form.Item>}
        </Form>
    </Modal>;
}

export function AllocationDialog({ source, sourceType, onClose, onSuccess }) {
    const [query, setQuery] = useState('');
    const [page, setPage] = useState(1);
    const [amounts, setAmounts] = useState({});
    const [selected, setSelected] = useState({});
    const [reason, setReason] = useState('');
    const [allocationDate, setAllocationDate] = useState(dayjs());
    const [saving, setSaving] = useState(false);
    const savingRef = useRef(false);
    const [error, setError] = useState('');
    const keyRef = useRef(mutationKey());
    const targetType = sourceType === 'payments' ? paymentTargetType(source) : source.document_type === 'customer_credit' ? 'customer_invoice' : 'vendor_bill';
    const result = useFinanceData('/documents', { document_type: targetType, partner_id: source.partner_id, status: 'posted', open_only: 1, q: query, p: page, s: 10 });
    const available = Number(source.available_amount ?? (sourceType === 'payments' ? source.unallocated_amount : source.residual_amount));
    const total = Object.keys(selected).reduce((sum, id) => sum + Math.round(Number(amounts[id] || 0) * 100), 0) / 100;
    const save = async () => {
        if (savingRef.current) return;
        const rows = Object.keys(selected).map(id => ({ document_id: Number(id), amount: Number(amounts[id]) }));
        if (!rows.length || rows.some(row => !Number.isFinite(row.amount) || row.amount <= 0 || Math.round(row.amount * 100) > Math.round(Number(selected[row.document_id].residual_amount) * 100))) {
            setError('请选择账单，并填写大于 0 且不超过账单未结金额的核销金额'); return;
        }
        if (Math.round(total * 100) > Math.round(available * 100)) { setError('核销合计不能超过可用余额'); return; }
        if (!allocationDate) { setError('请选择核销日期'); return; }
        savingRef.current = true; setSaving(true); setError('');
        try {
            await financeRequest('/allocations', {
                method: 'POST', body: {
                    [sourceType === 'payments' ? 'payment_id' : 'credit_document_id']: source.id,
                    version: source.version, allocations: rows, reason: reason.trim(), allocation_date: allocationDate.format('YYYY-MM-DD'), idempotency_key: keyRef.current,
                }
            });
            onSuccess(); onClose();
        } catch (err) { setError(err.message); }
        finally { savingRef.current = false; setSaving(false); }
    };
    return <Modal title="分配核销金额" open width={880} onCancel={() => { if (!saving) onClose(); }} onOk={save} okText="确认核销"
        confirmLoading={saving} closable={!saving} maskClosable={!saving} keyboard={!saving} cancelButtonProps={{ disabled: saving }}>
        <Alert type="info" showIcon message={`${source.partner_name} · ${source.number}`} description={`可用余额 ¥${money(available)}。支持部分核销；未分配余额继续保留。`} style={{ marginBottom: 18 }} />
        <ErrorNotice error={error || result.error} retry={result.error ? result.reload : undefined} />
        <div className={styles.toolbar}><Input.Search className={styles.search} placeholder="搜索待核销账单" allowClear onSearch={value => { setQuery(value); setPage(1); }} />
            <DatePicker aria-label="核销日期" value={allocationDate} onChange={setAllocationDate} disabled={saving} /></div>
        <Table rowKey="id" size="small" loading={result.loading} dataSource={result.data?.items || []} scroll={{ x: 620 }}
            rowSelection={{
                selectedRowKeys: Object.keys(selected).map(Number), preserveSelectedRowKeys: true,
                getCheckboxProps: row => ({ disabled: saving || Boolean(row.order_managed) }),
                onChange: keys => {
                    const cache = { ...selected, ...Object.fromEntries((result.data?.items || []).map(row => [row.id, row])) };
                    setSelected(Object.fromEntries(keys.map(id => [id, cache[id]])));
                    setAmounts(prev => Object.fromEntries(keys.map(id => [id, prev[id] ?? Math.min(Number(cache[id].residual_amount), available)])));
                }
            }}
            columns={[
                { title: '账单号', dataIndex: 'number', render: (value, row) => <>{value}{row.order_managed && <div><Text type="secondary">订单账单，请使用核销订单</Text></div>}</> }, { title: '到期日', dataIndex: 'due_date', render: value => value || '—' },
                { title: '未结金额', dataIndex: 'residual_amount', align: 'right', render: value => <Currency value={value} /> },
                { title: '本次核销 / CNY', key: 'amount', width: 180, render: (_, row) => <InputNumber aria-label={`${row.number} 核销金额`} min={0.01} max={Math.min(Number(row.residual_amount), available)} precision={2} disabled={!selected[row.id] || saving} value={amounts[row.id]} onChange={value => setAmounts(prev => ({ ...prev, [row.id]: value }))} /> },
            ]}
            pagination={{ current: page, pageSize: 10, total: result.data?.total || 0, showSizeChanger: false, onChange: setPage }} />
        <div className={styles.formSummary}><span>已选 {Object.keys(selected).length} 笔</span><strong>¥ {money(total)}</strong></div>
        <Input.TextArea aria-label="核销说明" placeholder="核销说明（选填）" rows={2} value={reason} onChange={event => setReason(event.target.value)} disabled={saving} />
    </Modal>;
}

function AllocationHistory({ params, revision, onReverse, title = '核销记录' }) {
    const [page, setPage] = useState(1);
    const result = useFinanceData('/allocations', { ...params, p: page, s: 10 }, revision);
    return <>
        <Title level={5} className={styles.sectionTitle}>{title}</Title>
        <ErrorNotice error={result.error} retry={result.reload} />
        <Table rowKey="id" size="small" dataSource={result.data?.items || []} loading={result.loading} scroll={{ x: 730 }} locale={{ emptyText: '暂无核销记录' }} columns={[
            { title: '目标账单', dataIndex: 'document_number' },
            { title: '来源', render: (_, row) => row.payment_number || row.credit_document_number || (row.payment_id ? `收付款 #${row.payment_id}` : `贷项 #${row.credit_document_id}`) },
            { title: '核销订单', dataIndex: 'order_number', render: (value, row) => row.order_uid ? <Link to={`/orders/${row.order_uid}`}>{value || row.order_uid}</Link> : '—' },
            { title: '核销日期', dataIndex: 'allocation_date', render: (value, row) => value || row.created_at?.slice(0, 10) || '—' },
            { title: '金额', dataIndex: 'amount', align: 'right', render: value => <Currency value={value} /> },
            { title: '状态', dataIndex: 'status', render: value => <StatusTag status={value} /> },
            { title: '操作', render: (_, row) => row.status === 'active' && <Button type="link" danger size="small" onClick={() => onReverse(row)}>撤销核销</Button> },
        ]} pagination={{ current: page, pageSize: 10, total: result.data?.total || 0, showSizeChanger: false, onChange: setPage }} />
    </>;
}

export function RecordDetail({ entity, recordId, business = false, onClose, onChanged }) {
    const [revision, setRevision] = useState(0);
    const detail = useFinanceData(recordId ? `/${entity}/${recordId}` : null, {}, revision);
    const record = detail.data;
    const payment = entity === 'payments';
    const [editing, setEditing] = useState(false);
    const [history, setHistory] = useState(false);
    const [action, setAction] = useState(null);
    const [allocating, setAllocating] = useState(false);
    const [allocatingOrders, setAllocatingOrders] = useState(false);
    const [messageApi, contextHolder] = message.useMessage();
    const { userId } = getCurrentTourUser();
    const selfReview = record && userId != null && String(record.created_by_id) === String(userId);
    const refresh = () => { setRevision(value => value + 1); onChanged?.(); };
    const setRecordAction = (name, label, description) => setAction({ entity, record, action: name, label, description });
    const remaining = Number(payment ? record?.unallocated_amount : record?.residual_amount);
    const available = Number(record?.available_amount ?? remaining);
    return <>
        {contextHolder}
        <Drawer title={record?.number || (payment ? '收付款详情' : '账单详情')} open={Boolean(recordId)} onClose={onClose} width="min(1000px, 100vw)" destroyOnHidden>
            <ErrorNotice error={detail.error} retry={detail.reload} /><Spin spinning={detail.loading}>
                {record && <>
                    <div className={styles.detailTop}><div className={styles.detailHeading}>
                        <div><Space wrap split={<Divider type="vertical" />}><Text type="secondary">{payment ? record.direction === 'incoming' ? '收款' : '付款' : FINANCE_DOCUMENT_TYPES[record.document_type]?.label}</Text><StatusTag status={record.status} />{record.is_opening && <Text type="secondary">期初余额</Text>}{record.status === 'posted' && record.payment_status && <StatusTag status={record.payment_status} />}</Space>
                            <Title level={4} style={{ margin: '12px 0 4px' }}>{record.partner_name}</Title>{record.reference && <Text type="secondary">参考号：{record.reference}</Text>}</div>
                        <Statistic title="金额（元）" value={payment ? record.amount : record.total_amount} precision={2} />
                    </div>
                        <div className={styles.detailActions}>
                            {record.status === 'draft' && (!business || !record.is_opening) && <>
                                <Button onClick={() => setEditing(true)}>编辑草稿</Button>
                                {payment && (business || record.requires_submission) ? <Button autoInsertSpace={false} type="primary" onClick={() => setRecordAction('submit', '提交', '提交后由另一位财务人员核对实际收付款。参考订单不会自动核销。')}>提交</Button>
                                    : <Button type="primary" icon={<CheckCircleOutlined />} onClick={() => setRecordAction('post', '确认生效', payment ? '请核对实际资金收付和账户。确认后生成会计凭证，资金金额锁定，可继续分配核销。' : '请核对往来单位、日期和费用明细。确认后生成会计凭证，账单金额锁定。')}>确认生效</Button>}
                                {!payment && <Button danger onClick={() => setRecordAction('cancel', '取消草稿', '取消后的草稿保留记录，不影响资金余额。')}>取消草稿</Button>}
                            </>}
                            {payment && ['draft', 'pending'].includes(record.status) && (!business || !record.is_opening) && (
                                <Button danger onClick={() => setRecordAction('cancel', '撤销收付款', '撤销后保留原记录和编号，撤销人、时间和原因记入修改历史。原收据作废，需要更正时请重新登记。')}>撤销收付款</Button>
                            )}
                            {payment && record.status === 'pending' && !business && <>
                                <Button type="primary" disabled={selfReview} onClick={() => setRecordAction('post', '确认收付款', '请核对实际资金收付和账户。确认后在本记录生成会计凭证，随后可独立核销。')}>确认收付款</Button>
                                <Button disabled={selfReview} onClick={() => setRecordAction('return', '退回修改', '退回为草稿，登记人修改后可重新提交；退回原因保留在历史中。')}>退回修改</Button>
                            </>}
                            {!business && record.status === 'posted' && available > 0 && (payment || (isCredit(record) && !record.order_managed)) && <Button icon={<SwapOutlined />} onClick={() => setAllocating(true)}>核销账单</Button>}
                            {!business && payment && record.partner_type === 'customer' && record.status === 'posted' && available > 0 && <Button type="primary" onClick={() => setAllocatingOrders(true)}>核销订单</Button>}
                            {!business && record.status === 'posted' && (payment || (!isCredit(record) && !record.order_managed)) && !record.reversed_by_id && <Button danger onClick={() => setRecordAction('reverse', payment ? '冲销收付款' : '冲销账单', payment ? '冲销会保留原资金记录并生成反向凭证。请先撤销此收付款的所有有效核销。' : '将生成等额贷项及反向凭证，抵扣原账单未结部分，原收付款保留。部分调减请另建贷项。')}>冲销</Button>}
                            {payment && <Button icon={<PrinterOutlined />} onClick={() => printFinancePayment(record.id, messageApi)}>打印</Button>}
                            <Button icon={<HistoryOutlined />} onClick={() => setHistory(true)}>修改历史</Button>
                        </div>
                        {payment && record.status === 'pending' && selfReview && !business && <Alert style={{ marginBottom: 16 }} type="info" message="不能审核本人登记的收付款，请由另一位财务人员处理。" />}
                        {business && record.is_opening && <Alert style={{ marginBottom: 16 }} type="info" message="期初余额请在财务工作台维护，不作为本期实际收付款登记。" />}
                        {payment && record.review_remark && <Alert style={{ marginBottom: 16 }} type="warning" message={`${record.status === 'draft' ? '退回原因' : '财务处理意见'}：${record.review_remark}`} />}
                        {payment && record.status === 'cancelled' && <Alert style={{ marginBottom: 16 }} type="warning" message={`收付款已撤销，原收据无效。撤销原因：${record.cancellation_reason || '请查看修改历史'}`} />}
                        <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }} items={[
                            { key: 'date', label: payment ? '资金日期' : '账单日期', children: payment ? record.payment_date : record.document_date },
                            { key: 'due', label: payment ? '资金账户' : '到期日', children: payment ? record.account_name : record.due_date || '—' },
                            { key: 'version', label: '版本', children: `V${record.version}` },
                            { key: 'allocated', label: '已核销', children: `¥ ${money(record.allocated_amount)}` },
                            { key: 'residual', label: payment ? '未分配余额' : '未结金额', children: record.status === 'posted' ? `¥ ${money(remaining)}` : '—' },
                            ...((payment || isCredit(record)) && record.status === 'posted' ? [{ key: 'available', label: '可核销余额', children: `¥ ${money(available)}` }] : []),
                            { key: 'creator', label: '登记人', children: record.created_by_name || '—' },
                            ...(payment ? [
                                { key: 'submitted', label: '提交时间', children: record.submitted_at || '—' },
                                { key: 'reviewer', label: '财务处理人', children: record.reviewed_by_name || '—' },
                                { key: 'reviewed', label: '财务处理时间', children: record.reviewed_at || '—' },
                                { key: 'references', label: '参考订单', span: 3, children: record.reference_orders?.length ? <Space wrap split="、">{record.reference_orders.map((row, index) => row.order_uid
                                    ? <Link key={row.order_uid} to={`/orders/${encodeURIComponent(row.order_uid)}`}>{row.order_number || row.order_uid}</Link>
                                    : <span key={index}>{row.order_number || '—'}</span>)}</Space> : '未指定（独立收付款）' },
                                { key: 'packingBoxes', label: '备注装箱单箱子', span: 3, children: record.reference_packing_boxes?.length ? <Space wrap split="、">{record.reference_packing_boxes.map((row, index) => {
                                    const label = `${row.list_number || row.packing_list_uid || '—'} / 箱 ${row.box_number ?? row.box_uid}`;
                                    return row.packing_list_uid ? <Link key={row.box_uid || index} to={`/packing-lists/${encodeURIComponent(row.packing_list_uid)}`}>{label}</Link> : <span key={row.box_uid || index}>{label}</span>;
                                })}</Space> : '未指定' },
                                ...(record.reference_packing_boxes?.length ? [{ key: 'packingOrders', label: '箱子当前所属订单', span: 3, children: record.packing_order_references?.length ? <Space wrap split="、">{record.packing_order_references.map((row, index) => row.order_uid
                                    ? <Link key={row.order_uid} to={`/orders/${encodeURIComponent(row.order_uid)}`}>{row.order_number || row.order_uid}</Link>
                                    : <span key={index}>{row.order_number || '—'}</span>)}</Space> : '尚无可核销订单' }] : []),
                            ] : []),
                        ]} />
                        {record.memo && <Typography.Paragraph style={{ marginTop: 16, marginBottom: 0 }}>备注：{record.memo}</Typography.Paragraph>}
                        {payment && record.unresolved_packing_boxes?.length > 0 && <Alert type="warning" showIcon style={{ marginTop: 16 }} message="部分备注箱子暂不能核销订单"
                            description={record.unresolved_packing_boxes.map(row => `${row.list_number} / 箱 ${row.box_number ?? row.box_uid}：${row.reason}`).join('；')} />}
                        {!payment && record.order_managed && <Alert style={{ marginTop: 16 }} type="info" showIcon message="此账单由订单报价生成。报价变更请在「订单应收」确认，收付款请通过「核销订单」办理；不能手工创建贷项或冲销此账单。" />}
                        {record.reversed_by_id && <Alert style={{ marginTop: 16 }} type="info" showIcon message={`已通过贷项冲销，关联贷项 #${record.reversed_by_id}`} />}
                    </div>
                    {!payment && <><Title level={5} className={styles.sectionTitle}>账单明细</Title><Table rowKey="id" size="small" pagination={false} dataSource={record.lines || []} scroll={{ x: 650 }} columns={[
                        { title: '费用说明', dataIndex: 'description', render: (value, row) => <>{value}{row.order_uid && <div><Link to={`/orders/${row.order_uid}`}>{row.order_number || '查看关联订单'}</Link></div>}</> }, { title: '数量', dataIndex: 'quantity', align: 'right' },
                        { title: '单价', dataIndex: 'unit_price', align: 'right', render: value => <Currency value={value} /> },
                        { title: '税率', dataIndex: 'tax_rate', align: 'right', render: value => `${Number(value || 0)}%` },
                        { title: '税额', dataIndex: 'tax_amount', align: 'right', render: value => <Currency value={value} /> },
                        { title: '含税金额', dataIndex: 'total_amount', align: 'right', render: value => <Currency value={value} strong /> },
                    ]} /></>}
                    {!business && <AllocationHistory params={payment ? { payment_id: recordId } : { document_id: recordId }} revision={revision}
                        title={!payment && isCredit(record) ? '退款核销记录' : '核销记录'}
                        onReverse={row => setAction({ entity: 'allocations', record: row, action: 'reverse', label: '撤销核销', description: '保留原核销记录，释放收付款或贷项余额，并恢复对应账单未结金额。' })} />}
                    {!payment && isCredit(record) && <AllocationHistory params={{ credit_document_id: recordId }} revision={revision} title="贷项抵扣记录"
                        onReverse={row => setAction({ entity: 'allocations', record: row, action: 'reverse', label: '撤销核销', description: '保留原核销记录，释放贷项余额并恢复对应账单未结金额。' })} />}
                </>}
            </Spin>
        </Drawer>
        {editing && (payment ? <PaymentEditor open payment={record} business={business} onClose={() => setEditing(false)} onSaved={refresh} /> : <DocumentEditor open document={record} onClose={() => setEditing(false)} onSaved={refresh} />)}
        {allocatingOrders && record && <OrderAllocationDialog payment={record} onClose={() => setAllocatingOrders(false)} onSuccess={refresh} />}
        {allocating && record && <AllocationDialog source={record} sourceType={entity} onClose={() => setAllocating(false)} onSuccess={refresh} />}
        <ActionDialog action={action} onClose={() => setAction(null)} onSuccess={refresh} />
        <FinanceHistoryDrawer open={history} onClose={() => setHistory(false)} historyUrl={`/${'finance/v2'}/${entity}/${recordId}/history`} title={`${record?.number || ''} 修改历史`} />
    </>;
}

export function FinanceDocuments({ initialFilter = {}, filterRevision = 0, onChanged }) {
    const [filters, setFilters] = useState({ open_only: 1, ...initialFilter });
    const [page, setPage] = useState(1);
    const [revision, setRevision] = useState(0);
    const [creating, setCreating] = useState(false);
    const [detailId, setDetailId] = useState(null);
    const initialRef = useRef(initialFilter);
    initialRef.current = initialFilter;
    useEffect(() => { if (filterRevision) { setFilters(initialRef.current); setPage(1); } }, [filterRevision]);
    const result = useFinanceData('/documents', { ...filters, p: page, s: 20 }, revision);
    const data = result.data || emptyList;
    const change = patch => { setFilters(prev => ({ ...prev, ...patch })); setPage(1); };
    const refresh = () => { setRevision(value => value + 1); onChanged?.(); };
    return <>
        <div className={styles.toolbar}><div className={styles.toolbarFilters}>
            <Input.Search key={filterRevision} className={styles.search} placeholder="账单号 / 往来单位 / 参考号" allowClear onSearch={q => change({ q })} />
            <Select aria-label="账单类型筛选" value={filters.document_type} allowClear placeholder="全部账单类型" style={{ width: 160 }} options={DOCUMENT_OPTIONS} onChange={document_type => change({ document_type })} />
            <Select aria-label="账单范围" style={{ width: 145 }} value={filters.overdue ? 'overdue' : filters.open_only ? 'open' : filters.status || 'all'} onChange={value => change({ open_only: value === 'open' ? 1 : undefined, overdue: value === 'overdue' ? 1 : undefined, status: ['draft', 'posted', 'cancelled'].includes(value) ? value : undefined })} options={[{ value: 'open', label: '全部未结' }, { value: 'overdue', label: '已逾期未结' }, { value: 'all', label: '全部账单' }, ...STATUS_OPTIONS]} />
            {filters.partner_id && <Space size={4}><Text type="secondary">{data.items?.[0]?.partner_name || '指定往来单位'}</Text><Button type="link" size="small" onClick={() => change({ partner_id: undefined, partner_type: undefined })}>清除</Button></Space>}
            <Button icon={<ReloadOutlined />} aria-label="刷新账单" onClick={refresh} />
        </div><Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>新建账单</Button></div>
        <ErrorNotice error={result.error} retry={result.reload} />
        <Panel><Table size="small" className={styles.table} rowKey="id" loading={result.loading} dataSource={data.items} scroll={{ x: 1090 }}
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前条件下没有账单" /> }}
            columns={[
                { title: '账单', dataIndex: 'number', width: 200, render: (value, row) => <><Button className={styles.recordLink} type="link" onClick={() => setDetailId(row.id)}>{value}</Button><div><Text type="secondary">{FINANCE_DOCUMENT_TYPES[row.document_type]?.label}</Text></div></> },
                { title: '往来单位', dataIndex: 'partner_name', width: 180 },
                { title: '账单日期', dataIndex: 'document_date', width: 110 },
                { title: '到期日', dataIndex: 'due_date', width: 115, render: (value, row) => <><Text type={isOverdue(row) ? 'danger' : undefined}>{value || '—'}</Text>{isOverdue(row) && <div><Text type="secondary">已逾期</Text></div>}</> },
                { title: '含税金额 / CNY', dataIndex: 'total_amount', align: 'right', width: 145, render: value => <Currency value={value} /> },
                { title: '未结 / CNY', dataIndex: 'residual_amount', align: 'right', width: 130, render: (value, row) => row.status === 'draft' || row.status === 'cancelled' ? <Text type="secondary">—</Text> : <Currency value={value} strong /> },
                { title: '状态', dataIndex: 'status', width: 115, render: (value, row) => <><StatusTag status={value} />{value === 'posted' && <div><Text type="secondary">{FINANCE_STATUS[row.payment_status]?.label || row.payment_status}</Text></div>}</> },
                { title: '', key: 'action', fixed: 'right', width: 70, render: (_, row) => <Button type="link" onClick={() => setDetailId(row.id)}>详情</Button> },
            ]}
            pagination={{ current: page, pageSize: 20, total: data.total, showSizeChanger: false, showTotal: total => `共 ${total} 份账单`, onChange: setPage }} />
        </Panel>
        <p className={styles.footnote}>未结范围包含所有日期的已生效账单。草稿不计入往来余额，贷项用于调减原账单或办理退款。</p>
        {creating && <DocumentEditor open initialType={filters.document_type || 'customer_invoice'} onClose={() => setCreating(false)} onSaved={saved => { refresh(); setDetailId(saved.id); }} />}
        {detailId && <RecordDetail entity="documents" recordId={detailId} onClose={() => setDetailId(null)} onChanged={refresh} />}
    </>;
}

export function FinancePayments({ onChanged, initialFilter = {}, filterRevision = 0, business = false, initialContext, navigationToken, initialPaymentId, onDetailClose }) {
    const [filters, setFilters] = useState(initialFilter);
    const [page, setPage] = useState(1);
    const [revision, setRevision] = useState(0);
    const [creating, setCreating] = useState(null);
    const [detailId, setDetailId] = useState(null);
    const initialRef = useRef(initialFilter);
    initialRef.current = initialFilter;
    useEffect(() => { if (filterRevision) { setFilters(initialRef.current); setPage(1); } }, [filterRevision]);
    const contextRef = useRef(initialContext);
    contextRef.current = initialContext;
    const previousPaymentLink = useRef(null);
    const closingPaymentLink = useRef(false);
    useEffect(() => {
        const previouslyLinked = previousPaymentLink.current;
        previousPaymentLink.current = initialPaymentId;
        if (initialPaymentId) {
            closingPaymentLink.current = false;
            setCreating(null);
            setDetailId(initialPaymentId);
            return;
        }
        if (previouslyLinked) setDetailId(null);
        // Removing the consumed deep link preserves navigation state without reopening its old creation context.
        if (closingPaymentLink.current) { closingPaymentLink.current = false; return; }
        if (business && contextRef.current) setCreating('incoming');
    }, [business, navigationToken, initialPaymentId]);
    const result = useFinanceData('/payments', { ...filters, ...(business ? { partner_type: 'customer' } : {}), p: page, s: 20 }, revision);
    const data = result.data || emptyList;
    const refresh = () => { setRevision(value => value + 1); onChanged?.(); };
    const change = patch => { setFilters(prev => ({ ...prev, ...patch })); setPage(1); };
    const closeDetail = () => {
        setDetailId(null);
        if (initialPaymentId && onDetailClose) {
            closingPaymentLink.current = true;
            onDetailClose();
        }
    };
    return <>
        <div className={styles.toolbar}><div className={styles.toolbarFilters}>
            <Input.Search key={filterRevision} className={styles.search} placeholder="收付款单号 / 往来单位" allowClear onSearch={q => change({ q })} />
            <Select aria-label="资金方向筛选" allowClear placeholder="全部方向" style={{ width: 120 }} value={filters.direction} options={[{ value: 'incoming', label: '收款' }, { value: 'outgoing', label: '付款' }]} onChange={direction => change({ direction })} />
            <Select aria-label="收付款状态筛选" allowClear placeholder="全部状态" style={{ width: 125 }} value={filters.open_only ? 'open' : filters.status} options={[{ value: 'open', label: '有未分配余额' }, ...STATUS_OPTIONS, { value: 'pending', label: '待财务确认' }, { value: 'reversed', label: '已冲销' }]} onChange={status => change({ status: status === 'open' ? undefined : status, open_only: status === 'open' ? 1 : undefined })} />
            <Button icon={<ReloadOutlined />} aria-label="刷新收付款" onClick={refresh} />
        </div><Space><Button icon={<ArrowUpOutlined />} onClick={() => setCreating('outgoing')}>登记付款</Button><Button type="primary" icon={<ArrowDownOutlined />} onClick={() => setCreating('incoming')}>登记收款</Button></Space></div>
        <ErrorNotice error={result.error} retry={result.reload} />
        <Panel><Table size="small" className={styles.table} rowKey="id" loading={result.loading} dataSource={data.items} scroll={{ x: 1050 }} locale={{ emptyText: '暂无收付款记录' }} columns={[
            { title: '收付款单', dataIndex: 'number', width: 200, render: (value, row) => <Button type="link" className={styles.number} style={{ padding: 0 }} onClick={() => setDetailId(row.id)}>{value}</Button> },
            { title: '资金方向', dataIndex: 'direction', width: 95, render: value => value === 'incoming' ? '收款' : '付款' },
            { title: '往来单位', dataIndex: 'partner_name', width: 170 },
            { title: '资金日期', dataIndex: 'payment_date', width: 115 },
            { title: '账户', dataIndex: 'account_name', width: 140 },
            { title: '登记人', dataIndex: 'created_by_name', width: 110 },
            { title: '金额 / CNY', dataIndex: 'amount', align: 'right', width: 130, render: value => <Currency value={value} strong /> },
            { title: '未分配 / CNY', dataIndex: 'unallocated_amount', align: 'right', width: 140, render: (value, row) => row.status === 'posted' ? <Currency value={value} /> : '—' },
            { title: '状态', dataIndex: 'status', width: 100, render: value => <StatusTag status={value} /> },
            { title: '', width: 70, fixed: 'right', render: (_, row) => <Button type="link" onClick={() => setDetailId(row.id)}>详情</Button> },
        ]} pagination={{ current: page, pageSize: 20, total: data.total, showSizeChanger: false, showTotal: total => `共 ${total} 笔收付款`, onChange: setPage }} /></Panel>
        <p className={styles.footnote}>{business ? '参考订单仅作备注。草稿提交财务确认后，由财务独立核销；预收可不关联订单。' : '业务提交与财务办理使用同一收付款记录。确认资金后，可按账单或重新选择订单进行部分、多笔核销。'}</p>
        {creating && <PaymentEditor open direction={creating} business={business} initialContext={initialContext} onClose={() => setCreating(null)} onSaved={saved => { refresh(); setDetailId(saved.id); }} />}
        {detailId && <RecordDetail key={`${detailId}:${navigationToken || ''}`} entity="payments" recordId={detailId} business={business} onClose={closeDetail} onChanged={refresh} />}
    </>;
}

function MasterEditor({ kind, record, open, onClose, onSaved }) {
    const [form] = Form.useForm();
    const [saving, setSaving] = useState(false);
    const savingRef = useRef(false);
    const keyRef = useRef(mutationKey());
    const [error, setError] = useState('');
    const vendor = kind === 'vendors';
    useEffect(() => {
        if (open) { setError(''); form.resetFields(); keyRef.current = mutationKey(); form.setFieldsValue(record || { active: true, currency: 'CNY', account_type: 'bank' }); }
    }, [form, open, record]);
    const save = async () => {
        if (savingRef.current) return;
        try {
            const values = await form.validateFields();
            savingRef.current = true; setSaving(true); setError('');
            await financeRequest(`/${kind}${record ? `/${record.id}` : ''}`, {
                method: record ? 'PATCH' : 'POST', body: {
                    ...values, ...(!vendor ? { currency: 'CNY' } : {}), ...(record ? { version: record.version } : { idempotency_key: keyRef.current }),
                }
            });
            onSaved(); onClose();
        } catch (err) { if (!err.errorFields) setError(err.message); }
        finally { savingRef.current = false; setSaving(false); }
    };
    return <Modal title={`${record ? '编辑' : '新增'}${vendor ? '供应商' : '资金账户'}`} open={open} onOk={save} onCancel={() => { if (!saving) onClose(); }}
        okText="保存" confirmLoading={saving} maskClosable={!saving} closable={!saving} keyboard={!saving} cancelButtonProps={{ disabled: saving }} destroyOnHidden>
        <ErrorNotice error={error} />
        <Form form={form} layout="vertical" disabled={saving} preserve={false}>
            <Form.Item name="name" label={vendor ? '供应商名称' : '账户名称'} rules={[{ required: true, whitespace: true, message: '请填写名称' }]}><Input maxLength={200} /></Form.Item>
            {vendor ? <div className={styles.formGrid}>
                <Form.Item name="contact" label="联系人"><Input maxLength={100} /></Form.Item>
                <Form.Item name="phone" label="联系电话"><Input maxLength={50} /></Form.Item>
            </div> : <>
                <Form.Item name="account_type" label="账户类型" rules={required('账户类型')}><Select options={[{ value: 'bank', label: '银行账户' }, { value: 'cash', label: '现金账户' }, { value: 'other', label: '其他资金账户' }]} /></Form.Item>
                <Form.Item name="account_number" label="账号"><Input maxLength={200} /></Form.Item>
                <Typography.Paragraph type="secondary">本位币为 CNY。期初余额通过总账期初凭证录入，资金流水按实际收付形成余额。</Typography.Paragraph>
            </>}
            <Form.Item name="memo" label="备注"><Input.TextArea rows={2} maxLength={2000} /></Form.Item>
            <Form.Item name="active" label="启用" valuePropName="checked"><Switch /></Form.Item>
        </Form>
    </Modal>;
}

export function FinanceSettings() {
    const [kind, setKind] = useState('accounts');
    const [page, setPage] = useState(1);
    const [query, setQuery] = useState('');
    const [revision, setRevision] = useState(0);
    const [editing, setEditing] = useState(undefined);
    const [history, setHistory] = useState(null);
    const result = useFinanceData(`/${kind}`, { p: page, s: 20, q: query }, revision);
    const vendor = kind === 'vendors';
    return <>
        <div className={styles.toolbar}><div className={styles.toolbarFilters}>
            <Select aria-label="基础资料类型" value={kind} style={{ width: 150 }} onChange={value => { setKind(value); setPage(1); setQuery(''); }} options={[{ value: 'accounts', label: '资金账户' }, { value: 'vendors', label: '供应商' }]} />
            <Input.Search key={kind} allowClear placeholder={vendor ? '搜索供应商' : '搜索账户'} className={styles.search} onSearch={value => { setQuery(value); setPage(1); }} />
        </div><Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing(null)}>{vendor ? '新增供应商' : '新增资金账户'}</Button></div>
        <ErrorNotice error={result.error} retry={result.reload} />
        <Panel><Table size="small" rowKey="id" className={styles.table} loading={result.loading} dataSource={result.data?.items || []} scroll={{ x: 750 }}
            columns={[
                { title: vendor ? '供应商' : '账户名称', dataIndex: 'name', width: 210, render: value => <Text strong>{value}</Text> },
                ...(vendor ? [
                    { title: '联系人', dataIndex: 'contact', render: value => value || '—' },
                    { title: '联系电话', dataIndex: 'phone', render: value => value || '—' },
                ] : [
                    { title: '类型', dataIndex: 'account_type', render: value => ({ bank: '银行', cash: '现金', other: '其他' }[value] || value) },
                    { title: '账号', dataIndex: 'account_number', render: value => value || '—' },
                    { title: '余额 / CNY', dataIndex: 'balance', align: 'right', render: value => <Currency value={value} strong /> },
                ]),
                { title: '状态', dataIndex: 'active', width: 90, render: value => <Text type={value ? undefined : 'secondary'}>{value ? '启用' : '停用'}</Text> },
                { title: '操作', width: 155, render: (_, row) => <Space><Button size="small" type="link" onClick={() => setEditing(row)}>编辑</Button><Button size="small" type="link" onClick={() => setHistory(row)}>历史</Button></Space> },
            ]}
            pagination={{ current: page, pageSize: 20, total: result.data?.total || 0, showSizeChanger: false, onChange: setPage }} /></Panel>
        <p className={styles.footnote}>{vendor ? '客户资料沿用现有客户管理；供应商单独维护。停用后的往来记录仍保留。' : '资金账户记录实际收付。已产生业务的账户保留历史，不可通过修改账户直接调整余额。'}</p>
        {editing !== undefined && <MasterEditor kind={kind} record={editing} open onClose={() => setEditing(undefined)} onSaved={() => setRevision(value => value + 1)} />}
        <FinanceHistoryDrawer open={Boolean(history)} onClose={() => setHistory(null)} historyUrl={`/finance/v2/${kind}/${history?.id}/history`} title={`${history?.name || ''} 修改历史`} />
    </>;
}

function AgingPanel({ revision }) {
    const [partnerType, setPartnerType] = useState('customer');
    const [asOf, setAsOf] = useState(dayjs());
    const result = useFinanceData('/aging', { partner_type: partnerType, as_of: asOf.format('YYYY-MM-DD') }, revision);
    const columns = [
        { title: '往来单位', dataIndex: 'partner_name', width: 160 },
        { title: '未到期', dataIndex: 'current' }, { title: '逾期 1–30 天', dataIndex: 'days_1_30' },
        { title: '31–60 天', dataIndex: 'days_31_60' }, { title: '61–90 天', dataIndex: 'days_61_90' },
        { title: '90 天以上', dataIndex: 'days_over_90' }, { title: '合计', dataIndex: 'total' },
    ].map((column, index) => index ? { ...column, align: 'right', width: 125, render: value => <Currency value={value} strong={index === 6} /> } : column);
    return <Panel title="往来账龄" extra={<Space wrap><Select aria-label="账龄类型" value={partnerType} onChange={setPartnerType} style={{ width: 130 }} options={[{ value: 'customer', label: '客户应收' }, { value: 'vendor', label: '供应商应付' }]} /><DatePicker aria-label="账龄截止日期" value={asOf} allowClear={false} onChange={setAsOf} /></Space>}>
        <div className={styles.panelBody}><ErrorNotice error={result.error} retry={result.reload} />
            <Table className={styles.table} size="small" rowKey="partner_id" loading={result.loading} dataSource={result.data?.items || []} columns={columns} scroll={{ x: 950 }} pagination={{ pageSize: 10, showSizeChanger: false }} locale={{ emptyText: '截至所选日期没有未结余额' }}
                summary={() => result.data?.totals && <Table.Summary.Row><Table.Summary.Cell index={0}><Text strong>合计 / CNY</Text></Table.Summary.Cell>{columns.slice(1).map((column, index) => <Table.Summary.Cell key={column.dataIndex} index={index + 1} align="right"><Currency value={result.data.totals[column.dataIndex]} strong /></Table.Summary.Cell>)}</Table.Summary.Row>} />
        </div>
    </Panel>;
}

function FinanceOverview({ revision, onDocuments, onPayments, onCreate, onOpenLegacy, onOpenDocument }) {
    const screens = Grid.useBreakpoint();
    const result = useFinanceData('/dashboard', {}, revision);
    const data = result.data;
    const tasks = [
        { key: 'legacy', label: '旧订单待核对', count: data?.legacy_reconciliation_required ?? '—', action: '核对差异', onClick: onOpenLegacy },
        { key: 'documents', label: '待确认账单', count: data?.draft_documents ?? '—', action: '查看', onClick: () => onDocuments({ status: 'draft' }) },
        { key: 'payments', label: '待确认收付款', count: data?.pending_payments ?? '—', action: '查看', onClick: () => onPayments({ status: 'pending' }) },
        { key: 'payables', label: '逾期应付', amount: data?.overdue_payable, action: '查看', onClick: () => onDocuments({ document_type: 'vendor_bill', overdue: 1 }) },
        { key: 'receivables', label: '逾期应收', amount: data?.overdue_receivable, action: '查看账单', onClick: () => onDocuments({ document_type: 'customer_invoice', overdue: 1 }) },
    ];
    return <>
        <ErrorNotice error={result.error} retry={result.reload} />
        <Spin spinning={result.loading}>
            <Card size="small" className={styles.panel}>
                <Row gutter={[24, 16]}>
                    {[
                        ['应收余额', 'receivable'], ['应付余额', 'payable'],
                        ['资金账户余额', 'account_balance'], ['逾期应收', 'overdue_receivable'],
                    ].map(([label, field]) => <Col xs={12} lg={6} key={field}>
                        <Statistic title={label} value={data?.[field] ?? '—'} precision={2} />
                    </Col>)}
                </Row>
            </Card>
            <Row gutter={[16, 0]}>
                <Col xs={24} xl={16}>
                    <Panel title="最近账单" extra={<Space size={8}><Button size="small" type="text" onClick={() => onDocuments({})}>全部账单</Button><Button size="small" type="primary" icon={<PlusOutlined />} onClick={onCreate}>新建账单</Button></Space>}>
                        <Table size="small" rowKey="id" dataSource={data?.recent_documents || []} pagination={false}
                            scroll={{ x: screens.md ? 620 : 480 }} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无账单" /> }} columns={[
                                { title: '账单', dataIndex: 'number', width: 200, render: (value, row) => <><Button type="link" className={styles.recordLink} onClick={() => onOpenDocument(row.id)}>{value}</Button><div><Text type="secondary">{screens.md ? FINANCE_DOCUMENT_TYPES[row.document_type]?.label || row.document_type : row.partner_name}</Text></div></> },
                                { title: '往来单位', dataIndex: 'partner_name', width: 160, responsive: ['md'] },
                                { title: '金额（元）', dataIndex: 'total_amount', align: 'right', width: 130, render: value => <Currency value={value} /> },
                                { title: '状态', dataIndex: 'status', width: 90, render: value => <StatusTag status={value} /> },
                            ]} />
                    </Panel>
                </Col>
                <Col xs={24} xl={8}>
                    <Panel title="待处理">
                        <List size="small" dataSource={tasks} renderItem={item => <List.Item className={styles.todo}
                            actions={[<Button key="action" type="link" size="small" onClick={item.onClick}>{item.action}</Button>]}>
                            <Text>{item.label}</Text>
                            {item.count !== undefined ? <Text strong>{item.count}</Text> : <Currency value={item.amount} />}
                        </List.Item>} />
                    </Panel>
                    <Panel title="未分配余额" extra={<Button type="link" size="small" onClick={() => onPayments({ open_only: 1 })}>办理核销</Button>}>
                        <List size="small" dataSource={[
                            ['客户预收', 'customer_advances'], ['供应商预付', 'vendor_prepayments'],
                            ['客户贷项', 'customer_credit'], ['供应商贷项', 'vendor_credit'],
                        ]} renderItem={([label, field]) => <List.Item><Text>{label}</Text><Currency value={data?.[field]} /></List.Item>} />
                    </Panel>
                </Col>
            </Row>
        </Spin>
        <AgingPanel revision={revision} />
        <Typography.Paragraph type="secondary" className={styles.footnote}>以上为已进入财务账簿的单据；当前报价变化见“订单应收”，旧收款记录见“历史收款清理”。</Typography.Paragraph>
    </>;
}

export default function FinanceWorkspace({ extraTabs = [], activeTab: selectedTab, onTabChange }) {
    const [localTab, setLocalTab] = useState('overview');
    const activeTab = selectedTab ?? localTab;
    const setActiveTab = key => { setLocalTab(key); onTabChange?.(key); };
    const [accountingTab, setAccountingTab] = useState('periods');
    const [accountingSectionToken, setAccountingSectionToken] = useState(0);
    const [revision, setRevision] = useState(0);
    const [filterRevision, setFilterRevision] = useState(0);
    const [documentFilter, setDocumentFilter] = useState({ open_only: 1 });
    const [paymentFilter, setPaymentFilter] = useState({});
    const [paymentFilterRevision, setPaymentFilterRevision] = useState(0);
    const [creating, setCreating] = useState(false);
    const [overviewRecordId, setOverviewRecordId] = useState(null);
    const [messageApi, contextHolder] = message.useMessage();
    const refresh = useCallback(() => setRevision(value => value + 1), []);
    const openDocuments = filter => { setDocumentFilter(filter); setFilterRevision(value => value + 1); setActiveTab('documents'); };
    const openLegacy = () => { setAccountingTab('migration'); setAccountingSectionToken(value => value + 1); setActiveTab('accounting'); };
    const openPayments = filter => { setPaymentFilter(filter); setPaymentFilterRevision(value => value + 1); setActiveTab('payments'); };
    return <div className={styles.workspace}>
        {contextHolder}
        <div className={styles.pageHeader}>
            <Title level={4} className={styles.title}>财务</Title>
            <Space><Text type="secondary">人民币 · CNY</Text>{activeTab === 'overview' && <Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button>}</Space>
        </div>
        <Tabs size="small" tabBarGutter={24} className={styles.tabs} activeKey={activeTab} onChange={setActiveTab} items={[
            { key: 'overview', label: '总览', children: <FinanceOverview revision={revision} onDocuments={openDocuments} onPayments={openPayments} onOpenLegacy={openLegacy} onCreate={() => setCreating(true)} onOpenDocument={setOverviewRecordId} /> },
            { key: 'documents', label: '账单', children: <FinanceDocuments initialFilter={documentFilter} filterRevision={filterRevision} onChanged={refresh} /> },
            { key: 'payments', label: '收付款', children: <FinancePayments onChanged={refresh} initialFilter={paymentFilter} filterRevision={paymentFilterRevision} /> },
            { key: 'statements', label: '往来对账', children: <FinancePartnerStatement /> },
            { key: 'accounting', label: '会计与月结', children: <FinanceAccounting initialTab={accountingTab} sectionToken={accountingSectionToken} onOpenLedger={({ partnerId }) => openDocuments({ partner_type: 'customer', partner_id: partnerId })} /> },
            ...extraTabs,
            { key: 'settings', label: '基础资料', children: <FinanceSettings /> },
        ]} />
        {creating && <DocumentEditor open onClose={() => setCreating(false)} onSaved={() => { refresh(); messageApi.success('账单草稿已保存'); openDocuments({ status: 'draft' }); }} />}
        {overviewRecordId && <RecordDetail entity="documents" recordId={overviewRecordId} onClose={() => setOverviewRecordId(null)} onChanged={refresh} />}
    </div>;
}
