import React, { useEffect, useState } from 'react';
import {
    Button,
    Card,
    Col,
    Input,
    InputNumber,
    Row,
    Space,
    Table,
    Typography,
    message
} from 'antd';
import { ReloadOutlined, SaveOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';

const { Title, Text } = Typography;

function getCurrentMonth() {
    const now = new Date();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    return `${now.getFullYear()}-${month}`;
}

function getJwtPayload() {
    const token = localStorage.getItem('jwt');
    if (!token) return {};
    try {
        const parts = token.split('.');
        if (parts.length !== 3) return {};
        return JSON.parse(atob(parts[1]));
    } catch (_) {
        return {};
    }
}

export default function FinanceCenter() {
    const navigate = useNavigate();
    const [messageApi, contextHolder] = message.useMessage();

    const [payload, setPayload] = useState({});
    const [month, setMonth] = useState(getCurrentMonth());

    const [rates, setRates] = useState({ '1': 0, '2': 0, '3': 0, '4': 0 });
    const [savingRates, setSavingRates] = useState(false);

    const [overview, setOverview] = useState(null);
    const [loadingOverview, setLoadingOverview] = useState(false);

    const role = payload?.role;
    const canAccess = ['admin', 'finance'].includes(role);

    useEffect(() => {
        setPayload(getJwtPayload());
    }, []);

    const fetchRates = async () => {
        try {
            const res = await fetch(`${endpoint}/finance/bonus-rates`, { headers: getSafeHeader() });
            const data = await res.json();
            if (data.code === 200) {
                setRates(data.data || { '1': 0, '2': 0, '3': 0, '4': 0 });
            } else {
                messageApi.error(data.msg || '获取奖金基数失败');
            }
        } catch (error) {
            messageApi.error('获取奖金基数失败');
            console.error(error);
        }
    };

    const fetchOverview = async () => {
        setLoadingOverview(true);
        try {
            const params = new URLSearchParams({ month });
            const res = await fetch(`${endpoint}/finance/worker-bonus-overview?${params.toString()}`, {
                headers: getSafeHeader()
            });
            const data = await res.json();
            if (data.code === 200) {
                setOverview(data.data);
            } else {
                messageApi.error(data.msg || '获取汇总失败');
            }
        } catch (error) {
            messageApi.error('获取汇总失败');
            console.error(error);
        } finally {
            setLoadingOverview(false);
        }
    };

    useEffect(() => {
        if (!canAccess) return;
        fetchRates();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [canAccess]);

    useEffect(() => {
        if (!canAccess) return;
        fetchOverview();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [canAccess, month]);

    const handleSaveRates = async () => {
        setSavingRates(true);
        try {
            const payloadRates = {
                rates: {
                    '1': Number(rates['1'] || 0),
                    '2': Number(rates['2'] || 0),
                    '3': Number(rates['3'] || 0),
                    '4': Number(rates['4'] || 0)
                }
            };

            const res = await fetch(`${endpoint}/finance/bonus-rates`, {
                method: 'PUT',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payloadRates)
            });
            const data = await res.json();
            if (data.code === 200) {
                setRates(data.data || rates);
                messageApi.success('奖金基数已更新');
                fetchOverview();
            } else {
                messageApi.error(data.msg || '更新失败');
            }
        } catch (error) {
            messageApi.error('更新失败');
            console.error(error);
        } finally {
            setSavingRates(false);
        }
    };

    const columns = [
        { title: '工人', dataIndex: 'worker_name', key: 'worker_name', width: 140 },
        { title: '手机号', dataIndex: 'worker_phone', key: 'worker_phone', width: 140 },
        {
            title: '1人合打',
            key: 'c1',
            width: 100,
            align: 'right',
            render: (_, record) => record?.counts_by_team_size?.['1'] || 0
        },
        {
            title: '2人合打',
            key: 'c2',
            width: 100,
            align: 'right',
            render: (_, record) => record?.counts_by_team_size?.['2'] || 0
        },
        {
            title: '3人合打',
            key: 'c3',
            width: 100,
            align: 'right',
            render: (_, record) => record?.counts_by_team_size?.['3'] || 0
        },
        {
            title: '4人合打',
            key: 'c4',
            width: 100,
            align: 'right',
            render: (_, record) => record?.counts_by_team_size?.['4'] || 0
        },
        { title: '汇总件数(箱)', dataIndex: 'total_boxes', key: 'total_boxes', width: 120, align: 'right' },
        { title: '总件数', dataIndex: 'total_piece_count', key: 'total_piece_count', width: 120, align: 'right' },
        {
            title: '预计奖金',
            dataIndex: 'estimated_bonus',
            key: 'estimated_bonus',
            align: 'right',
            render: (value) => Number(value || 0).toFixed(2)
        },
        {
            title: '操作',
            key: 'action',
            width: 140,
            render: (_, record) => (
                <Button
                    type="link"
                    onClick={() => {
                        const params = new URLSearchParams({
                            worker_id: String(record.worker_id),
                            month
                        });
                        navigate(`/work-details?${params.toString()}`);
                    }}
                >
                    查看工作详情
                </Button>
            )
        }
    ];

    if (!canAccess) {
        return (
            <div style={{ padding: 24 }}>
                {contextHolder}
                <Card>
                    <Text>当前账号没有财务页面权限。</Text>
                </Card>
            </div>
        );
    }

    return (
        <div style={{ padding: 24 }}>
            {contextHolder}
            <Title level={3} style={{ marginBottom: 16 }}>财务</Title>

            <Card title="奖金基数设置" style={{ marginBottom: 16 }}>
                <Row gutter={16}>
                    {[1, 2, 3, 4].map(size => (
                        <Col key={size} xs={24} sm={12} md={6}>
                            <div style={{ marginBottom: 8 }}>{size}人合打基数</div>
                            <InputNumber
                                min={0}
                                step={0.1}
                                style={{ width: '100%' }}
                                value={rates[String(size)]}
                                onChange={(value) => {
                                    const nextValue = value ?? 0;
                                    setRates(prev => ({ ...prev, [String(size)]: nextValue }));
                                }}
                            />
                        </Col>
                    ))}
                </Row>
                <Space style={{ marginTop: 16 }}>
                    <Button type="primary" icon={<SaveOutlined />} loading={savingRates} onClick={handleSaveRates}>
                        保存基数
                    </Button>
                    <Button icon={<ReloadOutlined />} onClick={fetchRates}>重置</Button>
                </Space>
            </Card>

            <Card title="工人预计奖金汇总">
                <Space wrap style={{ marginBottom: 12 }}>
                    <Input
                        type="month"
                        value={month}
                        onChange={(e) => setMonth(e.target.value || getCurrentMonth())}
                        style={{ width: 160 }}
                    />
                    <Button icon={<ReloadOutlined />} onClick={fetchOverview}>刷新</Button>
                </Space>

                <Table
                    rowKey="worker_id"
                    loading={loadingOverview}
                    dataSource={overview?.items || []}
                    columns={columns}
                    pagination={{ pageSize: 20, showSizeChanger: true }}
                />

                <div style={{ marginTop: 12 }}>
                    <Space split={<span>|</span>} wrap>
                        <Text>总箱数: <Text strong>{overview?.totals?.total_boxes || 0}</Text></Text>
                        <Text>总件数: <Text strong>{overview?.totals?.total_piece_count || 0}</Text></Text>
                        <Text>
                            预计奖金汇总: <Text strong style={{ color: '#cf1322' }}>
                                {Number(overview?.totals?.estimated_bonus || 0).toFixed(2)}
                            </Text>
                        </Text>
                    </Space>
                </div>
            </Card>
        </div>
    );
}
