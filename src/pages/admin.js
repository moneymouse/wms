import React, { useState, useEffect } from 'react';
import { Table, Button, Space, message, Card, Tag, Modal, Select, Input, Typography } from 'antd';
import { CheckOutlined, CloseOutlined, UserOutlined, KeyOutlined } from '@ant-design/icons';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import { useNavigate } from 'react-router-dom';

const ROLE_OPTIONS = [
    { value: 'admin', label: '管理员' },
    { value: 'store_manager', label: '店长' },
    { value: 'salesperson', label: '业务员' },
    { value: 'clerk', label: '文员' },
    { value: 'finance', label: '财务' },
    { value: 'worker', label: '操作人员' }
];

const AdminPage = () => {
    const [loading, setLoading] = useState(false);
    const [data, setData] = useState([]);
    const [approveModalVisible, setApproveModalVisible] = useState(false);
    const [rejectModalVisible, setRejectModalVisible] = useState(false);
    const [currentRecord, setCurrentRecord] = useState(null);
    const [selectedRole, setSelectedRole] = useState('salesperson');
    const [rejectRemark, setRejectRemark] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [usersLoading, setUsersLoading] = useState(false);
    const [users, setUsers] = useState([]);
    const [editingRoleUser, setEditingRoleUser] = useState({});
    // 密码重置相关状态
    const [passwordRequests, setPasswordRequests] = useState([]);
    const [passwordRequestsLoading, setPasswordRequestsLoading] = useState(false);
    const [rejectPasswordModalVisible, setRejectPasswordModalVisible] = useState(false);
    const [currentPasswordRequest, setCurrentPasswordRequest] = useState(null);
    const [passwordRejectRemark, setPasswordRejectRemark] = useState('');
    const [resetPasswordModalVisible, setResetPasswordModalVisible] = useState(false);
    const [resetPasswordUser, setResetPasswordUser] = useState(null);
    const [newPassword, setNewPassword] = useState('');
    const navigate = useNavigate();

    // 获取待审核用户列表
    const fetchApplications = async () => {
        setLoading(true);
        try {
            const response = await fetch(`${endpoint}/auth/pending`, {
                headers: getSafeHeader()
            });

            if (response.status === 401 || response.status === 403) {
                message.error('权限不足或登录已过期');
                navigate('/login');
                return;
            }

            const result = await response.json();
            if (result.code === 200) {
                setData(result.data || []);
            } else {
                message.error(result.msg || '获取申请列表失败');
            }
        } catch (error) {
            console.error('Error fetching applications:', error);
            message.error('获取申请列表失败');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchApplications();
        fetchUsers();
        fetchPasswordRequests();
    }, []);

    // 打开审核通过对话框
    const showApproveModal = (record) => {
        setCurrentRecord(record);
        setSelectedRole('salesperson');
        setApproveModalVisible(true);
    };

    // 打开审核拒绝对话框
    const showRejectModal = (record) => {
        setCurrentRecord(record);
        setRejectRemark('');
        setRejectModalVisible(true);
    };

    // 审核通过
    const handleApprove = async () => {
        if (!currentRecord) return;
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/auth/approve/${currentRecord.id}`, {
                method: 'POST',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ role: selectedRole })
            });

            const result = await response.json();
            if (result.code === 200) {
                message.success(`用户 ${currentRecord.name} 审核已通过`);
                setApproveModalVisible(false);
                fetchApplications();
            } else {
                message.error(result.msg || '操作失败');
            }
        } catch (error) {
            console.error('Approve error:', error);
            message.error('操作异常');
        } finally {
            setSubmitting(false);
        }
    };

    // 审核拒绝
    const handleReject = async () => {
        if (!currentRecord) return;
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/auth/reject/${currentRecord.id}`, {
                method: 'POST',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ remark: rejectRemark })
            });

            const result = await response.json();
            if (result.code === 200) {
                message.success(`用户 ${currentRecord.name} 申请已拒绝`);
                setRejectModalVisible(false);
                fetchApplications();
            } else {
                message.error(result.msg || '操作失败');
            }
        } catch (error) {
            console.error('Reject error:', error);
            message.error('操作异常');
        } finally {
            setSubmitting(false);
        }
    };

    const fetchUsers = async () => {
        setUsersLoading(true);
        try {
            const response = await fetch(`${endpoint}/users`, {
                headers: getSafeHeader()
            });
            const result = await response.json();
            if (result.code === 200) {
                setUsers((result.data || []).map((item) => ({ ...item, key: item.id })));
            } else {
                message.error(result.msg || '获取用户列表失败');
            }
        } catch (error) {
            console.error('Fetch users error:', error);
            message.error('获取用户列表失败');
        } finally {
            setUsersLoading(false);
        }
    };

    const handleUpdateRole = async (record) => {
        if (!Object.prototype.hasOwnProperty.call(editingRoleUser, record.id)) {
            message.warning('请先选择角色');
            return;
        }
        const role = editingRoleUser[record.id];
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/users/${record.id}/role`, {
                method: 'PUT',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ role: role || null })
            });
            const result = await response.json();
            if (result.code === 200) {
                message.success(result.msg || '角色更新成功');
                await fetchUsers();
                return;
            }
            message.error(result.msg || '角色更新失败');
        } catch (error) {
            console.error('Update role error:', error);
            message.error('角色更新失败');
        } finally {
            setSubmitting(false);
        }
    };

    // ==================== 密码重置相关函数 ====================

    const fetchPasswordRequests = async () => {
        setPasswordRequestsLoading(true);
        try {
            const response = await fetch(`${endpoint}/auth/password/requests`, {
                headers: getSafeHeader()
            });
            const result = await response.json();
            if (result.code === 200) {
                setPasswordRequests(result.data || []);
            }
        } catch (error) {
            console.error('Fetch password requests error:', error);
        } finally {
            setPasswordRequestsLoading(false);
        }
    };

    const handleApprovePasswordRequest = async (requestId) => {
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/auth/password/approve/${requestId}`, {
                method: 'POST',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                }
            });
            const result = await response.json();
            if (result.code === 200) {
                message.success('密码重置申请已通过');
                fetchPasswordRequests();
            } else {
                message.error(result.msg || '操作失败');
            }
        } catch (error) {
            console.error('Approve password request error:', error);
            message.error('操作异常');
        } finally {
            setSubmitting(false);
        }
    };

    const showRejectPasswordModal = (record) => {
        setCurrentPasswordRequest(record);
        setPasswordRejectRemark('');
        setRejectPasswordModalVisible(true);
    };

    const handleRejectPasswordRequest = async () => {
        if (!currentPasswordRequest) return;
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/auth/password/reject/${currentPasswordRequest.id}`, {
                method: 'POST',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ remark: passwordRejectRemark })
            });
            const result = await response.json();
            if (result.code === 200) {
                message.success('密码重置申请已拒绝');
                setRejectPasswordModalVisible(false);
                fetchPasswordRequests();
            } else {
                message.error(result.msg || '操作失败');
            }
        } catch (error) {
            console.error('Reject password request error:', error);
            message.error('操作异常');
        } finally {
            setSubmitting(false);
        }
    };

    const showResetPasswordModal = (record) => {
        setResetPasswordUser(record);
        setNewPassword('');
        setResetPasswordModalVisible(true);
    };

    const handleResetPassword = async () => {
        if (!resetPasswordUser) return;
        if (!newPassword || newPassword.length < 6) {
            message.warning('密码长度不能少于6位');
            return;
        }
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/users/${resetPasswordUser.id}/reset-password`, {
                method: 'POST',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ new_password: newPassword })
            });
            const result = await response.json();
            if (result.code === 200) {
                message.success(`用户 ${resetPasswordUser.name} 的密码已重置`);
                setResetPasswordModalVisible(false);
            } else {
                message.error(result.msg || '重置失败');
            }
        } catch (error) {
            console.error('Reset password error:', error);
            message.error('操作异常');
        } finally {
            setSubmitting(false);
        }
    };

    const columns = [
        {
            title: '姓名',
            dataIndex: 'name',
            key: 'name',
            render: (text) => <Space><UserOutlined />{text}</Space>
        },
        {
            title: '手机号',
            dataIndex: 'phone',
            key: 'phone',
        },
        {
            title: '申请时间',
            dataIndex: 'create_date',
            key: 'create_date',
        },
        {
            title: '状态',
            dataIndex: 'status',
            key: 'status',
            render: (status) => {
                let color = 'default';
                let text = '未知';
                if (status === 'pending') {
                    color = 'processing';
                    text = '待审核';
                } else if (status === 'approved') {
                    color = 'success';
                    text = '已通过';
                } else if (status === 'rejected') {
                    color = 'error';
                    text = '已拒绝';
                }
                return <Tag color={color}>{text}</Tag>;
            }
        },
        {
            title: '操作',
            key: 'action',
            render: (_, record) => (
                <Space size="middle">
                    {record.status === 'pending' && (
                        <>
                            <Button
                                type="primary"
                                size="small"
                                icon={<CheckOutlined />}
                                onClick={() => showApproveModal(record)}
                            >
                                通过
                            </Button>
                            <Button
                                danger
                                size="small"
                                icon={<CloseOutlined />}
                                onClick={() => showRejectModal(record)}
                            >
                                拒绝
                            </Button>
                        </>
                    )}
                </Space>
            ),
        },
    ];

    const userColumns = [
        {
            title: '姓名',
            dataIndex: 'name',
            key: 'name',
            render: (text) => <Space><UserOutlined />{text}</Space>
        },
        {
            title: '手机号',
            dataIndex: 'phone',
            key: 'phone',
        },
        {
            title: '状态',
            dataIndex: 'status',
            key: 'status',
            render: (status) => <Tag color={status === 'approved' ? 'success' : 'processing'}>{status || '-'}</Tag>
        },
        {
            title: '当前角色',
            dataIndex: 'role',
            key: 'role',
            render: (role) => role || <Typography.Text type="secondary">未设置</Typography.Text>
        },
        {
            title: '角色管理',
            key: 'roleAction',
            render: (_, record) => (
                <Space>
                    <Select
                        allowClear
                        placeholder="选择角色（清空=移除）"
                        style={{ width: 180 }}
                        value={Object.prototype.hasOwnProperty.call(editingRoleUser, record.id)
                            ? editingRoleUser[record.id] ?? undefined
                            : record.role ?? undefined}
                        options={ROLE_OPTIONS}
                        onChange={(value) => {
                            setEditingRoleUser((prev) => ({ ...prev, [record.id]: value === undefined ? null : value }));
                        }}
                    />
                    <Button type="primary" loading={submitting} onClick={() => handleUpdateRole(record)}>
                        保存
                    </Button>
                    <Button icon={<KeyOutlined />} onClick={() => showResetPasswordModal(record)}>
                        重置密码
                    </Button>
                </Space>
            )
        }
    ];

    const passwordRequestColumns = [
        {
            title: '用户姓名',
            dataIndex: 'user_name',
            key: 'user_name',
            render: (text) => <Space><UserOutlined />{text}</Space>
        },
        {
            title: '手机号',
            dataIndex: 'user_phone',
            key: 'user_phone',
        },
        {
            title: '申请时间',
            dataIndex: 'create_date',
            key: 'create_date',
        },
        {
            title: '操作',
            key: 'action',
            render: (_, record) => (
                <Space size="middle">
                    <Button
                        type="primary"
                        size="small"
                        icon={<CheckOutlined />}
                        onClick={() => handleApprovePasswordRequest(record.id)}
                        loading={submitting}
                    >
                        通过
                    </Button>
                    <Button
                        danger
                        size="small"
                        icon={<CloseOutlined />}
                        onClick={() => showRejectPasswordModal(record)}
                    >
                        拒绝
                    </Button>
                </Space>
            ),
        },
    ];

    return (
        <Space direction="vertical" size={16} style={{ margin: 20, width: 'calc(100% - 40px)' }}>
            <Card title="用户申请管理">
                <Table
                    columns={columns}
                    dataSource={data}
                    rowKey="id"
                    loading={loading}
                    pagination={{ pageSize: 10 }}
                />
            </Card>

            <Card title="用户角色管理">
                <Table
                    columns={userColumns}
                    dataSource={users}
                    rowKey="id"
                    loading={usersLoading}
                    pagination={{ pageSize: 10 }}
                />
            </Card>

            <Card title="密码重置申请">
                <Table
                    columns={passwordRequestColumns}
                    dataSource={passwordRequests}
                    rowKey="id"
                    loading={passwordRequestsLoading}
                    pagination={{ pageSize: 10 }}
                    locale={{ emptyText: '暂无密码重置申请' }}
                />
            </Card>

            {/* 审核通过对话框 */}
            <Modal
                title="审核通过"
                open={approveModalVisible}
                onOk={handleApprove}
                onCancel={() => setApproveModalVisible(false)}
                confirmLoading={submitting}
                okText="确认通过"
                cancelText="取消"
            >
                <p>确定通过用户 <strong>{currentRecord?.name}</strong> 的申请吗？</p>
                <div style={{ marginTop: 16 }}>
                    <span>分配角色：</span>
                    <Select
                        value={selectedRole}
                        onChange={setSelectedRole}
                        style={{ width: 200, marginLeft: 8 }}
                        options={ROLE_OPTIONS}
                    />
                </div>
            </Modal>

            {/* 审核拒绝对话框 */}
            <Modal
                title="审核拒绝"
                open={rejectModalVisible}
                onOk={handleReject}
                onCancel={() => setRejectModalVisible(false)}
                confirmLoading={submitting}
                okText="确认拒绝"
                cancelText="取消"
            >
                <p>确定拒绝用户 <strong>{currentRecord?.name}</strong> 的申请吗？</p>
                <div style={{ marginTop: 16 }}>
                    <span>拒绝原因（选填）：</span>
                    <Input.TextArea
                        value={rejectRemark}
                        onChange={(e) => setRejectRemark(e.target.value)}
                        placeholder="请输入拒绝原因"
                        rows={3}
                        style={{ marginTop: 8 }}
                    />
                </div>
            </Modal>

            {/* 拒绝密码重置申请对话框 */}
            <Modal
                title="拒绝密码重置申请"
                open={rejectPasswordModalVisible}
                onOk={handleRejectPasswordRequest}
                onCancel={() => setRejectPasswordModalVisible(false)}
                confirmLoading={submitting}
                okText="确认拒绝"
                cancelText="取消"
            >
                <p>确定拒绝用户 <strong>{currentPasswordRequest?.user_name}</strong> 的密码重置申请吗？</p>
                <div style={{ marginTop: 16 }}>
                    <span>拒绝原因（选填）：</span>
                    <Input.TextArea
                        value={passwordRejectRemark}
                        onChange={(e) => setPasswordRejectRemark(e.target.value)}
                        placeholder="请输入拒绝原因"
                        rows={3}
                        style={{ marginTop: 8 }}
                    />
                </div>
            </Modal>

            {/* 重置密码对话框 */}
            <Modal
                title="重置用户密码"
                open={resetPasswordModalVisible}
                onOk={handleResetPassword}
                onCancel={() => setResetPasswordModalVisible(false)}
                confirmLoading={submitting}
                okText="确认重置"
                cancelText="取消"
            >
                <p>为用户 <strong>{resetPasswordUser?.name}</strong>（{resetPasswordUser?.phone}）设置新密码：</p>
                <div style={{ marginTop: 16 }}>
                    <Input.Password
                        value={newPassword}
                        onChange={(e) => setNewPassword(e.target.value)}
                        placeholder="请输入新密码（至少6位）"
                        style={{ width: '100%' }}
                    />
                </div>
            </Modal>
        </Space>
    );
};

export default AdminPage;
