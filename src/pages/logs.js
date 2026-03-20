import React, {useEffect, useState} from 'react'
import {PicCenterOutlined} from "@ant-design/icons";
import {Table, Typography, Card, Space, Tag, Collapse, message, Empty} from "antd";
import {endpoint} from "../config";
import getSafeHeader from "../common/safeHeader"
import {useNavigate} from "react-router-dom";

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

    const fetchLogs = async () => {
        setTableLoading(true);
        try {
            const response = await (await fetch(`${endpoint}/logs`, {
                headers: getSafeHeader()
            })).json();
            console.log(response);
            const data = response.data.map((v, i) => ({...v, key: i })) || [];
            setLogs(data);
            setPagination({
                ...pagination,
                total: data.length,
            });
        } catch (error) {
            console.error('获取日志失败:', error);
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
                    // 检查用户角色是否为 boss
                    setIsAdmin(payload.role === 'admin');

                    if (payload.role !== 'admin') {
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
            console.log("abc");
            setTimeout(() => {
                navigate('/');
            }, 2000);
        }
    }, [navigate]);

    const handleTableChange = (newPagination, filters, sorter) => {
        setPagination({
            ...newPagination,
        });

        if (sorter.field) {
            setSortField(sorter.field);
            setSortOrder(sorter.order);
        }
    };

    // 本地排序函数
    const getSortedData = () => {
        // 复制一份日志数据避免直接修改原数据
        const sortedData = [...logs];

        if (sortField && sortOrder) {
            sortedData.sort((a, b) => {
                const fieldA = a[sortField];
                const fieldB = b[sortField];

                if (sortOrder === 'ascend') {
                    return fieldA > fieldB ? 1 : -1;
                } else {
                    return fieldA < fieldB ? 1 : -1;
                }
            });
        }

        return sortedData;
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
            <Card style={{marginTop: '20px'}}>
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
                dataSource={getSortedData()}
                rowKey={(record) => record.key}
                pagination={pagination}
                loading={tableLoading}
                onChange={handleTableChange}
                expandable={{
                    expandedRowRender,
                    rowExpandable: (record) =>
                        (record.kwargs && Object.keys(record.kwargs).length > 0) ||
                        (record.json && Object.keys(record.json).length > 0),
                }}
                scroll={{ x: 1000 }}
            />
        </Card>
    );
}

function LogIcon (){
    return <PicCenterOutlined />
}

export {LogIcon}