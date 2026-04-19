import React, { useState, useEffect } from 'react';
import {
    Modal,
    Table,
    Checkbox,
    Button,
    Space,
    Typography,
    message,
    Empty,
    Spin,
    Collapse,
    Tag,
    Alert,
    Input
} from 'antd';
import { InboxOutlined } from '@ant-design/icons';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';

const { Text } = Typography;
const { Panel } = Collapse;

/**
 * 箱子分配模态框组件
 * 用于在订单详情页中将箱子分配到订单
 * 
 * Props:
 * - visible: 模态框是否可见
 * - onClose: 关闭模态框回调
 * - customerId: 客户ID
 * - customerName: 客户名（用于显示）
 * - orderUid: 目标订单UID
 * - onSuccess: 分配成功后的回调
 */
export default function BoxAssignmentModal({
    visible,
    onClose,
    customerId,
    customerName,
    orderUid,
    onSuccess
}) {
    const [messageApi, contextHolder] = message.useMessage();

    // 数据状态
    const [packingGroups, setPackingGroups] = useState([]);
    const [loading, setLoading] = useState(false);
    const [submitting, setSubmitting] = useState(false);

    // 选中的箱子
    const [selectedBoxes, setSelectedBoxes] = useState([]);
    const [markSearch, setMarkSearch] = useState('');

    // 加载未分配的箱子
    useEffect(() => {
        if (visible) {
            fetchUnassignedBoxes();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [visible, customerId]);

    // 重置选中状态
    useEffect(() => {
        if (!visible) {
            setSelectedBoxes([]);
            setMarkSearch('');
        }
    }, [visible]);

    const getGroupMark = (group) => group?.list_number || group?.mark || '';

    const getBoxSequence = (box, index) => {
        const value = box?.box_number ?? box?.sequence ?? box?.serial_number ?? box?.index;
        if (value !== undefined && value !== null && value !== '') return value;
        return index + 1;
    };

    const getBoxDisplayId = (group, box, index) => {
        const mark = getGroupMark(group);
        const seq = getBoxSequence(box, index);
        return mark ? `${mark}-${seq}` : `箱号 ${seq}`;
    };

    const getBoxItemDetails = (box) => {
        const details = Array.isArray(box?.item_details) ? box.item_details : [];
        if (details.length > 0) {
            return details
                .map((row) => {
                    const itemName = String(row?.item_name || '').trim();
                    const pieceCount = Number(row?.piece_count || 0);
                    if (!itemName) return null;
                    return {
                        itemName,
                        pieceCount: pieceCount > 0 ? pieceCount : 0
                    };
                })
                .filter(Boolean);
        }

        const fallbackName = String(box?.item_name || '').trim();
        const fallbackCount = Number(box?.piece_count || 0);
        return fallbackName
            ? [{ itemName: fallbackName, pieceCount: fallbackCount > 0 ? fallbackCount : 0 }]
            : [];
    };

    const renderBoxItemDetails = (box) => {
        const details = getBoxItemDetails(box);
        if (!details.length) {
            return <Text type="secondary">-</Text>;
        }

        return (
            <Space direction="vertical" size={1}>
                {details.map((detail, idx) => (
                    <Text key={`${box.uid}-detail-${idx}`}>
                        {detail.itemName} x {detail.pieceCount}
                    </Text>
                ))}
            </Space>
        );
    };

    const fetchUnassignedBoxes = async () => {
        setLoading(true);
        try {
            const params = new URLSearchParams({ valid_only: 'true' });
            // if (customerId) {
            //     params.set('customer_id', String(customerId));
            // }

            const res = await fetch(`${endpoint}/boxes/unassigned?${params.toString()}`, {
                headers: getSafeHeader()
            });
            const data = await res.json();

            if (data.code === 200) {
                console.log(data.data)
                setPackingGroups(data.data || []);
            } else {
                messageApi.error(data.msg || '获取数据失败');
            }
        } catch (error) {
            messageApi.error('获取未分配箱子失败');
            console.error(error);
        } finally {
            setLoading(false);
        }
    };

    // 全选/取消全选某个装箱单的所有箱子
    const toggleGroupSelection = (boxes, checked) => {
        const boxUids = boxes.map(b => b.uid);
        setSelectedBoxes(prev => {
            if (checked) {
                // 添加所有箱子
                return [...new Set([...prev, ...boxUids])];
            } else {
                // 移除所有箱子
                return prev.filter(uid => !boxUids.includes(uid));
            }
        });
    };

    // 检查装箱单下的箱子是否全选
    const isGroupAllSelected = (boxes) => {
        return boxes.every(b => selectedBoxes.includes(b.uid));
    };

    // 检查装箱单下的箱子是否部分选中
    const isGroupIndeterminate = (boxes) => {
        const selectedCount = boxes.filter(b => selectedBoxes.includes(b.uid)).length;
        return selectedCount > 0 && selectedCount < boxes.length;
    };

    // 提交分配
    const handleSubmit = async () => {
        if (selectedBoxes.length === 0) {
            messageApi.warning('请至少选择一个箱子');
            return;
        }

        setSubmitting(true);
        try {
            const res = await fetch(`${endpoint}/boxes/assign`, {
                method: 'POST',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    box_uids: selectedBoxes,
                    order_uid: orderUid
                })
            });
            const data = await res.json();

            if (data.code === 200) {
                const successCount = data.data.success?.length || 0;
                const failedCount = data.data.failed?.length || 0;

                if (failedCount > 0) {
                    messageApi.warning(`成功分配 ${successCount} 个箱子，${failedCount} 个失败`);
                } else {
                    messageApi.success(`成功分配 ${successCount} 个箱子`);
                }

                // 回调
                if (onSuccess) {
                    onSuccess(data.data);
                }

                // 关闭模态框
                onClose();
            } else {
                messageApi.error(data.msg || '分配失败');
            }
        } catch (error) {
            messageApi.error('分配箱子失败');
            console.error(error);
        } finally {
            setSubmitting(false);
        }
    };

    // 计算选中箱子的总重量
    const calculateSelectedWeight = () => {
        let total = 0;
        packingGroups.forEach(group => {
            group.boxes.forEach(box => {
                if (selectedBoxes.includes(box.uid)) {
                    total += box.weight || 0;
                }
            });
        });
        return total.toFixed(2);
    };

    // 获取所有箱子数量
    const getTotalBoxCount = () => {
        return packingGroups.reduce((sum, group) => sum + group.boxes.length, 0);
    };

    const filteredGroups = packingGroups.filter(group =>
        getGroupMark(group).toUpperCase().includes((markSearch || '').trim().toUpperCase())
    );

    return (
        <Modal
            title={customerName ? `分配箱子到订单 - ${customerName}` : '分配箱子到订单'}
            open={visible}
            onCancel={onClose}
            width={700}
            footer={[
                <Button key="cancel" onClick={onClose}>
                    取消
                </Button>,
                <Button
                    key="submit"
                    type="primary"
                    onClick={handleSubmit}
                    loading={submitting}
                    disabled={selectedBoxes.length === 0}
                >
                    分配选中的 {selectedBoxes.length} 个箱子
                </Button>
            ]}
        >
            {contextHolder}

            {loading ? (
                <div style={{ textAlign: 'center', padding: '40px 0' }}>
                    <Spin size="large" />
                </div>
            ) : packingGroups.length === 0 ? (
                <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="没有未分配的有效箱子"
                >
                    <Text type="secondary">
                        提示：只有已称重的箱子才会显示在这里
                    </Text>
                </Empty>
            ) : (
                <>
                    <Alert
                        message={`共 ${getTotalBoxCount()} 个可分配箱子（当前筛选 ${filteredGroups.length} 个唛头），已选择 ${selectedBoxes.length} 个，总重量 ${calculateSelectedWeight()} kg`}
                        type="info"
                        showIcon
                        style={{ marginBottom: 16 }}
                    />

                    <Input.Search
                        placeholder="搜索唛头"
                        allowClear
                        value={markSearch}
                        onChange={(e) => setMarkSearch(e.target.value)}
                        style={{ marginBottom: 12 }}
                    />

                    {filteredGroups.length === 0 ? (
                        <Empty
                            image={Empty.PRESENTED_IMAGE_SIMPLE}
                            description="未找到匹配的唛头"
                        />
                    ) : (
                        <Collapse
                            defaultActiveKey={filteredGroups.map(g => g.packing_list_uid)}
                            style={{
                                maxHeight: '50vh',
                                overflowY: 'auto',
                                paddingRight: 8
                            }}
                        >
                            {filteredGroups.map(group => (
                                <Panel
                                    key={group.packing_list_uid}
                                    header={
                                        <Space>
                                            <Checkbox
                                                checked={isGroupAllSelected(group.boxes)}
                                                indeterminate={isGroupIndeterminate(group.boxes)}
                                                onChange={(e) => {
                                                    e.stopPropagation();
                                                    toggleGroupSelection(group.boxes, e.target.checked);
                                                }}
                                                onClick={(e) => e.stopPropagation()}
                                            />
                                            <InboxOutlined />
                                            <Text strong>{getGroupMark(group)}</Text>
                                            <Tag>{group.boxes.length} 个箱子</Tag>
                                        </Space>
                                    }
                                >
                                    <Table
                                        dataSource={group.boxes}
                                        rowKey="uid"
                                        size="small"
                                        pagination={false}
                                        rowSelection={{
                                            selectedRowKeys: selectedBoxes,
                                            onChange: (keys) => {
                                                // 更新选中的箱子，但只影响当前组
                                                const otherSelected = selectedBoxes.filter(
                                                    uid => !group.boxes.find(b => b.uid === uid)
                                                );
                                                setSelectedBoxes([...otherSelected, ...keys.filter(
                                                    key => group.boxes.find(b => b.uid === key)
                                                )]);
                                            }
                                        }}
                                        columns={[
                                            {
                                                title: '标识',
                                                key: 'box_identity',
                                                width: 220,
                                                render: (_, record, index) => (
                                                    <Text strong>{getBoxDisplayId(group, record, index)}</Text>
                                                )
                                            },
                                            {
                                                title: '箱号',
                                                key: 'box_number',
                                                width: 90,
                                                render: (_, record, index) => getBoxSequence(record, index)
                                            },
                                            {
                                                title: '品名件数明细',
                                                key: 'item_details',
                                                width: 260,
                                                render: (_, record) => renderBoxItemDetails(record)
                                            },
                                            {
                                                title: '总件数',
                                                dataIndex: 'piece_count',
                                                key: 'piece_count',
                                                width: 90,
                                                render: (c, record) => {
                                                    if (c !== undefined && c !== null) return c;
                                                    return getBoxItemDetails(record).reduce((sum, row) => sum + (row.pieceCount || 0), 0);
                                                }
                                            },
                                            {
                                                title: '重量',
                                                dataIndex: 'weight',
                                                key: 'weight',
                                                width: 100,
                                                render: (w) => `${w || 0} kg`
                                            }
                                        ]}
                                    />
                                </Panel>
                            ))}
                        </Collapse>
                    )}
                </>
            )}
        </Modal>
    );
}
