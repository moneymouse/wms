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
    const [bonusData, setBonusData] = useState(null);

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

    const fetchBonus = async () => {
        if (!role) return;

        const params = new URLSearchParams({ month });
        if (canSelectWorker && selectedWorkerId) {
            params.set('worker_id', String(selectedWorkerId));
        }

        setLoading(true);
        try {
            const res = await fetch(`${endpoint}/work/bonus?${params.toString()}`, {
                headers: getSafeHeader()
            });
            const data = await res.json();
            if (data.code === 200) {
                setBonusData(data.data);
            } else {
                messageApi.error(data.msg || '获取奖金失败');
            }
        } catch (error) {
            messageApi.error('获取奖金失败');
            console.error(error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (!role) return;
        if (canSelectWorker && !selectedWorkerId) return;
        if (!canSelectWorker && !currentUserId) return;
        fetchBonus();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [role, currentUserId, canSelectWorker, selectedWorkerId, month]);

    const hasUnmatched = useMemo(() => {
        const daily = bonusData?.daily || [];
        return daily.some(row => Number(row?.by_item?.unmatched?.piece_count || 0) > 0);
    }, [bonusData]);

    const itemDefs = useMemo(() => {
        const defs = (bonusData?.bonus_items || []).map(item => ({
            key: String(item.id),
            label: item.label,
            base_amount: Number(item.base_amount || 0)
        }));
        if (hasUnmatched) {
            defs.push({
                key: 'unmatched',
                label: '未匹配分项',
                base_amount: 0
            });
        }
        return defs;
    }, [bonusData, hasUnmatched]);

    const rows = (bonusData?.daily || []).map(dayRow => {
        const row = {
            key: dayRow.date,
            date: dayRow.date,
            total_piece_count: dayRow.total_piece_count || 0,
            total_boxes: dayRow.total_boxes || 0,
            estimated_bonus: Number(dayRow.estimated_bonus || 0).toFixed(2)
        };

        itemDefs.forEach(item => {
            row[`piece_${item.key}`] = dayRow?.by_item?.[item.key]?.piece_count || 0;
        });

        return row;
    });

    const columns = [
        {
            title: '日期',
            dataIndex: 'date',
            key: 'date',
            width: 130
        },
        ...itemDefs.map(item => ({
            title: `${item.label}件数`,
            dataIndex: `piece_${item.key}`,
            key: `piece_${item.key}`,
            width: 120,
            align: 'right'
        })),
        {
            title: '汇总件数',
            dataIndex: 'total_piece_count',
            key: 'total_piece_count',
            width: 120,
            align: 'right'
        },
        {
            title: '汇总箱数',
            dataIndex: 'total_boxes',
            key: 'total_boxes',
            width: 120,
            align: 'right'
        },
        {
            title: '预计奖金(元)',
            dataIndex: 'estimated_bonus',
            key: 'estimated_bonus',
            width: 130,
            align: 'right'
        }
    ];

    const escapeCsv = (value) => {
        const str = String(value ?? '');
        if (/[",\n]/.test(str)) {
            return `"${str.replace(/"/g, '""')}"`;
        }
        return str;
    };

    const handleExportCsv = () => {
        if (!bonusData) {
            messageApi.warning('暂无可导出的数据');
            return;
        }

        const workerName = bonusData?.worker?.name || 'unknown';
        const csvRows = [];

        csvRows.push(['月份', month]);
        csvRows.push(['工人姓名', workerName]);
        csvRows.push(['手机号', bonusData?.worker?.phone || '']);
        csvRows.push([]);

        csvRows.push(['奖金分项基数']);
        csvRows.push(['分项', '基数']);
        (bonusData?.bonus_items || []).forEach(item => {
            csvRows.push([item.label, Number(item.base_amount || 0).toFixed(2)]);
        });

        csvRows.push([]);

        const header = ['日期', ...itemDefs.map(item => `${item.label}件数`), '汇总件数', '汇总箱数', '预计奖金(元)'];
        csvRows.push(header);
        rows.forEach(row => {
            csvRows.push([
                row.date,
                ...itemDefs.map(item => row[`piece_${item.key}`]),
                row.total_piece_count,
                row.total_boxes,
                row.estimated_bonus
            ]);
        });

        csvRows.push([]);
        csvRows.push(['总箱数', bonusData?.totals?.total_boxes || 0]);
        csvRows.push(['总件数', bonusData?.totals?.total_piece_count || 0]);
        csvRows.push(['预计总奖金', Number(bonusData?.totals?.estimated_bonus || 0).toFixed(2)]);

        const csvText = csvRows.map(line => line.map(escapeCsv).join(',')).join('\n');
        const blob = new Blob(['\ufeff' + csvText], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);

        const link = document.createElement('a');
        link.href = url;
        link.download = `bonus_${workerName}_${month}.csv`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    };

    return (
        <div style={{ padding: '8px 16px' }}>
            {contextHolder}
            <Title level={4} style={{ marginBottom: 16 }}>我的奖金</Title>

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
                    <Button type="primary" icon={<ReloadOutlined />} onClick={fetchBonus}>查询</Button>
                    <Button icon={<DownloadOutlined />} onClick={handleExportCsv}>导出 CSV</Button>
                </div>
            </Card>

            <Card style={{ marginBottom: 16 }} size="small">
                <Row gutter={[8, 16]}>
                    <Col xs={12} sm={8}>
                        <Statistic title="总箱数" value={bonusData?.totals?.total_boxes || 0} />
                    </Col>
                    <Col xs={12} sm={8}>
                        <Statistic title="总件数" value={bonusData?.totals?.total_piece_count || 0} />
                    </Col>
                    <Col xs={24} sm={8}>
                        <Statistic
                            title="预计总奖金 (元)"
                            value={Number(bonusData?.totals?.estimated_bonus || 0).toFixed(2)}
                            valueStyle={{ color: '#cf1322', fontWeight: 'bold' }}
                        />
                    </Col>
                </Row>
            </Card>

            <Card title="奖金分项基数" size="small" style={{ marginBottom: 16 }}>
                <Row gutter={[8, 16]}>
                    {(bonusData?.bonus_items || []).map(item => (
                        <Col key={item.id} xs={12} sm={8} md={6}>
                            <Statistic
                                title={item.label}
                                value={Number(item.base_amount || 0).toFixed(2)}
                                suffix="元/箱"
                            />
                        </Col>
                    ))}
                </Row>
            </Card>

            <Card size="small" bodyStyle={{ padding: 0 }}>
                <Table
                    rowKey="key"
                    loading={loading}
                    dataSource={rows}
                    columns={columns}
                    pagination={{ pageSize: 20, showSizeChanger: true }}
                    scroll={{ x: 'max-content' }}
                    size="small"
                />
            </Card>
        </div>
    );
}
