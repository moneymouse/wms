import React, { useEffect, useState } from 'react';
import { Card, Collapse, Empty, Space, Table, Tag, Typography, message } from 'antd';
import { useNavigate } from 'react-router-dom';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import { hasPermission } from '../common/roleConfig';

const { Panel } = Collapse;
const { Title, Text } = Typography;

const EVENT_LABELS = {
    transportation_cost: '渠道成本',
    order_quote: '订单报价',
};

const ACTION_COLORS = {
    create: 'green',
    update: 'orange',
    archive: 'red',
    quote_submit: 'blue',
    quote_adopt: 'green',
    quote_approve: 'green',
    quote_reject: 'red',
};

export default function AuditLogs() {
    const [tableLoading, setTableLoading] = useState(false);
    const [logs, setLogs] = useState([]);
    const [pagination, setPagination] = useState({
        current: 1,
        pageSize: 10,
        total: 0,
    });
    const [sortField, setSortField] = useState('create_date');
    const [sortOrder, setSortOrder] = useState('descend');
    const [isAdmin, setIsAdmin] = useState(false);
    const navigate = useNavigate();

    const fetchLogs = async () => {
        setTableLoading(true);
        try {
            const response = await fetch(`${endpoint}/audit-logs`, {
                headers: getSafeHeader(),
            });
            const result = await response.json();
            const data = (result.data || []).map((item, index) => ({ ...item, key: item.id || index }));
            setLogs(data);
            setPagination(prev => ({
                ...prev,
                total: data.length,
            }));
        } catch (error) {
            console.error('获取审计日志失败:', error);
            message.error('获取审计日志失败');
        } finally {
            setTableLoading(false);
        }
    };

    useEffect(() => {
        const jwt = localStorage.getItem('jwt');
        if (!jwt) {
            message.error('请先登录系统');
            setTimeout(() => navigate('/'), 2000);
            return;
        }

        try {
            const parts = jwt.split('.');
            if (parts.length !== 3) throw new Error('invalid token');
            const payload = JSON.parse(atob(parts[1]));
            const userRoles = payload.roles || (payload.role ? [payload.role] : []);
            const allowed = hasPermission(userRoles, ['admin']);
            setIsAdmin(allowed);

            if (!allowed) {
                message.error('只有管理员有权限查看审计日志！');
                setTimeout(() => navigate('/'), 2000);
                return;
            }

            fetchLogs();
        } catch (error) {
            console.error('解析 JWT 时出错:', error);
            message.error('权限验证失败');
            setTimeout(() => navigate('/'), 2000);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [navigate]);

    const handleTableChange = (newPagination, filters, sorter) => {
        setPagination({ ...newPagination });
        if (sorter.field) {
            setSortField(sorter.field);
            setSortOrder(sorter.order);
        }
    };

    const getSortedData = () => {
        const sortedData = [...logs];
        if (sortField && sortOrder) {
            sortedData.sort((a, b) => {
                const fieldA = a[sortField] || '';
                const fieldB = b[sortField] || '';
                if (sortOrder === 'ascend') {
                    return fieldA > fieldB ? 1 : -1;
                }
                return fieldA < fieldB ? 1 : -1;
            });
        }
        return sortedData;
    };

    const columns = [
        {
            title: '日期',
            dataIndex: 'create_date',
            key: 'create_date',
            sorter: true,
            sortOrder: sortField === 'create_date' ? sortOrder : null,
            width: 180,
        },
        {
            title: '审计事件',
            dataIndex: 'event_type',
            key: 'event_type',
            width: 140,
            render: (eventType) => <Tag color="blue">{EVENT_LABELS[eventType] || eventType}</Tag>,
        },
        {
            title: '动作',
            dataIndex: 'action',
            key: 'action',
            width: 130,
            render: (action) => <Tag color={ACTION_COLORS[action] || 'default'}>{action}</Tag>,
        },
        {
            title: '审计对象',
            key: 'target',
            width: 210,
            render: (_, record) => `${record.target_type || '-'}:${record.target_id || '-'}`,
        },
        {
            title: '责任人',
            dataIndex: 'operator_name',
            key: 'operator_name',
            width: 150,
            render: (name) => name ? <Text strong>{name}</Text> : '-',
        },
        {
            title: '用户角色',
            dataIndex: 'operator_role',
            key: 'operator_role',
            width: 140,
            render: (role) => role ? <Tag color={role.includes('admin') ? 'red' : 'blue'}>{role}</Tag> : '-',
        },
        {
            title: 'IP地址',
            dataIndex: 'ip',
            key: 'ip',
            width: 140,
        },
        {
            title: '说明',
            dataIndex: 'remark',
            key: 'remark',
            ellipsis: true,
        },
    ];

    const expandedRowRender = (record) => (
        <Space direction="vertical" style={{ width: '100%' }}>
            {record.before_data && (
                <Collapse ghost>
                    <Panel header="变更前" key="before">
                        <pre>{JSON.stringify(record.before_data, null, 2)}</pre>
                    </Panel>
                </Collapse>
            )}
            {record.after_data && (
                <Collapse ghost>
                    <Panel header="变更后" key="after">
                        <pre>{JSON.stringify(record.after_data, null, 2)}</pre>
                    </Panel>
                </Collapse>
            )}
        </Space>
    );

    if (!isAdmin) {
        return (
            <Card style={{ marginTop: '20px' }}>
                <Empty
                    description="无权限查看审计日志"
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                />
            </Card>
        );
    }

    return (
        <Card>
            <Title level={4}>系统审计日志</Title>
            <Table
                columns={columns}
                dataSource={getSortedData()}
                rowKey={(record) => record.key}
                pagination={pagination}
                loading={tableLoading}
                onChange={handleTableChange}
                expandable={{
                    expandedRowRender,
                    rowExpandable: (record) => !!record.before_data || !!record.after_data,
                }}
                scroll={{ x: 1300 }}
            />
        </Card>
    );
}
