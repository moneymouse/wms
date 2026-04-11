import React, { useEffect, useState } from "react";
import {
    Badge,
    Button,
    Descriptions,
    Form,
    InputNumber,
    message,
    Popconfirm,
    Popover,
    Space,
    Select,
    Table,
    Timeline,
    Typography
} from "antd";
import orderProperty from "../common/orderProperty";
// import crypto from 'crypto';
import Input from "antd/es/input/Input";
import { endpoint } from "../config.js";
import { useParams } from "react-router-dom";
import getSafeHeader from '../common/safeHeader';
import styles from './orderDetail.module.css';
import Transportation from "../components/transportation";
import ExportButton from "../components/ExportButton";
import trackStatus from "../common/trackStatus";
import GoodInput from "../components/GoodName";
import BoxAssignmentModal from "../components/BoxAssignmentModal";
import { InboxOutlined } from "@ant-design/icons";

const passHash = '18667b982b1c774d3c096422e457906afb227cfc7f956d3f4fc1f9bc07b98862';

const verify = () => {
    // const now_time = (new Date()).getTime()
    // // 十分钟内有效
    // if (now_time - Number(window.localStorage.getItem('verified')) < 300000) return true;
    // // const pass = window.prompt('请输入管理员密码');
    // const pass = 0;
    // const hashFunction = crypto.createHash('sha256');
    // if (!pass || hashFunction.update(pass).digest().toString('hex') !== passHash) {
    //     window.localStorage.setItem('verified', now_time.toString());
    //     return true;
    // }
    // window.localStorage.setItem('verified', now_time.toString());
    return true;
}

let focusFlag = '';


const EditableCell = (props) => {
    const {
        editing,
        dataIndex,
        title,
        // inputType,
        record,
        index,
        children,
        onClick,
        onEnter,
        onBlur,
        ...restProps
    } = props;
    const dict = {
        weight: {
            addonAfter: 'kg'
        },
        price: {
            addonAfter: '元'
        },
        count: {
            addonAfter: '件'
        }
    }
    return (
        <td {...restProps}>
            {editing ? (
                <Form.Item
                    name={dataIndex}
                    style={{
                        margin: 0,
                    }}
                    rules={[
                        {
                            required: false,
                            message: `请输入 ${title}!`,
                        },
                    ]}
                >

                    {dataIndex !== 'real_en_name' ? (<Space>
                        <Input
                            rootClassName={'myEditableCellInputIdToAvoidBlur'}
                            onBlur={onBlur}
                            ref={(node) => {
                                if (focusFlag === dataIndex && node) {
                                    node.focus();
                                    focusFlag = '';
                                }
                                return () => {
                                    focusFlag = '';
                                }
                            }}
                            onPressEnter={() => onEnter(dataIndex)}
                            defaultValue={record[dataIndex] === 0 ? '' : record[dataIndex]}
                        />
                    </Space>) :
                        (<GoodInput onEnter={() => onEnter(dataIndex)} onBlur={onBlur}
                            defaultValue={record[dataIndex]} />)}


                </Form.Item>
            ) : (
                <div
                    className={dataIndex ? styles['editable-cell-value-wrap'] : ""}
                    style={{ paddingInlineEnd: 24 }}
                    onClick={onClick}
                >
                    {children}
                </div>
            )}
        </td>
    );
};

export default function OrderDetail() {
    // const _orderProperty = [...orderProperty];
    const { order_id } = useParams()

    //message
    const [messageX, messageComponent] = message.useMessage();

    //description data状态管理
    const [descriptionData, setDescriptionData] = useState({});
    const [jwtPayload, setJwtPayload] = useState({});
    const [salesman, setSalesman] = useState(null);
    const [salesmanOptions, setSalesmanOptions] = useState([]);
    const [salesmanEditorValue, setSalesmanEditorValue] = useState(undefined);
    const [salesmanLoading, setSalesmanLoading] = useState(false);
    const [salesmanSaving, setSalesmanSaving] = useState(false);
    const [salesmanUsersLoading, setSalesmanUsersLoading] = useState(false);
    const [salesmanEditing, setSalesmanEditing] = useState(false);

    // 客户联系信息状态
    const [customerContact, setCustomerContact] = useState({ phone: '', wechat: '' });
    const [customerContactLoading, setCustomerContactLoading] = useState(false);

    // 箱子分配模态框状态
    const [boxAssignmentVisible, setBoxAssignmentVisible] = useState(false);

    // 检查是否有查看客户联系信息的权限
    const canViewCustomerContact = ['admin', 'store_manager', 'salesperson'].includes(jwtPayload?.role);
    // 检查是否有分配箱子的权限
    const canAssignBoxes = ['admin', 'store_manager', 'salesperson'].includes(jwtPayload?.role);

    useEffect(() => {
        const jwt = localStorage.getItem('jwt');
        if (jwt) {
            try {
                const parts = jwt.split('.');
                if (parts.length === 3) {
                    setJwtPayload(JSON.parse(atob(parts[1])));
                }
            } catch (e) {
                console.error('解析 JWT 时出错:', e);
            }
        }

        (async () => {
            const { data } = await (await fetch(`${endpoint}/orders/${order_id}`, { headers: getSafeHeader() })).json();
            setDescriptionData(data);
            setSalesman(data?.salesman || null);
            setSalesmanEditorValue(data?.salesman?.id ?? data?.salesman_id ?? undefined);
        })();

        (async () => {
            setSalesmanLoading(true);
            try {
                const res = await (await fetch(`${endpoint}/orders/${order_id}/salesman`, { headers: getSafeHeader() })).json();
                if (res.code === 200) {
                    setSalesman(res.data || null);
                    setSalesmanEditorValue(res.data?.id ?? undefined);
                    setDescriptionData(prev => ({ ...prev, salesman: res.data || null, salesman_id: res.data?.id ?? null }));
                }
            } finally {
                setSalesmanLoading(false);
            }
        })();
    }, []);

    useEffect(() => {
        (async () => {
            setSalesmanUsersLoading(true);
            try {
                const res = await (await fetch(`${endpoint}/users/list`, { headers: getSafeHeader() })).json();
                if (res.code === 200 && Array.isArray(res.data)) {
                    setSalesmanOptions(
                        res.data.map((user) => ({
                            value: user.id,
                            label: `${user.name || '-'} (${user.phone || '-'})`
                        }))
                    );
                }
            } finally {
                setSalesmanUsersLoading(false);
            }
        })();
    }, [jwtPayload]);

    // 获取客户联系信息
    useEffect(() => {
        if (canViewCustomerContact && descriptionData.customer_ids) {
            (async () => {

                setCustomerContactLoading(true);
                try {
                    const res = await (await fetch(`${endpoint}/customer_detail/${descriptionData.customer_ids[0]}`, { headers: getSafeHeader() })).json();
                    if (res.code === 200 && res.data) {
                        setCustomerContact({
                            phone: res.data.phone || '',
                            wechat: res.data.wechat || ''
                        });
                    }
                } catch (e) {
                    console.error('获取客户联系信息失败:', e);
                } finally {
                    setCustomerContactLoading(false);
                }
            })();
        }
    }, [canViewCustomerContact, descriptionData.customer_ids]);

    const currentUserId = jwtPayload?.user_id ?? jwtPayload?.id ?? jwtPayload?.uid;
    const canEditSalesman = jwtPayload?.role === 'admin'
        || (currentUserId !== undefined && salesman?.id !== undefined && Number(currentUserId) === Number(salesman.id));

    const handleSaveSalesman = async (userId) => {
        if (!canEditSalesman) {
            messageX.error('你没有权限修改业务员');
            return;
        }
        if (userId === undefined) {
            messageX.warning('请选择业务员');
            return;
        }
        const parsedUserId = Number(userId);
        if (Number.isNaN(parsedUserId)) {
            messageX.error('业务员ID无效');
            return;
        }
        setSalesmanSaving(true);
        try {
            const res = await (await fetch(`${endpoint}/orders/${order_id}/salesman`, {
                method: 'PUT',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ user_id: parsedUserId })
            })).json();
            if (res.code === 200) {
                setSalesman(res.data || null);
                setSalesmanEditorValue(res.data?.id ?? undefined);
                setDescriptionData(prev => ({ ...prev, salesman: res.data || null, salesman_id: res.data?.id ?? null }));
                setSalesmanEditing(false);
                messageX.success('业务员更新成功');
                return;
            }
            messageX.error(res.msg || '业务员更新失败');
        } finally {
            setSalesmanSaving(false);
        }
    };

    const handleRemoveSalesman = async () => {
        if (!canEditSalesman) {
            messageX.error('你没有权限修改业务员');
            return;
        }
        setSalesmanSaving(true);
        try {
            const res = await (await fetch(`${endpoint}/orders/${order_id}/salesman`, {
                method: 'PUT',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ user_id: null })
            })).json();
            if (res.code === 200) {
                setSalesman(null);
                setSalesmanEditorValue(undefined);
                setDescriptionData(prev => ({ ...prev, salesman: null, salesman_id: null }));
                setSalesmanEditing(false);
                messageX.success('业务员已移除');
                return;
            }
            messageX.error(res.msg || '移除业务员失败');
        } finally {
            setSalesmanSaving(false);
        }
    };

    //纸箱表格
    const [form] = Form.useForm();
    const [editingKey, setEditingKey] = useState('');
    const [cargoData, setCargoData] = useState([]);
    const fetchCargoData = async () => {
        const {
            code,
            data
        } = await (await fetch(`${endpoint}/orders/${order_id}/cargo?time=${(new Date()).getTime()}`, { headers: getSafeHeader() })).json();
        if (code === 500) {
            message.error("17Track 获取订单跟踪信息失败")
        }
        setCargoData((data || []).map(v => ({ ...v, key: v['uid'] })));
    };
    useEffect(() => {
        (async () => {
            await fetchCargoData();
        })();
    }, [])
    const isEditing = (record) => {
        return record['uid'] === editingKey;
    }

    const edit = (record) => {
        form.setFieldsValue({
            ...record,
        });
        setEditingKey(record.uid);
    };
    const cancel = () => {
        setEditingKey('');
    };
    const save = async (key) => {
        if (!verify()) {
            message.error("密码错误！");
            return;
        }
        try {
            const row = await form.validateFields();

            const newData = [...cargoData];
            const index = newData.findIndex((item) => key === item.uid);
            if (key) {

                const item = newData[index];

                const timestamp = (new Date()).getTime().toString(16);
                await (await fetch(`${endpoint}/cargo/${key}`, {
                    headers: getSafeHeader(),
                    body: JSON.stringify({ ...row }),
                    method: 'PUT'
                })).json();

                newData.splice(index, 1, {
                    ...item,
                    ...row,
                });
                setCargoData(newData);
            } else {
                newData.push(row);
                setCargoData(newData);
            }
            setEditingKey('');
            message.success('修改成功！');
        } catch (errInfo) {
            console.log('Validate Failed:', errInfo);
        }
    };
    const columns = [
        {
            title: '原单号',
            key: 'transfer_id',
            dataIndex: 'transfer_id',
            ellipsis: true,
            fixed: 'left',
            editable: true,
            width: 200,
            render: (text, record, i) => text && <Typography.Text copyable key={i}>{text}</Typography.Text>
        }, {
            title: '转单号',
            key: 'waybill_id',
            dataIndex: 'waybill_id',
            ellipsis: true,
            fixed: 'left',
            editable: true,
            width: 200,
            render: (text, record, i) => text && <Typography.Text copyable key={i}>{text}</Typography.Text>
        },
        // {
        //     title: '唛头',
        //     key: 'tag',
        //     dataIndex: 'tag',
        //     ellipsis: true,
        //     fixed: 'left',
        //     width: 120,
        //     render: (text, record, i) => text && <Typography.Text copyable key={i}>{text}</Typography.Text>
        // },
        {
            title: '申报数量(件)',
            key: 'count',
            dataIndex: 'count',
            ellipsis: false,
            editable: true,
            width: 150,
            render(text, _, i) {
                return text && <Typography.Text copyable={true} key={i}>{text ? text + '件' : ''}</Typography.Text>
            }
        },
        {
            title: '英文品名',
            key: 'real_en_name',
            dataIndex: 'real_en_name',
            ellipsis: false,
            editable: true,
            width: 150,
            render(text, _, i) {
                return text && <Typography.Text copyable key={i}>{text}</Typography.Text>
            }
        },
        {
            title: '重量(KG)',
            key: 'weight',
            dataIndex: 'weight',
            ellipsis: false,
            editable: true,
            width: 150,
            render(text, _, i) {
                return text && <Typography.Text copyable key={i}>{text ? text + 'KG' : ''}</Typography.Text>
            }
        },
        {
            title: '申报价值',
            key: 'price',
            dataIndex: 'price',
            ellipsis: false,
            editable: true,
            width: 150,
            render(text, _, i) {
                return text && <Typography.Text copyable={true} key={i}>{text}</Typography.Text>
            }
        },
        {
            title: '状态',
            key: 'status',
            width: 220,
            dataIndex: 'status',
            render(statusText, record, i) {
                // 装箱单包裹在未出库时显示业务状态；已出库后切换为第三方轨迹状态。
                if (record?.packing_list_uid) {
                    const cargoStatus = Number(record?.status || 0);
                    if (cargoStatus !== 1) {
                        const hasWaybill = !!String(record?.waybill_id || '').trim();
                        if (hasWaybill) {
                            return <Badge status={'processing'} text={'待出库'} />;
                        }
                        return <Badge status={'warning'} text={'待上传'} />;
                    }
                }

                const _trackStatus = trackStatus[statusText] || {
                    status: 'default',
                    badgeText: String(statusText ?? '未知状态'),
                    detail: false,
                    title: '状态'
                };
                const MyBadge = () => <Badge style={{ cursor: "pointer" }} status={_trackStatus.status || "processing"}
                    text={_trackStatus.badgeText} onClick={() => {
                        window.open("https://t.17track.net/zh-cn#nums=" + record['waybill_id'])
                    }} />;
                return _trackStatus.detail ?
                    <Popover trigger="hover" content={
                        <Timeline style={{ paddingTop: '1rem' }} reverse={false}
                            items={(record['events'] || []).map((item, i) => {
                                return {
                                    children:
                                        <Space>
                                            <div>{item?.time_raw?.date} {item?.time_raw?.time}</div>
                                            <div>{item?.location}, {item?.description}</div>
                                        </Space>,
                                    color: i === 0 ? _trackStatus.status === 'error' ? 'red' : '#1668dc' : 'gray'
                                }
                            })}>
                        </Timeline>
                    } title={<Typography.Text level={5}>{_trackStatus.title}</Typography.Text>} placement="top">
                        <Button type={"text"} style={{ padding: "unset", background: "transparent" }}><MyBadge /></Button>
                    </Popover>
                    : (<MyBadge />)
                // return text === 0 ? <Badge status={'default'} text={'在库'}/> :
                //     <Badge status={'success'} text={<Typography.Text>出库</Typography.Text>} style={{cursor: "pointer"}} onClick={() =>
                //     {window.open("https://t.17track.net/zh-cn#nums="+record['waybill_id'])}}/>

            }
        },
        {
            title: '出库日期',
            key: 'date',
            dataIndex: 'date',
            width: 200,
            render: (text, record, i) => text && <Typography.Text copyable key={i}>{text}</Typography.Text>
        }, {
            title: '创建日期',
            key: 'create_date',
            dataIndex: 'create_date',
            width: 200,
            render: (text, record, i) => text && <Typography.Text copyable key={i}>{text}</Typography.Text>
        }, {
            title: '更新日期',
            key: 'update_date',
            dataIndex: 'update_date',
            width: 200,
            render: (text, record, i) => text && <Typography.Text copyable key={i}>{text}</Typography.Text>
        },
        {
            title: '操作',
            key: 'x',
            dataIndex: '',
            fixed: 'right',
            align: 'center',
            width: 140,
            render(_, record) {
                const editable = isEditing(record);
                return editable ? (
                    <Space size={'middle'}>
                        <Button type={'text'}
                            onClick={() => save(record.uid)}
                            style={{
                                color: "#1677FF"
                            }}
                        >
                            保存
                        </Button>
                        <Button danger type={'text'} className={'myEditableCellInputIdToAvoidBlur'}
                            onClick={cancel}>取消</Button>
                    </Space>
                ) : (
                    <Space size={'middle'}>
                        <Popconfirm
                            title="删除包装箱"
                            description="你确认要删除该包装箱吗？"
                            onConfirm={handleDeleteCargo.bind({}, [record.uid])}
                            okText="是的"
                            cancelText="取消"
                        >
                            <Button type={'text'} danger>删除</Button>
                        </Popconfirm>
                        <Button type={'text'} style={{ color: "#1677FF" }} disabled={editingKey !== ''}
                            onClick={() => edit(record)}>
                            编辑
                        </Button>
                    </Space>);
            }
        }
    ];
    const mergedColumns = columns.map((col) => {
        if (!col.editable) {
            return col;
        }
        return {
            ...col,
            onCell: (record) => {
                return {
                    record,
                    // inputType: col.dataIndex === 'age' ? 'number' : 'text',
                    dataIndex: col.dataIndex,
                    title: col.title,
                    editing: isEditing(record),
                    onEnter: async (flag) => {
                        await save(record.uid);
                        focusFlag = flag;
                        const index = cargoData.findIndex((item) => record.uid === item.uid);
                        if (index > -1 && index < cargoData.length - 1) {
                            edit(cargoData[index + 1]);
                        }
                    },
                    onBlur: async (e) => {
                        // 当点击了当前行的任意一个输入框（className里带有myEditableCellInputIdToAvoidBlur），
                        // 则跳过保存以及取消编辑当前行
                        if (e.relatedTarget
                            && e.relatedTarget.className.includes('myEditableCellInputIdToAvoidBlur')) {
                            return;
                        }
                        await save(record.uid);
                    },
                    onClick: () => {
                        edit(record);
                    }
                }
            },
        };
    });
    // 删除包装箱
    const handleDeleteCargo = async (records, deleteSelected = false) => {
        if (!window.confirm("确认删除吗？")) return
        if (!verify()) message.error('密码错误！');
        else {
            //删除逻辑
            const timestamp = (new Date()).getTime().toString(16);
            console.log(records)
            const record_ids = deleteSelected ? records : records.map(r => r.uid);
            await (await fetch(`${endpoint}/cargo`, {
                headers: getSafeHeader(),
                body: JSON.stringify({ cargo_id_list: record_ids }),
                method: 'DELETE'
            })).json();

            // // 更新cargoData状态，移除id在record_ids中的项
            setCargoData(prevState => {
                return prevState.filter(item => !record_ids.includes(item.key));
            });

            // 清除选中状态
            if (deleteSelected) setSelectedKeys([]);

            messageX.success('删除成功！');
            // window.location.reload();
        }
    }

    const [count, setCount] = useState(1);//包装箱添加计数
    const handleAdd = async () => {
        // console.log(descriptionData)
        if (!descriptionData.order_id) {
            message.error("请先补充订单号");
            return
        }
        // console.log(count);
        const timestamp = (new Date()).getTime().toString(16);
        const { data, cargo_id_list } = await (await fetch(`${endpoint}/orders/${order_id}/add_cargo`, {
            headers: getSafeHeader(),
            body: JSON.stringify({ cargo_count: count }),
            method: 'POST'
        })).json()
        setCount(1);
        const data_with_key = data.map(r => ({ ...r, key: r.uid }));
        setCargoData(prevState => [...prevState, ...data_with_key]);
        // download
        // window.open(`${endpoint}/cargo/pdf/${cargo_id_list.join('_')}`);
        message.success('添加成功！');
        // window.location.reload();
    }

    // 批量查询进度
    const handleQueryLogistics = () => {
        if (selectedKeys.length > 40) {
            message.error("查询订单量过多！");
            return;
        }
        const table = {}
        for (let d in cargoData) {
            table[cargoData[d]['key']] = cargoData[d];
        }
        console.log(table);
        const queryParams = selectedKeys.map(key => table[key]['waybill_id']);
        console.log(queryParams);
        window.open(`https://t.17track.net/zh-cn#nums=${queryParams.join(',')}`);

    }

    // 选择打印
    const [selectedKeys, setSelectedKeys] = useState([]);
    // 打印
    const handlePrint = () => {
        window.open(`${endpoint}/cargo/pdf/${selectedKeys.join('_')}`);
    }

    const [TransportationEditing, setTransportationEditing] = useState("")

    return (
        <>
            {messageComponent}
            <Typography.Title level={4} style={{ marginBottom: '2rem' }}>订单详情/Order Detail</Typography.Title>
            <Space style={{ marginBottom: '1rem' }} align="center" wrap size="small">
                <Typography.Text strong>业务员：</Typography.Text>
                {!salesmanEditing ? (
                    <Input
                        readOnly
                        style={{ width: 240, height: 32 }}
                        value={salesman ? `${salesman.name || '-'}${salesman.phone ? ` / ${salesman.phone}` : ''}` : '未分配'}
                    />
                ) : (
                    salesmanOptions.length > 0 ? (
                        <Select
                            style={{ width: 240 }}
                            size="middle"
                            placeholder="选择业务员"
                            loading={salesmanUsersLoading || salesmanLoading}
                            value={salesmanEditorValue}
                            onChange={(value) => setSalesmanEditorValue(value)}
                            options={salesmanOptions}
                        />
                    ) : (
                        <InputNumber
                            min={1}
                            placeholder="输入业务员ID"
                            style={{ width: 240, height: 32 }}
                            value={salesmanEditorValue}
                            onChange={(value) => setSalesmanEditorValue(value)}
                        />
                    )
                )}
                {canEditSalesman && !salesmanEditing && (
                    <Button
                        size="middle"
                        onClick={() => {
                            setSalesmanEditorValue(salesman?.id ?? undefined);
                            setSalesmanEditing(true);
                        }}
                    >
                        编辑
                    </Button>
                )}
                {canEditSalesman && salesmanEditing && (
                    <Button size="middle" type="primary" loading={salesmanSaving}
                        onClick={() => handleSaveSalesman(salesmanEditorValue)}>保存</Button>
                )}
                {canEditSalesman && salesmanEditing && (
                    <Button size="middle" onClick={() => {
                        setSalesmanEditorValue(salesman?.id ?? undefined);
                        setSalesmanEditing(false);
                    }}>取消</Button>
                )}
                {canEditSalesman && salesmanEditing && (
                    <Button size="middle" danger loading={salesmanSaving}
                        onClick={handleRemoveSalesman}>移除</Button>
                )}
            </Space>
            <Descriptions style={{ marginBottom: '2rem' }} bordered>
                {orderProperty.map((v, k) => {
                    const handleDescriptionDataChange = async (val) => {
                        if (descriptionData[v.name] === val) return;
                        //权限
                        if (!verify()) {
                            message.error('密码错误！');
                            return false;
                        }
                        //预检查
                        if (v.name === 'total_weight' && isNaN(val)) {
                            messageX.warning(`${v.label}请输入数字`)
                            return;
                        }

                        const timestamp = (new Date()).getTime().toString(16);
                        await (await fetch(`${endpoint}/orders/${order_id}`, {
                            headers: getSafeHeader(),
                            body: JSON.stringify({ [v.name]: val }),
                            method: 'PUT'
                        })).json()
                        messageX.success(`修改${v.label}成功`);
                        setDescriptionData(prevState => ({ ...prevState, [v.name]: val }))
                    }

                    return v.name === 'transportation' || v.name === 'en_name' ? (
                        <Descriptions.Item style={TransportationEditing ? { width: 300 } : {}} key={k} span={v.span || 1}
                            label={v.label.split('/')[0]}>
                            {TransportationEditing === 'en_name' && v.name === 'en_name' ? (
                                <GoodInput onEnter={() => setTransportationEditing("")}
                                    onBlur={() => setTransportationEditing("")}
                                    onChange={handleDescriptionDataChange}
                                    defaultValue={descriptionData[v.name]} />
                            ) : TransportationEditing === 'transportation' && v.name === 'transportation' ? (
                                <Transportation onEnter={() => setTransportationEditing("")}
                                    onBlur={() => setTransportationEditing("")}
                                    onChange={handleDescriptionDataChange}
                                    defaultValue={descriptionData[v.name]} />
                            ) : (
                                <>
                                    <Typography.Text
                                        copyable={!!descriptionData[v.name]}
                                        editable={{
                                            onStart: () => setTransportationEditing(v.name),
                                        }}>{descriptionData[v.name]}</Typography.Text>{descriptionData[v.name] &&
                                            <span>{v.name === 'total_weight' ? 'kg' : ''}</span>}
                                </>
                            )}
                        </Descriptions.Item>
                    ) : (
                        <Descriptions.Item key={k} span={v.span || 1} label={v.label.split('/')[0]}>
                            <Typography.Text
                                copyable={!!descriptionData[v.name]}
                                editable={v.name === 'customer_name' ? false : {
                                    onChange: handleDescriptionDataChange,
                                }}>{descriptionData[v.name]}</Typography.Text>{descriptionData[v.name] &&
                                    <span>{v.name === 'total_weight' ? 'kg' : ''}</span>}
                        </Descriptions.Item>
                    )
                })}
                {canViewCustomerContact && (
                    <>
                        <Descriptions.Item label="客户手机号">
                            {customerContactLoading ? '加载中...' : (
                                <Typography.Text copyable={!!customerContact.phone}>
                                    {customerContact.phone || '-'}
                                </Typography.Text>
                            )}
                        </Descriptions.Item>
                        <Descriptions.Item label="客户微信">
                            {customerContactLoading ? '加载中...' : (
                                <Typography.Text copyable={!!customerContact.wechat}>
                                    {customerContact.wechat || '-'}
                                </Typography.Text>
                            )}
                        </Descriptions.Item>
                    </>
                )}
            </Descriptions>
            <Typography.Title level={4} style={{ marginBottom: '2rem' }}>包裹详情/Cargo Detail</Typography.Title>
            <Typography.Title level={5}>添加包装箱</Typography.Title>
            <Space size='small' style={{ marginBottom: '2rem' }} align={'center'}>
                <InputNumber value={count} onChange={setCount} />
                <Button type={'primary'} onClick={handleAdd}>添加</Button>
                {canAssignBoxes && (
                    <Button
                        type={'default'}
                        icon={<InboxOutlined />}
                        onClick={() => setBoxAssignmentVisible(true)}
                    >
                        从装箱单分配
                    </Button>
                )}
                <ExportButton selectedKeys={[descriptionData.uid]} onSuccess={() => setSelectedKeys([])}
                    selectedCargos={selectedKeys} data={[{ ...descriptionData, key: descriptionData.uid }]} />
                <Button onClick={handleQueryLogistics}>查询进度</Button>
                {selectedKeys.length > 0 &&
                    <Button type={'primary'} danger onClick={() => handleDeleteCargo(selectedKeys, true)}>删除</Button>}
            </Space>

            {/* 箱子分配模态框 */}
            <BoxAssignmentModal
                visible={boxAssignmentVisible}
                onClose={() => setBoxAssignmentVisible(false)}
                customerId={descriptionData.customer_ids?.[0]}
                customerName={descriptionData.customer_name}
                orderUid={descriptionData.uid}
                onSuccess={(result) => {
                    message.success(`成功分配 ${result.success?.length || 0} 个箱子`);
                    fetchCargoData();
                }}
            />

            <Form form={form} component={false}>
                <Table components={{ body: { cell: EditableCell } }} pagination={{ onChange: cancel }} dataSource={cargoData}
                    columns={mergedColumns}
                    onClick={console.log}
                    rowSelection={{
                        type: 'checkbox', onChange: (e) => {
                            setSelectedKeys(e);
                            console.log(e)
                        }, selectedRowKeys: selectedKeys
                    }}

                    scroll={{ y: 250 }} />
            </Form>
        </>
    )

}
