import React, { useEffect, useMemo, useState } from 'react';
import {
    Button,
    Card,
    Input,
    Select,
    Table,
    Tag,
    Typography,
    message,
    Row,
    Col,
    Statistic
} from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useSearchParams } from 'react-router-dom';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import { hasPermission } from '../common/roleConfig';

const { Title } = Typography;

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

export default function WorkDetails() {
    const [searchParams] = useSearchParams();
    const [messageApi, contextHolder] = message.useMessage();

    const [payload, setPayload] = useState({});
    const [month, setMonth] = useState(() => searchParams.get('month') || getCurrentMonth());

    const [workers, setWorkers] = useState([]);
    const [selectedWorkerId, setSelectedWorkerId] = useState(undefined);

    const [loading, setLoading] = useState(false);
    const [detailData, setDetailData] = useState(null);

    const userRoles = useMemo(
        () => payload?.roles || (payload?.role ? [payload.role] : []),
        [payload]
    );
    const currentUserId = payload?.user_id;
    const canSelectWorker = hasPermission(userRoles, ['admin', 'finance']);

    const selectedWorkerOptions = useMemo(
        () => workers.map(worker => ({ label: `${worker.name} (${worker.phone || '-'})`, value: worker.id })),
        [workers]
    );

    useEffect(() => {
        setPayload(getJwtPayload());
    }, []);

    useEffect(() => {
        const queryMonth = searchParams.get('month');
        if (queryMonth) {
            setMonth(queryMonth);
        }

        const queryWorkerId = searchParams.get('worker_id');
        if (queryWorkerId) {
            const parsed = Number(queryWorkerId);
            if (!Number.isNaN(parsed) && parsed > 0) {
                setSelectedWorkerId(parsed);
            }
        }
    }, [searchParams]);

    useEffect(() => {
        if (!canSelectWorker) return;

        (async () => {
            try {
                const res = await fetch(`${endpoint}/work/workers`, { headers: getSafeHeader() });
                const data = await res.json();
                if (data.code === 200) {
                    const list = data.data || [];
                    setWorkers(list);
                    const queryWorkerId = Number(searchParams.get('worker_id'));
                    const hasQueryWorker = !Number.isNaN(queryWorkerId) && queryWorkerId > 0;

                    if (hasQueryWorker && list.some(worker => worker.id === queryWorkerId)) {
                        setSelectedWorkerId(queryWorkerId);
                    } else if (!selectedWorkerId && list.length > 0) {
                        setSelectedWorkerId(list[0].id);
                    }
                }
            } catch (error) {
                console.error(error);
            }
        })();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [canSelectWorker, searchParams]);

    const fetchDetails = async () => {
        if (!userRoles.length) return;

        const params = new URLSearchParams({ month });
        if (canSelectWorker && selectedWorkerId) {
            params.set('worker_id', String(selectedWorkerId));
        }

        setLoading(true);
        try {
            const res = await fetch(`${endpoint}/work/details?${params.toString()}`, {
                headers: getSafeHeader()
            });
            const data = await res.json();

            if (data.code === 200) {
                setDetailData(data.data);
            } else {
                messageApi.error(data.msg || '获取工作详情失败');
            }
        } catch (error) {
            messageApi.error('获取工作详情失败');
            console.error(error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (!userRoles.length) return;
        if (canSelectWorker && !selectedWorkerId) return;
        if (!canSelectWorker && !currentUserId) return;
        fetchDetails();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [userRoles, currentUserId, canSelectWorker, selectedWorkerId, month]);

    const groupColumns = [
        {
            title: '日期',
            dataIndex: 'create_date',
            key: 'create_date',
            width: 140,
            render: (value) => (value ? String(value).slice(0, 10) : '-')
        },
        {
            title: '唛头',
            dataIndex: 'mark',
            key: 'mark',
            width: 180
        },
        {
            title: '箱数',
            dataIndex: 'box_count',
            key: 'box_count',
            width: 80,
            align: 'right'
        },
        {
            title: '装箱单总重量(kg)',
            dataIndex: 'total_weight',
            key: 'total_weight',
            width: 140,
            align: 'right',
            render: (value) => Number(value || 0).toFixed(2)
        }
    ];

    const boxColumns = [
        {
            title: '箱号',
            dataIndex: 'box_number',
            key: 'box_number',
            width: 80,
            align: 'center'
        },
        {
            title: '品名',
            dataIndex: 'item_name',
            key: 'item_name',
            ellipsis: true
        },
        {
            title: '重量(kg)',
            dataIndex: 'weight',
            key: 'weight',
            width: 120,
            align: 'right',
            render: (value) => Number(value || 0).toFixed(2)
        },
        {
            title: '合打人数',
            dataIndex: 'worker_count',
            key: 'worker_count',
            width: 110,
            align: 'center',
            render: (value) => <Tag color="blue">{value || 0} 人</Tag>
        }
    ];

    const groups = (detailData?.groups || []).map(group => ({
        ...group,
        key: group.packing_list_uid
    }));

    return (
        <div style={{ padding: '8px 16px' }}>
            {contextHolder}
            <Title level={4} style={{ marginBottom: 16 }}>我的工作详情</Title>

            <Card style={{ marginBottom: 16 }} size="small" bodyStyle={{ padding: '12px' }}>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    <Input
                        type="month"
                        value={month}
                        onChange={(e) => setMonth(e.target.value || getCurrentMonth())}
                        style={{ width: 140 }}
                    />
                    {canSelectWorker && (
                        <Select
                            style={{ minWidth: 160, flex: 1 }}
                            placeholder="选择操作人员"
                            options={selectedWorkerOptions}
                            value={selectedWorkerId}
                            onChange={setSelectedWorkerId}
                            showSearch
                            optionFilterProp="label"
                        />
                    )}
                    <Button type="primary" icon={<ReloadOutlined />} onClick={fetchDetails}>查询</Button>
                </div>
            </Card>

            <Card style={{ marginBottom: 16 }} size="small">
                <Row gutter={[8, 16]}>
                    <Col xs={12} sm={8}>
                        <Statistic title="总箱数" value={detailData?.total_boxes || 0} />
                    </Col>
                    {/* <Col xs={12} sm={8}>
                        <Statistic title="总件数" value={detailData?.total_piece_count || 0} />
                    </Col> */}
                    {/* <Col xs={24} sm={8}>
                        <Statistic title="总重量(kg)" value={Number(detailData?.total_weight || 0).toFixed(2)} />
                    </Col> */}
                </Row>
            </Card>

            <Card size="small" bodyStyle={{ padding: 0 }}>
                <Table
                    rowKey="key"
                    loading={loading}
                    dataSource={groups}
                    columns={groupColumns}
                    pagination={{ pageSize: 20, showSizeChanger: true }}
                    expandable={{
                        expandedRowRender: (record) => (
                            <Table
                                rowKey="box_uid"
                                columns={boxColumns}
                                dataSource={record.boxes || []}
                                pagination={false}
                                size="small"
                            />
                        )
                    }}
                    scroll={{ x: 'max-content' }}
                    size="small"
                />
            </Card>
        </div>
    );
}
