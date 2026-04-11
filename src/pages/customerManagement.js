import React, { useEffect, useState } from 'react';
import { Button, Form, Input, message, Modal, Popconfirm, Space, Table, Typography } from 'antd';
import { DeleteOutlined, EditOutlined, SearchOutlined } from '@ant-design/icons';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';

export default function CustomerManagement() {
    const [messageX, messageComponent] = message.useMessage();
    const [loading, setLoading] = useState(false);
    const [customers, setCustomers] = useState([]);
    const [searchText, setSearchText] = useState('');

    // 编辑模态框
    const [editVisible, setEditVisible] = useState(false);
    const [editLoading, setEditLoading] = useState(false);
    const [editingCustomer, setEditingCustomer] = useState(null);
    const [deletingCustomerId, setDeletingCustomerId] = useState(null);
    const [editForm] = Form.useForm();

    // 加载客户列表
    const loadCustomers = async () => {
        setLoading(true);
        try {
            const res = await fetch(`${endpoint}/customers_detail`, {
                headers: getSafeHeader()
            });
            const { data } = await res.json();
            setCustomers(data || []);
        } catch (error) {
            messageX.error('获取客户列表失败');
            console.error(error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadCustomers();
    }, []);

    // 打开编辑模态框
    const handleEdit = (record) => {
        setEditingCustomer(record);
        editForm.setFieldsValue({
            name: record.name,
            phone: record.phone || '',
            wechat: record.wechat || ''
        });
        setEditVisible(true);
    };

    // 关闭编辑模态框
    const handleEditClose = () => {
        setEditVisible(false);
        setEditingCustomer(null);
        editForm.resetFields();
    };

    // 提交编辑
    const handleEditSubmit = async () => {
        try {
            const values = await editForm.validateFields();
            setEditLoading(true);

            const res = await fetch(`${endpoint}/customer/${editingCustomer.id}`, {
                headers: getSafeHeader(),
                method: 'PUT',
                body: JSON.stringify(values)
            });
            const result = await res.json();

            if (result.code === 200) {
                messageX.success('修改成功！');
                handleEditClose();
                loadCustomers();
            } else {
                messageX.error(result.msg || '修改失败！');
            }
        } catch (error) {
            if (error.errorFields) {
                // 表单验证错误
            } else {
                messageX.error('修改失败！');
                console.error(error);
            }
        } finally {
            setEditLoading(false);
        }
    };

    // 删除客户
    const handleDeleteCustomer = async (record) => {
        setDeletingCustomerId(record.id);
        try {
            const res = await fetch(`${endpoint}/del_customer/${record.id}`, {
                method: 'POST',
                headers: getSafeHeader()
            });
            const result = await res.json();

            if (result.code === 200) {
                messageX.success('删除成功！');
                await loadCustomers();
            } else {
                messageX.error(result.msg || '删除失败！');
            }
        } catch (error) {
            messageX.error('删除失败！');
            console.error(error);
        } finally {
            setDeletingCustomerId(null);
        }
    };

    // 过滤客户列表
    const filteredCustomers = customers.filter(customer =>
        customer.name?.toLowerCase().includes(searchText.toLowerCase()) ||
        customer.phone?.toLowerCase().includes(searchText.toLowerCase()) ||
        customer.wechat?.toLowerCase().includes(searchText.toLowerCase())
    );

    const columns = [
        {
            title: 'ID',
            dataIndex: 'id',
            key: 'id',
            width: 80,
        },
        {
            title: '客户姓名',
            dataIndex: 'name',
            key: 'name',
        },
        {
            title: '手机号',
            dataIndex: 'phone',
            key: 'phone',
            render: (text) => text || '-',
        },
        {
            title: '微信',
            dataIndex: 'wechat',
            key: 'wechat',
            render: (text) => text || '-',
        },
        {
            title: '操作',
            key: 'action',
            width: 180,
            render: (_, record) => (
                <Space>
                    <Button
                        type="link"
                        icon={<EditOutlined />}
                        onClick={() => handleEdit(record)}
                    >
                        编辑
                    </Button>
                    <Popconfirm
                        title="删除客户"
                        description={`确认删除客户“${record.name}”及其相关信息吗？`}
                        onConfirm={() => handleDeleteCustomer(record)}
                        okText="确认"
                        cancelText="取消"
                    >
                        <Button
                            type="link"
                            danger
                            icon={<DeleteOutlined />}
                            loading={deletingCustomerId === record.id}
                        >
                            删除
                        </Button>
                    </Popconfirm>
                </Space>
            ),
        },
    ];

    return (
        <>
            {messageComponent}
            <Typography.Title level={4} style={{ marginBottom: '1.5rem' }}>
                客户信息管理
            </Typography.Title>

            <Space style={{ marginBottom: 16 }}>
                <Input
                    placeholder="搜索客户姓名/手机号/微信"
                    prefix={<SearchOutlined />}
                    value={searchText}
                    onChange={(e) => setSearchText(e.target.value)}
                    style={{ width: 300 }}
                    allowClear
                />
                <Button onClick={loadCustomers}>刷新</Button>
            </Space>

            <Table
                columns={columns}
                dataSource={filteredCustomers}
                rowKey="id"
                loading={loading}
                pagination={{
                    defaultPageSize: 20,
                    showSizeChanger: true,
                    showTotal: (total) => `共 ${total} 条`,
                }}
            />

            {/* 编辑客户模态框 */}
            <Modal
                open={editVisible}
                title="编辑客户信息"
                onCancel={handleEditClose}
                footer={[
                    <Button key="cancel" onClick={handleEditClose}>
                        取消
                    </Button>,
                    <Button key="submit" type="primary" loading={editLoading} onClick={handleEditSubmit}>
                        保存
                    </Button>
                ]}
            >
                <Form form={editForm} layout="vertical">
                    <Form.Item
                        name="name"
                        label="客户姓名"
                        rules={[{ required: true, message: '请输入客户姓名' }]}
                    >
                        <Input placeholder="请输入客户姓名" />
                    </Form.Item>
                    <Form.Item
                        name="phone"
                        label="客户手机号"
                        extra="留空则清空手机号"
                    >
                        <Input placeholder="13800138000" />
                    </Form.Item>
                    <Form.Item
                        name="wechat"
                        label="客户微信"
                        extra="留空则清空微信"
                    >
                        <Input placeholder="wx_customer" />
                    </Form.Item>
                </Form>
            </Modal>
        </>
    );
}
