import React, { useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, DatePicker, Descriptions, Empty, Select, Space, Spin, Table, Typography, message } from 'antd';
import { DownloadOutlined, PrinterOutlined, SearchOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import { financeRequest, money, queryString } from '../common/financeApi';
import statementStyles from './financePartnerStatement.module.css';

const { Text } = Typography;
const statementPath = '/accounting/partner-statement';
const initialDates = () => [dayjs().startOf('month'), dayjs()];
const sourceLabels = {
    finance_document: '财务账单', document: '财务账单', customer_invoice: '客户账单', vendor_bill: '供应商账单',
    customer_credit: '客户贷项', vendor_credit: '供应商贷项', finance_payment: '收付款', payment: '收付款',
    manual: '手工凭证', opening: '期初余额', revenue_recognition: '收入确认', reversal: '冲销',
};
const sourceLabel = value => sourceLabels[value] || '业务凭证';
function balanceMeaning(statement) {
    return statement.partner_type === 'vendor'
        ? '余额为正表示应付，余额为负表示预付或应退。'
        : '余额为正表示应收，余额为负表示预收或应退。';
}
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));

/** Print a standalone statement only; all names and descriptions are untrusted text. */
export function buildStatementPrintHtml(statement) {
    const type = statement.partner_type === 'vendor' ? '供应商' : '客户';
    const amount = value => escapeHtml(money(value));
    const rows = (statement.items || []).map(item => `<tr><td>${escapeHtml(item.entry_date)}</td><td>${escapeHtml(item.entry_number)}</td><td>${escapeHtml(item.description)}</td><td>${escapeHtml(sourceLabel(item.source_type))}</td><td class="amount">${amount(item.increase)}</td><td class="amount">${amount(item.decrease)}</td><td class="amount">${amount(item.balance)}</td></tr>`).join('');
    return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>${escapeHtml(statement.partner_name)} · 往来对账单</title>
<style>@page{size:A4 landscape;margin:15mm}*{box-sizing:border-box}body{font:12px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft Yahei",sans-serif;margin:0}h1{font-size:20px;margin:0 0 6px}h2{font-size:16px;margin:16px 0 8px}header{border-bottom:1px solid;padding-bottom:12px}.meta{display:flex;justify-content:space-between;gap:16px}.summary{display:flex;gap:16px;margin:16px 0}.summary>div{flex:1}.summary strong{display:block;font-size:16px;font-variant-numeric:tabular-nums}table{border-collapse:collapse;width:100%;table-layout:auto}thead{display:table-header-group}tr{break-inside:avoid}th,td{border-bottom:1px solid;padding:9px 7px;vertical-align:top;text-align:left;word-break:break-word}.amount{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}footer{margin-top:16px}.notice{padding:8px 0;margin:12px 0}.empty{text-align:center;padding:24px}</style></head><body>
<header><h1>${escapeHtml(statement.company_name || '财务账簿')}</h1><div class="meta"><span>${type}往来对账单 · ${escapeHtml(statement.partner_name)}</span><span>币种：${escapeHtml(statement.currency || 'CNY')}</span></div></header>
<h2>${escapeHtml(statement.partner_name)}</h2><div class="meta"><span>对账期间：${escapeHtml(statement.date_from)} 至 ${escapeHtml(statement.date_to)}</span><span>${escapeHtml(balanceMeaning(statement))}</span></div>
${!statement.opening_confirmed ? '<div class="notice">期初余额尚未核对，本对账单为待核对口径。</div>' : ''}
<div class="summary"><div>期初余额<strong>${amount(statement.opening_balance)}</strong></div><div>本期增加<strong>${amount(statement.total_increase)}</strong></div><div>本期减少<strong>${amount(statement.total_decrease)}</strong></div><div>期末余额<strong>${amount(statement.closing_balance)}</strong></div></div>
<table><thead><tr><th>日期</th><th>凭证号</th><th>摘要</th><th>业务来源</th><th class="amount">增加</th><th class="amount">减少</th><th class="amount">余额</th></tr></thead><tbody>${rows || '<tr><td colspan="7" class="empty">本期无往来发生额</td></tr>'}</tbody></table>
<footer>期末余额 = 期初余额 + 本期增加 − 本期减少。金额单位：人民币元。<br>本单依据已过账凭证编制，包含本期全部明细。</footer></body></html>`;
}

function StatementPartnerSelect({ partnerType, value, onChange }) {
    const [search, setSearch] = useState('');
    const [result, setResult] = useState({ items: [], loading: false, error: '' });
    useEffect(() => {
        const controller = new AbortController();
        setResult({ items: [], loading: true, error: '' });
        financeRequest('/partners', { params: { partner_type: partnerType, q: search, include_inactive: 1 }, signal: controller.signal })
            .then(data => { if (!controller.signal.aborted) setResult({ items: data.items || [], loading: false, error: '' }); })
            .catch(error => { if (!controller.signal.aborted) setResult({ items: [], loading: false, error: error.message }); });
        return () => controller.abort();
    }, [partnerType, search]);
    return <div className={statementStyles.partnerFilter}>
        <Select aria-label="对账往来单位" showSearch allowClear filterOption={false} value={value} onChange={onChange} onSearch={setSearch}
            loading={result.loading} placeholder={partnerType === 'vendor' ? '搜索并选择供应商' : '搜索并选择客户'} style={{ width: '100%' }}
            options={result.items.map(item => ({ value: item.id, label: item.name }))}
            notFoundContent={result.error || (result.loading ? <Spin size="small" /> : '没有匹配的往来单位')} />
        {result.error && <Text type="danger" role="alert">{result.error}</Text>}
    </div>;
}

export default function FinancePartnerStatement() {
    const [partnerType, setPartnerType] = useState('customer');
    const [partnerId, setPartnerId] = useState(undefined);
    const [dates, setDates] = useState(initialDates);
    const [statement, setStatement] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [downloading, setDownloading] = useState(false);
    const downloadingRef = useRef(false);
    const requestId = useRef(0);
    const controller = useRef(null);
    const [messageApi, contextHolder] = message.useMessage();
    const filters = { partner_type: partnerType, partner_id: partnerId, date_from: dates?.[0]?.format('YYYY-MM-DD'), date_to: dates?.[1]?.format('YYYY-MM-DD') };
    const filterKey = queryString(filters);
    useEffect(() => {
        requestId.current += 1; controller.current?.abort();
        setStatement(null); setError(''); setLoading(false);
        return () => { requestId.current += 1; controller.current?.abort(); };
    }, [filterKey]);

    const load = async () => {
        if (!partnerId) { setError('请选择需要对账的客户或供应商'); return; }
        if (!dates?.[0] || !dates?.[1] || dates[0].isAfter(dates[1], 'day')) { setError('请选择有效的对账日期范围'); return; }
        controller.current?.abort(); controller.current = new AbortController();
        const activeRequest = ++requestId.current;
        setLoading(true); setStatement(null); setError('');
        try {
            const data = await financeRequest(statementPath, { params: filters, signal: controller.current.signal });
            if (activeRequest === requestId.current) setStatement(data);
        } catch (err) { if (activeRequest === requestId.current && err.name !== 'AbortError') setError(err.message); }
        finally { if (activeRequest === requestId.current) setLoading(false); }
    };
    const download = async () => {
        if (!statement || downloadingRef.current) return;
        downloadingRef.current = true; setDownloading(true);
        try {
            const params = queryString({ partner_type: statement.partner_type, partner_id: statement.partner_id, date_from: statement.date_from, date_to: statement.date_to });
            const response = await fetch(`${endpoint}/finance/v2${statementPath}/export?${params}`, { headers: getSafeHeader() });
            if (!response.ok) {
                let result = {};
                try { result = await response.json(); } catch (_) { /* A failed binary response can be empty. */ }
                throw new Error(result.msg || result.message || '下载对账单失败');
            }
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = `往来对账单-${statement.partner_name}-${statement.date_from}-${statement.date_to}.csv`.replace(/[\\/:*?"<>|]/g, '_');
            document.body.appendChild(link); link.click(); link.remove();
            window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        } catch (err) { messageApi.error(err.message); }
        finally { downloadingRef.current = false; setDownloading(false); }
    };
    const print = () => {
        if (!statement) return;
        const preview = window.open('', '_blank');
        if (!preview) { messageApi.warning('浏览器拦截了打印窗口，请允许弹窗后重试'); return; }
        preview.opener = null;
        preview.document.write(buildStatementPrintHtml(statement));
        preview.document.close(); preview.focus(); preview.print();
    };
    const columns = [
        { title: '日期', dataIndex: 'entry_date', width: 110 },
        { title: '凭证号', dataIndex: 'entry_number', width: 175, render: value => <Text>{value}</Text> },
        { title: '摘要', dataIndex: 'description', width: 230 },
        { title: '业务来源', dataIndex: 'source_type', width: 115, render: sourceLabel },
        ...[['本期增加', 'increase'], ['本期减少', 'decrease'], ['余额', 'balance']].map(([title, field]) => ({ title, dataIndex: field, width: 135, align: 'right', render: value => <Text strong={field === 'balance'}>{money(value)}</Text> })),
    ];
    return <div>
        {contextHolder}
        <div className={statementStyles.toolbar}>
            <Space wrap className={statementStyles.filters}>
                <Select aria-label="对账往来类型" value={partnerType} style={{ width: 140 }} options={[{ value: 'customer', label: '客户对账' }, { value: 'vendor', label: '供应商对账' }]} onChange={value => { setPartnerType(value); setPartnerId(undefined); }} />
                <StatementPartnerSelect key={partnerType} partnerType={partnerType} value={partnerId} onChange={setPartnerId} />
                <DatePicker.RangePicker aria-label="对账期间" value={dates} onChange={setDates} allowClear={false} />
                <Button type="primary" icon={<SearchOutlined />} onClick={load} loading={loading}>生成对账单</Button>
            </Space>
            <Space><Button icon={<DownloadOutlined />} disabled={!statement || loading} loading={downloading} onClick={download}>下载 CSV</Button><Button icon={<PrinterOutlined />} disabled={!statement || loading} onClick={print}>打印</Button></Space>
        </div>
        {error && <Alert className={statementStyles.error} type="error" showIcon message={error} action={<Button size="small" onClick={load}>重试</Button>} />}
        <Spin spinning={loading}>
            {statement ? <section className={statementStyles.statement} aria-label="往来对账单">
                <Card size="small" title={<Space direction="vertical" size={2}><Text strong>{statement.company_name || '财务账簿'}</Text><Text type="secondary">{statement.partner_type === 'vendor' ? '供应商' : '客户'}往来对账单</Text></Space>}
                    extra={<Space direction="vertical" size={2} align="end"><Text>{statement.currency || 'CNY'} 人民币</Text><Text type="secondary">已过账凭证口径</Text></Space>}>
                    <Descriptions size="small" column={{ xs: 1, sm: 2 }} items={[
                        { key: 'partner', label: '往来单位', children: <Text strong>{statement.partner_name}</Text> },
                        { key: 'period', label: '对账期间', children: `${statement.date_from} 至 ${statement.date_to}` },
                    ]} />
                    {!statement.opening_confirmed && <Alert type="warning" showIcon message="期初余额尚未核对，本对账单为待核对口径。" className={statementStyles.notice} />}
                    <Descriptions className={statementStyles.summary} size="small" column={{ xs: 1, sm: 2, md: 4 }} items={
                        [['期初余额', 'opening_balance'], ['本期增加', 'total_increase'], ['本期减少', 'total_decrease'], ['期末余额', 'closing_balance']].map(([label, field]) => ({
                            key: field, label, children: <div role="group" aria-label={label}><Text strong>{money(statement[field])}</Text></div>,
                        }))
                    } />
                    <Table className={statementStyles.table} rowKey="__key" dataSource={(statement.items || []).map((item, index) => ({ ...item, __key: `${item.entry_id}-${index}` }))} columns={columns} scroll={{ x: 1030 }}
                        pagination={{ pageSize: 20, showSizeChanger: false, showTotal: total => `共 ${total} 条明细 · 打印和下载包含全部明细` }} locale={{ emptyText: '本期无往来发生额，余额按期初结转' }} />
                    <div className={statementStyles.statementNote}><Text>{balanceMeaning(statement)}</Text><Text type="secondary">期末余额 = 期初余额 + 本期增加 − 本期减少。金额单位：人民币元。</Text></div>
                </Card>
            </section> : <Card size="small" className={statementStyles.empty}><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={loading ? '正在整理往来明细…' : '选择客户或供应商及日期，生成可下载、可打印的对账单'} /></Card>}
        </Spin>
    </div>;
}
