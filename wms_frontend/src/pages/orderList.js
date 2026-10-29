import React, { useEffect, useMemo, useState } from 'react';
import { Button, Input, message, Modal, Row, Space, Table, Typography } from "antd";
import { DeleteOutlined, HistoryOutlined, SearchOutlined } from "@ant-design/icons";
import { buildOrderColumns } from '../common/orderColumns';
import { useNavigate } from "react-router-dom";
import { endpoint } from "../config.js";
import getSafeHeader from '../common/safeHeader';
import useUrlState from '../common/useUrlState';
import ExportButton from '../components/ExportButton';
import FeatureTour from '../components/FeatureTour';
import OrderHistoryDrawer from '../components/OrderHistoryDrawer';
import { hasPermission } from '../common/roleConfig';
import { COST_QUOTE_RECEIPT_TOUR, getCostQuoteReceiptChapter } from '../common/featureTourConfig';
import {
    clearFeatureTourFlow,
    getCurrentTourUser,
    readFeatureTourFlow,
    saveFeatureTourFlow,
} from '../common/featureTourState';

const selectQuoteOrderTourChapter = getCostQuoteReceiptChapter('selectQuoteOrder');

export default function OrderList() {
    const [orderData, setOrderData] = useState([]);
    const [cargo] = useState({});
    const [deletedHistoryOpen, setDeletedHistoryOpen] = useState(false);
    const [deletedHistoryRefreshKey, setDeletedHistoryRefreshKey] = useState(0);
    const navigate = useNavigate();
    const { userId: tourUserId } = getCurrentTourUser();
    const tourFlow = readFeatureTourFlow(tourUserId);
    const userRoles = useMemo(() => {
        try {
            const token = localStorage.getItem('jwt');
            const payload = token ? JSON.parse(atob(token.split('.')[1])) : {};
            return payload.roles || (payload.role ? [payload.role] : []);
        } catch (_) {
            return [];
        }
    }, []);
    const canViewOrderHistory = hasPermission(userRoles, ['admin', 'store_manager']);
    const selectingQuoteOrder = tourFlow?.campaignId === COST_QUOTE_RECEIPT_TOUR.id
        && tourFlow.stage === 'select-quote-order';
    const selectQuoteOrderTourSteps = selectQuoteOrderTourChapter.steps.map(step => ({
        ...step,
        target: () => document.querySelector('[data-tour="workflow-order-list"]'),
    }));
    const [page, setPage] = useUrlState('p', 1, { validate: value => Number.isSafeInteger(value) && value > 0 });
    const [pageSize, setPageSize] = useUrlState('s', 20, { validate: value => Number.isSafeInteger(value) && value > 0 });
    const [keyword, setKeyword] = useUrlState('q', '');
    const [sortField, setSortField] = useUrlState('sf', '');
    const [sortDirection, setSortDirection] = useUrlState('so', 1, { validate: value => value === 0 || value === 1 });
    const [total, setTotal] = useState(0);
    const [tableLoading, setTableLoading] = useState(false);
    const pagination = { current: page, pageSize, total, showSizeChanger: false, showTotal: count => `共${count}单` };

    useEffect(() => {
        let active = true;
        const controller = new AbortController();
        const params = new URLSearchParams({ q: keyword, p: page, s: pageSize,
            ...(sortField && { sf: sortField, so: sortDirection }) });
        setTableLoading(true);
        fetch(`${endpoint}/orders?${params}`, { headers: getSafeHeader(), signal: controller.signal })
            .then(response => response.json())
            .then(result => {
                if (!active) return;
                setOrderData((result.data || []).map(row => ({ ...row, key: row.uid })));
                setTotal(result.total || 0);
            })
            .catch(error => { if (active && error.name !== 'AbortError') message.error('读取订单列表失败'); })
            .finally(() => { if (active) setTableLoading(false); });
        return () => { active = false; controller.abort(); };
    }, [keyword, page, pageSize, sortField, sortDirection]);

    const columns = buildOrderColumns({ onOpenOrder: uid => openOrder(uid) }).map(column => ({
        ...column,
        sortOrder: column.dataIndex === sortField ? (sortDirection === 1 ? 'descend' : 'ascend') : null,
    }));

    columns.push({
        title: '操作',
        dataIndex: '',
        key: 'x',
        width: 120,
        fixed: 'right',
        align: 'center',
        render: (_, record) => (
            <Space>
                <Button type="link" size="small" onClick={() => openOrder(record.uid)}>详情</Button>
                {/*<Button type="link" size="small" onClick={() => navigate(`/?orderId=${record.order_id}`)}>新建</Button>*/}
            </Space>
        ),
    });

    const handleSearch = event => {
        setKeyword(event.target.value);
        setPage(1);
    };

    //选择与导出逻辑
    const [selectedKeys, setSelectedKeys] = useState([]);
    const [archiveLoading, setArchiveLoading] = useState(false); //归档时按钮loading状态
    const [deleteLoading, setDeleteLoading] = useState(false); //删除时按钮loading状态

    const handleSelectedChange = (newSelectedKey) => {
        setSelectedKeys(newSelectedKey);
    }

    // 归档订单逻辑
    const handleArchive = async () => {
        if (selectedKeys.length <= 0) {
            message.warning('请先选择要归档的订单');
            return;
        }

        Modal.confirm({
            title: '确认归档订单',
            content: `确定要归档选中的 ${selectedKeys.length} 个订单吗？关联货物/箱子及财务信息会一并归档，历史审计记录仍会保留。`,
            okText: '确认归档',
            okType: 'danger',
            cancelText: '取消',
            onOk: async () => {
                try {
                    setArchiveLoading(true);

                    let passKey = prompt("请输入管理密码。")
                    if (passKey !== "159753") {
                        alert("密码错误")
                        return;
                    }

                    // 发送归档请求
                    const result = await fetch(`${endpoint}/orders/archive`, {
                        method: 'POST',
                        headers: {
                            ...getSafeHeader(),
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            uid_list: selectedKeys
                        })
                    });

                    const response = await result.json();

                    if (response.code === 200) {
                        message.success('归档成功');

                        // 更新数据，移除已归档的订单
                        setOrderData(prevData => prevData.filter(item => !selectedKeys.includes(item.key)));

                        // 清空选中状态
                        setSelectedKeys([]);
                        if (deletedHistoryOpen) {
                            setDeletedHistoryRefreshKey(value => value + 1);
                        }
                    } else {
                        message.error(response.msg || response.message || '归档失败');
                    }
                } catch (error) {
                    console.error('归档订单时出错:', error);
                    message.error('归档订单失败，请稍后重试');
                } finally {
                    setArchiveLoading(false);
                }
            }
        });
    };

    // 删除订单逻辑
    const handleDelete = async () => {
        if (selectedKeys.length <= 0) {
            message.warning('请先选择要删除的订单');
            return;
        }

        Modal.confirm({
            title: '确认彻底删除订单',
            content: `确定要彻底删除选中的 ${selectedKeys.length} 个订单吗？此操作不可恢复，订单数据将从数据库中永久删除。`,
            okText: '确认删除',
            okType: 'danger',
            cancelText: '取消',
            onOk: async () => {
                try {
                    setDeleteLoading(true);

                    let passKey = prompt("请输入管理密码。")
                    if (passKey !== "159753") {
                        alert("密码错误")
                        return;
                    }

                    // 发送删除请求
                    const result = await fetch(`${endpoint}/orders`, {
                        method: 'DELETE',
                        headers: {
                            ...getSafeHeader(),
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            uid_list: selectedKeys
                        })
                    });

                    const response = await result.json();

                    if (response.code === 200) {
                        message.success('删除成功');

                        // 更新数据，移除已删除的订单
                        setOrderData(prevData => prevData.filter(item => !selectedKeys.includes(item.key)));

                        // 清空选中状态
                        setSelectedKeys([]);
                        if (deletedHistoryOpen) {
                            setDeletedHistoryRefreshKey(value => value + 1);
                        }
                    } else {
                        message.error(response.msg || response.message || '删除失败');
                    }
                } catch (error) {
                    console.error('删除订单时出错:', error);
                    message.error('删除订单失败，请稍后重试');
                } finally {
                    setDeleteLoading(false);
                }
            }
        });
    };
    const handleTableChange = (nextPagination, filters, sorter) => {
        const currentSorter = Array.isArray(sorter) ? sorter[sorter.length - 1] : sorter;
        setPage(nextPagination.current);
        setPageSize(nextPagination.pageSize);
        setSortField(currentSorter?.order ? currentSorter.field || currentSorter.column?.dataIndex || '' : '');
        setSortDirection(currentSorter?.order === 'ascend' ? 0 : 1);
    };

    function openOrder(orderUid) {
        if (selectingQuoteOrder) {
            saveFeatureTourFlow({
                userId: tourUserId,
                campaignId: COST_QUOTE_RECEIPT_TOUR.id,
                stage: 'quote',
            });
        }
        navigate(orderUid);
    }

    return (
        <>
            <Typography.Title level={4} style={{ marginBottom: '2rem' }}>订单列表/Orders List</Typography.Title>
            <Row style={{ marginBottom: "2rem" }}>
                <Space size={'large'}>
                    <Space>
                        <Input.TextArea
                            rows={1}
                            onChange={handleSearch}
                            placeholder={"订单号/客户名/收件人名/业务员/国家"}
                            value={keyword}
                            style={{ width: '20rem' }}
                        />
                        <Button type="primary" icon={<SearchOutlined />}>查找</Button>
                    </Space>

                    {/* 导出按钮 */}
                    <ExportButton
                        selectedKeys={selectedKeys}
                        data={orderData}
                        onSuccess={() => setSelectedKeys([])}
                    />

                    {canViewOrderHistory && (
                        <Button icon={<HistoryOutlined />} onClick={() => setDeletedHistoryOpen(true)}>
                            已删除订单历史
                        </Button>
                    )}

                    {selectedKeys.length > 0 && <Button
                        danger
                        loading={archiveLoading}
                        onClick={handleArchive}
                        disabled={selectedKeys.length === 0}
                    >
                        归档选中订单
                    </Button>}
                    {selectedKeys.length > 0 && <Button
                        type="danger"
                        icon={<DeleteOutlined />}
                        loading={deleteLoading}
                        onClick={handleDelete}
                        disabled={selectedKeys.length === 0}
                    >
                        删除选中订单
                    </Button>}
                </Space>
            </Row>

            <div data-tour="workflow-order-list">
                <Table loading={tableLoading}
                    rowSelection={{ type: 'checkbox', onChange: handleSelectedChange, selectedRowKeys: selectedKeys }}
                    columns={columns} dataSource={orderData}
                    scroll={{ x: 3600, y: 600 }}
                    defaultSortOrder={['order_date', 'descend']}
                    pagination={pagination}
                    expandable={
                        {
                            expendedRowRender(record) {
                                console.log('a')
                                const columns = {
                                    key: 'uid',
                                    title: '原单号',
                                    dataIndex: 'transfer_id',
                                    render: (text, record, i) => text &&
                                        <Typography.Text copyable key={i}>{text}</Typography.Text>
                                }
                                const data = cargo[record.key].map((v, i) => ({ ...v, key: i })) || [];
                                return <Table columns={columns} dataSource={data} pagination={false} />;
                            },
                            defaultExpandAllRows: true
                        }
                    }
                    onChange={handleTableChange}
                />
            </div>
            <FeatureTour
                chapter={selectQuoteOrderTourChapter}
                steps={selectQuoteOrderTourSteps}
                autoEnabled={false}
                forceAutoStart={selectingQuoteOrder}
                showTrigger={false}
                persistOnFinish={false}
                persistOnDismiss={false}
                onTourEnd={(status) => {
                    if (status === 'dismissed') clearFeatureTourFlow(tourUserId);
                }}
            />
            <OrderHistoryDrawer
                open={deletedHistoryOpen}
                onClose={() => setDeletedHistoryOpen(false)}
                deletedMode
                refreshKey={deletedHistoryRefreshKey}
            />
        </>
    )
}
