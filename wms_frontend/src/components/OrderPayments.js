import React, { useEffect, useState } from 'react';
import { Alert, Button, Space, Table, Tag, Tooltip, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { FINANCE_STATUS, financeRequest, money } from '../common/financeApi';
import styles from './OrderPayments.module.css';

const PAGE_SIZE = 10;
const RELATION_LABELS = { reference: '订单备注', packing: '箱子备注', allocation: '本单核销' };
const SUMMARY_AMOUNTS = ['received_amount', 'refunded_amount', 'net_received_amount', 'related_received_amount', 'related_refunded_amount'];

function validateResult(data) {
    if (!data || !Array.isArray(data.items) || !data.summary
        || !Number.isFinite(Number(data.total))
        || SUMMARY_AMOUNTS.some(key => data.summary[key] == null || !Number.isFinite(Number(data.summary[key])))) {
        throw new Error('收付款记录返回格式错误，请重试');
    }
    return data;
}

export default function OrderPayments({ orderUid, refreshKey = 0, embedded = false }) {
    const [paging, setPaging] = useState({ orderUid, refreshKey, page: 1 });
    const [retry, setRetry] = useState(0);
    const [result, setResult] = useState({ identity: '', data: null, error: '', loading: true });
    const page = paging.orderUid === orderUid && paging.refreshKey === refreshKey ? paging.page : 1;
    const identity = JSON.stringify([orderUid, refreshKey, page, retry]);

    useEffect(() => {
        if (!orderUid) return undefined;
        let active = true;
        const controller = new AbortController();
        setResult({ identity, data: null, error: '', loading: true });
        financeRequest(`/order-payments/${encodeURIComponent(orderUid)}`, {
            params: { p: page, s: PAGE_SIZE }, signal: controller.signal,
        }).then(validateResult)
            .then(data => { if (active) setResult({ identity, data, error: '', loading: false }); })
            .catch(error => {
                if (active && error.name !== 'AbortError') {
                    setResult({ identity, data: null, error: error.message || '获取收付款记录失败', loading: false });
                }
            });
        return () => { active = false; controller.abort(); };
    }, [orderUid, page, identity]);

    const current = result.identity === identity ? result : { data: null, error: '', loading: Boolean(orderUid) };
    const data = current.data;
    const summary = data?.summary;
    const columns = [
        { title: '收付款单号', dataIndex: 'number', width: 180, render: (value, row) => <Space direction="vertical" size={4}>
            <Typography.Text copyable>{value}</Typography.Text>
            {row.is_opening && <Tag>期初余额</Tag>}
        </Space> },
        { title: '日期', dataIndex: 'payment_date', width: 112 },
        { title: '方向', dataIndex: 'direction', width: 70, render: value => <Tag color={value === 'incoming' ? 'green' : 'red'}>{value === 'incoming' ? '收款' : '付款'}</Tag> },
        { title: '流水金额（元）', dataIndex: 'amount', align: 'right', width: 136, render: value => money(value) },
        { title: '本单已核销（元）', dataIndex: 'order_allocated_amount', align: 'right', width: 150, render: value => money(value) },
        { title: '状态', dataIndex: 'status', width: 128, render: value => <Tag color={FINANCE_STATUS[value]?.color}>{FINANCE_STATUS[value]?.label || value}</Tag> },
        { title: '账户', dataIndex: 'account_name', width: 150, ellipsis: true },
        { title: '关联来源', dataIndex: 'relation_types', width: 170, render: values => <Space size={4} wrap>{(values || []).map(value => <Tag key={value}>{RELATION_LABELS[value] || value}</Tag>)}</Space> },
        { title: '登记人', dataIndex: 'created_by_name', width: 110 },
        { title: '流水号 / 支付参考号', dataIndex: 'reference', width: 170, ellipsis: true },
        { title: '备注', dataIndex: 'memo', width: 220, ellipsis: { showTitle: false }, render: value => <Tooltip title={value}>{value || '-'}</Tooltip> },
    ];
    return <section className={embedded ? styles.embedded : styles.section} aria-label="本单收付款">
        <div className={styles.header}>
            <Space wrap>
                {!embedded && <Typography.Title level={4} className={styles.title}>收付款记录</Typography.Title>}
                {summary && <Space size={8} wrap>
                    <Tag color="orange">待财务确认 {summary.pending_count || 0} 笔</Tag>
                    <Tag>草稿 {summary.draft_count || 0} 笔</Tag>
                </Space>}
            </Space>
            <Tooltip title="刷新收付款记录">
                <Button size="small" icon={<ReloadOutlined />} aria-label="刷新收付款记录" loading={current.loading} onClick={() => setRetry(value => value + 1)} />
            </Tooltip>
        </div>
        {current.error && <Alert type="error" showIcon message={current.error} action={<Button size="small" onClick={() => setRetry(value => value + 1)}>重试</Button>} />}
        {current.loading && <Typography.Text type="secondary" role="status">正在加载收付款记录...</Typography.Text>}
        {data && <>
            {data.visibility === 'own' && <Typography.Paragraph type="secondary" className={styles.note}>仅统计本人登记的收付款。</Typography.Paragraph>}
            <dl className={styles.summary}>
                {[
                    ['关联收款（已生效）', summary.related_received_amount],
                    ['关联付款（已生效）', summary.related_refunded_amount],
                    ['本单已核销收款', summary.received_amount],
                    ['本单已核销付款', summary.refunded_amount],
                ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{money(value)} <span>元</span></dd></div>)}
            </dl>
            <Space wrap className={styles.totals}>
                <Typography.Text>本单核销净额：{money(summary.net_received_amount)} 元</Typography.Text>
            </Space>
            <Typography.Paragraph type="secondary" className={styles.note}>关联流水金额包含整笔收付款，多订单流水以本单核销金额为准。</Typography.Paragraph>
            <Table rowKey="id" size="small" columns={columns} dataSource={data.items} scroll={{ x: 1696 }}
                locale={{ emptyText: '暂无本单收付款记录' }}
                pagination={{ current: page, pageSize: PAGE_SIZE, total: data.total, showSizeChanger: false, hideOnSinglePage: true,
                    onChange: nextPage => setPaging({ orderUid, refreshKey, page: nextPage }) }} />
        </>}
    </section>;
}
