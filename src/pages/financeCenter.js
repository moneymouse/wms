import React, { useEffect, useMemo, useState } from 'react';
import {
    Button,
    Card,
    Form,
    Input,
    InputNumber,
    Select,
    Space,
    Switch,
    Table,
    Typography,
    message,
    Modal
} from 'antd';
import { EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
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

const EMPTY_NEW_ITEM = {
    label: '',
    base_amount: 0,
    worker_count_rule: 1,
    weight_min: 0,
    weight_max: 0
};

export default function FinanceCenter() {
    const [messageApi, contextHolder] = message.useMessage();
    const [createForm] = Form.useForm();
    const [editForm] = Form.useForm();

    const [payload, setPayload] = useState({});
    const [month, setMonth] = useState(getCurrentMonth());
    const [markSearch, setMarkSearch] = useState('');

    const [workers, setWorkers] = useState([]);

    const [bonusItems, setBonusItems] = useState([]);
    const [loadingBonusItems, setLoadingBonusItems] = useState(false);
    const [savingItemIds, setSavingItemIds] = useState([]);
    const [creatingItem, setCreatingItem] = useState(false);
    const [newItem, setNewItem] = useState(EMPTY_NEW_ITEM);
    const [createModalVisible, setCreateModalVisible] = useState(false);
    const [editModalVisible, setEditModalVisible] = useState(false);
    const [editingItem, setEditingItem] = useState(null);

    const [pendingData, setPendingData] = useState({ items: [], total: 0 });
    const [loadingPending, setLoadingPending] = useState(false);
    const [allocatingPackingUid, setAllocatingPackingUid] = useState('');
    const [allocationModalVisible, setAllocationModalVisible] = useState(false);
    const [selectedPackingList, setSelectedPackingList] = useState(null);
    const [showOnlyIncompletePacking, setShowOnlyIncompletePacking] = useState(false);
    const [showOnlyIncompleteBoxes, setShowOnlyIncompleteBoxes] = useState(false);

    const [drafts, setDrafts] = useState({});

    const role = payload?.role;
    const canAccess = ['admin', 'finance'].includes(role);

    const workerOptions = useMemo(
        () => workers.map(worker => ({ label: `${worker.name} (${worker.phone || '-'})`, value: worker.id })),
        [workers]
    );

    const bonusItemOptions = useMemo(
        () => bonusItems.map(item => ({ label: `${item.label} (基数 ${Number(item.base_amount || 0).toFixed(2)})`, value: item.id })),
        [bonusItems]
    );

    useEffect(() => {
        setPayload(getJwtPayload());
    }, []);

    const fetchWorkers = async () => {
        try {
            const res = await fetch(`${endpoint}/work/workers`, { headers: getSafeHeader() });
            const data = await res.json();
            if (data.code === 200) {
                setWorkers(data.data || []);
            }
        } catch (error) {
            console.error(error);
        }
    };

    const fetchBonusItems = async () => {
        setLoadingBonusItems(true);
        try {
            const res = await fetch(`${endpoint}/finance/bonus-items?active_only=true`, { headers: getSafeHeader() });
            const data = await res.json();
            if (data.code === 200) {
                setBonusItems(data.data || []);
            } else {
                messageApi.error(data.msg || '获取奖金分项失败');
            }
        } catch (error) {
            messageApi.error('获取奖金分项失败');
            console.error(error);
        } finally {
            setLoadingBonusItems(false);
        }
    };

    const fetchPendingPackingLists = async () => {
        setLoadingPending(true);
        try {
            const params = new URLSearchParams({ month });
            if (markSearch.trim()) {
                params.set('q', markSearch.trim());
            }
            const res = await fetch(`${endpoint}/finance/bonus-allocation/pending-packing-lists?${params.toString()}`, {
                headers: getSafeHeader()
            });
            const data = await res.json();
            if (data.code === 200) {
                const result = data.data || { items: [], total: 0 };
                setPendingData(result);

                const nextDrafts = {};
                (result.items || []).forEach(listItem => {
                    (listItem.boxes || []).forEach(box => {
                        nextDrafts[box.box_uid] = {
                            worker_ids: box.worker_ids || [],
                            bonus_item_id: box.bonus_item_id || box.suggested_bonus_item_id || undefined
                        };
                    });
                });
                setDrafts(nextDrafts);
            } else {
                messageApi.error(data.msg || '获取待分配装箱单失败');
            }
        } catch (error) {
            messageApi.error('获取待分配装箱单失败');
            console.error(error);
        } finally {
            setLoadingPending(false);
        }
    };

    useEffect(() => {
        if (!canAccess) return;
        fetchWorkers();
        fetchBonusItems();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [canAccess]);

    useEffect(() => {
        if (!canAccess) return;
        fetchPendingPackingLists();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [canAccess, month]);

    const validateItem = (item) => {
        if (!item.label || !String(item.label).trim()) {
            return '分项名称不能为空';
        }
        if (Number(item.base_amount) < 0) {
            return '基数不能小于 0';
        }
        if (!Number.isInteger(Number(item.worker_count_rule)) || Number(item.worker_count_rule) <= 0) {
            return '人数规则必须是大于 0 的整数';
        }
        if (Number(item.weight_min) < 0 || Number(item.weight_max) < 0) {
            return '重量规则不能小于 0';
        }
        if (Number(item.weight_max) < Number(item.weight_min)) {
            return '重量上限不能小于下限';
        }
        return '';
    };

    const openCreateModal = () => {
        createForm.setFieldsValue(newItem);
        setCreateModalVisible(true);
    };

    const handleCreateModalOk = async () => {
        try {
            const values = await createForm.validateFields();
            setNewItem(values);

            const validationError = validateItem(values);
            if (validationError) {
                messageApi.warning(validationError);
                return;
            }

            setCreatingItem(true);
            const res = await fetch(`${endpoint}/finance/bonus-items`, {
                method: 'POST',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    ...values,
                    label: String(values.label).trim()
                })
            });
            const data = await res.json();
            if (data.code === 200) {
                messageApi.success('奖金分项已新增');
                setNewItem(EMPTY_NEW_ITEM);
                createForm.resetFields();
                setCreateModalVisible(false);
                fetchBonusItems();
            } else {
                messageApi.error(data.msg || '新增失败');
            }
        } catch (error) {
            if (error?.errorFields) return;
            messageApi.error('新增失败');
            console.error(error);
        } finally {
            setCreatingItem(false);
        }
    };

    const handleSaveItem = async (item) => {
        const validationError = validateItem(item);
        if (validationError) {
            messageApi.warning(validationError);
            return false;
        }

        setSavingItemIds(prev => [...prev, item.id]);
        try {
            const res = await fetch(`${endpoint}/finance/bonus-items/${item.id}`, {
                method: 'PUT',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    label: String(item.label).trim(),
                    base_amount: Number(item.base_amount || 0),
                    worker_count_rule: Number(item.worker_count_rule || 0),
                    weight_min: Number(item.weight_min || 0),
                    weight_max: Number(item.weight_max || 0)
                })
            });
            const data = await res.json();
            if (data.code === 200) {
                messageApi.success('分项已更新');
                fetchBonusItems();
                return true;
            } else {
                messageApi.error(data.msg || '更新失败');
                return false;
            }
        } catch (error) {
            messageApi.error('更新失败');
            console.error(error);
            return false;
        } finally {
            setSavingItemIds(prev => prev.filter(id => id !== item.id));
        }
    };

    const openEditModal = (item) => {
        setEditingItem(item);
        editForm.setFieldsValue({
            label: item.label,
            base_amount: Number(item.base_amount || 0),
            worker_count_rule: Number(item.worker_count_rule || 1),
            weight_min: Number(item.weight_min || 0),
            weight_max: Number(item.weight_max || 0)
        });
        setEditModalVisible(true);
    };

    const handleEditModalOk = async () => {
        if (!editingItem) return;
        try {
            const values = await editForm.validateFields();
            const ok = await handleSaveItem({ ...editingItem, ...values });
            if (ok) {
                setEditModalVisible(false);
                setEditingItem(null);
            }
        } catch (error) {
            if (error?.errorFields) return;
            messageApi.error('更新失败');
            console.error(error);
        }
    };

    const handleDisableItem = (item) => {
        Modal.confirm({
            title: '确认停用该分项吗？',
            content: `分项：${item.label}`,
            okText: '停用',
            okType: 'danger',
            cancelText: '取消',
            onOk: async () => {
                setSavingItemIds(prev => [...prev, item.id]);
                try {
                    const res = await fetch(`${endpoint}/finance/bonus-items/${item.id}`, {
                        method: 'DELETE',
                        headers: getSafeHeader()
                    });
                    const data = await res.json();
                    if (data.code === 200) {
                        messageApi.success('分项已停用');
                        fetchBonusItems();
                        fetchPendingPackingLists();
                    } else {
                        messageApi.error(data.msg || '停用失败');
                    }
                } catch (error) {
                    messageApi.error('停用失败');
                    console.error(error);
                } finally {
                    setSavingItemIds(prev => prev.filter(id => id !== item.id));
                }
            }
        });
    };

    const updateDraft = (boxUid, patch) => {
        setDrafts(prev => ({
            ...prev,
            [boxUid]: {
                ...(prev[boxUid] || {}),
                ...patch
            }
        }));
    };

    const isBoxIncomplete = (box) => {
        const draft = drafts[box.box_uid] || {};
        const hasWorkers = (draft.worker_ids || []).length > 0;
        const hasBonusItem = !!draft.bonus_item_id;
        return !(hasWorkers && hasBonusItem);
    };

    const getPackingProgress = (packingList) => {
        const boxes = packingList?.boxes || [];
        const total = boxes.length;
        if (!total) return { total: 0, completed: 0, incomplete: 0 };

        const incomplete = boxes.filter(isBoxIncomplete).length;
        return {
            total,
            completed: total - incomplete,
            incomplete
        };
    };

    const handleSubmitPackingList = async (packingList) => {
        const assignments = (packingList.boxes || []).map(box => {
            const draft = drafts[box.box_uid] || {};
            return {
                box_uid: box.box_uid,
                worker_ids: draft.worker_ids || [],
                bonus_item_id: draft.bonus_item_id
            };
        });

        const invalid = assignments.find(row => !(row.worker_ids || []).length || !row.bonus_item_id);
        if (invalid) {
            messageApi.warning('请为每个箱子选择操作员和奖金分项');
            return;
        }

        setAllocatingPackingUid(packingList.packing_list_uid);
        try {
            const res = await fetch(`${endpoint}/finance/bonus-allocation/packing-list/${packingList.packing_list_uid}`, {
                method: 'PUT',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ assignments })
            });
            const data = await res.json();
            if (data.code === 200) {
                messageApi.success('该装箱单奖金分配已提交');
                setAllocationModalVisible(false);
                setSelectedPackingList(null);
                fetchPendingPackingLists();
            } else {
                messageApi.error(data.msg || '提交失败');
            }
        } catch (error) {
            messageApi.error('提交失败');
            console.error(error);
        } finally {
            setAllocatingPackingUid('');
        }
    };

    const openAllocationModal = (packingList) => {
        setSelectedPackingList(packingList);
        setAllocationModalVisible(true);
    };

    const bonusItemColumns = [
        {
            title: '分项名称',
            dataIndex: 'label',
            key: 'label'
        },
        {
            title: '基数',
            dataIndex: 'base_amount',
            key: 'base_amount',
            width: 120,
            render: (value) => Number(value || 0).toFixed(2)
        },
        {
            title: '人数规则(相等)',
            dataIndex: 'worker_count_rule',
            key: 'worker_count_rule',
            width: 140,
            render: (value) => Number(value || 0)
        },
        {
            title: '重量下限(kg)',
            dataIndex: 'weight_min',
            key: 'weight_min',
            width: 140,
            render: (value) => Number(value || 0).toFixed(2)
        },
        {
            title: '重量上限(kg)',
            dataIndex: 'weight_max',
            key: 'weight_max',
            width: 140,
            render: (value) => Number(value || 0).toFixed(2)
        },
        {
            title: '操作',
            key: 'action',
            width: 180,
            render: (_, record) => (
                <Space>
                    <Button
                        type="primary"
                        icon={<EditOutlined />}
                        loading={savingItemIds.includes(record.id)}
                        onClick={() => openEditModal(record)}
                    >
                        编辑
                    </Button>
                    <Button
                        danger
                        loading={savingItemIds.includes(record.id)}
                        onClick={() => handleDisableItem(record)}
                    >
                        停用
                    </Button>
                </Space>
            )
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
            key: 'item_name'
        },
        {
            title: '件数',
            dataIndex: 'piece_count',
            key: 'piece_count',
            width: 100,
            align: 'right'
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
            title: '操作员',
            key: 'worker_ids',
            width: 260,
            render: (_, record) => (
                <div>
                    <Select
                        mode="multiple"
                        value={drafts[record.box_uid]?.worker_ids || []}
                        options={workerOptions}
                        onChange={(value) => updateDraft(record.box_uid, { worker_ids: value })}
                        style={{ width: '100%' }}
                        maxTagCount={1}
                        optionFilterProp="label"
                        showSearch
                    />
                    {!(drafts[record.box_uid]?.worker_ids || []).length && (
                        <Text style={{ color: '#cf1322', fontSize: 12 }}>请选择操作员</Text>
                    )}
                </div>
            )
        },
        {
            title: '奖金分项',
            key: 'bonus_item_id',
            width: 240,
            render: (_, record) => (
                <div>
                    <Select
                        value={drafts[record.box_uid]?.bonus_item_id}
                        options={bonusItemOptions}
                        onChange={(value) => updateDraft(record.box_uid, { bonus_item_id: value })}
                        style={{ width: '100%' }}
                        optionFilterProp="label"
                        showSearch
                    />
                    {!drafts[record.box_uid]?.bonus_item_id && (
                        <Text style={{ color: '#cf1322', fontSize: 12 }}>请选择奖金分项</Text>
                    )}
                </div>
            )
        },
        {
            title: '系统建议',
            key: 'suggested',
            width: 180,
            render: (_, record) => record.suggested_bonus_item_label || '-'
        }
    ];

    const pendingListColumns = [
        {
            title: '日期',
            dataIndex: 'create_date',
            key: 'create_date',
            width: 120,
            render: (value) => value ? String(value).slice(0, 10) : '-'
        },
        {
            title: '唛头',
            dataIndex: 'mark',
            key: 'mark',
            width: 180,
            render: (value, record) => value ? `${value}${record.status === 'draft' ? ' [草稿]' : ''}` : '-'
        },
        {
            title: '客户',
            dataIndex: 'customer_name',
            key: 'customer_name',
            width: 160,
            render: (value) => value || '-'
        },
        {
            title: '总箱数',
            dataIndex: 'box_count',
            key: 'box_count',
            width: 90,
            align: 'right'
        },
        {
            title: '待分配箱数',
            dataIndex: 'pending_box_count',
            key: 'pending_box_count',
            width: 110,
            align: 'right'
        },
        {
            title: '填写进度',
            key: 'progress',
            width: 150,
            render: (_, record) => {
                const progress = getPackingProgress(record);
                return `${progress.completed}/${progress.total} (未完成${progress.incomplete})`;
            }
        },
        {
            title: '总重量(kg)',
            dataIndex: 'total_weight',
            key: 'total_weight',
            width: 120,
            align: 'right',
            render: (value) => Number(value || 0).toFixed(2)
        },
        {
            title: '操作',
            key: 'action',
            width: 120,
            render: (_, record) => (
                <Button
                    type="primary"
                    onClick={() => openAllocationModal(record)}
                >
                    分配
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

    const filteredPendingItems = (pendingData.items || []).filter((item) => {
        if (!showOnlyIncompletePacking) return true;
        return getPackingProgress(item).incomplete > 0;
    });

    const selectedBoxes = selectedPackingList?.boxes || [];
    const selectedProgress = selectedPackingList ? getPackingProgress(selectedPackingList) : { total: 0, completed: 0, incomplete: 0 };
    const modalBoxData = showOnlyIncompleteBoxes
        ? selectedBoxes.filter(isBoxIncomplete)
        : selectedBoxes;

    return (
        <div style={{ padding: 24 }}>
            {contextHolder}
            <Title level={3} style={{ marginBottom: 16 }}>财务</Title>

            <Card title="奖金分项与规则设置" style={{ marginBottom: 16 }} loading={loadingBonusItems}>
                <Space style={{ marginBottom: 12 }}>
                    <Button
                        type="primary"
                        icon={<PlusOutlined />}
                        onClick={openCreateModal}
                    >
                        新增奖金分项
                    </Button>
                </Space>

                <Table
                    rowKey="id"
                    dataSource={bonusItems}
                    columns={bonusItemColumns}
                    pagination={false}
                    scroll={{ x: 'max-content' }}
                    size="small"
                />
            </Card>

            <Card title="未进行奖金分配的装箱单">
                <Space wrap style={{ marginBottom: 12 }}>
                    <Input
                        type="month"
                        value={month}
                        onChange={(e) => setMonth(e.target.value || getCurrentMonth())}
                        style={{ width: 160 }}
                    />
                    <Input
                        placeholder="按唛头搜索"
                        value={markSearch}
                        onChange={(e) => setMarkSearch(e.target.value)}
                        onPressEnter={fetchPendingPackingLists}
                        style={{ width: 220 }}
                    />
                    <Button icon={<ReloadOutlined />} onClick={fetchPendingPackingLists} loading={loadingPending}>刷新</Button>
                    <Space>
                        <Text>仅显示未完成填写</Text>
                        <Switch checked={showOnlyIncompletePacking} onChange={setShowOnlyIncompletePacking} />
                    </Space>
                </Space>

                <Table
                    rowKey="packing_list_uid"
                    loading={loadingPending}
                    dataSource={filteredPendingItems}
                    columns={pendingListColumns}
                    pagination={{ pageSize: 10, showSizeChanger: true }}
                    scroll={{ x: 'max-content' }}
                    size="small"
                />

                {!loadingPending && !(pendingData.items || []).length && (
                    <Text type="secondary">当前筛选条件下没有待分配奖金的装箱单。</Text>
                )}
            </Card>

            <Modal
                title="新增奖金分项"
                open={createModalVisible}
                onCancel={() => setCreateModalVisible(false)}
                onOk={handleCreateModalOk}
                confirmLoading={creatingItem}
                okText="创建"
                cancelText="取消"
                destroyOnClose
            >
                <Form
                    form={createForm}
                    layout="vertical"
                    initialValues={newItem}
                >
                    <Form.Item
                        label="分项名称"
                        name="label"
                        rules={[{ required: true, message: '请输入分项名称' }]}
                    >
                        <Input placeholder="例如：轻货双人" />
                    </Form.Item>

                    <Form.Item
                        label="奖金基数"
                        name="base_amount"
                        rules={[{ required: true, message: '请输入奖金基数' }]}
                    >
                        <Space>
                            <InputNumber min={0} step={0.1} precision={2} style={{ width: 160 }} />
                            <Text type="secondary">元/箱</Text>
                        </Space>
                    </Form.Item>

                    <Form.Item
                        label="人数规则（相等匹配）"
                        name="worker_count_rule"
                        rules={[{ required: true, message: '请输入人数规则' }]}
                    >
                        <Space>
                            <InputNumber min={1} precision={0} style={{ width: 120 }} />
                            <Text type="secondary">人</Text>
                        </Space>
                    </Form.Item>

                    <Form.Item
                        label="重量范围（范围匹配）"
                        required
                    >
                        <Space align="center" wrap>
                            <Form.Item
                                name="weight_min"
                                noStyle
                                rules={[{ required: true, message: '请输入重量下限' }]}
                            >
                                <InputNumber min={0} step={1} precision={2} style={{ width: 120 }} placeholder="下限" />
                            </Form.Item>
                            <Text>-</Text>
                            <Form.Item
                                name="weight_max"
                                noStyle
                                rules={[{ required: true, message: '请输入重量上限' }]}
                            >
                                <InputNumber min={0} step={1} precision={2} style={{ width: 120 }} placeholder="上限" />
                            </Form.Item>
                            <Text type="secondary">kg</Text>
                        </Space>
                    </Form.Item>
                </Form>
            </Modal>

            <Modal
                title={editingItem ? `编辑奖金分项 - ${editingItem.label}` : '编辑奖金分项'}
                open={editModalVisible}
                onCancel={() => {
                    setEditModalVisible(false);
                    setEditingItem(null);
                }}
                onOk={handleEditModalOk}
                confirmLoading={editingItem ? savingItemIds.includes(editingItem.id) : false}
                okText="保存"
                cancelText="取消"
                destroyOnClose
            >
                <Form form={editForm} layout="vertical">
                    <Form.Item
                        label="分项名称"
                        name="label"
                        rules={[{ required: true, message: '请输入分项名称' }]}
                    >
                        <Input placeholder="例如：轻货双人" />
                    </Form.Item>

                    <Form.Item
                        label="奖金基数"
                        name="base_amount"
                        rules={[{ required: true, message: '请输入奖金基数' }]}
                    >
                        <Space>
                            <InputNumber min={0} step={0.1} precision={2} style={{ width: 160 }} />
                            <Text type="secondary">元/箱</Text>
                        </Space>
                    </Form.Item>

                    <Form.Item
                        label="人数规则（相等匹配）"
                        name="worker_count_rule"
                        rules={[{ required: true, message: '请输入人数规则' }]}
                    >
                        <Space>
                            <InputNumber min={1} precision={0} style={{ width: 120 }} />
                            <Text type="secondary">人</Text>
                        </Space>
                    </Form.Item>

                    <Form.Item label="重量范围（范围匹配）" required>
                        <Space align="center" wrap>
                            <Form.Item
                                name="weight_min"
                                noStyle
                                rules={[{ required: true, message: '请输入重量下限' }]}
                            >
                                <InputNumber min={0} step={1} precision={2} style={{ width: 120 }} placeholder="下限" />
                            </Form.Item>
                            <Text>-</Text>
                            <Form.Item
                                name="weight_max"
                                noStyle
                                rules={[{ required: true, message: '请输入重量上限' }]}
                            >
                                <InputNumber min={0} step={1} precision={2} style={{ width: 120 }} placeholder="上限" />
                            </Form.Item>
                            <Text type="secondary">kg</Text>
                        </Space>
                    </Form.Item>
                </Form>
            </Modal>

            <Modal
                title={selectedPackingList ? `装箱单奖金分配 - ${selectedPackingList.mark}${selectedPackingList.status === 'draft' ? ' [草稿]' : ''}` : '装箱单奖金分配'}
                open={allocationModalVisible}
                onCancel={() => {
                    setAllocationModalVisible(false);
                    setSelectedPackingList(null);
                }}
                onOk={() => selectedPackingList && handleSubmitPackingList(selectedPackingList)}
                confirmLoading={allocatingPackingUid === selectedPackingList?.packing_list_uid}
                okText="提交该装箱单分配"
                cancelText="取消"
                width={1200}
                destroyOnClose
            >
                {selectedPackingList && (
                    <>
                        <div style={{ marginBottom: 12 }}>
                            <Text>客户：{selectedPackingList.customer_name || '-'}</Text>
                            <Text style={{ marginLeft: 16 }}>待分配：{selectedPackingList.pending_box_count} / {selectedPackingList.box_count} 箱</Text>
                            <Text style={{ marginLeft: 16 }}>总重量：{Number(selectedPackingList.total_weight || 0).toFixed(2)} kg</Text>
                        </div>
                        <Space style={{ marginBottom: 12 }} wrap>
                            <Text>填写进度：{selectedProgress.completed}/{selectedProgress.total}，未完成 {selectedProgress.incomplete} 箱</Text>
                            <Space>
                                <Text>仅显示未完成项</Text>
                                <Switch checked={showOnlyIncompleteBoxes} onChange={setShowOnlyIncompleteBoxes} />
                            </Space>
                        </Space>
                        <Table
                            rowKey="box_uid"
                            dataSource={modalBoxData}
                            columns={boxColumns}
                            pagination={false}
                            onRow={(record) => (
                                isBoxIncomplete(record)
                                    ? { style: { background: '#fff2f0' } }
                                    : {}
                            )}
                            scroll={{ x: 'max-content' }}
                            size="small"
                        />
                    </>
                )}
            </Modal>
        </div>
    );
}
