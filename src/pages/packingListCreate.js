import React, { useState, useEffect } from 'react';
import {
    Form,
    Select,
    Button,
    Input,
    InputNumber,
    message,
    Card,
    Space,
    Table,
    Upload,
    Image,
    Divider,
    Typography,
    Popconfirm,
    Tabs
} from 'antd';
import {
    PlusOutlined,
    DeleteOutlined,
    CameraOutlined,
    SaveOutlined,
    CheckOutlined
} from '@ant-design/icons';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';

const { Title, Text } = Typography;
const { Option } = Select;

const COMMON_GOODS = ['衣服', '鞋子', '包包', '日用品', '电子产品', '玩具', '化妆品', '食品', '零食', '书籍', '配件', '饰品', '五金', '文具', '护肤品', '家居', '杂货'];

function PackingListTab({ tabKey, updateTabTitle }) {
    const [form] = Form.useForm();
    const [messageApi, contextHolder] = message.useMessage();

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

    // 箱子表单
    const [boxForm] = Form.useForm();

    // 加载客户列表和操作员列表
    useEffect(() => {
        fetchCustomers();
        fetchWorkers();

        // 恢复持久化状态
        const savedState = localStorage.getItem(`packingList_tab_${tabKey}`);
        if (savedState) {
            try {
                const parsed = JSON.parse(savedState);
                if (parsed.selectedCustomerId) setSelectedCustomerId(parsed.selectedCustomerId);
                if (parsed.photos) setPhotos(parsed.photos);
                if (parsed.boxes) setBoxes(parsed.boxes);
                if (parsed.packingListUid) setPackingListUid(parsed.packingListUid);
                if (parsed.listNumber) setListNumber(parsed.listNumber);
                if (parsed.inputMark) {
                    setInputMark(parsed.inputMark);
                    form.setFieldValue('mark', parsed.inputMark);
                    if (parsed.selectedCustomerId) form.setFieldValue('customer_id', parsed.selectedCustomerId);
                }
            } catch (e) {
                console.error("恢复保存的状态失败", e);
            }
        }
    }, [tabKey]);

    // 监听状态变化并持久化
    useEffect(() => {
        const stateToSave = {
            selectedCustomerId, photos, boxes, packingListUid, listNumber, inputMark
        };
        localStorage.setItem(`packingList_tab_${tabKey}`, JSON.stringify(stateToSave));
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
            const res = await fetch(`${endpoint}/users/list`, {
                headers: getSafeHeader()
            });
            const data = await res.json();
            if (data.code === 200) {
                // 过滤出操作员角色的用户
                const workerList = (data.data || []);
                setWorkers(workerList);
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
                setPackingListUid(data.data.uid);
                const finalMark = data.data.list_number || data.data.mark || normalizedMark;
                updateTabTitle(tabKey, finalMark);
                setListNumber(finalMark);
                messageApi.success(`装箱单创建成功！唛头: ${finalMark}`);
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

    // 上传照片
    const handleUploadPhoto = async (file) => {
        const formData = new FormData();
        formData.append('photo', file);

        try {
            const res = await fetch(`${endpoint}/upload/photo`, {
                method: 'POST',
                headers: getSafeHeader(),
                body: formData
            });
            const data = await res.json();

            if (data.code === 200) {
                setPhotos(prev => [...prev, { url: data.data.url, uid: Date.now() }]);
                messageApi.success('照片上传成功');
            } else {
                messageApi.error(data.msg || '上传失败');
            }
        } catch (error) {
            messageApi.error('上传照片失败');
            console.error(error);
        }

        return false; // 阻止默认上传行为
    };

    // 删除照片
    const handleRemovePhoto = (uid) => {
        setPhotos(prev => prev.filter(p => p.uid !== uid));
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

            const res = await fetch(`${endpoint}/packing-list/${packingListUid}/box`, {
                method: 'POST',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    item_name: Array.isArray(values.item_name) ? values.item_name.join(', ') : values.item_name,
                    piece_count: values.piece_count,
                    weight: values.weight || null
                })
            });
            const data = await res.json();

            if (data.code === 200) {
                const newBox = {
                    ...data.data,
                    key: data.data.uid,
                    workers: values.worker_ids || []
                };

                // 如果选择了操作员，设置操作员
                if (values.worker_ids && values.worker_ids.length > 0) {
                    await setBoxWorkers(data.data.uid, values.worker_ids);
                }

                setBoxes(prev => [...prev, newBox]);
                boxForm.setFieldsValue({ weight: null, piece_count: null }); // 保留品名和操作员
                messageApi.success('箱子添加成功');
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
            await fetch(`${endpoint}/box/${boxUid}/workers`, {
                method: 'PUT',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ worker_ids: workerIds })
            });
        } catch (error) {
            console.error('设置操作员失败:', error);
        }
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

    // 提交装箱单
    const handleComplete = async () => {
        if (!packingListUid) {
            messageApi.warning('请先创建装箱单');
            return;
        }

        if (boxes.length === 0) {
            messageApi.warning('请至少添加一个箱子');
            return;
        }

        // 检查是否所有箱子都已称重
        const unweighedBoxes = boxes.filter(b => !b.weight || b.weight <= 0);
        if (unweighedBoxes.length > 0) {
            messageApi.warning(`还有 ${unweighedBoxes.length} 个箱子未称重`);
            return;
        }

        try {
            const res = await fetch(`${endpoint}/packing-list/${packingListUid}/complete`, {
                method: 'POST',
                headers: getSafeHeader()
            });
            const data = await res.json();

            if (data.code === 200) {
                messageApi.success('装箱单已提交！');
                // 重置页面
                handleReset();
            } else {
                messageApi.error(data.msg || '提交失败');
            }
        } catch (error) {
            messageApi.error('操作失败');
            console.error(error);
        }
    };

    // 重置页面
    const handleReset = () => {
        setPackingListUid(null);
        setListNumber('');
        setSelectedCustomerId(null);
        setInputMark('');
        setPhotos([]);
        setBoxes([]);
        form.resetFields();
        boxForm.resetFields();
        localStorage.removeItem(`packingList_tab_${tabKey}`);
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
            dataIndex: 'item_name',
            key: 'item_name',
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
                        <Popconfirm title="确定删除？" onConfirm={() => handleDeleteBox(record.uid)}>
                            <Button type="text" danger icon={<DeleteOutlined />} style={{ padding: 0 }} />
                        </Popconfirm>
                    </Space>
                );
            }
        }
    ];

    return (
        <div style={{ padding: '8px' }}>
            {contextHolder}

            {/* 基本信息 */}
            {!packingListUid ? (
                <>
                    <Title level={4}>创建新装箱单</Title>
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
                        <Divider orientation="left" style={{ margin: '12px 0' }}>照片</Divider>
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
                            ))}
                            <Upload
                                accept="image/*"
                                showUploadList={false}
                                beforeUpload={handleUploadPhoto}
                            >
                                <Button size="large" icon={<CameraOutlined />}>拍照/上传</Button>
                            </Upload>
                        </Space>

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
                    <Space split={<Divider type="vertical" />}>
                        <Text type="secondary">当前唛头</Text>
                        <Text strong style={{ fontSize: 18, color: '#52c41a' }}>{listNumber}</Text>
                        <Button type="link" size="small" onClick={handleReset}>[重置/新建]</Button>
                    </Space>
                </Card>
            )}

            {/* 添加箱子 */}
            {packingListUid && (
                <Card title="➕ 添加新箱子" style={{ marginBottom: 16 }} size="small" bodyStyle={{ padding: '12px' }}>
                    <Form form={boxForm} layout="vertical">
                        <Form.Item
                            name="item_name"
                            label="品名选择 (可多选)"
                            rules={[{ required: true, message: '选择或输入品名' }]}
                            style={{ marginBottom: 12 }}
                        >
                            <Select
                                mode="tags"
                                size="large"
                                placeholder="选择或输入品名"
                                style={{ width: '100%' }}
                                options={COMMON_GOODS.map(g => ({ label: g, value: g }))}
                            />
                        </Form.Item>

                        <Form.Item
                            name="piece_count"
                            label="件数"
                            rules={[{ required: true, message: '请输入件数' }]}
                            style={{ marginBottom: 12 }}
                        >
                            <InputNumber
                                size="large"
                                placeholder="请输入件数"
                                min={1}
                                precision={0}
                                step={1}
                                style={{ width: '100%' }}
                            />
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
                                    <Option key={w.id} value={w.id}>{w.name}</Option>
                                ))}
                            </Select>
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
            )}

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
                        />

                        <div style={{ marginTop: 16, textAlign: 'right' }}>
                            <Space>
                                <Text>
                                    总重量: <Text strong>{boxes.reduce((sum, b) => sum + (b.weight || 0), 0).toFixed(2)} kg</Text>
                                </Text>
                                <Button
                                    type="primary"
                                    icon={<CheckOutlined />}
                                    onClick={handleComplete}
                                    style={{ marginLeft: 16 }}
                                >
                                    提交装箱单
                                </Button>
                            </Space>
                        </div>
                    </Card>
                )
            }

        </div>
    );
}

export default function PackingListCreate() {
    const [activeKey, setActiveKey] = useState(() => localStorage.getItem('packingList_activeKey') || '1');
    const [items, setItems] = useState([]);
    const newTabIndex = React.useRef(1);

    useEffect(() => {
        const savedTabs = localStorage.getItem('packingList_tabs');
        if (savedTabs) {
            try {
                const parsed = JSON.parse(savedTabs);
                if (parsed.length > 0) {
                    const maxKey = Math.max(...parsed.map(t => parseInt(t.key, 10) || 0));
                    newTabIndex.current = maxKey > 0 ? maxKey : 1;

                    setItems(parsed.map(tab => ({
                        key: tab.key,
                        label: tab.label,
                        children: <PackingListTab tabKey={tab.key} updateTabTitle={updateTabTitle} />
                    })));
                    return;
                }
            } catch (e) { }
        }

        setItems([
            { key: '1', label: '新装箱单', children: <PackingListTab tabKey="1" updateTabTitle={updateTabTitle} /> }
        ]);
    }, []);

    // 监听 activeKey 或 items 变化，同步到 localStorage
    useEffect(() => {
        localStorage.setItem('packingList_activeKey', activeKey);
    }, [activeKey]);

    useEffect(() => {
        const tabsData = items.map(item => ({ key: item.key, label: item.label }));
        localStorage.setItem('packingList_tabs', JSON.stringify(tabsData));
    }, [items]);

    const updateTabTitle = (key, title) => {
        setItems(prev => prev.map(item => item.key === key ? { ...item, label: title } : item));
    };

    const onChange = (newActiveKey) => {
        setActiveKey(newActiveKey);
    };

    const add = () => {
        newTabIndex.current += 1;
        const newActiveKey = `${newTabIndex.current}`;
        setItems(prev => [
            ...prev,
            {
                label: '新装箱单',
                key: newActiveKey,
                children: <PackingListTab tabKey={newActiveKey} updateTabTitle={updateTabTitle} />
            }
        ]);
        setActiveKey(newActiveKey);
    };

    const remove = (targetKey) => {
        // 清除持久化的数据
        localStorage.removeItem(`packingList_tab_${targetKey}`);

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
                children: <PackingListTab tabKey={fallbackKey} updateTabTitle={updateTabTitle} />
            });
            newActiveKey = fallbackKey;
        }

        setItems(newPanes);
        setActiveKey(newActiveKey);
    };

    const onEdit = (targetKey, action) => {
        if (action === 'add') {
            add();
        } else {
            remove(targetKey);
        }
    };

    return (
        <div style={{ padding: '0', height: '100%', display: 'flex', flexDirection: 'column' }}>
            <Tabs
                type="editable-card"
                onChange={onChange}
                activeKey={activeKey}
                onEdit={onEdit}
                items={items}
                style={{ flex: 1 }}
            />
        </div>
    );
}
