import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Input, Space, Table, Tag, Typography } from 'antd';
import { CloseOutlined, DownOutlined, RightOutlined } from '@ant-design/icons';
import { financeRequest } from '../common/financeApi';

const API_PAGE_SIZE = 200;
const LIST_PAGE_SIZE = 10;
const label = row => `${row.list_number || row.packing_list_uid} / 箱 ${row.box_number ?? row.box_uid}`;
const listLabel = row => row.list_number || row.packing_list_uid;
const weight = rows => new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 3 }).format(
    rows.reduce((sum, row) => sum + (Number(row.weight) || 0), 0));
const boxColumns = [
    { title: '箱号', dataIndex: 'box_number', width: 75 },
    { title: '原单号', dataIndex: 'transfer_id', width: 180, render: value => value || '—' },
    { title: '品名', dataIndex: 'item_name', width: 160, render: value => value || '—' },
    { title: '重量(kg)', dataIndex: 'weight', width: 100 },
    { title: '订单分配', dataIndex: 'target_order_uid', width: 120, render: value => value ? '已分配' : '待分配' },
];

// The lookup paginates boxes, so finish fetching before paginating packing-list parents.
// Otherwise a large packing list would appear as several incomplete parent rows.
async function loadAllBoxes(params, signal) {
    const first = await financeRequest('/payment-options/packing-boxes', { params: { ...params, p: 1, s: API_PAGE_SIZE }, signal });
    const rows = [...(first?.items || [])];
    const pageSize = Number(first?.page_size) || API_PAGE_SIZE;
    const pages = Math.ceil(Number(first?.total || rows.length) / pageSize);
    for (let page = 2; page <= pages; page += 1) {
        const next = await financeRequest('/payment-options/packing-boxes', { params: { ...params, p: page, s: API_PAGE_SIZE }, signal });
        rows.push(...(next?.items || []));
    }
    return [...new Map(rows.map(row => [row.box_uid, row])).values()];
}

export default function PaymentPackingBoxPicker({ value = [], onChange, customerId, selectedBoxes = [], disabled = false, id }) {
    const customerKey = customerId ? String(customerId) : '';
    const previousCustomer = useRef(customerKey);
    const completedResult = useRef(null);
    const fullLists = useRef({ customerKey, lists: {} });
    const [search, setSearch] = useState({ customerKey, text: '', query: '', page: 1 });
    const [retry, setRetry] = useState(0);
    const [childRetry, setChildRetry] = useState(0);
    const [result, setResult] = useState({ key: '', items: [], loading: false, error: '' });
    const [cache, setCache] = useState({ customerKey, rows: {} });
    const [children, setChildren] = useState({ customerKey, lists: {} });
    const [expansion, setExpansion] = useState({ customerKey, query: '', keys: [] });
    const scoped = search.customerKey === customerKey ? search : { text: '', query: '', page: 1 };
    const requestKey = JSON.stringify([customerKey, scoped.query, retry]);
    const current = result.key === requestKey ? result : { items: [], loading: Boolean(!disabled && customerKey), error: '' };
    const selected = useMemo(() => Array.isArray(value) ? value : [], [value]);
    const groups = useMemo(() => {
        const lists = new Map();
        current.items.forEach(row => {
            const uid = row.packing_list_uid;
            if (!lists.has(uid)) lists.set(uid, { packing_list_uid: uid, list_number: row.list_number, customer_id: row.customer_id, boxes: [] });
            lists.get(uid).boxes.push(row);
        });
        return [...lists.values()];
    }, [current.items]);
    const expandedKeys = useMemo(() => expansion.customerKey === customerKey && expansion.query === scoped.query ? expansion.keys : [],
        [customerKey, expansion, scoped.query]);

    useEffect(() => {
        if (previousCustomer.current === customerKey) return;
        const old = previousCustomer.current;
        previousCustomer.current = customerKey;
        setSearch({ customerKey, text: '', query: '', page: 1 });
        setCache({ customerKey, rows: {} });
        setChildren({ customerKey, lists: {} });
        setExpansion({ customerKey, query: '', keys: [] });
        completedResult.current = null;
        fullLists.current = { customerKey, lists: {} };
        if (old && selected.length) onChange?.([]);
    }, [customerKey, onChange, selected]);

    useEffect(() => {
        if (!customerKey || disabled || completedResult.current?.key === requestKey) return undefined;
        let active = true;
        const controller = new AbortController();
        completedResult.current = null;
        setResult({ key: requestKey, items: [], loading: true, error: '' });
        loadAllBoxes({ customer_id: customerKey, q: scoped.query }, controller.signal)
            .then(items => {
                if (!active) return;
                const next = { key: requestKey, items, loading: false, error: '' };
                completedResult.current = next;
                setResult(next);
                setCache(previous => ({ customerKey, rows: { ...(previous.customerKey === customerKey ? previous.rows : {}), ...Object.fromEntries(items.map(row => [row.box_uid, row])) } }));
            }).catch(error => { if (active && error.name !== 'AbortError') setResult({ key: requestKey, items: [], loading: false, error: error.message || '装箱单加载失败' }); });
        return () => { active = false; controller.abort(); };
    }, [customerKey, disabled, requestKey, scoped.query]);

    useEffect(() => {
        if (!customerKey || disabled || !scoped.query || current.loading || current.error) return undefined;
        const pending = groups.filter(group => expandedKeys.includes(group.packing_list_uid)
            && !(fullLists.current.customerKey === customerKey && fullLists.current.lists[group.packing_list_uid]));
        if (!pending.length) return undefined;
        let active = true;
        const controller = new AbortController();
        setChildren(previous => ({ customerKey, lists: { ...(previous.customerKey === customerKey ? previous.lists : {}),
            ...Object.fromEntries(pending.map(group => [group.packing_list_uid, { items: [], loading: true, error: '' }])) } }));
        pending.forEach(group => {
            loadAllBoxes({ customer_id: customerKey, packing_list_uid: group.packing_list_uid }, controller.signal)
                .then(items => {
                    if (!active) return;
                    fullLists.current.lists[group.packing_list_uid] = items;
                    setChildren(previous => ({ customerKey, lists: { ...previous.lists, [group.packing_list_uid]: { items, loading: false, error: '' } } }));
                    setCache(previous => ({ customerKey, rows: { ...(previous.customerKey === customerKey ? previous.rows : {}), ...Object.fromEntries(items.map(row => [row.box_uid, row])) } }));
                }).catch(error => {
                    if (active && error.name !== 'AbortError') setChildren(previous => ({ customerKey, lists: { ...previous.lists,
                        [group.packing_list_uid]: { items: [], loading: false, error: error.message || '箱子加载失败' } } }));
                });
        });
        return () => { active = false; controller.abort(); };
    }, [childRetry, current.error, current.loading, customerKey, disabled, expandedKeys, groups, scoped.query]);

    const childResult = group => {
        if (!scoped.query) return { items: group.boxes, loading: false, error: '' };
        return children.customerKey === customerKey && children.lists[group.packing_list_uid]
            ? children.lists[group.packing_list_uid] : { items: [], loading: true, error: '' };
    };
    const rowsByUid = { ...Object.fromEntries(selectedBoxes.map(row => [row.box_uid, row])), ...(cache.customerKey === customerKey ? cache.rows : {}) };
    const selectedInList = group => selected.filter(uid => rowsByUid[uid]?.packing_list_uid === group.packing_list_uid).length;
    const updateSearch = changes => setSearch(previous => ({ ...(previous.customerKey === customerKey ? previous : { text: '', query: '', page: 1 }), customerKey, ...changes }));
    const columns = [
        { title: '装箱单 / 唛头', dataIndex: 'list_number', width: 200, render: (_, group) => listLabel(group) },
        { title: '客户绑定', dataIndex: 'customer_id', width: 130, render: value => value == null ? <Tag>未绑定客户</Tag> : '当前客户' },
        { title: '箱数', width: 130, render: (_, group) => {
            const boxes = childResult(group);
            return !boxes.loading && !boxes.error ? `${boxes.items.length} 箱` : `匹配 ${group.boxes.length} 箱`;
        } },
        { title: '总重量(kg)', width: 130, render: (_, group) => {
            const boxes = childResult(group);
            return boxes.loading || boxes.error ? '展开后查看' : weight(boxes.items);
        } },
        { title: '已选箱子', width: 110, render: (_, group) => `${selectedInList(group)} 箱` },
    ];

    return <div id={id} role="group" aria-label="备注装箱单箱子">
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
            {selected.length > 0 && <Space wrap size={[4, 4]}><Typography.Text>已选 {selected.length} 箱</Typography.Text>
                {selected.map(uid => <Tag key={uid}>{rowsByUid[uid] ? label(rowsByUid[uid]) : uid}<Button type="text" size="small" icon={<CloseOutlined />} disabled={disabled}
                    aria-label={`移除备注箱子 ${rowsByUid[uid] ? label(rowsByUid[uid]) : uid}`} onClick={() => onChange?.(selected.filter(key => key !== uid))} /></Tag>)}
                <Button type="link" size="small" disabled={disabled} onClick={() => onChange?.([])}>清空箱子选择</Button>
            </Space>}
            <Input.Search aria-label="搜索备注装箱单箱子" placeholder="装箱单唛头 / 原单号 / 品名" allowClear enterButton="搜索" value={scoped.text} disabled={disabled || !customerKey}
                onChange={event => updateSearch({ text: event.target.value, ...(!event.target.value ? { query: '', page: 1 } : {}) })}
                onSearch={query => updateSearch({ text: query, query: query.trim(), page: 1 })} />
            <Typography.Text type="secondary">展开装箱单选择具体箱子；未绑定客户的装箱单也可备注。</Typography.Text>
            {scoped.query && <Typography.Text type="secondary">搜索结果按装箱单展示，展开后可选择该单的全部箱子。</Typography.Text>}
            {current.error && <Alert type="error" showIcon message={current.error} action={<Button size="small" aria-label="重试装箱单加载" disabled={disabled} onClick={() => setRetry(count => count + 1)}>重试</Button>} />}
            <Table size="small" rowKey="packing_list_uid" dataSource={groups} loading={current.loading} columns={columns} scroll={{ x: 750 }}
                locale={{ emptyText: !customerKey ? '请先选择客户' : current.error ? '装箱单加载失败' : '没有匹配的装箱单' }}
                expandable={{ expandedRowKeys: expandedKeys, columnWidth: 44,
                    onExpandedRowsChange: keys => setExpansion({ customerKey, query: scoped.query, keys }),
                    expandIcon: ({ expanded, onExpand, record }) => <Button type="text" size="small" disabled={disabled} icon={expanded ? <DownOutlined /> : <RightOutlined />}
                        aria-expanded={expanded} aria-label={`${expanded ? '收起' : '展开'}装箱单 ${listLabel(record)}`} onClick={event => onExpand(record, event)} />,
                    expandedRowRender: group => {
                        const boxes = childResult(group);
                        const groupUids = new Set(boxes.items.map(row => row.box_uid));
                        return <div role="group" aria-label={`装箱单 ${listLabel(group)} 的箱子`}>
                            {boxes.error && <Alert type="error" showIcon message={boxes.error} action={<Button size="small" disabled={disabled} onClick={() => setChildRetry(count => count + 1)}>重试箱子加载</Button>} />}
                            <Table size="small" rowKey="box_uid" dataSource={boxes.items} loading={boxes.loading} columns={boxColumns} scroll={{ x: 700, y: 280 }} pagination={false}
                                locale={{ emptyText: boxes.error ? '箱子加载失败' : '没有可选的箱子' }}
                                rowSelection={{ selectedRowKeys: selected.filter(uid => groupUids.has(uid)),
                                    onChange: keys => onChange?.([...selected.filter(uid => !groupUids.has(uid)), ...keys.filter(uid => groupUids.has(uid))]),
                                    getCheckboxProps: row => ({ disabled: disabled || boxes.loading || Boolean(boxes.error), 'aria-label': `选择备注箱子 ${label(row)}` }) }} />
                        </div>;
                    } }}
                pagination={{ current: scoped.page, pageSize: LIST_PAGE_SIZE, total: groups.length, showSizeChanger: false, showTotal: total => `共 ${total} 张装箱单` }}
                onChange={pagination => updateSearch({ page: pagination.current })} />
        </Space>
    </div>;
}
