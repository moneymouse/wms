import React, { useEffect, useState } from 'react';
import { Alert, Button, Collapse, Divider, Drawer, Empty, Pagination, Spin, Table, Typography } from 'antd';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import { ROLE_LABEL_MAP } from '../common/roleConfig';
import styles from './FinanceHistoryDrawer.module.css';

const { Text } = Typography;
export const AUDIT_EVENT_LABELS = { transportation_cost: '渠道成本', order_quote: '订单报价', order_receipt_revision: '订单业务修订', payment_receipt: '收款单', sales_bonus_rate: '跟单奖金费率', supplier_export: '供应商导出', finance_document: '财务账单', finance_payment: '收付款', finance_period: '会计期间', finance_journal: '会计凭证', bonus_item: '奖金项目', bonus_allocation: '奖金分配' };
export const AUDIT_ACTION_LABELS = { create: '创建', update: '修改', archive: '停用 / 归档', post: '确认入账', cancel: '作废', reverse: '冲销', allocate: '核销', unallocate: '撤销核销', close: '关账', reopen: '重开期间', quote_submit: '提交报价', quote_adopt: '采纳报价', quote_approve: '通过报价', quote_reject: '驳回报价', receipt_create: '创建收款单', receipt_approve: '通过收款单', receipt_reject: '驳回收款单', order_unlock: '解锁订单', order_relock: '重新锁定订单', export_blocked_invalid_quote: '因报价无效阻止导出' };
Object.assign(AUDIT_EVENT_LABELS, { finance_accounting: '会计与月结', finance_allocation: '核销', finance_vendor: '供应商资料', finance_account: '资金账户' });
Object.assign(AUDIT_EVENT_LABELS, { finance_legacy_link: '旧订单接入' });
Object.assign(AUDIT_EVENT_LABELS, { finance_order_settlement: '订单应收结算' });
Object.assign(AUDIT_ACTION_LABELS, { order_receivable_sync: '同步订单应收', submit: '提交审核', return: '退回修改' });
Object.assign(AUDIT_ACTION_LABELS, { settings_configure: '建账设置', opening_confirm: '确认期初', account_create: '创建会计科目', journal_create: '创建凭证', journal_post: '凭证过账', journal_cancel: '作废凭证', journal_reverse: '冲销凭证', period_create: '创建会计期间', period_close: '关闭会计期间', period_reopen: '重开会计期间', bank_import: '导入银行流水', bank_match: '银行流水匹配', bank_unmatch: '撤销银行匹配' });
Object.assign(AUDIT_ACTION_LABELS, { revenue_recognize: '确认履约收入', revenue_reverse: '撤销收入确认' });
Object.assign(AUDIT_ACTION_LABELS, { legacy_import: '导入旧账净余额', legacy_reconcile: '核对旧账变化' });
Object.assign(AUDIT_ACTION_LABELS, { legacy_revoke: '撤销旧账接入', legacy_reimport: '重新接入旧账' });
const FIELD_LABELS = { id: '编号', number: '单号', document_no: '账单号', receipt_no: '收款单号', kind: '类型', document_type: '账单类型', status: '状态', customer_id: '客户编号', customer_name: '客户', partner_name: '往来单位', partner_id: '往来单位编号', supplier_name: '供应商', currency: '币种', amount: '金额', total_amount: '合计金额', paid_amount: '已付金额', remaining_amount: '剩余金额', balance: '余额', date: '业务日期', document_date: '账单日期', due_date: '到期日', receipt_date: '收款日期', payment_method: '支付方式', settlement_status: '结清状态', items: '明细', lines: '账单明细', description: '项目说明', quantity: '数量', unit_price: '单价', price: '价格', account_code: '科目代码', debit: '借方', credit: '贷方', remark: '备注', reason: '变更原因', review_remark: '审核意见', reviewer_id: '审核人编号', reviewer_name: '审核人', creator_id: '创建人编号', creator_name: '创建人', review_date: '审核时间', create_date: '创建时间', update_date: '更新时间', order_uid: '订单 UID', order_id: '订单号', adjustment_id: '差价单编号', receivable_snapshot: '应收快照', received_before: '此前已收', remaining_after: '剩余应收', settlement_difference: '结清减免', preview_settlement_difference: '预计结清减免', archive: '归档', transportation_name: '渠道', order_transportation: '订单渠道', min_price: '最低售价', channel_cost: '渠道成本', cost: '成本', surcharge: '附加费', quoted_price: '报价', weight_snapshot: '重量快照', billing_weight_snapshot: '计费重量', receivable_amount: '应收金额', is_final: '当前生效', version_no: '版本', effective_date: '生效时间', effective_from: '生效日期', quote_remark: '报价备注', quoter_id: '报价人编号', quoter_name: '报价人', rate_per_kg: '每公斤费率', base_amount: '奖金基数', worker_count_rule: '人数规则', weight_min: '最低重量', weight_max: '最高重量', bonus_item_id: '奖金项目编号', worker_ids: '操作员编号', bonus_assigned: '已分配奖金', is_active: '已启用', label: '名称', name: '名称', channel_group: '渠道分组' };
const VALUE_LABELS = { pending: '待审核', approved: '已通过', rejected: '已驳回', draft: '草稿', posted: '已入账', cancelled: '已作废', canceled: '已作废', reversed: '已冲销', settled: '已结清', unsettled: '未结清', adopted: '已采纳', bank_transfer: '银行转账', cash: '现金', wechat: '微信', alipay: '支付宝', other: '其他', customer_invoice: '客户账单', vendor_bill: '供应商账单', customer_credit: '客户贷项', vendor_credit: '供应商贷项' };
Object.assign(FIELD_LABELS, { subtotal: '未税金额', tax_amount: '税额', tax_rate: '税率', residual_amount: '待核销金额', allocated_amount: '已核销金额', document_number: '账单号', document_id: '账单编号', payment_id: '收付款编号', payment_date: '收付款日期', account_id: '资金账户编号', account_name: '资金账户', account_type: '账户类型', account_number: '账号', partner_type: '往来类型', direction: '收付方向', reference: '外部参考号', memo: '摘要', version: '版本', sequence: '行号', order_number: '订单号', active: '已启用', created_at: '创建时间', created_by_id: '创建人编号', created_by_name: '创建人', updated_at: '更新时间', posted_at: '生效时间', cancelled_at: '作废时间', cancellation_reason: '作废原因', reversed_at: '冲销时间', reversal_date: '冲销日期', reversal_reason: '冲销原因', original_document_id: '原账单编号', reversed_by_id: '冲销贷项编号', allocation_date: '核销日期', credit_document_id: '贷项编号', entry_date: '凭证日期', source_type: '来源类型', source_id: '来源编号', source_action: '来源动作', reversal_of_id: '原凭证编号', cashflow_activity: '现金流类别', total_debit: '借方合计', total_credit: '贷方合计', fund_account_id: '资金账户编号', company_name: '公司名称', revenue_policy: '收入确认方式', opening_date: '建账日期', opening_confirmed: '期初已确认', configured: '已建账', date_from: '期间开始', date_to: '期间结束', closed_at: '关账时间', closed_by: '关账人', transaction_date: '银行交易日期', matched_at: '匹配时间', code: '科目代码', system: '系统科目' });
Object.assign(VALUE_LABELS, { incoming: '收款', outgoing: '付款', customer: '客户', vendor: '供应商', bank: '银行', open: '开放', closed: '已关闭', matched: '已匹配', unmatched: '未匹配', invoice: '账单确认收入', deferred: '履约后确认收入', operating: '经营活动', investing: '投资活动', financing: '筹资活动', transfer: '内部调拨', opening: '期初', manual: '手工凭证', document: '账单凭证', payment: '资金凭证', reversal: '冲销凭证', asset: '资产', liability: '负债', equity: '权益', revenue: '收入', expense: '费用' });
Object.assign(FIELD_LABELS, { deferred_amount: '待履约金额', recognized_amount: '已确认收入', is_opening: '期初账单' });
Object.assign(FIELD_LABELS, { import_kind: '接入类型', cutoff_date: '切换日期', imported_at: '接入时间', last_reconciled_at: '上次核对时间', baseline: '核对基线', current_preview: '当前来源', source: '来源', received_amount: '已审收款', signed_balance: '净余额', drift: '来源已变化', evidence: '处理依据', effect_amount: '处理金额', snapshot: '凭据快照', delta: '变化金额' });
Object.assign(FIELD_LABELS, { payment_status: '核销状态' });
Object.assign(FIELD_LABELS, {
    reference_orders: '备注订单', reference_order_uids: '备注订单编号',
    reference_packing_boxes: '备注装箱单箱子', reference_box_uids: '备注箱子编号',
    packing_order_references: '箱子当前所属订单', packing_order_uids: '箱子当前所属订单编号',
    unresolved_packing_boxes: '暂不能核销的备注箱子', packing_list_uid: '装箱单编号',
    list_number: '装箱单唛头', box_uid: '箱子编号', box_uids: '箱子编号', box_number: '箱号',
    transfer_id: '原单号', target_order_uid: '箱子所属订单', item_name: '品名', weight: '重量',
    reviewer: '审核人', submitted_at: '提交时间', submitted_by_id: '提交人编号', submitted_by_name: '提交人',
    reviewed_at: '审核时间', reviewed_by_id: '审核人编号', reviewed_by_name: '审核人', requires_submission: '需要提交审核',
    unallocated_amount: '未核销金额', available_amount: '可用金额', payment_number: '收付款单号',
    legacy_settled_amount: '旧账已结算金额', receivable_balance: '待收余额', refundable_amount: '可退金额',
    sync_delta: '应收同步差额', can_allocate: '可核销', blockers: '待处理事项', documents: '关联账单', source_hash: '来源校验值',
});
Object.assign(VALUE_LABELS, { unpaid: '未结清', partial: '部分结清', paid: '已结清' });
export const auditFieldLabel = path => String(path || '').split('.').map(part => {
    const [, name, suffix] = part.match(/^([^[]+)(.*)$/) || ['', part, ''];
    return `${FIELD_LABELS[name] || name}${suffix || ''}`;
}).join(' · ');
const display = value => {
    if (value === null || value === undefined || value === '') return '—';
    if (typeof value === 'boolean') return value ? '是' : '否';
    if (Array.isArray(value)) return value.map(display).join('、') || '—';
    if (typeof value === 'object') return Object.entries(value).map(([key, val]) => `${FIELD_LABELS[key] || key}：${display(val)}`).join('；');
    return VALUE_LABELS[value] || String(value);
};
const fallbackChanges = record => [...new Set([...Object.keys(record.before_data || {}), ...Object.keys(record.after_data || {})])].filter(key => JSON.stringify(record.before_data?.[key]) !== JSON.stringify(record.after_data?.[key])).map(field => ({ field, before: record.before_data?.[field], after: record.after_data?.[field] }));

const SYSTEM_FIELDS = new Set(['id', 'created_at', 'updated_at', 'created_by_id']);
const isSystemChange = change => SYSTEM_FIELDS.has(String(change.field));

function ChangesTable({ changes }) {
    return <Table size="small" bordered tableLayout="fixed" pagination={false} rowKey="field" dataSource={changes} columns={[
            { title: '变更字段', dataIndex: 'field', render: auditFieldLabel, width: '28%' },
            { title: '修改前', dataIndex: 'before', render: value => <Text type="secondary" className={`${styles.value} ${isNumeric(value) ? styles.numericValue : ''}`}>{display(value)}</Text> },
            { title: '修改后', dataIndex: 'after', render: value => <Text className={`${styles.value} ${isNumeric(value) ? styles.numericValue : ''}`}>{display(value)}</Text> },
        ]} />;
}

export function AuditChanges({ record }) {
    const changes = record.changes || fallbackChanges(record);
    const businessChanges = changes.filter(change => !isSystemChange(change));
    const systemChanges = changes.filter(isSystemChange);
    const details = [];
    if (systemChanges.length) details.push({ key: 'system', label: <Text type="secondary">系统字段（{systemChanges.length} 项）</Text>, children: <ChangesTable changes={systemChanges} /> });
    details.push({ key: 'raw', label: <Text type="secondary">原始记录（JSON）</Text>, children: <pre className={styles.raw}>{JSON.stringify({ before: record.before_data, after: record.after_data, metadata: record.metadata }, null, 2)}</pre> });
    return <div className={styles.changes}>
        {businessChanges.length ? <ChangesTable changes={businessChanges} /> : <Text type="secondary">{systemChanges.length ? '仅系统字段发生变化' : '本次操作没有字段差异'}</Text>}
        <Collapse className={styles.rawDisclosure} ghost size="small" items={details} />
    </div>;
}

function isNumeric(value) {
    return typeof value === 'number' || (typeof value === 'string' && /^-?\d+(\.\d+)?$/.test(value));
}

function groupRecordsByDate(records) {
    const groups = new Map();
    records.forEach(record => {
        const parts = String(record.create_date || '').match(/^(\d{4}-\d{2}-\d{2})(?:[ T](.*))?$/);
        const date = parts?.[1] || '日期未记录';
        if (!groups.has(date)) groups.set(date, { date, items: [] });
        groups.get(date).items.push({ record, time: parts?.[2] || '—' });
    });
    return [...groups.values()];
}

export default function FinanceHistoryDrawer({ open, onClose, historyUrl, title = '单据变更历史' }) {
    const [state, setState] = useState({ items: [], total: 0 });
    const [page, setPage] = useState(1);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [retry, setRetry] = useState(0);
    useEffect(() => { setPage(1); setState({ items: [], total: 0 }); }, [historyUrl, open]);
    useEffect(() => {
        if (!open || !historyUrl) return undefined;
        const controller = new AbortController();
        setLoading(true); setError('');
        fetch(`${endpoint}${historyUrl}${historyUrl.includes('?') ? '&' : '?'}p=${page}&s=10`, { headers: getSafeHeader(), signal: controller.signal })
            .then(async response => { const result = await response.json(); if (!response.ok || result.code !== 200) throw new Error(result.msg || '历史加载失败'); return result.data; })
            .then(data => { if (!controller.signal.aborted) setState(data || { items: [], total: 0 }); })
            .catch(err => { if (!controller.signal.aborted) { setError(err.message || '历史加载失败'); setState({ items: [], total: 0 }); } })
            .finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => controller.abort();
    }, [open, historyUrl, page, retry]);
    const groups = groupRecordsByDate(state.items || []);
    return <Drawer rootClassName={styles.drawer} title={title} open={open} onClose={onClose} width="min(760px, 100vw)" destroyOnClose
        footer={state.total > 10 ? <div className={styles.pagination}><Pagination size="small" current={page} total={state.total} pageSize={10} onChange={setPage} showSizeChanger={false} /></div> : null}>
        <div className={styles.summary}><Text type="secondary">共 {state.total || 0} 条记录</Text><Text type="secondary">最新记录在前</Text></div>
        {state.notice && (state.history_complete === false
            ? <Alert type="warning" showIcon message="历史记录范围" description={state.notice} className={styles.notice} />
            : <Text type="secondary" className={styles.noticeText}>{state.notice}</Text>)}
        {error && <Alert className={styles.notice} type="error" showIcon message={error} action={<Button aria-label="重试" size="small" onClick={() => setRetry(value => value + 1)}>重试</Button>} />}
        <Spin spinning={loading}>
            <div className={styles.records}>
                {!loading && !error && !state.items?.length && <Empty className={styles.empty} image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无已保存的变更记录" />}
                {groups.map(group => <section className={styles.dateGroup} key={group.date} aria-label={`${group.date} 变更记录`}>
                    <div className={styles.dateHeading}><Text strong>{group.date}</Text><Text type="secondary">{group.items.length} 条</Text></div>
                    <Divider className={styles.dateDivider} />
                    {group.items.map(({ record, time }, index) => <article className={styles.event} key={record.id}>
                        <div className={styles.eventHeader}>
                            <Text type="secondary" className={styles.time}><time dateTime={record.create_date?.replace(' ', 'T')}>{time}</time></Text>
                            <div className={styles.eventMeta}>
                                <Text strong>{AUDIT_ACTION_LABELS[record.action] || record.action}</Text>
                                <Text>{record.operator_name || (record.operator_id ? `用户 #${record.operator_id}` : '未记录操作人')}</Text>
                                {record.operator_role && <Text type="secondary">{record.operator_role.split(',').map(role => ROLE_LABEL_MAP[role] || role).join('、')}</Text>}
                                {record.legacy && <Text type="secondary">旧版记录</Text>}
                            </div>
                        </div>
                        <div className={styles.eventBody}>
                            {record.remark && <div className={styles.reason}><Text type="secondary" className={styles.reasonLabel}>说明</Text><Text>{record.remark}</Text></div>}
                            <AuditChanges record={record} />
                            {record.correlation_id && <Text type="secondary" className={styles.correlation}>关联号 {record.correlation_id}</Text>}
                        </div>
                        {index < group.items.length - 1 && <Divider className={styles.eventDivider} />}
                    </article>)}
                </section>)}
            </div>
        </Spin>
    </Drawer>;
}
