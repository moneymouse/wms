import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Input, Space, Table, Tag, Typography } from 'antd';
import { CloseOutlined } from '@ant-design/icons';
import { financeRequest } from '../common/financeApi';
import { buildOrderColumns } from '../common/orderColumns';
import orderProperty from '../common/orderProperty';

const priorityFields = ['order_id', 'order_date', 'customer_name', 'receiver', 'country', 'tag_all', 'transportation'];
const pickerProperties = [
    ...priorityFields.map(name => orderProperty.find(property => property.name === name)),
    { name: 'cargo_count', label: '箱数', width: 100 },
    { name: 'total_weight', label: '总重量(kg)', width: 130 },
    ...orderProperty.filter(property => !priorityFields.includes(property.name)),
];
const columns = buildOrderColumns({ properties: pickerProperties, sortable: false, fixedColumnCount: 1 });
const tableWidth = columns.reduce((sum, column) => sum + column.width, 48);
const emptySearch = customerKey => ({ customerKey, text: '', query: '', page: 1 });
const normalizeOrder = row => ({
    ...row,
    uid: row.order_uid || row.uid,
    order_id: row.order_id || row.order_number,
    order_date: row.create_date || row.order_date,
});

export default function PaymentOrderPicker({ value = [], onChange, customerId, selectedOrders = [], disabled = false, id }) {
    const customerKey = customerId ? String(customerId) : '';
    const previousCustomer = useRef(customerKey);
    const [search, setSearch] = useState(() => emptySearch(customerKey));
    const [retry, setRetry] = useState(0);
    const [result, setResult] = useState({ key: '', items: [], total: 0, loading: false, error: '' });
    const [cachedOrders, setCachedOrders] = useState({ customerKey, rows: {} });
    const scopedSearch = search.customerKey === customerKey ? search : emptySearch(customerKey);
    const { text, query, page } = scopedSearch;
    const requestKey = JSON.stringify([customerKey, query, page, retry]);
    const pageSize = 10;
    const current = result.key === requestKey ? result : { items: [], total: 0, loading: Boolean(customerKey && !disabled), error: '' };
    const selectedKeys = useMemo(() => Array.isArray(value) ? value : [], [value]);

    useEffect(() => {
        if (previousCustomer.current === customerKey) return;
        const oldCustomer = previousCustomer.current;
        previousCustomer.current = customerKey;
        setSearch(emptySearch(customerKey));
        setCachedOrders({ customerKey, rows: {} });
        if (oldCustomer && selectedKeys.length) onChange?.([]);
    }, [customerKey, onChange, selectedKeys]);

    useEffect(() => {
        if (!customerKey || disabled) return undefined;
        let active = true;
        const controller = new AbortController();
        setResult({ key: requestKey, items: [], total: 0, loading: true, error: '' });
        financeRequest('/payment-options/orders', {
            params: { customer_id: customerKey, q: query, p: page, s: pageSize }, signal: controller.signal,
        }).then(data => {
            if (!active) return;
            const items = (data?.items || []).map(normalizeOrder);
            setResult({ key: requestKey, items, total: Number(data?.total || 0), loading: false, error: '' });
            setCachedOrders(previous => ({
                customerKey,
                rows: { ...(previous.customerKey === customerKey ? previous.rows : {}), ...Object.fromEntries(items.map(row => [row.uid, row])) },
            }));
        }).catch(error => {
            if (active && error.name !== 'AbortError') {
                setResult({ key: requestKey, items: [], total: 0, loading: false, error: error.message || '订单加载失败，请重试' });
            }
        });
        return () => { active = false; controller.abort(); };
    }, [customerKey, disabled, page, query, requestKey]);

    const selectionLabels = useMemo(() => {
        const fallbacks = Object.fromEntries(selectedOrders.map(normalizeOrder).map(row => [row.uid, row.order_id]));
        const cached = cachedOrders.customerKey === customerKey ? cachedOrders.rows : {};
        return Object.fromEntries(selectedKeys.map(uid => [uid, cached[uid]?.order_id || fallbacks[uid] || uid]));
    }, [cachedOrders, customerKey, selectedKeys, selectedOrders]);
    const updateSearch = changes => setSearch(previous => ({
        ...(previous.customerKey === customerKey ? previous : emptySearch(customerKey)), ...changes,
    }));

    return <div id={id} role="group" aria-label="参考订单">
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Input.Search aria-label="搜索参考订单" placeholder="订单号 / 收货人 / 唛头 / 品名 / 国家" allowClear
                value={text} disabled={!customerKey || disabled} enterButton="搜索"
                onChange={event => updateSearch({ text: event.target.value, ...(!event.target.value ? { query: '', page: 1 } : {}) })}
                onSearch={keyword => updateSearch({ text: keyword, query: keyword.trim(), page: 1 })} />
            <Typography.Text type="secondary">按创建时间倒序，最新订单在前；可横向滚动查看订单详情。</Typography.Text>
            {selectedKeys.length > 0 && <Space wrap size={[4, 4]}>
                <Typography.Text>已选择 {selectedKeys.length} 单</Typography.Text>
                {selectedKeys.map(uid => <Tag key={uid} style={{ marginInlineEnd: 0 }}>
                    {selectionLabels[uid]}
                    <Button aria-label={`移除参考订单 ${selectionLabels[uid]}`} type="text" size="small" disabled={disabled}
                        icon={<CloseOutlined />} onClick={() => onChange?.(selectedKeys.filter(key => key !== uid))} />
                </Tag>)}
                <Button type="link" size="small" disabled={disabled} onClick={() => onChange?.([])}>清空选择</Button>
            </Space>}
            {current.error && <Alert type="error" showIcon message={current.error}
                action={<Button size="small" disabled={disabled} onClick={() => setRetry(count => count + 1)}>重试</Button>} />}
            <Table size="small" rowKey="uid" columns={columns} dataSource={current.items} loading={current.loading}
                scroll={{ x: tableWidth, y: 280 }} locale={{ emptyText: !customerKey ? '请先选择客户' : current.error ? '订单加载失败' : '没有匹配的订单' }}
                rowSelection={{ selectedRowKeys: selectedKeys, preserveSelectedRowKeys: true, onChange,
                    getCheckboxProps: () => ({ disabled: disabled || current.loading || Boolean(current.error) }),
                }}
                pagination={customerKey ? { current: page, pageSize, total: current.total, showSizeChanger: false, showTotal: total => `共 ${total} 单` } : false}
                onChange={pagination => updateSearch({ page: pagination.current })} />
        </Space>
    </div>;
}
