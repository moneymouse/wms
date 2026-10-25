import React, { useEffect, useState } from 'react';
import { Alert, Button, Card, Descriptions, Space, Table, Tag, Typography } from 'antd';
import { FINANCE_STATUS, money } from '../common/financeApi';
import { reconciliationRequest } from '../common/supplierReconciliationApi';

export default function OrderSupplierCosts({ orderUid, refreshKey = 0, embedded = false }) {
    const [reload, setReload] = useState(0);
    const [result, setResult] = useState({ orderUid: null, data: null, error: '', loading: true });
    useEffect(() => {
        let active = true;
        const controller = new AbortController();
        setResult({ orderUid, data: null, error: '', loading: true });
        (async () => {
            try {
                const data = await reconciliationRequest(`/orders/${encodeURIComponent(orderUid)}/costs`, { signal: controller.signal });
                if (!data || Array.isArray(data)) throw new Error('第三方成本返回格式错误');
                if (active) setResult({ orderUid, data, error: '', loading: false });
            } catch (error) {
                if (active && error.name !== 'AbortError') setResult({ orderUid, data: null, error: error.message || '获取第三方成本失败', loading: false });
            }
        })();
        return () => { active = false; controller.abort(); };
    }, [orderUid, refreshKey, reload]);

    const current = result.orderUid === orderUid ? result : { data: null, error: '', loading: true };
    const data = current.data;
    const columns = [
        { title: '账单编号', dataIndex: 'number', render: value => <Typography.Text copyable>{value}</Typography.Text> },
        { title: '费用说明', dataIndex: 'description' },
        { title: '费用归属', dataIndex: 'match_type', render: value => value === 'order' ? '整单对账' : value === 'cargo' ? '包裹对账' : '财务登记' },
        { title: '类型', dataIndex: 'document_type', render: value => value === 'vendor_credit' ? '供应商贷项' : '供应商应付' },
        { title: '费用（元）', dataIndex: 'total_amount', align: 'right', render: value => money(value) },
        { title: '状态', dataIndex: 'status', render: value => <Tag color={FINANCE_STATUS[value]?.color}>{FINANCE_STATUS[value]?.label || value}</Tag> },
        { title: '对账来源', render: (_, row) => row.source_batch_id ? `批次 ${row.source_batch_id} / Excel 第 ${row.source_row} 行` : '财务登记' },
    ];
    const refreshButton = <Button size="small" loading={current.loading} onClick={() => setReload(value => value + 1)}>刷新成本</Button>;
    const content = <>
        {current.error && <Alert type="error" showIcon message={current.error} />}
        {current.loading && <Typography.Text type="secondary">正在加载第三方成本…</Typography.Text>}
        {data && <>
            <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }}>
                <Descriptions.Item label="已确认成本（不含税）">{money(data.confirmed_net_amount)} 元</Descriptions.Item>
                <Descriptions.Item label="已确认费用（含税）">{money(data.confirmed_amount)} 元</Descriptions.Item>
                <Descriptions.Item label="待财务确认费用">{money(data.pending_amount)} 元</Descriptions.Item>
            </Descriptions>
            <Space direction="vertical" style={{ width: '100%' }}>
                <Typography.Text type="secondary">已生效供应商账单计入实际成本，贷项冲减成本。草稿费用待财务确认。</Typography.Text>
                {data.items?.length > 0 && <Table rowKey="line_id" size="small" columns={columns} dataSource={data.items} pagination={{ pageSize: 5 }} scroll={{ x: 820 }} />}
                {data.total > (data.items?.length || 0) && <Typography.Text type="secondary">仅展示最近 {data.items.length} 条，汇总金额包含全部费用。</Typography.Text>}
            </Space>
        </>}
    </>;
    return embedded ? <section aria-label="本单第三方成本">
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>{refreshButton}</div>
        {content}
    </section> : <Card title="第三方成本" style={{ margin: '16px 0' }} extra={refreshButton}>{content}</Card>;
}
