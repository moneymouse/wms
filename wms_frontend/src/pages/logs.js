import React, { useEffect, useState } from 'react'
import { PicCenterOutlined } from "@ant-design/icons";
import { Table, Typography, Card, Space, Tag, Collapse, message, Empty } from "antd";
import { endpoint } from "../config";
import getSafeHeader from "../common/safeHeader"
import { hasPermission } from "../common/roleConfig";
import { useNavigate } from "react-router-dom";

const { Panel } = Collapse;
const { Title, Text } = Typography;

export default function () {
    const [tableLoading, setTableLoading] = useState(false);
    const [logs, setLogs] = useState([]);
    const [pagination, setPagination] = useState({
        current: 1,
        pageSize: 10,
        total: 0,
    });
    const [sortField, setSortField] = useState('log_date');
    const [sortOrder, setSortOrder] = useState('descend');
    const [isAdmin, setIsAdmin] = useState(false);
    const navigate = useNavigate();

    const fetchLogs = async (
        nextPagination = pagination,
        nextSortField = sortField,
        nextSortOrder = sortOrder
    ) => {
        setTableLoading(true);
        try {
            const requestPagination = { ...pagination, ...nextPagination };
            const params = new URLSearchParams({
                p: requestPagination.current,
                s: requestPagination.pageSize,
                sf: nextSortField || 'log_date',
                so: Number(nextSortOrder !== 'ascend'),
            });

            const response = await (await fetch(`${endpoint}/logs?${params.toString()}`, {
                headers: getSafeHeader()
            })).json();

            if (response.code !== 200) {
                message.error(response.msg || '获取日志失败');
                return;
            }

            const data = (response.data || []).map((v, i) => ({
                ...v,
                key: v.id ?? `${requestPagination.current}-${i}`,
            }));
            setLogs(data);
            setPagination(prev => ({
                ...prev,
                ...requestPagination,
                current: response.page || requestPagination.current,
                pageSize: response.page_size || requestPagination.pageSize,
                total: response.total || 0,
            }));
        } catch (error) {
            console.error('获取日志失败:', error);
            message.error('获取日志失败');
        } finally {
            setTableLoading(false);
        }
    };

    useEffect(() => {
        // 检查用户权限
        const jwt = localStorage.getItem('jwt');
        if (jwt) {
            try {
                // 分割 JWT 并获取负载部分（第二部分）
                const parts = jwt.split('.');
                if (parts.length === 3) {
                    // 解码 base64 编码的负载
                    const payload = JSON.parse(atob(parts[1]));
                    const userRoles = payload.roles || (payload.role ? [payload.role] : []);
                    setIsAdmin(hasPermission(userRoles, ['admin']));

                    if (!hasPermission(userRoles, ['admin'])) {
                        message.error('只有管理员有权限查看操作日志！');
                        // 延迟一下跳转，让用户能看到消息
                        setTimeout(() => {
                            navigate('/');
                        }, 2000);
                    } else {
                        fetchLogs();
                    }
                }
            } catch (e) {
                console.error('解析 JWT 时出错:', e);
                message.error('权限验证失败');
                setTimeout(() => {
                    navigate('/');
                }, 2000);
            }
        } else {
            message.error('请先登录系统');
            setTimeout(() => {
                navigate('/');
            }, 2000);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [navigate]);

    const handleTableChange = (newPagination, filters, sorter) => {
        const nextSortField = sorter.field || 'log_date';
        const nextSortOrder = sorter.order || 'descend';
        setSortField(nextSortField);
        setSortOrder(nextSortOrder);
        fetchLogs(newPagination, nextSortField, nextSortOrder);
    };

    const columns = [
        {
            title: '日期',
            dataIndex: 'log_date',
            key: 'log_date',
            sorter: true,
            sortOrder: sortField === 'log_date' ? sortOrder : null,
            width: 180,
        },
        {
            title: '操作说明',
            dataIndex: 'desc',
            key: 'desc',
            ellipsis: true,
        },
        {
            title: '操作用户',
            dataIndex: 'user_name',
            key: 'user_name',
            width: 150,
            render: (name) => name ? <Text strong>{name}</Text> : '-',
        },
        {
            title: '用户角色',
            dataIndex: 'user_role',
            key: 'user_role',
            width: 120,
            render: (role) => role ? <Tag color={role === 'admin' ? 'red' : 'blue'}>{role}</Tag> : '-',
        },
        {
            title: 'PC名称',
            dataIndex: 'pc_name',
            key: 'pc_name',
            sorter: true,
            sortOrder: sortField === 'pc_name' ? sortOrder : null,
            width: 150,
        },
        {
            title: 'IP地址',
            dataIndex: 'ip',
            key: 'ip',
            width: 140,
        },
        {
            title: '请求方法',
            dataIndex: 'method',
            key: 'method',
            width: 100,
            render: (method) => {
                let color = 'blue';
                if (method === 'POST') color = 'green';
                if (method === 'DELETE') color = 'red';
                if (method === 'PUT') color = 'orange';
                return <Tag color={color}>{method}</Tag>;
            }
        }
    ];

    const expandedRowRender = (record) => {
        return (
            <Space direction="vertical" style={{ width: '100%' }}>
                {/*{record.args && record.args.length > 0 && (*/}
                {/*    <Collapse ghost>*/}
                {/*        <Panel header="参数 (args)" key="args">*/}
                {/*            <pre>{JSON.stringify(record.args, null, 2)}</pre>*/}
                {/*        </Panel>*/}
                {/*    </Collapse>*/}
                {/*)}*/}

                {record.kwargs && Object.keys(record.kwargs).length > 0 && (
                    <Collapse ghost>
                        <Panel header="关键字参数 (kwargs)" key="kwargs">
                            <pre>{JSON.stringify(record.kwargs, null, 2)}</pre>
                        </Panel>
                    </Collapse>
                )}

                {record.json && Object.keys(record.json).length > 0 && (
                    <Collapse ghost>
                        <Panel header="JSON数据" key="json">
                            <pre>{JSON.stringify(record.json, null, 2)}</pre>
                        </Panel>
                    </Collapse>
                )}
            </Space>
        );
    };

    if (!isAdmin) {
        return (
            <Card style={{ marginTop: '20px' }}>
                <Empty
                    description="无权限查看操作日志"
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                />
            </Card>
        );
    }

    return (
        <Card>
            <Title level={4}>系统操作日志</Title>
            <Table
                columns={columns}
                dataSource={logs}
                rowKey={(record) => record.id ?? record.key}
                pagination={pagination}
                loading={tableLoading}
                onChange={handleTableChange}
                expandable={{
                    expandedRowRender,
                    rowExpandable: (record) =>
                        (record.kwargs && Object.keys(record.kwargs).length > 0) ||
                        (record.json && Object.keys(record.json).length > 0),
                }}
                scroll={{ x: 1200 }}
            />
        </Card>
    );
}

function LogIcon() {
    return <PicCenterOutlined />
}

export { LogIcon }
