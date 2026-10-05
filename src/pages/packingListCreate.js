import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
    AutoComplete,
    Form,
    Select,
    Button,
    Input,
    InputNumber,
    message,
    Card,
    Modal,
    Space,
    Table,
    Divider,
    Typography,
    Popconfirm,
    Tabs,
    Grid,
    Spin
} from 'antd';
import {
    PlusOutlined,
    DeleteOutlined,
    SaveOutlined,
    CheckOutlined,
    CloseOutlined,
    ReloadOutlined,
    CameraOutlined,
    EditOutlined
} from '@ant-design/icons';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import { PaperIntakeUpload } from './intakes';
import { getIntakeRoles } from '../common/intakeApi';
import entryStyles from './packingListEntry.module.css';

const { Title, Text } = Typography;
const { Option, OptGroup } = Select;
const { useBreakpoint } = Grid;

const packingStorageKey = key => {
    try {
        const payload = JSON.parse(atob(localStorage.getItem('jwt').split('.')[1]));
        return `packingList_${payload.user_id || payload.id}_${key}`;
    } catch { return `packingList_guest_${key}`; }
};

const normalizeLoadedPhotos = (value, prefix) => {
    if (!Array.isArray(value)) return [];

    return value
        .map((item, index) => {
            if (item && typeof item === 'object') {
                const url = String(item.url || '').trim();
                if (!url) return null;
                return {
                    url,
                    uid: item.uid || `${prefix}-photo-${index}`
                };
            }

            const url = String(item || '').trim();
            if (!url) return null;
            return {
                url,
                uid: `${prefix}-photo-${index}`
            };
        })
        .filter(Boolean);
};

const COMMON_GOODS_GROUPS = [
    {
        label: '服装类',
        items: ['T-恤', '衬衫', '背心', '布料', '荷兰布', '围巾', '头巾', '帽子', '连衣裙', '女套裙', '童裙', '童套装', '裤子', '牛仔裤', '西服', '卫衣', '休闲服', '运动套装', '毛衣', '毛巾', '枕头', '窗帘', '文胸']
    },
    {
        label: '鞋包类',
        items: ['运动鞋', '女凉鞋', '男凉鞋', '高跟鞋', '拖鞋', '手提包', '钱包', '卡包', '皮带', '假发', '眼镜']
    },
    {
        label: '首饰类',
        items: ['手镯', '耳环', '戒指', '项链', '铁牌']
    },
    {
        label: '杂项',
        items: ['不锈钢锅', '不锈钢盆', '陶瓷盆', '陶瓷碗', '耳机']
    }
];

function PackingListTab({
    tabKey,
    updateTabTitle,
    updateTabMeta,
    initialDraftUid,
    refreshDraftPackingLists,
    requestCloseTab
}) {
    const [form] = Form.useForm();
    const [messageApi, contextHolder] = message.useMessage();
    const screens = useBreakpoint();
    const isMobile = !screens.sm;

    // 状态
    const [customers, setCustomers] = useState([]);
    const [workers, setWorkers] = useState([]);
    const [selectedCustomerId, setSelectedCustomerId] = useState(null);
    const [photos, setPhotos] = useState([]);
    const [boxes, setBoxes] = useState([]);
    const [packingListUid, setPackingListUid] = useState(null);
    const [listNumber, setListNumber] = useState('');
    const [inputMark, setInputMark] = useState('');
    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(false);
    const [initializingDraft, setInitializingDraft] = useState(!!initialDraftUid);

    // 箱子表单
    const [boxForm] = Form.useForm();

    const parsePieceCountExpression = (value) => {
        const expression = String(value ?? '').replace(/\s+/g, '');
        if (!expression) return null;
        if (!/^[+-]?\d+(?:[+-]\d+)*$/.test(expression)) return null;

        const tokens = expression.match(/[+-]?\d+/g);
        if (!tokens || !tokens.length) return null;

        const total = tokens.reduce((sum, token) => sum + Number(token), 0);
        if (!Number.isFinite(total) || total <= 0) return null;

        return total;
    };

    const applyPackingListDetail = useCallback((detail) => {
        if (!detail) return;

        const nextUid = detail.uid || null;
        const nextMark = (detail.list_number || detail.mark || '').trim();
        const nextCustomerId = detail.customer_id ?? null;
        const nextPhotos = normalizeLoadedPhotos(detail.photos, nextUid || tabKey);
        const nextBoxes = Array.isArray(detail.boxes) ? detail.boxes : [];

        setSelectedCustomerId(nextCustomerId);
        setPhotos(nextPhotos);
        setBoxes(nextBoxes);
        setPackingListUid(nextUid);
        setListNumber(nextMark);
        setInputMark(nextMark);
        form.setFieldsValue({
            customer_id: nextCustomerId,
            mark: nextMark
        });
        boxForm.resetFields();
        updateTabTitle(tabKey, nextMark || '新装箱单');
    }, [boxForm, form, tabKey, updateTabTitle]);

    const loadPackingListDetail = useCallback(async (uid) => {
        if (!uid) return false;

        try {
            const res = await fetch(`${endpoint}/packing-list/${uid}`, {
                headers: getSafeHeader()
            });
            const data = await res.json();

            if (data.code === 200 && data.data) {
                applyPackingListDetail(data.data);
                return true;
            }

            messageApi.error(data.msg || '加载草稿失败');
        } catch (error) {
            messageApi.error('加载草稿失败');
            console.error(error);
        }

        return false;
    }, [applyPackingListDetail, messageApi]);

    useEffect(() => {
        if (initializingDraft && !packingListUid) {
            return;
        }

        updateTabMeta?.(tabKey, {
            draftUid: packingListUid || null
        });
    }, [initializingDraft, packingListUid, tabKey, updateTabMeta]);

    // 加载客户列表和操作员列表
    useEffect(() => {
        fetchCustomers();
        fetchWorkers();
    }, []);

    // 恢复持久化状态 / 打开草稿
    useEffect(() => {
        let cancelled = false;

        const restoreDraftOrSavedState = async () => {
            // 恢复持久化状态
            const savedState = localStorage.getItem(packingStorageKey(`tab_${tabKey}`));
            if (savedState) {
                try {
                    const parsed = JSON.parse(savedState);
                    if (parsed.packingListUid) {
                        applyPackingListDetail({
                            uid: parsed.packingListUid,
                            list_number: parsed.listNumber || parsed.inputMark || '',
                            customer_id: parsed.selectedCustomerId ?? null,
                            photos: parsed.photos || [],
                            boxes: parsed.boxes || []
                        });
                    } else {
                        if (parsed.selectedCustomerId !== undefined) {
                            setSelectedCustomerId(parsed.selectedCustomerId ?? null);
                        }
                        if (Array.isArray(parsed.photos)) {
                            setPhotos(normalizeLoadedPhotos(parsed.photos, tabKey));
                        }
                        if (Array.isArray(parsed.boxes)) setBoxes(parsed.boxes);
                        const savedMark = parsed.listNumber || parsed.inputMark || '';
                        if (parsed.listNumber !== undefined || parsed.inputMark !== undefined) {
                            setListNumber(savedMark);
                            setInputMark(savedMark);
                            form.setFieldValue('mark', savedMark);
                        }
                        if (parsed.selectedCustomerId !== undefined) {
                            form.setFieldValue('customer_id', parsed.selectedCustomerId ?? null);
                        }
                    }
                } catch (e) {
                    console.error("恢复保存的状态失败", e);
                }
                if (!cancelled) {
                    setInitializingDraft(false);
                }
                return;
            }

            if (initialDraftUid) {
                await loadPackingListDetail(initialDraftUid);
            }

            if (!cancelled) {
                setInitializingDraft(false);
            }
        };

        restoreDraftOrSavedState();

        return () => {
            cancelled = true;
        };
    }, [applyPackingListDetail, boxForm, form, initialDraftUid, loadPackingListDetail, tabKey]);

    // 监听状态变化并持久化
    useEffect(() => {
        const stateToSave = {
            selectedCustomerId, photos, boxes, packingListUid, listNumber, inputMark
        };
        localStorage.setItem(packingStorageKey(`tab_${tabKey}`), JSON.stringify(stateToSave));
    }, [selectedCustomerId, photos, boxes, packingListUid, listNumber, inputMark, tabKey]);

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
            const res = await fetch(`${endpoint}/work/workers`, {
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

    // 创建装箱单
    const handleCreatePackingList = async () => {
        const normalizedMark = (inputMark || '').trim().toUpperCase();
        if (!normalizedMark) {
            messageApi.warning('请先填写唛头');
            return;
        }

        setSaving(true);
        try {
            const res = await fetch(`${endpoint}/packing-list`, {
                method: 'POST',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    ...(selectedCustomerId ? { customer_id: selectedCustomerId } : {}),
                    list_number: normalizedMark,
                    mark: normalizedMark,
                    photos: photos.map(p => p.url)
                })
            });
            const data = await res.json();

            if (data.code === 200) {
                const finalMark = data.data.list_number || data.data.mark || normalizedMark;
                setPackingListUid(data.data.uid);
                setInputMark(finalMark);
                form.setFieldValue('mark', finalMark);
                updateTabTitle(tabKey, finalMark);
                setListNumber(finalMark);
                messageApi.success(`装箱单创建成功！唛头: ${finalMark}`);
                refreshDraftPackingLists?.();
            } else {
                messageApi.error(data.msg || '创建失败');
            }
        } catch (error) {
            messageApi.error('创建装箱单失败');
            console.error(error);
        } finally {
            setSaving(false);
        }
    };

    // 添加箱子
    const handleAddBox = async () => {
        if (!packingListUid) {
            messageApi.warning('请先创建装箱单');
            return;
        }

        try {
            const values = await boxForm.validateFields();
            setLoading(true);

            const parsedRows = (values.item_details || []).map((row, index) => ({
                index,
                item_name: (row?.item_name || '').trim(),
                piece_count: parsePieceCountExpression(row?.piece_count)
            }));

            const invalidRow = parsedRows.find(row => row.item_name && row.piece_count === null);
            if (invalidRow) {
                messageApi.warning(`第 ${invalidRow.index + 1} 行件数格式无效，支持 + / - 运算，例如 1+2+3`);
                setLoading(false);
                return;
            }

            const itemDetails = parsedRows
                .filter(row => row.item_name && row.piece_count !== null)
                .map(row => ({
                    item_name: row.item_name,
                    piece_count: row.piece_count
                }));

            if (!itemDetails.length) {
                messageApi.warning('请至少填写一条“品名-件数”');
                setLoading(false);
                return;
            }

            const totalPieceCount = itemDetails.reduce((sum, row) => sum + row.piece_count, 0);
            const itemNameSummary = itemDetails.map(row => row.item_name).join('、');

            const res = await fetch(`${endpoint}/packing-list/${packingListUid}/box`, {
                method: 'POST',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    item_name: itemNameSummary,
                    item_details: itemDetails,
                    piece_count: totalPieceCount,
                    remark: (values.remark || '').trim() || null,
                    weight: values.weight || null
                })
            });
            const data = await res.json();

            if (data.code === 200) {
                let workerAssignResult = { success: true };

                // 如果选择了操作员，尝试设置（仅允许首次设置）
                if (values.worker_ids && values.worker_ids.length > 0) {
                    workerAssignResult = await setBoxWorkers(data.data.uid, values.worker_ids);
                }

                const newBox = {
                    ...data.data,
                    key: data.data.uid,
                    workers: workerAssignResult.success ? (values.worker_ids || []) : []
                };

                setBoxes(prev => [...prev, newBox]);
                boxForm.setFieldsValue({
                    weight: null,
                    remark: '',
                    item_details: itemDetails.map(row => ({
                        item_name: row.item_name,
                        piece_count: ''
                    })),
                    worker_ids: values.worker_ids || []
                });
                if (workerAssignResult.success) {
                    messageApi.success('箱子添加成功');
                } else {
                    messageApi.warning(`箱子已添加，但操作员设置失败：${workerAssignResult.msg}`);
                }
            } else {
                messageApi.error(data.msg || '添加失败');
            }
        } catch (error) {
            if (error.errorFields) {
                // 表单验证错误
                return;
            }
            messageApi.error('添加箱子失败');
            console.error(error);
        } finally {
            setLoading(false);
        }
    };

    // 设置箱子操作员
    const setBoxWorkers = async (boxUid, workerIds) => {
        try {
            const res = await fetch(`${endpoint}/box/${boxUid}/workers/add`, {
                method: 'POST',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ worker_ids: workerIds })
            });

            let data = {};
            try {
                data = await res.json();
            } catch (_) {
                data = {};
            }

            const code = data?.code ?? res.status;
            if (res.ok && code === 200) {
                return { success: true };
            }

            return {
                success: false,
                code,
                msg: data?.msg || `设置操作员失败（${code}）`
            };
        } catch (error) {
            console.error('设置操作员失败:', error);
            return {
                success: false,
                code: 0,
                msg: '设置操作员请求失败，请检查网络或稍后重试'
            };
        }
    };

    // 归档箱子
    const handleArchiveBox = (box) => {
        Modal.confirm({
            title: '确认归档该箱子吗？',
            content: `箱号：${box.box_number || '-'}。归档后箱子将不再显示。`,
            okText: '确认归档',
            okType: 'danger',
            cancelText: '取消',
            onOk: async () => {
                try {
                    const res = await fetch(`${endpoint}/box/${box.uid}/archive`, {
                        method: 'POST',
                        headers: getSafeHeader()
                    });
                    const data = await res.json();

                    if (data.code === 200) {
                        setBoxes(prev => prev.filter(b => b.uid !== box.uid));
                        messageApi.success('箱子已归档');
                    } else {
                        messageApi.error(data.msg || '归档失败');
                    }
                } catch (error) {
                    messageApi.error('归档箱子失败');
                    console.error(error);
                }
            }
        });
    };

    // 删除箱子
    const handleDeleteBox = async (uid) => {
        try {
            const res = await fetch(`${endpoint}/box/${uid}`, {
                method: 'DELETE',
                headers: getSafeHeader()
            });
            const data = await res.json();

            if (data.code === 200) {
                setBoxes(prev => prev.filter(b => b.uid !== uid));
                messageApi.success('箱子已删除');
            } else {
                messageApi.error(data.msg || '删除失败');
            }
        } catch (error) {
            messageApi.error('删除箱子失败');
            console.error(error);
        }
    };

    // 称重箱子
    const handleWeighBox = async (uid, weight) => {
        if (!weight || weight <= 0) {
            messageApi.warning('请输入有效重量');
            return;
        }

        try {
            const res = await fetch(`${endpoint}/box/${uid}/weigh`, {
                method: 'PUT',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ weight })
            });
            const data = await res.json();

            if (data.code === 200) {
                setBoxes(prev => prev.map(b =>
                    b.uid === uid ? { ...b, weight } : b
                ));
                messageApi.success('称重成功');
            } else {
                messageApi.error(data.msg || '称重失败');
            }
        } catch (error) {
            messageApi.error('称重失败');
            console.error(error);
        }
    };

    // 保存装箱单（保持草稿并关闭当前子页面）
    const handleComplete = async () => {
        if (!packingListUid) {
            messageApi.warning('请先创建装箱单');
            return;
        }
        messageApi.success('装箱单已保存为草稿');
        refreshDraftPackingLists?.();
        requestCloseTab?.(tabKey);
    };

    // 重置页面
    const handleReset = () => {
        setInitializingDraft(false);
        setPackingListUid(null);
        setListNumber('');
        setSelectedCustomerId(null);
        setInputMark('');
        setPhotos([]);
        setBoxes([]);
        form.resetFields();
        boxForm.resetFields();
        localStorage.removeItem(packingStorageKey(`tab_${tabKey}`));
        updateTabTitle(tabKey, '新装箱单');
    };

    // 箱子表格列
    const boxColumns = [
        {
            title: '箱号',
            dataIndex: 'box_number',
            key: 'box_number',
            width: 60,
            align: 'center',
            render: (value, _, index) => value || (index + 1)
        },
        {
            title: '品名',
            dataIndex: 'item_details',
            render: (_, record) => {
                const details = record.item_details || [];
                if (!details.length) {
                    return record.item_name || '-';
                }
                return (
                    <div>
                        {details.map((row, idx) => (
                            <div key={`${record.uid}-item-${idx}`}>{row.item_name} x{row.piece_count}</div>
                        ))}
                    </div>
                );
            }
        },
        {
            title: '件数',
            dataIndex: 'piece_count',
            key: 'piece_count',
            width: 90,
            align: 'center',
            render: (value) => value || 0
        },
        {
            title: '重量(kg)',
            dataIndex: 'weight',
            key: 'weight',
            width: 140,
            align: 'right',
            render: (weight, record) => {
                if (weight && weight > 0) {
                    return (
                        <Space>
                            <Text strong style={{ color: '#52c41a', fontSize: '16px' }}>{weight} kg</Text>
                            <Popconfirm title="确定删除？" onConfirm={() => handleDeleteBox(record.uid)}>
                                <Button type="text" danger icon={<DeleteOutlined />} style={{ padding: 0 }} />
                            </Popconfirm>
                        </Space>
                    );
                }
                return (
                    <Space>
                        <InputNumber
                            size="large"
                            placeholder="输入重量"
                            inputMode="decimal"
                            min={0.01}
                            step={0.1}
                            style={{ width: 90, border: '1px solid #1890ff', borderRadius: '4px' }}
                            onPressEnter={(e) => handleWeighBox(record.uid, parseFloat(e.target.value))}
                        />
                        <Button type="text" danger style={{ padding: 0 }} onClick={() => handleArchiveBox(record)}>归档</Button>
                        <Popconfirm title="确定删除？" onConfirm={() => handleDeleteBox(record.uid)}>
                            <Button type="text" danger icon={<DeleteOutlined />} style={{ padding: 0 }} />
                        </Popconfirm>
                    </Space>
                );
            }
        },
        {
            title: '备注',
            dataIndex: 'remark',
            key: 'remark',
            width: 180,
            ellipsis: true,
            render: (value) => value || '-'
        }
    ];

    if (initializingDraft) {
        return (
            <div style={{ padding: '8px' }}>
                {contextHolder}
                <Card>
                    <Space direction="vertical" align="center" style={{ width: '100%', padding: '32px 0' }}>
                        <Spin size="large" />
                        <Text type="secondary">正在打开草稿装箱单...</Text>
                    </Space>
                </Card>
            </div>
        );
    }

    return (
        <div style={{ padding: '8px' }}>
            {contextHolder}

            {/* 基本信息 */}
            {!packingListUid ? (
                <>
                    <Card title="基本信息" style={{ marginBottom: 16 }} size="small">
                        <Form form={form} layout="vertical">
                            <Form.Item
                                label="选择客户"
                                name="customer_id"
                            >
                                <Select
                                    showSearch
                                    allowClear
                                    placeholder="搜索并选择客户（可选）"
                                    optionFilterProp="children"
                                    onChange={(value) => setSelectedCustomerId(value || null)}
                                    disabled={!!packingListUid}
                                    style={{ width: '100%' }}
                                    size="large"
                                >
                                    {customers.map(c => (
                                        <Option key={c.id} value={c.id}>{c.name}</Option>
                                    ))}
                                </Select>
                            </Form.Item>

                            <Form.Item
                                label="唛头"
                                name="mark"
                                rules={[{ required: true, message: '请输入唛头' }]}
                            >
                                <Input
                                    size="large"
                                    placeholder="请输入唛头（自动大写）"
                                    style={{ width: '100%' }}
                                    value={inputMark}
                                    onChange={(e) => {
                                        const upperValue = (e.target.value || '').toUpperCase();
                                        setInputMark(upperValue);
                                        form.setFieldValue('mark', upperValue);
                                    }}
                                    disabled={!!packingListUid}
                                />
                            </Form.Item>
                        </Form>

                        {/* 照片上传 */}
                        {/* <Divider orientation="left" style={{ margin: '12px 0' }}>照片</Divider>
                        <Space wrap>
                            {photos.map(photo => (
                                <div key={photo.uid} style={{ position: 'relative' }}>
                                    <Image
                                        src={photo.url}
                                        width={80}
                                        height={80}
                                        style={{ objectFit: 'cover', borderRadius: '8px' }}
                                    />
                                    <Button
                                        type="primary"
                                        danger
                                        size="small"
                                        icon={<DeleteOutlined />}
                                        style={{ position: 'absolute', top: -4, right: -4, borderRadius: '50%' }}
                                        onClick={() => handleRemovePhoto(photo.uid)}
                                    />
                                </div>
                            ))} */}
                        {/* <Upload
                                accept="image/*"
                                showUploadList={false}
                                beforeUpload={handleUploadPhoto}
                            >
                                <Button size="large" icon={<CameraOutlined />}>拍照/上传</Button>
                            </Upload> */}
                        {/* </Space> */}

                        <div style={{ marginTop: 24 }}>
                            <Button
                                type="primary"
                                size="large"
                                block
                                icon={<SaveOutlined />}
                                onClick={handleCreatePackingList}
                                loading={saving}
                            >
                                创建装箱单
                            </Button>
                        </div>
                    </Card>
                </>
            ) : (
                <Card size="small" style={{ marginBottom: 16, backgroundColor: '#f6ffed', border: '1px solid #b7eb8f' }}>
                    <Space wrap split={isMobile ? null : <Divider type="vertical" />}>
                        <Text type="secondary">当前唛头</Text>
                        <Text strong style={{ fontSize: 18, color: '#52c41a' }}>{listNumber}</Text>
                        <Button type="link" size="small" onClick={handleReset}>[重置/新建]</Button>
                    </Space>
                </Card>
            )
            }

            {/* 添加箱子 */}
            {
                packingListUid && (
                    <Card title="➕ 添加新箱子" style={{ marginBottom: 16 }} size="small" bodyStyle={{ padding: '12px' }}>
                        <Form
                            form={boxForm}
                            layout="vertical"
                            initialValues={{ item_details: [{ item_name: '', piece_count: '' }] }}
                        >
                            <Form.Item
                                label="品名与件数"
                                style={{ marginBottom: 12 }}
                            >
                                <Form.List name="item_details">
                                    {(fields, { add, remove }) => (
                                        <div>
                                            {fields.map((field) => (
                                                <Space
                                                    key={field.key}
                                                    align="start"
                                                    style={{ display: 'flex', width: '100%', marginBottom: 8 }}
                                                >
                                                    <Button
                                                        type="text"
                                                        icon={<CloseOutlined />}
                                                        danger
                                                        onClick={() => remove(field.name)}
                                                        disabled={fields.length <= 1}
                                                        style={{ marginTop: isMobile ? 8 : 4 }}
                                                    />
                                                    <Form.Item
                                                        {...field}
                                                        name={[field.name, 'item_name']}
                                                        rules={[{ required: true, message: '请输入品名' }]}
                                                        style={{ width: isMobile ? 140 : 220, marginBottom: 24 }}
                                                    >
                                                        <AutoComplete
                                                            size="large"
                                                            placeholder="选择品名或输入"
                                                            style={{ width: '100%' }}
                                                            filterOption={(inputValue, option) =>
                                                                [option?.value, option?.label, option?.children]
                                                                    .filter((item) => item !== undefined && item !== null)
                                                                    .map((item) => String(item))
                                                                    .join(' ')
                                                                    .toUpperCase()
                                                                    .includes(inputValue.toUpperCase())
                                                            }
                                                        >
                                                            {COMMON_GOODS_GROUPS.map((group) => (
                                                                <OptGroup key={group.label} label={group.label}>
                                                                    {group.items.map((item) => (
                                                                        <Option key={item} value={item}>
                                                                            {item}
                                                                        </Option>
                                                                    ))}
                                                                </OptGroup>
                                                            ))}
                                                        </AutoComplete>
                                                    </Form.Item>

                                                    <Form.Item
                                                        {...field}
                                                        name={[field.name, 'piece_count']}
                                                        rules={[
                                                            { required: true, message: '请输入件数' },
                                                            {
                                                                validator: (_, value) => {
                                                                    if (parsePieceCountExpression(value) !== null) {
                                                                        return Promise.resolve();
                                                                    }
                                                                    return Promise.reject(new Error('支持 + / - 运算，例如 1+2+3'));
                                                                }
                                                            }
                                                        ]}
                                                        style={{ width: isMobile ? 90 : 120, marginBottom: 24 }}
                                                    >
                                                        <Input
                                                            size="large"
                                                            inputMode="tel"
                                                            placeholder="件数或算式"
                                                            style={{ width: '100%' }}
                                                        />
                                                    </Form.Item>
                                                </Space>
                                            ))}

                                            <Button
                                                type="dashed"
                                                icon={<PlusOutlined />}
                                                block={isMobile}
                                                onClick={() => add({ item_name: '', piece_count: '' })}
                                            >
                                                新增品名件数
                                            </Button>
                                        </div>
                                    )}
                                </Form.List>
                            </Form.Item>

                            <Form.Item
                                name="weight"
                                label="️重量 (kg)"
                                rules={[{ required: true, message: '输入重量' }]}
                                style={{ marginBottom: 12 }}
                            >
                                <InputNumber
                                    size="large"
                                    placeholder="请输入重量"
                                    inputMode="decimal"
                                    min={0.01}
                                    step={0.1}
                                    style={{ width: '100%', border: '2px solid #1890ff', borderRadius: '6px' }}
                                />
                            </Form.Item>

                            <Form.Item
                                name="worker_ids"
                                label="操作员 (最多4人)"
                                rules={[{ required: true, message: '选择操作人员' }]}
                                style={{ marginBottom: 16 }}
                            >
                                <Select
                                    mode="multiple"
                                    size="large"
                                    placeholder="选择操作员"
                                    style={{ width: '100%' }}
                                    maxTagCount={3}
                                >
                                    {workers.map(w => (
                                        <Option key={w.id} value={w.id}>{w.name} {w.phone ? `(${w.phone})` : ''}</Option>
                                    ))}
                                </Select>
                            </Form.Item>

                            <Form.Item name="remark" label="备注" style={{ marginBottom: 12 }}>
                                <Input.TextArea rows={2} placeholder="可填写额外说明信息" />
                            </Form.Item>

                            <Form.Item style={{ marginBottom: 0 }}>
                                <Button
                                    type="primary"
                                    size="large"
                                    block
                                    icon={<PlusOutlined />}
                                    onClick={handleAddBox}
                                    loading={loading}
                                    style={{ height: '48px', fontSize: '16px', fontWeight: 'bold' }}
                                >
                                    添加箱子
                                </Button>
                            </Form.Item>
                        </Form>
                    </Card>
                )
            }

            {/* 箱子列表 */}
            {
                boxes.length > 0 && (
                    <Card title={`箱子列表 (${boxes.length})`} style={{ marginBottom: 16 }}>
                        <Table
                            dataSource={boxes}
                            columns={boxColumns}
                            pagination={false}
                            rowKey="uid"
                            size="small"
                            scroll={{ x: isMobile ? 680 : undefined }}
                        />

                        <div style={{ marginTop: 16, textAlign: isMobile ? 'left' : 'right' }}>
                            <Space wrap>
                                <Text>
                                    总重量: <Text strong>{boxes.reduce((sum, b) => sum + (b.weight || 0), 0).toFixed(2)} kg</Text>
                                </Text>
                                <Button
                                    type="primary"
                                    icon={<CheckOutlined />}
                                    onClick={handleComplete}
                                    style={{ marginLeft: 16 }}
                                >
                                    保存装箱单
                                </Button>
                            </Space>
                        </div>
                    </Card>
                )
            }

        </div >
    );
}

export default function PackingListCreate() {
    const navigate = useNavigate();
    const roles = getIntakeRoles();
    const workerOnly = roles.some(role => ['worker', 'employee'].includes(role)) &&
        !roles.some(role => ['admin', 'store_manager', 'salesperson', 'clerk', 'finance'].includes(role));
    const [entryMode, setEntryMode] = useState('manual');
    const [activeKey, setActiveKey] = useState(() => localStorage.getItem(packingStorageKey('activeKey')) || '1');
    const [items, setItems] = useState([]);
    const [draftPackingLists, setDraftPackingLists] = useState([]);
    const [draftLoading, setDraftLoading] = useState(false);
    const [selectedDraftUid, setSelectedDraftUid] = useState(undefined);
    const [tabToClose, setTabToClose] = useState(null);
    const newTabIndex = React.useRef(1);

    const fetchDraftPackingLists = useCallback(async () => {
        setDraftLoading(true);
        try {
            const params = new URLSearchParams({
                p: 1,
                s: 1000,
                status: 'draft'
            });
            const res = await fetch(`${endpoint}/packing-lists?${params.toString()}`, {
                headers: getSafeHeader()
            });
            const data = await res.json();

            if (data.code === 200) {
                setDraftPackingLists(data.data.items || []);
            } else {
                message.error(data.msg || '获取草稿装箱单失败');
            }
        } catch (error) {
            console.error('获取草稿装箱单失败:', error);
            message.error('获取草稿装箱单失败');
        } finally {
            setDraftLoading(false);
        }
    }, []);

    const updateTabTitle = useCallback((key, title) => {
        setItems(prev => prev.map(item => item.key === key ? { ...item, label: title } : item));
    }, []);

    const updateTabMeta = useCallback((key, meta) => {
        setItems(prev => prev.map(item => item.key === key ? { ...item, ...meta } : item));
    }, []);

    const buildTabItem = useCallback((key, label = '新装箱单', draftUid = null) => {
        return {
            key,
            label,
            draftUid,
            children: (
                <PackingListTab
                    tabKey={key}
                    updateTabTitle={updateTabTitle}
                    updateTabMeta={updateTabMeta}
                    initialDraftUid={draftUid}
                    refreshDraftPackingLists={fetchDraftPackingLists}
                    requestCloseTab={setTabToClose}
                />
            )
        };
    }, [fetchDraftPackingLists, updateTabTitle, updateTabMeta]);

    useEffect(() => {
        fetchDraftPackingLists();
    }, [fetchDraftPackingLists]);

    useEffect(() => {
        const savedTabs = localStorage.getItem(packingStorageKey('tabs'));
        if (savedTabs) {
            try {
                const parsed = JSON.parse(savedTabs);
                if (parsed.length > 0) {
                    const numericKeys = parsed
                        .map((tab) => {
                            const key = String(tab.key || '');
                            return /^\d+$/.test(key) ? parseInt(key, 10) : 0;
                        })
                        .filter((value) => Number.isFinite(value) && value > 0);
                    const maxKey = numericKeys.length > 0 ? Math.max(...numericKeys) : 0;
                    newTabIndex.current = maxKey > 0 ? maxKey : 1;

                    setItems(parsed.map(tab => buildTabItem(tab.key, tab.label, tab.draftUid || null)));
                    return;
                }
            } catch (e) { }
        }

        setItems([buildTabItem('1', '新装箱单')]);
    }, [buildTabItem]);

    // 监听 activeKey 或 items 变化，同步到 localStorage
    useEffect(() => {
        localStorage.setItem(packingStorageKey('activeKey'), activeKey);
    }, [activeKey]);

    useEffect(() => {
        const tabsData = items.map(item => ({
            key: item.key,
            label: item.label,
            draftUid: item.draftUid || null
        }));
        localStorage.setItem(packingStorageKey('tabs'), JSON.stringify(tabsData));
    }, [items]);

    const onChange = (newActiveKey) => {
        setActiveKey(newActiveKey);
    };

    const openDraftTab = (record) => {
        if (!record?.uid) return;

        const existingTab = items.find((item) => item.draftUid === record.uid);
        if (existingTab) {
            setActiveKey(existingTab.key);
            setSelectedDraftUid(undefined);
            return;
        }

        const newKey = `draft-${record.uid}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        setItems(prev => [
            ...prev,
            buildTabItem(newKey, record.list_number || record.mark || '草稿', record.uid)
        ]);
        setActiveKey(newKey);
        setSelectedDraftUid(undefined);
    };

    const add = () => {
        newTabIndex.current += 1;
        const newActiveKey = `${newTabIndex.current}`;
        setItems(prev => [
            ...prev,
            {
                label: '新装箱单',
                key: newActiveKey,
                draftUid: null,
                children: (
                    <PackingListTab
                        tabKey={newActiveKey}
                        updateTabTitle={updateTabTitle}
                        updateTabMeta={updateTabMeta}
                        refreshDraftPackingLists={fetchDraftPackingLists}
                        requestCloseTab={setTabToClose}
                    />
                )
            }
        ]);
        setActiveKey(newActiveKey);
    };

    const remove = useCallback((targetKey) => {
        // 清除持久化的数据
        localStorage.removeItem(packingStorageKey(`tab_${targetKey}`));

        let newActiveKey = activeKey;
        let lastIndex = -1;
        items.forEach((item, i) => {
            if (item.key === targetKey) {
                lastIndex = i - 1;
            }
        });
        const newPanes = items.filter((item) => item.key !== targetKey);

        if (newPanes.length && newActiveKey === targetKey) {
            if (lastIndex >= 0) {
                newActiveKey = newPanes[lastIndex].key;
            } else {
                newActiveKey = newPanes[0].key;
            }
        } else if (newPanes.length === 0) {
            const fallbackKey = `${++newTabIndex.current}`;
            newPanes.push({
                label: '新装箱单',
                key: fallbackKey,
                draftUid: null,
                children: (
                    <PackingListTab
                        tabKey={fallbackKey}
                        updateTabTitle={updateTabTitle}
                        updateTabMeta={updateTabMeta}
                        refreshDraftPackingLists={fetchDraftPackingLists}
                        requestCloseTab={setTabToClose}
                    />
                )
            });
            newActiveKey = fallbackKey;
        }

        setItems(newPanes);
        setActiveKey(newActiveKey);
    }, [activeKey, fetchDraftPackingLists, items, updateTabMeta, updateTabTitle]);

    const onEdit = (targetKey, action) => {
        if (action === 'add') {
            add();
        } else {
            remove(targetKey);
        }
    };

    useEffect(() => {
        if (!tabToClose) return;
        remove(tabToClose);
        setTabToClose(null);
    }, [tabToClose, remove]);

    return (
        <div className={entryStyles.createPage}>
            <div className={entryStyles.heading}>
                <div><Title level={3}>创建装箱单</Title><div className={entryStyles.subtitle}>逐箱录入，或拍照提交已填写的纸质装箱单。</div></div>
                <Button type="link" onClick={() => navigate('/packing-lists')}>{workerOnly ? '我的装箱单' : '装箱单列表'}</Button>
            </div>
            <div className={entryStyles.entryModes} role="group" aria-label="装箱单创建方式">
                <Button icon={<EditOutlined />} type={entryMode === 'manual' ? 'primary' : 'default'} aria-pressed={entryMode === 'manual'} onClick={() => setEntryMode('manual')}>手动录入</Button>
                <Button icon={<CameraOutlined />} type={entryMode === 'paper' ? 'primary' : 'default'} aria-pressed={entryMode === 'paper'} onClick={() => setEntryMode('paper')}>拍照上传纸质单</Button>
            </div>
            <div className={entryStyles.paperPanel} hidden={entryMode !== 'paper'}><PaperIntakeUpload /></div>
            <div className={entryStyles.manualPanel} hidden={entryMode !== 'manual'}>
            <Card size="small" style={{ marginBottom: 12 }}>
                <Space wrap style={{ width: '100%' }}>
                    <Text strong>继续编辑草稿</Text>
                    <Select
                        showSearch
                        allowClear
                        placeholder="选择草稿装箱单后会在新标签页中打开"
                        optionFilterProp="label"
                        loading={draftLoading}
                        value={selectedDraftUid}
                        onChange={(uid) => {
                            if (!uid) {
                                setSelectedDraftUid(undefined);
                                return;
                            }
                            const record = draftPackingLists.find((item) => item.uid === uid);
                            if (record) {
                                openDraftTab(record);
                            }
                        }}
                        options={draftPackingLists.map((record) => ({
                            value: record.uid,
                            label: [
                                record.list_number || record.mark || '草稿',
                                record.customer_name || '无客户',
                                record.creator_name || '未知创建人',
                                record.create_date || '-',
                                `${(record.boxes || []).length}箱`
                            ].join(' · ')
                        }))}
                        style={{ minWidth: 0, width: '100%', flex: '1 1 280px' }}
                        notFoundContent="暂无草稿装箱单"
                    />
                    <Button icon={<ReloadOutlined />} onClick={fetchDraftPackingLists} loading={draftLoading}>
                        刷新草稿
                    </Button>
                </Space>
            </Card>
            <Tabs
                type="editable-card"
                onChange={onChange}
                activeKey={activeKey}
                onEdit={onEdit}
                items={items}
                style={{ flex: 1 }}
            />
            </div>
        </div>
    );
}
