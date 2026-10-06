import React, { useEffect, useState } from 'react';
import { Alert, Button, Card, DatePicker, Empty, Form, Input, Select, Space, Table, Tag, Typography } from 'antd';
import { AuditOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import { hasPermission, ROLE_LABEL_MAP } from '../common/roleConfig';
import { AuditChanges, AUDIT_EVENT_LABELS, AUDIT_ACTION_LABELS } from '../components/FinanceHistoryDrawer';

const { Title, Text } = Typography;
const adminAccess = () => {
    try {
        const encoded = (localStorage.getItem('jwt') || '').split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
        const payload = JSON.parse(atob(encoded));
        return hasPermission(payload.roles || [payload.role], ['admin']);
    } catch (_) { return false; }
};

export default function AuditLogs() {
    const [form] = Form.useForm();
    const [allowed] = useState(adminAccess);
    const [query, setQuery] = useState({ p: 1, s: 20, sf: 'create_date', so: 1 });
    const [state, setState] = useState({ items: [], total: 0 });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [retry, setRetry] = useState(0);
    useEffect(() => {
        if (!allowed) return undefined;
        const controller = new AbortController();
        setLoading(true); setError('');
        const params = new URLSearchParams(Object.entries(query).filter(([, value]) => value !== undefined && value !== ''));
        fetch(`${endpoint}/audit-logs?${params}`, { headers: getSafeHeader(), signal: controller.signal })
            .then(async response => { const result = await response.json(); if (!response.ok || result.code !== 200) throw new Error(result.msg || '获取审计日志失败'); return result; })
            .then(result => { if (!controller.signal.aborted) setState({ items: result.data || [], total: result.total || 0 }); })
            .catch(err => { if (!controller.signal.aborted) { setError(err.message); setState({ items: [], total: 0 }); } })
            .finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => controller.abort();
    }, [allowed, query, retry]);
    const submit = values => {
        const { dates, ...filters } = values;
        setQuery(prev => ({ ...filters, p: 1, s: prev.s, sf: prev.sf, so: prev.so, date_from: dates?.[0]?.format('YYYY-MM-DD'), date_to: dates?.[1]?.format('YYYY-MM-DD') }));
    };
    if (!allowed) return <Card><Empty description="只有管理员有权限查看审计日志" /></Card>;
    return <div style={{ maxWidth: 1480, margin: '0 auto', padding: '12px 0' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, marginBottom: 24 }}>
            <div><Text style={{ color: '#557b79', letterSpacing: 2, fontSize: 12 }}>AUDIT TRAIL</Text><Title level={3} style={{ margin: '6px 0' }}><AuditOutlined /> 系统审计日志</Title><Text type="secondary">查清谁在何时修改了哪笔业务，逐项核对修改前后的内容。</Text></div>
            <Button icon={<ReloadOutlined />} onClick={() => setRetry(value => value + 1)}>刷新记录</Button>
        </div>
        <Card style={{ borderRadius: 14, marginBottom: 16 }}>
            <Form form={form} layout="inline" onFinish={submit} style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                <Form.Item name="event_type"><Select aria-label="审计类型" allowClear placeholder="全部审计类型" style={{ width: 170 }} options={Object.entries(AUDIT_EVENT_LABELS).map(([value, label]) => ({ value, label }))} /></Form.Item>
                <Form.Item name="q"><Input allowClear placeholder="对象编号、操作人或说明" aria-label="搜索审计记录" style={{ width: 230 }} /></Form.Item>
                <Form.Item name="dates"><DatePicker.RangePicker aria-label="记录日期" /></Form.Item>
                <Space><Button htmlType="submit" type="primary" icon={<SearchOutlined />}>筛选</Button><Button onClick={() => { form.resetFields(); submit({}); }}>重置</Button></Space>
            </Form>
        </Card>
        {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} action={<Button onClick={() => setRetry(value => value + 1)}>重试</Button>} />}
        <Card style={{ borderRadius: 14 }} bodyStyle={{ padding: 0 }}>
            <div style={{ padding: '16px 20px', borderBottom: '1px solid #eef1f4' }}><Text strong>变更记录</Text><Text type="secondary" style={{ marginLeft: 12 }}>共 {state.total} 条 · 展开记录查看字段差异</Text></div>
            <Table rowKey="id" loading={loading} dataSource={state.items} scroll={{ x: 1050 }}
                pagination={{ current: query.p, pageSize: query.s, total: state.total, showSizeChanger: true }}
                onChange={(pagination, _, sorter) => setQuery(prev => ({ ...prev, p: pagination.current, s: pagination.pageSize, sf: sorter.field || 'create_date', so: sorter.order === 'ascend' ? 0 : 1 }))}
                expandable={{ expandedRowRender: record => <div style={{ padding: '0 20px 12px' }}>{record.remark && <Alert type="info" showIcon message={record.remark} />}<AuditChanges record={record} />{record.correlation_id && <Text type="secondary">关联号：{record.correlation_id}</Text>}</div> }}
                columns={[
                    { title: '记录时间', dataIndex: 'create_date', width: 180, sorter: true, sortOrder: query.sf === 'create_date' ? (query.so ? 'descend' : 'ascend') : null },
                    { title: '审计事件', dataIndex: 'event_type', width: 145, render: value => <Tag color="cyan">{AUDIT_EVENT_LABELS[value] || value}</Tag> },
                    { title: '动作', dataIndex: 'action', width: 150, render: value => <Tag color={value.includes('reject') || value === 'archive' ? 'orange' : 'blue'}>{AUDIT_ACTION_LABELS[value] || value}</Tag> },
                    { title: '对象编号', dataIndex: 'target_id', width: 140, ellipsis: true },
                    { title: '操作人', dataIndex: 'operator_name', width: 120, render: (value, row) => value || (row.operator_id ? `用户 #${row.operator_id}` : '未记录') },
                    { title: '角色', dataIndex: 'operator_role', width: 110, render: value => (value || '').split(',').filter(Boolean).map(role => ROLE_LABEL_MAP[role] || role).join('、') || '—' },
                    { title: '说明', dataIndex: 'remark', ellipsis: true, render: value => value || '—' },
                ]}
            />
        </Card>
    </div>;
}
