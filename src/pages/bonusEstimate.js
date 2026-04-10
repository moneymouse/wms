import React, { useEffect, useMemo, useState } from 'react';
import { Button, Card, Input, Select, Table, Typography, message, Row, Col, Statistic } from 'antd';
import { ReloadOutlined, DownloadOutlined } from '@ant-design/icons';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';

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

export default function BonusEstimate() {
    const [messageApi, contextHolder] = message.useMessage();

    const [payload, setPayload] = useState({});
    const [month, setMonth] = useState(getCurrentMonth());

    const [workers, setWorkers] = useState([]);
    const [selectedWorkerId, setSelectedWorkerId] = useState(undefined);

    const [loading, setLoading] = useState(false);
    const [estimateData, setEstimateData] = useState(null);

    const role = payload?.role;
    const currentUserId = payload?.user_id;
    const canSelectWorker = ['admin', 'finance'].includes(role);

    const selectedWorkerOptions = useMemo(
        () => workers.map(worker => ({ label: `${worker.name} (${worker.phone || '-'})`, value: worker.id })),
        [workers]
    );

    useEffect(() => {
        setPayload(getJwtPayload());
    }, []);

    useEffect(() => {
        if (!canSelectWorker) return;
        (async () => {
            try {
                const res = await fetch(`${endpoint}/work/workers`, { headers: getSafeHeader() });
                const data = await res.json();
                if (data.code === 200) {
                    const list = data.data || [];
                    setWorkers(list);
                    if (!selectedWorkerId && list.length > 0) {
                        setSelectedWorkerId(list[0].id);
                    }
                }
            } catch (error) {
                console.error(error);
            }
        })();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [canSelectWorker]);

    const fetchEstimate = async () => {
        if (!role) return;

        const params = new URLSearchParams({ month });
        if (canSelectWorker && selectedWorkerId) {
            params.set('worker_id', String(selectedWorkerId));
        }

        setLoading(true);
        try {
            const res = await fetch(`${endpoint}/work/bonus-estimate?${params.toString()}`, {
                headers: getSafeHeader()
            });
            const data = await res.json();
            if (data.code === 200) {
                setEstimateData(data.data);
            } else {
                messageApi.error(data.msg || '获取预计奖金失败');
            }
        } catch (error) {
            messageApi.error('获取预计奖金失败');
            console.error(error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (!role) return;
        if (canSelectWorker && !selectedWorkerId) return;
        if (!canSelectWorker && !currentUserId) return;
        fetchEstimate();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [role, currentUserId, canSelectWorker, selectedWorkerId, month]);

    const counts = estimateData?.counts_by_team_size || { '1': 0, '2': 0, '3': 0, '4': 0 };
    const rates = estimateData?.rates || { '1': 0, '2': 0, '3': 0, '4': 0 };

    const rows = [1, 2, 3, 4].map(size => {
        const key = String(size);
        const count = counts[key] || 0;
        const rate = Number(rates[key] || 0);
        return {
            key,
            teamLabel: `${size}人合打`,
            count,
            rate,
            amount: (count * rate).toFixed(2)
        };
    });

    const columns = [
        { title: '类型', dataIndex: 'teamLabel', key: 'teamLabel' },
        { title: '件数(箱)', dataIndex: 'count', key: 'count', align: 'right' },
        { title: '奖金基数', dataIndex: 'rate', key: 'rate', align: 'right' },
        { title: '小计', dataIndex: 'amount', key: 'amount', align: 'right' }
    ];

    const escapeCsv = (value) => {
        const str = String(value ?? '');
        if (/[",\n]/.test(str)) {
            return `"${str.replace(/"/g, '""')}"`;
        }
        return str;
    };

    const handleExportCsv = () => {
        if (!estimateData) {
            messageApi.warning('暂无可导出的数据');
            return;
        }

        const workerName = estimateData?.worker?.name || 'unknown';
        const csvRows = [];

        csvRows.push(['月份', month]);
        csvRows.push(['工人姓名', workerName]);
        csvRows.push(['手机号', estimateData?.worker?.phone || '']);
        csvRows.push([]);
        csvRows.push(['类型', '件数(箱)', '奖金基数', '小计']);

        rows.forEach(row => {
            csvRows.push([row.teamLabel, row.count, row.rate, row.amount]);
        });

        csvRows.push([]);
        csvRows.push(['总箱数', estimateData?.total_boxes || 0]);
        csvRows.push(['总件数', estimateData?.total_piece_count || 0]);
        csvRows.push(['预计总奖金', Number(estimateData?.estimated_bonus || 0).toFixed(2)]);

        const csvText = csvRows.map(line => line.map(escapeCsv).join(',')).join('\n');
        const blob = new Blob(['\ufeff' + csvText], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);

        const link = document.createElement('a');
        link.href = url;
        link.download = `bonus_estimate_${workerName}_${month}.csv`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    };

    return (
        <div style={{ padding: '8px 16px' }}>
            {contextHolder}
            <Title level={4} style={{ marginBottom: 16 }}>我的预计奖金</Title>

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
                    <Button type="primary" icon={<ReloadOutlined />} onClick={fetchEstimate}>查询</Button>
                    <Button icon={<DownloadOutlined />} onClick={handleExportCsv}>导出 CSV</Button>
                </div>
            </Card>

            <Card style={{ marginBottom: 16 }} size="small">
                <Row gutter={[8, 16]}>
                    <Col xs={12} sm={8}>
                        <Statistic title="总箱数" value={estimateData?.total_boxes || 0} />
                    </Col>
                    <Col xs={12} sm={8}>
                        <Statistic title="总件数" value={estimateData?.total_piece_count || 0} />
                    </Col>
                    <Col xs={24} sm={8}>
                        <Statistic
                            title="预计总奖金 (元)"
                            value={Number(estimateData?.estimated_bonus || 0).toFixed(2)}
                            valueStyle={{ color: '#cf1322', fontWeight: 'bold' }}
                        />
                    </Col>
                </Row>
            </Card>

            <Card size="small" bodyStyle={{ padding: 0 }}>
                <Table
                    rowKey="key"
                    loading={loading}
                    dataSource={rows}
                    columns={columns}
                    pagination={false}
                    scroll={{ x: 'max-content' }}
                    size="small"
                />
            </Card>
        </div>
    );
}
