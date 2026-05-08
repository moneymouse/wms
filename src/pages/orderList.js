import React, { useEffect, useMemo, useState } from 'react';
import { Button, Input, message, Modal, Row, Space, Table, Typography } from "antd";
import { DeleteOutlined, SearchOutlined } from "@ant-design/icons";
import orderProperty from "../common/orderProperty";
import { useNavigate, useSearchParams } from "react-router-dom";
import { endpoint } from "../config.js";
import getSafeHeader from '../common/safeHeader';
import ExportButton from '../components/ExportButton';

export default function OrderList() {
    const [orderData, setOrderData] = useState([]);
    const [cargo, setCargo] = useState({});
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();
    const [pagination, setPagination] = useState({
        pageSize: 20,
        showSizeChanger: false,
        showTotal: (total) => `共${total}单`,
        current: Number(searchParams.get('p') || 1),
        total: 0
    });
    let flag = false;

    async function fetchOrderData(_pagination = {}, sorter = {}, query = searchParams.get('q') || '') {
        const newPagination = { ...pagination, ..._pagination };
        // p=${newPagination.current}&s=${newPagination.pageSize}${sorter.order?`&sf=${sorter.column.dataIndex}&so=${Number(sorter.order==='descend')}`:""}${query&&`&q=${query}`}
        const { data, total } = await (await fetch(`${endpoint}/orders?` +
            new URLSearchParams({
                q: query,
                p: newPagination.current,
                s: newPagination.pageSize,
                ...(sorter.order && {
                    sf: sorter.column.dataIndex,
                    so: Number(sorter.order === 'descend')
                })
            }).toString(), {
            headers: getSafeHeader()
        })).json();

        // setOrderData((_data) => [..._data, ...sortedData.map((v) => ({...v, key: v.uid})), ]);
        setOrderData(data.map((v) => ({ ...v, key: v.uid })));

        // 分页
        setPagination({
            ...newPagination,
            total
        });
    }

    //请求并初始化数据
    const [tableLoading, setTableLoading] = useState(false);
    useEffect(() => {
        (async () => {
            if (flag) return;
            setTableLoading(true);
            await fetchOrderData();

            searchParams.set('p', pagination.current.toString());
            // setSearchParams(searchParams);

            // const res = await fetch(`${endpoint}/cargo`, {
            //     headers: getSafeHeader()
            // });
            const p = { data: {} };
            setCargo(p.data);

            setTableLoading(false);
            flag = true;
        })()
    }, []);

    // 配置字段名以及类型
    const columns = orderProperty.map((property, i) => {
        return {
            key: property.name,
            title: property.label,
            dataIndex: property.name,
            width: i < 2 ? 160 : property.width || 200,
            ellipsis: true,
            sorter: property.name === 'order_date' || property.name === 'update_date' ?
                {
                    compare: (a, b) => new Date(a[property.name]).getTime() - new Date(b[property.name]).getTime(),
                    multiple: 1
                } :
                (property.name === 'receiver_name' || property.name === 'customer_name')
                    ?
                    {
                        compare: (a, b) => {
                            // 处理null或undefined情况
                            const nameA = a[property.name] || '';
                            const nameB = b[property.name] || '';
                            return nameA.localeCompare(nameB);
                        },
                        multiple: 2
                    } :
                    false,
            fixed: i < 2 ? 'left' : '',
            render: (text, record, i) => {
                if (property.name === 'order_id') {
                    return text && <Typography.Text copyable key={i}>
                        <Button type='link' onClick={() => navigate(record.uid)}>{text}</Button>
                    </Typography.Text>
                }
                return text && <Typography.Text copyable key={i}>{text}</Typography.Text>
            }
        }
    });

    columns.push({
        title: '操作',
        dataIndex: '',
        key: 'x',
        width: 120,
        fixed: 'right',
        align: 'center',
        render: (_, record) => (
            <Space>
                <Button type="link" size="small" onClick={() => {
                    navigate(record.uid);
                }}>详情</Button>
                {/*<Button type="link" size="small" onClick={() => navigate(`/?orderId=${record.order_id}`)}>新建</Button>*/}
            </Space>
        ),
    });

    //查找逻辑
    const keyword = searchParams.get('q') || '';

    const handleSearch = async (e) => {
        const value = e.target.value;
        if (value) {
            setSearchParams({ ...searchParams, q: value });
        } else {
            // 如果搜索框为空，清除查询参数
            searchParams.delete('q');
            setSearchParams(searchParams);
        }
        setTableLoading(true);
        await fetchOrderData({ current: 1 }, {}, value);
        setTableLoading(false);
        setTableLoading(false);
    }

    const filteredData = useMemo(() => {
        const _keyword = keyword.split("\n").map(value => value.trim());
        return orderData.filter((v) => {

            for (let i in v) {
                if (v[i] === null) continue;
                if (v[i].toString().toLowerCase().includes(keyword.toString().split('-')[0].toLowerCase())) return true
            }
            for (let c of cargo[v['uid']] || []) {
                for (let k of _keyword) {
                    if (c['transfer_id'] && c['transfer_id'].toString().toLowerCase().includes(k.toString().toLowerCase())) return true
                    if (c['waybill_id'] && c['waybill_id'].toString().toLowerCase().includes(k.toString().toLowerCase())) return true
                }
            }
            return false;
        })
    }, [keyword, orderData, cargo])

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
            content: `确定要归档选中的 ${selectedKeys.length} 个订单吗？归档后订单将不再显示在列表中。`,
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
                    } else {
                        message.error(response.message || '归档失败');
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
                    } else {
                        message.error(response.message || '删除失败');
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
    const handleTableChange = async (pagination, filters, sorter) => {
        setTableLoading(true)
        searchParams.set('p', pagination.current);
        setSearchParams(searchParams);
        await fetchOrderData(pagination, Array.isArray(sorter) ? sorter[-1] : sorter);
        // `dataSource` is useless since `pageSize` changed
        if (pagination.pageSize !== pagination.pageSize) {
            setOrderData([]);
        }
        setTableLoading(false);
    };

    return (
        <>
            <Typography.Title level={4} style={{ marginBottom: '2rem' }}>订单列表/Orders List</Typography.Title>
            <Row style={{ marginBottom: "2rem" }}>
                <Space size={'large'}>
                    <Space>
                        <Input.TextArea
                            rows={1}
                            onChange={handleSearch}
                            placeholder={"订单号/客户名/收件人名/国家"}
                            defaultValue={keyword}
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
                                title: '转单号',
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
        </>
    )
}
