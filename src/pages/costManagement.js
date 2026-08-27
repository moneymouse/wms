import React, { useEffect, useState } from 'react';
import { Button, Card, Drawer, Form, Input, InputNumber, Modal, Space, Table, Tabs, Tag, Typography, message } from 'antd';
import { EditOutlined, HistoryOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';

const EMPTY_FORM = { name: '', channel_group: '', cost: 0, min_price: 0, remark: '' };

export default function CostManagement() {
    const [messageApi, contextHolder] = message.useMessage();
    const [form] = Form.useForm();
    const [modes, setModes] = useState([]);
    const [loading, setLoading] = useState(false);
    const [modalOpen, setModalOpen] = useState(false);
    const [editing, setEditing] = useState(null);
    const [submitting, setSubmitting] = useState(false);
    const [versionsOpen, setVersionsOpen] = useState(false);
    const [versions, setVersions] = useState([]);
    const [versionsLoading, setVersionsLoading] = useState(false);
    const [quoteApprovals, setQuoteApprovals] = useState([]);
    const [quoteApprovalsLoading, setQuoteApprovalsLoading] = useState(false);
    const [isAdmin] = useState(() => {
        try {
            const payload = JSON.parse(atob((localStorage.getItem('jwt') || '').split('.')[1]));
            return (payload.roles || [payload.role]).includes('admin');
        } catch (_) {
            return false;
        }
    });

    const fetchModes = async () => {
        setLoading(true);
        try {
            const res = await fetch(`${endpoint}/transportation-modes`, { headers: getSafeHeader() });
            const data = await res.json();
            if (data.code === 200) setModes(data.data || []);
            else messageApi.error(data.msg || '获取渠道成本失败');
        } catch (error) {
            messageApi.error('获取渠道成本失败');
            console.error(error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchModes();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const openModal = (record = null) => {
        setEditing(record);
        form.setFieldsValue(record ? { ...record, remark: '' } : EMPTY_FORM);
        setModalOpen(true);
    };

    const saveMode = async () => {
        setSubmitting(true);
        try {
            const values = await form.validateFields();
            const url = editing ? `${endpoint}/transportation-modes/${editing.id}` : `${endpoint}/transportation-modes`;
            const res = await fetch(url, {
                method: editing ? 'PUT' : 'POST',
                headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ...values,
                    name: String(values.name || '').trim(),
                    channel_group: String(values.channel_group || '').trim(),
                    cost: Number(values.cost || 0),
                    min_price: Number(values.min_price || 0),
                })
            });
            const data = await res.json();
            if (data.code === 200) {
                messageApi.success(editing ? '成本已更新' : '渠道已创建');
                setModalOpen(false);
                fetchModes();
            } else {
                messageApi.error(data.msg || '保存失败');
            }
        } catch (error) {
            if (error?.errorFields) return;
            messageApi.error('保存失败');
            console.error(error);
        } finally {
            setSubmitting(false);
        }
    };

    const fetchVersions = async (record) => {
        setEditing(record);
        setVersionsOpen(true);
        setVersionsLoading(true);
        try {
            const res = await fetch(`${endpoint}/transportation-modes/${record.id}/cost-versions`, { headers: getSafeHeader() });
            const data = await res.json();
            if (data.code === 200) setVersions(data.data || []);
            else messageApi.error(data.msg || '获取版本失败');
        } catch (error) {
            messageApi.error('获取版本失败');
            console.error(error);
        } finally {
            setVersionsLoading(false);
        }
    };

    const fetchQuoteApprovals = async () => {
        if (!isAdmin) return;
        setQuoteApprovalsLoading(true);
        try {
            const res = await fetch(`${endpoint}/finance/quote-approvals`, { headers: getSafeHeader() });
            const data = await res.json();
            if (data.code === 200) setQuoteApprovals(data.data || []);
            else messageApi.error(data.msg || '获取低价报价失败');
        } finally {
            setQuoteApprovalsLoading(false);
        }
    };

    // fetchQuoteApprovals intentionally reruns only when admin visibility changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    useEffect(() => { fetchQuoteApprovals(); }, [isAdmin]);

    const reviewQuote = (record, action) => {
        let reviewRemark = '';
        Modal.confirm({
            title: action === 'approve' ? '确认通过低价报价' : '确认驳回报价',
            content: <Input.TextArea rows={3} placeholder="审核说明" onChange={e => { reviewRemark = e.target.value; }} />,
            okText: action === 'approve' ? '通过' : '驳回',
            okButtonProps: { danger: action === 'reject' },
            onOk: async () => {
                const res = await fetch(`${endpoint}/finance/quote-approvals/${record.id}`, {
                    method: 'PUT',
                    headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action, review_remark: reviewRemark }),
                });
                const data = await res.json();
                if (!res.ok || data.code !== 200) throw new Error(data.msg || '审核失败');
                messageApi.success('审核完成');
                fetchQuoteApprovals();
            }
        });
    };

    const columns = [
        { title: '渠道', dataIndex: 'name', key: 'name', fixed: 'left', width: 220 },
        { title: '分组', dataIndex: 'channel_group', key: 'channel_group', width: 120 },
        { title: '成本', dataIndex: 'cost', key: 'cost', width: 120, render: v => Number(v || 0).toFixed(2) },
        { title: '最低报价', dataIndex: 'min_price', key: 'min_price', width: 120, render: v => Number(v || 0).toFixed(2) },
        { title: '更新时间', dataIndex: 'update_date', key: 'update_date', width: 160 },
        {
            title: '操作',
            key: 'action',
            width: 190,
            fixed: 'right',
            render: (_, record) => (
                <Space>
                    <Button icon={<EditOutlined />} size="small" onClick={() => openModal(record)}>调整</Button>
                    <Button icon={<HistoryOutlined />} size="small" onClick={() => fetchVersions(record)}>版本</Button>
                </Space>
            )
        }
    ];

    return (
        <div style={{ padding: 24 }}>
            {contextHolder}
            <Typography.Title level={3}>成本管理</Typography.Title>
            <Tabs items={[
                {
                    key: 'cost', label: '渠道成本', children: <Card>
                        <Space style={{ marginBottom: 12 }}>
                            <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal(null)}>新增渠道</Button>
                            <Button icon={<ReloadOutlined />} onClick={fetchModes}>刷新</Button>
                        </Space>
                        <Table rowKey="id" loading={loading} columns={columns} dataSource={modes} scroll={{ x: 1000 }} />
                    </Card>
                },
                ...(isAdmin ? [{
                    key: 'quote-approval', label: `低价报价审核${quoteApprovals.length ? ` (${quoteApprovals.length})` : ''}`, children: <Card>
                        <Button icon={<ReloadOutlined />} onClick={fetchQuoteApprovals} style={{ marginBottom: 12 }}>刷新</Button>
                        <Table rowKey="id" loading={quoteApprovalsLoading} dataSource={quoteApprovals} scroll={{ x: 'max-content' }} columns={[
                            { title: '订单号', dataIndex: 'order_id', width: 190 },
                            { title: '客户', dataIndex: 'customer_name', width: 150 },
                            { title: '渠道', dataIndex: 'transportation_name', width: 150 },
                            { title: '单价p', dataIndex: 'unit_price', width: 100, render: v => Number(v || 0).toFixed(4) },
                            { title: '最低p', dataIndex: 'min_price', width: 100, render: v => Number(v || 0).toFixed(4) },
                            { title: '附加费f', dataIndex: 'surcharge', width: 100, render: v => Number(v || 0).toFixed(2) },
                            { title: '重量(kg)', dataIndex: 'weight_snapshot', width: 110, render: v => Number(v || 0).toFixed(3) },
                            { title: '应收', dataIndex: 'receivable_amount', width: 110, render: v => Number(v || 0).toFixed(2) },
                            { title: '状态', render: () => <Tag color="orange">待审核</Tag>, width: 90 },
                            { title: '报价人', dataIndex: 'quoter_name', width: 110 },
                            { title: '操作', fixed: 'right', width: 140, render: (_, record) => <Space><Button size="small" type="primary" onClick={() => reviewQuote(record, 'approve')}>通过</Button><Button size="small" danger onClick={() => reviewQuote(record, 'reject')}>驳回</Button></Space> },
                        ]} />
                    </Card>
                }] : [])
            ]} />

            <Modal
                title={editing ? '调整渠道成本' : '新增渠道成本'}
                open={modalOpen}
                onCancel={() => setModalOpen(false)}
                onOk={saveMode}
                confirmLoading={submitting}
                okText="保存"
                cancelText="取消"
            >
                <Form form={form} layout="vertical">
                    <Form.Item name="name" label="渠道名称" rules={[{ required: true, message: '请输入渠道名称' }]}>
                        <Input />
                    </Form.Item>
                    <Form.Item name="channel_group" label="渠道分组">
                        <Input />
                    </Form.Item>
                    <Form.Item name="cost" label="渠道成本" rules={[{ required: true }]}>
                        <InputNumber min={0} precision={2} style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item
                        name="min_price"
                        label="最低报价限制"
                        dependencies={['cost']}
                        rules={[
                            { required: true },
                            ({ getFieldValue }) => ({
                                validator(_, value) {
                                    const cost = Number(getFieldValue('cost') || 0);
                                    const minPrice = Number(value || 0);
                                    if (minPrice >= cost) {
                                        return Promise.resolve();
                                    }
                                    return Promise.reject(new Error('最低报价限制不能低于渠道成本'));
                                }
                            })
                        ]}
                    >
                        <InputNumber min={0} precision={2} style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item name="remark" label="调整说明">
                        <Input.TextArea rows={3} />
                    </Form.Item>
                </Form>
            </Modal>

            <Drawer
                title={`${editing?.name || ''} 成本版本`}
                open={versionsOpen}
                width={760}
                onClose={() => setVersionsOpen(false)}
            >
                <Table
                    rowKey="id"
                    loading={versionsLoading}
                    dataSource={versions}
                    pagination={false}
                    columns={[
                        { title: '版本', dataIndex: 'version_no', key: 'version_no', width: 80 },
                        { title: '动作', dataIndex: 'change_type', key: 'change_type', width: 100 },
                        { title: '成本', dataIndex: 'cost', key: 'cost', width: 100, render: v => Number(v || 0).toFixed(2) },
                        { title: '最低报价', dataIndex: 'min_price', key: 'min_price', width: 120, render: v => Number(v || 0).toFixed(2) },
                        { title: '责任人', dataIndex: 'operator_name', key: 'operator_name', width: 120 },
                        { title: '时间', dataIndex: 'create_date', key: 'create_date', width: 170 },
                        { title: '说明', dataIndex: 'remark', key: 'remark' },
                    ]}
                />
            </Drawer>
        </div>
    );
}
