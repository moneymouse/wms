import React, { useEffect, useState } from 'react';
import { Alert, Button, DatePicker, Input, Space, Table, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import dayjs from 'dayjs';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import { money, queryString } from '../common/financeApi';
import useUrlState from '../common/useUrlState';
import { PaymentEditor } from './financeWorkspace';

export default function BusinessReceivables({ active: isActive = true }) {
    const [filters, setFilters] = useUrlState('receivableFilters', { q: '', p: 1, s: 20 }, {
        validate: value => typeof value.q === 'string' && Number.isSafeInteger(value.p) && value.p > 0
            && [20, 50, 100].includes(value.s)
            && [value.date_from, value.date_to].every(date => date === undefined || (typeof date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(date) && dayjs(date).isValid())),
    });
    const [revision, setRevision] = useState(0);
    const [context, setContext] = useState(null);
    const [state, setState] = useState({ items: [], total: 0, loading: true, error: '' });
    const key = queryString(filters);
    useEffect(() => {
        if (!isActive) return undefined;
        let active = true;
        const controller = new AbortController();
        setState({ items: [], total: 0, loading: true, error: '' });
        fetch(`${endpoint}/receivables/unregistered-orders?${key}`, { headers: getSafeHeader(), signal: controller.signal })
            .then(async response => {
                const result = await response.json();
                if (!response.ok || result.code !== 200) throw new Error(result.msg || '读取应收款失败');
                return result;
            })
            .then(result => { if (active) setState({ items: result.data || [], total: result.total || 0, loading: false, error: '' }); })
            .catch(error => { if (active && error.name !== 'AbortError') setState({ items: [], total: 0, loading: false, error: error.message }); });
        return () => { active = false; controller.abort(); };
    }, [isActive, key, revision]);
    const change = patch => setFilters(previous => ({ ...previous, ...patch, p: 1 }));
    return <>
        <Typography.Paragraph type="secondary">
            当前本人名下已生效报价、尚未登记收付款的订单。待财务确认的收付款按备注订单识别，已登记的订单不再列出。
        </Typography.Paragraph>
        <Space wrap style={{ marginBottom: 16 }}>
            <Input.Search aria-label="搜索应收款订单" key={filters.q || ''} defaultValue={filters.q} placeholder="订单号 / 客户" allowClear onSearch={q => change({ q })} style={{ width: 320, maxWidth: '100%' }} />
            <DatePicker.RangePicker aria-label="应收款订单日期" value={filters.date_from && filters.date_to ? [dayjs(filters.date_from), dayjs(filters.date_to)] : null}
                onChange={dates => change({ date_from: dates?.[0]?.format('YYYY-MM-DD'), date_to: dates?.[1]?.format('YYYY-MM-DD') })} />
            <Button icon={<ReloadOutlined />} onClick={() => setRevision(value => value + 1)}>刷新</Button>
        </Space>
        {state.error && <Alert type="error" showIcon message={state.error} action={<Button size="small" onClick={() => setRevision(value => value + 1)}>重试</Button>} style={{ marginBottom: 12 }} />}
        <Table rowKey="uid" size="small" loading={state.loading} dataSource={state.items} scroll={{ x: 1060 }}
            locale={{ emptyText: '暂无未登记收付款的应收订单' }} columns={[
                { title: '订单号', dataIndex: 'order_id', width: 190, render: (value, row) => <Link to={`/orders/${row.uid}`}>{value || row.uid}</Link> },
                { title: '客户', dataIndex: 'customer_name', width: 180 },
                { title: '订单日期', dataIndex: 'create_date', width: 160 },
                { title: '报价人', dataIndex: 'quoter_name', width: 100 },
                { title: '报价生效时间', dataIndex: 'effective_date', width: 160 },
                { title: '计费重量 / kg', dataIndex: 'billing_weight', align: 'right', width: 130 },
                { title: '应收 / CNY', dataIndex: 'receivable_amount', align: 'right', width: 140, render: value => <Typography.Text strong>{money(value)}</Typography.Text> },
                { title: '操作', width: 140, fixed: 'right', render: (_, row) => <Button size="small" disabled={!row.customer_id} onClick={() => setContext({ customerId: row.customer_id, customerName: row.customer_name, orderUid: row.uid, orderNumber: row.order_id })}>登记收付款</Button> },
            ]} pagination={{ current: filters.p, pageSize: filters.s, total: state.total, showSizeChanger: true, pageSizeOptions: [20, 50, 100], showTotal: total => `共 ${total} 个订单`,
                onChange: (p, s) => setFilters(previous => ({ ...previous, p: s === previous.s ? p : 1, s })) }} />
        {context && <PaymentEditor open business modal initialContext={context} onClose={() => setContext(null)} onSaved={() => setRevision(value => value + 1)} />}
    </>;
}
