import React, { useState, useEffect } from 'react';
import {
    Table,
    Card,
    Input,
    InputNumber,
    Select,
    Button,
    Space,
    Tag,
    Typography,
    message,
    Modal,
    Descriptions,
    Image,
    List,
    Form,
    Grid,
    Checkbox
} from 'antd';
import {
    SearchOutlined,
    EyeOutlined,
    PrinterOutlined,
    ReloadOutlined,
    PlusOutlined,
    CheckOutlined,
    DeleteOutlined,
    EditOutlined
} from '@ant-design/icons';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';

const { Title, Text } = Typography;
const { Option } = Select;

const BOX_STATUS = {
    PENDING_ASSIGN: 'pending_assign',
    PENDING_UPLOAD: 'pending_upload',
    PENDING_OUTBOUND: 'pending_outbound',
    OUTBOUND: 'outbound'
};

const BOX_STATUS_META = {
    [BOX_STATUS.PENDING_ASSIGN]: { text: '待分配', color: 'gold', level: 0 },
    [BOX_STATUS.PENDING_UPLOAD]: { text: '待上传', color: 'orange', level: 1 },
    [BOX_STATUS.PENDING_OUTBOUND]: { text: '待出库', color: 'blue', level: 2 },
    [BOX_STATUS.OUTBOUND]: { text: '已出库', color: 'green', level: 3 }
};

const PACKING_DRAFT_META = { text: '草稿', color: 'default', level: -1 };

const getMarkText = (record) => record?.list_number || record?.mark || '-';

const normalizeCustomerId = (value) => {
    if (value === undefined || value === null || value === '') return null;
    const n = Number(value);
    return Number.isNaN(n) ? null : n;
};

const getBoxItemDetails = (box) => {
    const details = Array.isArray(box?.item_details) ? box.item_details : [];
    if (details.length > 0) {
        return details
            .map((row) => {
                const name = (row?.item_name || '').trim();
                const piece = Number(row?.piece_count || 0);
                if (!name) return null;
                return { item_name: name, piece_count: piece > 0 ? piece : 0 };
            })
            .filter(Boolean);
    }

    const fallbackName = (box?.item_name || '').trim();
    const fallbackPiece = Number(box?.piece_count || 0);
    return fallbackName
        ? [{ item_name: fallbackName, piece_count: fallbackPiece > 0 ? fallbackPiece : 0 }]
        : [];
};

const normalizeBoxStatus = (box) => {
    const raw = String(box?.status ?? '').trim().toLowerCase();
    if (raw === '1' || raw === BOX_STATUS.OUTBOUND) {
        return BOX_STATUS.OUTBOUND;
    }

    const hasOrder = !!box?.target_order_uid;
    const hasWaybill = !!String(box?.waybill_id || '').trim();
    if (!hasOrder) {
        return BOX_STATUS.PENDING_ASSIGN;
    }
    if (!hasWaybill) {
        return BOX_STATUS.PENDING_UPLOAD;
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

const renderBoxStatusTag = (box) => (
    <Tag color={getBoxStatusMeta(box).color}>{getBoxStatusMeta(box).text}</Tag>
);

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

export default function PackingListList() {
    const [messageApi, contextHolder] = message.useMessage();
    const [payload, setPayload] = useState({});
    const screens = Grid.useBreakpoint();

    // 数据状态
    const [packingLists, setPackingLists] = useState([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);

    // 筛选状态
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(20);
    const [search, setSearch] = useState('');
    const [status, setStatus] = useState(undefined);

    // 详情模态框
    const [detailVisible, setDetailVisible] = useState(false);
    const [currentDetail, setCurrentDetail] = useState(null);
    const [workers, setWorkers] = useState([]);
    const [customers, setCustomers] = useState([]);
    const [boxForm] = Form.useForm();
    const [addingBox, setAddingBox] = useState(false);
    const [completing, setCompleting] = useState(false);
    const [deleting, setDeleting] = useState(false);
    const [customerEditVisible, setCustomerEditVisible] = useState(false);
    const [editingCustomerId, setEditingCustomerId] = useState(null);
    const [savingCustomer, setSavingCustomer] = useState(false);
    const [shipping, setShipping] = useState(false);
    const [selectedShipBoxUids, setSelectedShipBoxUids] = useState([]);

    const canDeletePackingList = ['admin', 'store_manager'].includes(payload?.role);
    const canEditPackingListCustomer = ['admin', 'store_manager'].includes(payload?.role);
    const canShipBoxes = ['admin', 'store_manager', 'salesperson'].includes(payload?.role);

    useEffect(() => {
        setPayload(getJwtPayload());
    }, []);

    useEffect(() => {
        fetchPackingLists();
        fetchWorkers();
        fetchCustomers();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [page, pageSize]);

    useEffect(() => {
        setSelectedShipBoxUids([]);
    }, [currentDetail?.uid, detailVisible]);

    const fetchCustomers = async () => {
        try {
            const res = await fetch(`${endpoint}/customer_list`, {
                headers: getSafeHeader()
            });
            const data = await res.json();
            if (data.code === 200) {
                setCustomers(data.data || []);
            }
        } catch (error) {
            console.error('获取客户列表失败:', error);
        }
    };

    const fetchWorkers = async () => {
        try {
            const res = await fetch(`${endpoint}/users/list`, {
                headers: getSafeHeader()
            });
            const data = await res.json();
            if (data.code === 200) {
                setWorkers(data.data || []);
            }
        } catch (error) {
            console.error('获取操作员列表失败:', error);
        }
    };

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

    const handleViewDetail = async (uid) => {
        try {
            const res = await fetch(`${endpoint}/packing-list/${uid}`, {
                headers: getSafeHeader()
            });
            const data = await res.json();

            if (data.code === 200) {
                setCurrentDetail(data.data);
                setDetailVisible(true);
            } else {
                messageApi.error(data.msg || '获取详情失败');
            }
        } catch (error) {
            messageApi.error('获取详情失败');
            console.error(error);
        }
    };

    const handlePrintLabels = (boxes) => {
        // 批量打印所有箱子标签
        boxes.forEach(box => {
            window.open(`${endpoint}/box/${box.uid}/label`, '_blank');
        });
    };

    const handleAddBox = async () => {
        if (!currentDetail) return;
        try {
            const values = await boxForm.validateFields();
            setAddingBox(true);

            const res = await fetch(`${endpoint}/packing-list/${currentDetail.uid}/box`, {
                method: 'POST',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    item_name: values.item_name,
                    piece_count: values.piece_count,
                    weight: values.weight || null
                })
            });
            const data = await res.json();

            if (data.code === 200) {
                if (values.worker_ids && values.worker_ids.length > 0) {
                    await fetch(`${endpoint}/box/${data.data.uid}/workers`, {
                        method: 'PUT',
                        headers: {
                            ...getSafeHeader(),
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ worker_ids: values.worker_ids })
                    });
                }
                messageApi.success('箱子添加成功');
                boxForm.resetFields();
                handleViewDetail(currentDetail.uid); // 刷新详情
                fetchPackingLists(); // 刷新列表以更新箱子数和总重量
            } else {
                messageApi.error(data.msg || '添加失败');
            }
        } catch (error) {
            if (error.errorFields) return;
            messageApi.error('添加请求失败');
            console.error(error);
        } finally {
            setAddingBox(false);
        }
    };

    const handleCompleteCurrent = async () => {
        if (!currentDetail) return;

        const boxes = currentDetail.boxes || [];
        if (boxes.length === 0) {
            messageApi.warning('请至少添加一个箱子');
            return;
        }

        const unweighedBoxes = boxes.filter(b => !b.weight || b.weight <= 0);
        if (unweighedBoxes.length > 0) {
            messageApi.warning(`还有 ${unweighedBoxes.length} 个箱子未称重`);
            return;
        }

        setCompleting(true);
        try {
            const res = await fetch(`${endpoint}/packing-list/${currentDetail.uid}/complete`, {
                method: 'POST',
                headers: getSafeHeader()
            });
            const data = await res.json();

            if (data.code === 200) {
                messageApi.success('装箱单已提交');
                await handleViewDetail(currentDetail.uid);
                fetchPackingLists();
            } else {
                messageApi.error(data.msg || '提交失败');
            }
        } catch (error) {
            messageApi.error('提交失败');
            console.error(error);
        } finally {
            setCompleting(false);
        }
    };

    const handleDeleteCurrent = () => {
        if (!currentDetail) return;

        Modal.confirm({
            title: '确认删除该装箱单吗？',
            content: `唛头：${getMarkText(currentDetail)}。删除后不可恢复。`,
            okText: '删除',
            okType: 'danger',
            cancelText: '取消',
            onOk: async () => {
                setDeleting(true);
                try {
                    const res = await fetch(`${endpoint}/packing-list/${currentDetail.uid}`, {
                        method: 'DELETE',
                        headers: getSafeHeader()
                    });
                    const data = await res.json();

                    if (data.code === 200) {
                        messageApi.success('装箱单已删除');
                        setDetailVisible(false);
                        setCurrentDetail(null);
                        fetchPackingLists();
                    } else {
                        messageApi.error(data.msg || '删除失败');
                    }
                } catch (error) {
                    messageApi.error('删除失败');
                    console.error(error);
                } finally {
                    setDeleting(false);
                }
            }
        });
    };

    const openCustomerEditModal = () => {
        if (!currentDetail) return;
        setEditingCustomerId(currentDetail.customer_id ?? null);
        setCustomerEditVisible(true);
    };

    const handleUpdateCustomer = async () => {
        if (!currentDetail) return;

        const currentCustomerId = normalizeCustomerId(currentDetail.customer_id);
        const nextCustomerId = normalizeCustomerId(editingCustomerId);
        if (currentCustomerId === nextCustomerId) {
            messageApi.info('所属客户未变化，无需保存');
            setCustomerEditVisible(false);
            return;
        }

        setSavingCustomer(true);
        try {
            const res = await fetch(`${endpoint}/packing-list/${currentDetail.uid}`, {
                method: 'PUT',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ customer_id: editingCustomerId })
            });
            const data = await res.json();

            if (data.code === 200) {
                messageApi.success('所属客户已更新');
                setCustomerEditVisible(false);
                await handleViewDetail(currentDetail.uid);
                fetchPackingLists();
            } else {
                messageApi.error(data.msg || '更新客户失败');
            }
        } catch (error) {
            messageApi.error('更新客户失败');
            console.error(error);
        } finally {
            setSavingCustomer(false);
        }
    };

    const shipCandidates = (currentDetail?.boxes || []).filter(
        (box) => normalizeBoxStatus(box) === BOX_STATUS.PENDING_OUTBOUND
    );
    const allShipCandidateUids = shipCandidates.map((box) => box.uid);
    const selectedShipCount = selectedShipBoxUids.filter((uid) => allShipCandidateUids.includes(uid)).length;
    const isShipAllChecked = allShipCandidateUids.length > 0 && selectedShipCount === allShipCandidateUids.length;
    const isShipIndeterminate = selectedShipCount > 0 && selectedShipCount < allShipCandidateUids.length;

    const toggleShipBox = (boxUid, checked) => {
        setSelectedShipBoxUids((prev) => {
            if (checked) {
                return Array.from(new Set([...prev, boxUid]));
            }
            return prev.filter((uid) => uid !== boxUid);
        });
    };

    const toggleSelectAllShipBoxes = (checked) => {
        if (!checked) {
            setSelectedShipBoxUids((prev) => prev.filter((uid) => !allShipCandidateUids.includes(uid)));
            return;
        }
        setSelectedShipBoxUids((prev) => Array.from(new Set([...prev, ...allShipCandidateUids])));
    };

    const handleShipSelectedBoxes = async () => {
        if (!currentDetail?.uid) return;
        if (selectedShipCount === 0) {
            messageApi.warning('请先选择待出库的箱子');
            return;
        }

        setShipping(true);
        try {
            const boxUids = selectedShipBoxUids.filter((uid) => allShipCandidateUids.includes(uid));
            const res = await fetch(`${endpoint}/packing-list/${currentDetail.uid}/ship`, {
                method: 'POST',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ box_uids: boxUids })
            });
            const data = await res.json();

            if (data.code === 200) {
                const successCount = data.data?.success?.length || 0;
                const failedCount = data.data?.failed?.length || 0;
                if (failedCount > 0) {
                    messageApi.warning(`已出货 ${successCount} 箱，失败 ${failedCount} 箱`);
                } else {
                    messageApi.success(`已出货 ${successCount} 箱`);
                }
                setSelectedShipBoxUids([]);
                await handleViewDetail(currentDetail.uid);
                fetchPackingLists();
            } else {
                messageApi.error(data.msg || '出货失败');
            }
        } catch (error) {
            messageApi.error('出货失败');
            console.error(error);
        } finally {
            setShipping(false);
        }
    };

    const columns = [
        {
            title: '唛头',
            key: 'mark',
            width: 180,
            render: (_, record) => <Text strong>{getMarkText(record)}</Text>
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
            width: 100
        },
        {
            title: '创建时间',
            dataIndex: 'create_date',
            key: 'create_date',
            width: 160
        },
        {
            title: '操作',
            key: 'action',
            width: 150,
            render: (_, record) => (
                <Space>
                    <Button
                        type="link"
                        icon={<EyeOutlined />}
                        onClick={() => handleViewDetail(record.uid)}
                    >
                        详情
                    </Button>
                    <Button
                        type="link"
                        icon={<PrinterOutlined />}
                        onClick={() => handlePrintLabels(record.boxes || [])}
                        disabled={!record.boxes || record.boxes.length === 0}
                    >
                        打印
                    </Button>
                </Space>
            )
        }
    ];

    const filteredPackingLists = (packingLists || []).filter((record) => {
        if (!status) return true;
        const meta = getPackingListStatusMeta(record);
        return meta.text === status;
    });

    return (
        <div style={{ padding: '24px' }}>
            {contextHolder}

            <Title level={2}>装箱单列表</Title>

            {/* 搜索筛选 */}
            <Card style={{ marginBottom: 16 }}>
                <Space wrap>
                    <Input
                        placeholder="搜索唛头或客户名"
                        prefix={<SearchOutlined />}
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        onPressEnter={handleSearch}
                        style={{ width: 250 }}
                    />
                    <Select
                        placeholder="状态"
                        allowClear
                        value={status}
                        onChange={setStatus}
                        style={{ width: 130 }}
                    >
                        <Option value="草稿">草稿</Option>
                        <Option value="待分配">待分配</Option>
                        <Option value="待上传">待上传</Option>
                        <Option value="待出库">待出库</Option>
                        <Option value="已出库">已出库</Option>
                    </Select>
                    <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
                        搜索
                    </Button>
                    <Button icon={<ReloadOutlined />} onClick={() => {
                        setSearch('');
                        setStatus(undefined);
                        setPage(1);
                        fetchPackingLists();
                    }}>
                        重置
                    </Button>
                </Space>
            </Card>

            {/* 数据表格 */}
            <Card>
                <Table
                    dataSource={filteredPackingLists}
                    columns={columns}
                    rowKey="uid"
                    loading={loading}
                    pagination={{
                        current: page,
                        pageSize: pageSize,
                        total: status ? filteredPackingLists.length : total,
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

            {/* 详情模态框 */}
            <Modal
                title={`装箱单详情 - ${getMarkText(currentDetail)}`}
                open={detailVisible}
                onCancel={() => setDetailVisible(false)}
                footer={[
                    <Button key="close" onClick={() => setDetailVisible(false)}>
                        关闭
                    </Button>,
                    <Button
                        key="complete"
                        type="primary"
                        icon={<CheckOutlined />}
                        onClick={handleCompleteCurrent}
                        loading={completing}
                        style={{ display: currentDetail?.status === 'draft' ? 'inline-flex' : 'none' }}
                    >
                        提交装箱单
                    </Button>,
                    <Button
                        key="delete"
                        danger
                        icon={<DeleteOutlined />}
                        onClick={handleDeleteCurrent}
                        loading={deleting}
                        style={{ display: canDeletePackingList ? 'inline-flex' : 'none' }}
                    >
                        删除装箱单
                    </Button>,
                    <Button
                        key="print"
                        type="default"
                        icon={<PrinterOutlined />}
                        onClick={() => handlePrintLabels(currentDetail?.boxes || [])}
                    >
                        打印所有标签
                    </Button>
                ]}
                width={800}
            >
                {currentDetail && (
                    <>
                        <Descriptions bordered column={2} style={{ marginBottom: 16 }}>
                            <Descriptions.Item label="唛头">
                                <Text strong>{getMarkText(currentDetail)}</Text>
                            </Descriptions.Item>
                            <Descriptions.Item label="客户名">
                                <Space>
                                    <Text>{currentDetail.customer_name || '-'}</Text>
                                    {canEditPackingListCustomer && (
                                        <Button
                                            type="link"
                                            size="small"
                                            icon={<EditOutlined />}
                                            onClick={openCustomerEditModal}
                                            style={{ paddingInline: 0 }}
                                        >
                                            编辑
                                        </Button>
                                    )}
                                </Space>
                            </Descriptions.Item>
                            <Descriptions.Item label="状态">
                                <Tag color={getPackingListStatusMeta(currentDetail).color}>
                                    {getPackingListStatusMeta(currentDetail).text}
                                </Tag>
                            </Descriptions.Item>
                            <Descriptions.Item label="创建人">
                                {currentDetail.creator_name}
                            </Descriptions.Item>
                            <Descriptions.Item label="创建时间">
                                {currentDetail.create_date}
                            </Descriptions.Item>
                            <Descriptions.Item label="更新时间">
                                {currentDetail.update_date || '-'}
                            </Descriptions.Item>
                        </Descriptions>

                        {/* 照片 */}
                        {currentDetail.photos && currentDetail.photos.length > 0 && (
                            <div style={{ marginBottom: 16 }}>
                                <Title level={5}>照片</Title>
                                <Image.PreviewGroup>
                                    <Space wrap>
                                        {currentDetail.photos.map((url, idx) => (
                                            <Image
                                                key={idx}
                                                src={url}
                                                width={100}
                                                height={100}
                                                style={{ objectFit: 'cover' }}
                                            />
                                        ))}
                                    </Space>
                                </Image.PreviewGroup>
                            </div>
                        )}

                        {/* 箱子列表 */}
                        <div style={{ marginTop: 16, marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <Title level={5} style={{ margin: 0 }}>
                                箱子列表 ({currentDetail.boxes?.length || 0})
                            </Title>
                            {canShipBoxes && (
                                <Space size={8} wrap>
                                    <Checkbox
                                        checked={isShipAllChecked}
                                        indeterminate={isShipIndeterminate}
                                        disabled={allShipCandidateUids.length === 0}
                                        onChange={(e) => toggleSelectAllShipBoxes(e.target.checked)}
                                    >
                                        全选
                                    </Checkbox>
                                    <Button
                                        type="primary"
                                        onClick={handleShipSelectedBoxes}
                                        loading={shipping}
                                        disabled={selectedShipCount === 0}
                                    >
                                        出货已选({selectedShipCount})
                                    </Button>
                                </Space>
                            )}
                        </div>

                        {currentDetail.status === 'draft' && (
                            <Card size="small" style={{ marginBottom: 16, marginTop: 16 }}>
                                <Form form={boxForm} layout="inline">
                                    <Form.Item
                                        name="item_name"
                                        rules={[{ required: true, message: '请输入品名' }]}
                                    >
                                        <Input placeholder="品名" style={{ width: 150 }} />
                                    </Form.Item>
                                    <Form.Item
                                        name="piece_count"
                                        rules={[{ required: true, message: '请输入件数' }]}
                                    >
                                        <InputNumber
                                            placeholder="件数"
                                            min={1}
                                            precision={0}
                                            step={1}
                                            style={{ width: 90 }}
                                        />
                                    </Form.Item>
                                    <Form.Item name="weight">
                                        <InputNumber
                                            placeholder="重量(kg)"
                                            min={0.01}
                                            step={0.1}
                                            style={{ width: 100 }}
                                        />
                                    </Form.Item>
                                    <Form.Item name="worker_ids">
                                        <Select
                                            mode="multiple"
                                            placeholder="选择操作员"
                                            style={{ width: 220 }}
                                            maxTagCount={1}
                                        >
                                            {workers.map(w => (
                                                <Option key={w.id} value={w.id}>{w.name}</Option>
                                            ))}
                                        </Select>
                                    </Form.Item>
                                    <Form.Item>
                                        <Button
                                            type="primary"
                                            icon={<PlusOutlined />}
                                            onClick={handleAddBox}
                                            loading={addingBox}
                                        >
                                            添加
                                        </Button>
                                    </Form.Item>
                                </Form>
                            </Card>
                        )}

                        <List
                            bordered
                            style={{ marginTop: 12 }}
                            dataSource={currentDetail.boxes || []}
                            renderItem={(box, idx) => {
                                const itemDetails = getBoxItemDetails(box);
                                return (
                                    <List.Item
                                        actions={[
                                            <Button
                                                type="link"
                                                icon={<PrinterOutlined />}
                                                onClick={() => window.open(`${endpoint}/box/${box.uid}/label`, '_blank')}
                                            >
                                                打印
                                            </Button>,
                                            box.target_order_uid ? (
                                                <Button
                                                    type="link"
                                                    onClick={() => window.open(`/orders/${box.target_order_uid}`, '_blank')}
                                                >
                                                    所属订单{box.target_order_id ? `(${box.target_order_id})` : ''}
                                                </Button>
                                            ) : null
                                        ].filter(Boolean)}
                                    >
                                        {screens.md ? (
                                            <div style={{ display: 'flex', width: '100%', alignItems: 'flex-start', flexWrap: 'wrap', gap: '24px' }}>
                                                <div style={{ flex: '0 0 140px' }}>
                                                    <Space direction="vertical" size={6}>
                                                        {canShipBoxes && (
                                                            <Checkbox
                                                                checked={selectedShipBoxUids.includes(box.uid)}
                                                                disabled={normalizeBoxStatus(box) !== BOX_STATUS.PENDING_OUTBOUND}
                                                                onChange={(e) => toggleShipBox(box.uid, e.target.checked)}
                                                            >
                                                                选择出货
                                                            </Checkbox>
                                                        )}
                                                        <Text strong>箱子 {box.box_number || (idx + 1)}</Text>
                                                        {renderBoxStatusTag(box)}
                                                    </Space>
                                                </div>

                                                <div style={{ flex: '1 1 180px' }}>
                                                    <Text type="secondary" style={{ fontSize: '13px' }}>品名明细</Text>
                                                    <div style={{ marginTop: 4 }}>
                                                        {itemDetails.length > 0 ? (
                                                            itemDetails.map((row, itemIdx) => (
                                                                <div key={`${box.uid}-detail-${itemIdx}`}>
                                                                    <Text>{row.item_name}</Text>
                                                                    <Text type="secondary" style={{ marginLeft: 8 }}>x{row.piece_count}</Text>
                                                                </div>
                                                            ))
                                                        ) : (
                                                            <Text type="secondary">-</Text>
                                                        )}
                                                    </div>
                                                </div>

                                                <div style={{ flex: '0 0 120px' }}>
                                                    <Text type="secondary" style={{ fontSize: '13px' }}>统计</Text>
                                                    <Space direction="vertical" size={2} style={{ marginTop: 4, display: 'flex' }}>
                                                        <Text>总件数: <Text strong>{box.piece_count || 0}</Text></Text>
                                                        <Text>总重量: <Text strong>{box.weight ? `${box.weight} kg` : '未称重'}</Text></Text>
                                                    </Space>
                                                </div>

                                                <div style={{ flex: '1 1 150px' }}>
                                                    <Text type="secondary" style={{ fontSize: '13px' }}>备注</Text>
                                                    <div style={{ marginTop: 4 }}>
                                                        <Text>{(box.remark || '').trim() || '-'}</Text>
                                                    </div>
                                                </div>
                                            </div>
                                        ) : (
                                            <div style={{ display: 'flex', flexDirection: 'column', width: '100%', gap: '8px' }}>
                                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                                                    <Space size={8}>
                                                        {canShipBoxes && (
                                                            <Checkbox
                                                                checked={selectedShipBoxUids.includes(box.uid)}
                                                                disabled={normalizeBoxStatus(box) !== BOX_STATUS.PENDING_OUTBOUND}
                                                                onChange={(e) => toggleShipBox(box.uid, e.target.checked)}
                                                            />
                                                        )}
                                                        <Text strong style={{ fontSize: '15px' }}>箱号: {box.box_number || (idx + 1)}</Text>
                                                        {renderBoxStatusTag(box)}
                                                    </Space>
                                                    <Space size={12}>
                                                        <Text>重: <Text strong>{box.weight ? `${box.weight}kg` : '-'}</Text></Text>
                                                        <Text>件: <Text strong>{box.piece_count || 0}</Text></Text>
                                                    </Space>
                                                </div>

                                                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                                    <Text type="secondary" style={{ flexShrink: 0 }}>包含品名：</Text>
                                                    <Text>{itemDetails.length > 0 ? Array.from(new Set(itemDetails.map(r => r.item_name))).join('、') : '-'}</Text>
                                                </div>

                                                {box.remark?.trim() && (
                                                    <div style={{ display: 'flex', gap: '8px' }}>
                                                        <Text type="secondary" style={{ flexShrink: 0 }}>箱子备注：</Text>
                                                        <Text>{box.remark.trim()}</Text>
                                                    </div>
                                                )}
                                            </div>
                                        )}
                                    </List.Item>
                                );
                            }}
                        />

                        <div style={{ marginTop: 16, textAlign: 'right' }}>
                            <Text>
                                总重量: <Text strong>
                                    {(currentDetail.boxes || []).reduce((sum, b) => sum + (b.weight || 0), 0).toFixed(2)} kg
                                </Text>
                            </Text>
                        </div>
                    </>
                )}
            </Modal>

            <Modal
                title="修改所属客户"
                open={customerEditVisible}
                onCancel={() => setCustomerEditVisible(false)}
                onOk={handleUpdateCustomer}
                okText="保存"
                cancelText="取消"
                confirmLoading={savingCustomer}
                okButtonProps={{
                    disabled:
                        normalizeCustomerId(editingCustomerId) ===
                        normalizeCustomerId(currentDetail?.customer_id)
                }}
            >
                <div style={{ marginBottom: 8 }}>
                    <Text type="secondary">唛头：{getMarkText(currentDetail)}</Text>
                </div>
                <Select
                    showSearch
                    allowClear
                    placeholder="请选择客户"
                    style={{ width: '100%' }}
                    optionFilterProp="children"
                    value={editingCustomerId}
                    onChange={(value) => setEditingCustomerId(value ?? null)}
                >
                    {customers.map((customer) => (
                        <Option key={customer.id} value={customer.id}>{customer.name}</Option>
                    ))}
                </Select>
                {normalizeCustomerId(editingCustomerId) === normalizeCustomerId(currentDetail?.customer_id) && (
                    <div style={{ marginTop: 8 }}>
                        <Text type="secondary">当前未修改客户，保存按钮将不可用。</Text>
                    </div>
                )}
            </Modal>
        </div>
    );
}
