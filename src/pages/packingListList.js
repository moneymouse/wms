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
    Form
} from 'antd';
import {
    SearchOutlined,
    EyeOutlined,
    PrinterOutlined,
    ReloadOutlined,
    PlusOutlined,
    CheckOutlined
} from '@ant-design/icons';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';

const { Title, Text } = Typography;
const { Option } = Select;

const getMarkText = (record) => record?.list_number || record?.mark || '-';

export default function PackingListList() {
    const [messageApi, contextHolder] = message.useMessage();

    // 数据状态
    const [packingLists, setPackingLists] = useState([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);

    // 筛选状态
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(20);
    const [search, setSearch] = useState('');
    const [status, setStatus] = useState(null);

    // 详情模态框
    const [detailVisible, setDetailVisible] = useState(false);
    const [currentDetail, setCurrentDetail] = useState(null);
    const [workers, setWorkers] = useState([]);
    const [boxForm] = Form.useForm();
    const [addingBox, setAddingBox] = useState(false);
    const [completing, setCompleting] = useState(false);

    useEffect(() => {
        fetchPackingLists();
        fetchWorkers();
    }, [page, pageSize, status]);

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
                ...(search && { q: search }),
                ...(status && { status })
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
            dataIndex: 'status',
            key: 'status',
            width: 100,
            render: (status) => {
                const statusMap = {
                    draft: { text: '草稿', color: 'default' },
                    completed: { text: '已完成', color: 'success' }
                };
                const s = statusMap[status] || { text: status, color: 'default' };
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
                        style={{ width: 120 }}
                    >
                        <Option value="draft">草稿</Option>
                        <Option value="completed">已完成</Option>
                    </Select>
                    <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
                        搜索
                    </Button>
                    <Button icon={<ReloadOutlined />} onClick={() => {
                        setSearch('');
                        setStatus(null);
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
                    dataSource={packingLists}
                    columns={columns}
                    rowKey="uid"
                    loading={loading}
                    pagination={{
                        current: page,
                        pageSize: pageSize,
                        total: total,
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
                                {currentDetail.customer_name}
                            </Descriptions.Item>
                            <Descriptions.Item label="状态">
                                <Tag color={currentDetail.status === 'completed' ? 'success' : 'default'}>
                                    {currentDetail.status === 'completed' ? '已完成' : '草稿'}
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
                        <div style={{ marginTop: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <Title level={5} style={{ margin: 0 }}>
                                箱子列表 ({currentDetail.boxes?.length || 0})
                            </Title>
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
                            dataSource={currentDetail.boxes || []}
                            renderItem={(box, idx) => (
                                <List.Item
                                    actions={[
                                        <Button
                                            type="link"
                                            icon={<PrinterOutlined />}
                                            onClick={() => window.open(`${endpoint}/box/${box.uid}/label`, '_blank')}
                                        >
                                            打印
                                        </Button>
                                    ]}
                                >
                                    <List.Item.Meta
                                        title={`箱子 ${box.box_number || (idx + 1)}: ${box.item_name || '无品名'}`}
                                        description={
                                            <Space>
                                                <Text>件数: {box.piece_count || 0}</Text>
                                                <Text>重量: {box.weight ? `${box.weight} kg` : '未称重'}</Text>
                                                <Tag color={box.status === 'assigned' ? 'green' : 'orange'}>
                                                    {box.status === 'assigned' ? '已分配' : '待分配'}
                                                </Tag>
                                            </Space>
                                        }
                                    />
                                </List.Item>
                            )}
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
        </div>
    );
}
