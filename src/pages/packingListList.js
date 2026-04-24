import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
    Table,
    Card,
    Input,
    Select,
    Button,
    Space,
    Tag,
    Typography,
    message,
    Grid,
    Checkbox
} from 'antd';
import {
    SearchOutlined,
    EyeOutlined,
    PrinterOutlined,
    ReloadOutlined
} from '@ant-design/icons';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';

const { Title, Text } = Typography;
const { Option } = Select;

const BOX_STATUS = {
    PENDING_ASSIGN: 'pending_assign',
    PENDING_OUTBOUND: 'pending_outbound',
    OUTBOUND: 'outbound'
};

const BOX_STATUS_META = {
    [BOX_STATUS.PENDING_ASSIGN]: { text: '待分配', color: 'gold', level: 0 },
    [BOX_STATUS.PENDING_OUTBOUND]: { text: '待出库', color: 'blue', level: 1 },
    [BOX_STATUS.OUTBOUND]: { text: '已出库', color: 'green', level: 2 }
};

const PACKING_DRAFT_META = { text: '草稿', color: 'default', level: -1 };

const getMarkText = (record) => record?.list_number || record?.mark || '-';

const normalizeBoxStatus = (box) => {
    const raw = String(box?.status ?? '').trim().toLowerCase();
    if (raw === '1' || raw === BOX_STATUS.OUTBOUND) {
        return BOX_STATUS.OUTBOUND;
    }

    const hasOrder = !!box?.target_order_uid;
    if (!hasOrder) {
        return BOX_STATUS.PENDING_ASSIGN;
    }
    return BOX_STATUS.PENDING_OUTBOUND;
};

const getBoxStatusMeta = (box) => {
    const code = normalizeBoxStatus(box);
    return BOX_STATUS_META[code] || BOX_STATUS_META[BOX_STATUS.PENDING_ASSIGN];
};

const getPackingListStatusMeta = (record) => {
    if (record?.status === 'draft') {
        return PACKING_DRAFT_META;
    }

    const boxes = Array.isArray(record?.boxes) ? record.boxes : [];
    if (boxes.length === 0) return BOX_STATUS_META[BOX_STATUS.PENDING_ASSIGN];

    const minLevel = boxes.reduce((min, box) => {
        const meta = getBoxStatusMeta(box);
        return Math.min(min, meta.level);
    }, Number.MAX_SAFE_INTEGER);

    const matched = Object.values(BOX_STATUS_META).find((meta) => meta.level === minLevel);
    return matched || BOX_STATUS_META[BOX_STATUS.PENDING_ASSIGN];
};

export default function PackingListList() {
    const [messageApi, contextHolder] = message.useMessage();
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();
    const screens = Grid.useBreakpoint();

    // 数据状态
    const [packingLists, setPackingLists] = useState([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);

    // 筛选状态
    const [page, setPage] = useState(parseInt(searchParams.get('page')) || 1);
    const [pageSize, setPageSize] = useState(parseInt(searchParams.get('pageSize')) || 20);
    const [search, setSearch] = useState(searchParams.get('search') || '');
    const [status, setStatus] = useState(() => {
        const urlStatus = searchParams.get('status');
        if (urlStatus) return urlStatus.split(',');
        return typeof window !== 'undefined' && window.innerWidth < 768 ? ['待出库'] : ['草稿'];
    });
    const [excludeStatus, setExcludeStatus] = useState(() => {
        const urlExclude = searchParams.get('excludeStatus');
        if (urlExclude !== null) return urlExclude === 'true';
        return typeof window !== 'undefined' && window.innerWidth < 768 ? false : true;
    });
    const [shakeCount, setShakeCount] = useState(0);

    // 同步状态到 URL
    useEffect(() => {
        const params = new URLSearchParams();
        if (page !== 1) params.set('page', page);
        if (pageSize !== 20) params.set('pageSize', pageSize);
        if (search) params.set('search', search);
        if (status && status.length > 0) params.set('status', status.join(','));
        params.set('excludeStatus', excludeStatus);
        setSearchParams(params, { replace: true });
    }, [page, pageSize, search, status, excludeStatus, setSearchParams]);

    useEffect(() => {
        fetchPackingLists();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [page, pageSize]);

    const fetchPackingLists = async () => {
        setLoading(true);
        try {
            const params = new URLSearchParams({
                p: page,
                s: pageSize,
                ...(search && { q: search })
            });

            const res = await fetch(`${endpoint}/packing-lists?${params}`, {
                headers: getSafeHeader()
            });
            const data = await res.json();

            if (data.code === 200) {
                setPackingLists(data.data.items || []);
                setTotal(data.data.total || 0);
            } else {
                messageApi.error(data.msg || '获取数据失败');
            }
        } catch (error) {
            messageApi.error('获取装箱单列表失败');
            console.error(error);
        } finally {
            setLoading(false);
        }
    };

    const handleSearch = () => {
        setPage(1);
        fetchPackingLists();
    };

    const handleViewDetail = (uid) => {
        navigate(`/packing-lists/${uid}`);
    };

    const handlePrintLabels = (boxes) => {
        // 批量打印所有箱子标签
        boxes.forEach(box => {
            window.open(`${endpoint}/box/${box.uid}/label`, '_blank');
        });
    };

    const columns = [
        {
            title: '唛头',
            key: 'mark',
            width: 180,
            render: (_, record) => (
                <Button
                    type="link"
                    onClick={() => handleViewDetail(record.uid)}
                    style={{ padding: 0, fontWeight: 'bold' }}
                >
                    {getMarkText(record)}
                </Button>
            )
        },
        {
            title: '客户名',
            dataIndex: 'customer_name',
            key: 'customer_name',
            width: 150
        },
        {
            title: '箱子数',
            dataIndex: 'boxes',
            key: 'box_count',
            width: 100,
            render: (boxes) => boxes?.length || 0
        },
        {
            title: '总重量',
            dataIndex: 'boxes',
            key: 'total_weight',
            width: 120,
            render: (boxes) => {
                const total = (boxes || []).reduce((sum, b) => sum + (b.weight || 0), 0);
                return `${total.toFixed(2)} kg`;
            }
        },
        {
            title: '状态',
            key: 'status',
            width: 100,
            render: (_, record) => {
                const s = getPackingListStatusMeta(record);
                return <Tag color={s.color}>{s.text}</Tag>;
            }
        },
        {
            title: '创建人',
            dataIndex: 'creator_name',
            key: 'creator_name',
            width: 100,
            responsive: ['md']
        },
        {
            title: '创建时间',
            dataIndex: 'create_date',
            key: 'create_date',
            width: 160,
            responsive: ['md']
        },
        {
            title: '操作',
            key: 'action',
            width: 150,
            render: (_, record) => (
                <Space>
                    <Button
                        type="link"
                        icon={<PrinterOutlined />}
                        onClick={() => handlePrintLabels(record.boxes || [])}
                        disabled={!record.boxes || record.boxes.length === 0}
                        style={{ paddingLeft: 0 }}
                    >
                        打印
                    </Button>
                </Space>
            )
        }
    ];

    const filteredPackingLists = (packingLists || []).filter((record) => {
        if (!status || status.length === 0) return true;
        const meta = getPackingListStatusMeta(record);
        const inSelected = status.includes(meta.text);
        return excludeStatus ? !inSelected : inSelected;
    });

    return (
        <div style={{ padding: screens.md ? '24px' : '12px' }}>
            {contextHolder}

            <Title level={screens.md ? 2 : 4} style={{ marginBottom: 16 }}>装箱单列表</Title>

            {/* 搜索筛选 */}
            <Card style={{ marginBottom: 16 }} bodyStyle={screens.md ? {} : { padding: 12 }}>
                <Space wrap style={{ width: '100%' }}>
                    <Input
                        placeholder="搜索唛头或客户名"
                        prefix={<SearchOutlined />}
                        value={search}
                        onChange={(e) => {
                            setSearch(e.target.value);
                            console.log('a')
                            handleSearch();
                        }}
                        // onPressEnter={handleSearch}
                        style={{ width: 250 }}
                    />
                    <Select
                        mode="multiple"
                        placeholder="状态"
                        allowClear
                        value={status}
                        onChange={setStatus}
                        maxTagCount={1}
                        style={{ minWidth: 150, maxWidth: 220 }}
                    >
                        <Option value="草稿">草稿</Option>
                        <Option value="待分配">待分配</Option>
                        <Option value="待出库">待出库</Option>
                        <Option value="已出库">已出库</Option>
                    </Select>
                    <Checkbox
                        checked={excludeStatus}
                        onChange={(e) => setExcludeStatus(e.target.checked)}
                    >
                        排除所选状态
                    </Checkbox>
                    <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
                        搜索
                    </Button>
                    <Button icon={<ReloadOutlined />} onClick={() => {
                        setSearch('');
                        setStatus(window.innerWidth < 768 ? ['待出库'] : ['待分配']);
                        setExcludeStatus(false);
                        setPage(1);
                        fetchPackingLists();
                    }}>
                        重置
                    </Button>
                </Space>
            </Card>

            {/* 数据表格 */}
            <Card bodyStyle={screens.md ? {} : { padding: 0 }}>
                <Table
                    dataSource={filteredPackingLists}
                    columns={columns}
                    rowKey="uid"
                    loading={loading}
                    scroll={{ x: 800 }}
                    pagination={{
                        current: page,
                        pageSize: pageSize,
                        total: (status && status.length > 0) ? filteredPackingLists.length : total,
                        showSizeChanger: true,
                        showQuickJumper: true,
                        showTotal: (total) => `共 ${total} 条`,
                        onChange: (p, ps) => {
                            setPage(p);
                            setPageSize(ps);
                        }
                    }}
                />
            </Card>
        </div>
    );
}
