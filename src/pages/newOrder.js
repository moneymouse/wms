import React, {useEffect, useState} from 'react'
import {useSearchParams} from "react-router-dom";
import {AutoComplete, Button, Col, Form, Input, List, message, Modal, Row, Select, Space, Typography} from 'antd';
import {endpoint} from "../config"
import countryList from "../common/countryList";
import getSafeHeader from "../common/safeHeader";
import {BookOutlined, CloseOutlined, DeleteOutlined} from "@ant-design/icons";
import genWayBill from "../common/genWayBill";
import styles from './newOrder.module.css';
import Transportation from "../components/transportation";
import GoodInput from "../components/GoodName";

const {Item} = Form;

// 定义localStorage的键名
const FORM_STORAGE_KEY = 'newOrderFormData';

export default function () {

    // 所有静态的选项都在这里管理，setOptions只会在获取后端数据时调用。
    // 以下选项均为静态，不会在运行期间因用户操作而发生更新
    // 键值区分属于不同表单字段的选项
    const [options, setOptions] = useState({
        customerNames: [],
        country: countryList,
        receiverList: [],
        formKey: []
    });

    const [searchParams, _] = useSearchParams();

    // message
    const [messageX, messageComponent] = message.useMessage();
    const [loading, setLoading] = useState(false)

    const [customerNameOptions, setCustomerNameOptions] = useState([]);

    const [form] = Form.useForm();

    // modal
    const [modalVisible, setModalVisible] = useState(false);
    const [modalCustomerOptions, setModalCustomerOptions] = useState([]);
    const [modalCustomer, setModalCustomer] = useState('');
    const [ReceiverList, setReceiverList] = useState([]);
    const [zipCodeList, setZipCodeList] = useState([]);
    const [zipCodeFilter, setZipCodeFilter] = useState(null);

    async function handleModalOpen() {
        await updateCustomerName()
        setModalVisible(true);
    }

    function handleModalClose() {
        setModalVisible(false);
    }

    async function handleModalSelect(value) {
        setModalCustomer(value);
        try {
            const res = await (await fetch(`${endpoint}/receiver_info_list/${value}`, {
                headers: getSafeHeader()
            })).json();

            setZipCodeList(res.data
                .sort((v1,v2)=>Number(v1['zip_code']) - Number(v2['zip_code'])).map((v, index)=>({label: v['zip_code'], value: v['zip_code']})))
            setReceiverList(res.data);
        } catch (err) {
            messageX.error("获取列表失败")
        }

    }

    // 保存表单数据到localStorage
    const saveFormToLocalStorage = () => {
        const currentValues = form.getFieldsValue();
        localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(currentValues));
    };

    // 从localStorage加载已保存的表单数据或根据templateOrderId加载模板数据
    useEffect(() => {
        const templateOrderId = searchParams.get("orderId");
        loadFromLocalStorage();
    }, []);
    // 清空表单并从localStorage中移除保存的数据
    const handleClearForm = () => {
        form.resetFields();
        localStorage.removeItem(FORM_STORAGE_KEY);
        messageX.success('表单已清空');
    };

    const loadFromLocalStorage = () => {
        const savedFormData = localStorage.getItem(FORM_STORAGE_KEY);
        if (savedFormData) {
            try {
                const parsedData = JSON.parse(savedFormData);
                form.setFieldsValue(parsedData);
                if (parsedData.customer_name) {
                    handleSelect(parsedData.customer_name);
                }
            } catch (e) {
                console.error('Error parsing saved form data:', e);
                localStorage.removeItem(FORM_STORAGE_KEY);
            }
        }
    };

    const handleFinish = async (values) => {
        setLoading(true)
        try {
            values['en_name'] = (values['en_name'] || '').toUpperCase();
            const res = await (await fetch(`${endpoint}/create`, {
                headers: getSafeHeader(),
                method: 'POST',
                body: JSON.stringify(values)
            })).json();
            if (res['code'] === 200) {
                // Reset form to initial state.
                form.resetFields();
                messageX.success('创建成功！');

                // 清空localStorage中保存的表单数据
                localStorage.removeItem(FORM_STORAGE_KEY);
            } else {
                messageX.error('创建失败！');
                console.log(res);
            }
        } catch (error) {
            messageX.error('创建失败！');
            console.error('提交表单时发生错误:', error);
        } finally {
            setLoading(false);
        }
    }

    // 海关编码
    const [hs_keyword, set_hs_keyword] = useState('');
    // 邮编查询
    const [zip_code, setZipCode] = useState('');

    const updateCustomerName = async () => {
        try {// 获取用户名并自动补全
            const res = await fetch(`${endpoint}/customer_list`, {
                headers: getSafeHeader()
            });
            const {data} = await res.json();
            setOptions(prevState => ({
                ...prevState,
                customerNames: data.map(v => ({label: v, value: v}))
            }));
        } catch (error) {
            console.log(error);
            messageX.error('获取用户名失败。')
        }
    }

    // 用户名以及自动补全相关
    useEffect(() => {
        updateCustomerName();
    }, []);

    const [customerName, setCustomerName] = useState('')
    const handleSelect = async (value) => {
        // 选择客户后，更新其收件人列表
        const res = await fetch(`${endpoint}/receiver_list/${value}`, {headers: getSafeHeader()});
        const {data} = await res.json();
        setOptions(prevState => ({
            ...prevState, receiverList: data.map(v => ({label: v['receiver_name'], value: v['receiver_id']}))
        }));
    }

    const handleReceiverSelect = async (value) => {
        // 选择收件人后，补全所有
        const res = await fetch(`${endpoint}/receiver_info/${value}`, {headers: getSafeHeader()});
        const {data} = await res.json();
        // 提示自动补全
        setOptions(prevState => ({
            ...prevState, formKey: data,
        }));
        form.setFieldValue('receiver', data[0].receiver)
    }

    // 导出订单预览
    const handleExportPreview = async () => {
        try {
            // 获取当前表单所有数据
            const formValues = form.getFieldsValue();
            await genWayBill(formValues);

            messageX.success('导出成功！');
        } catch (error) {
            console.error('导出失败:', error);
            messageX.error('导出失败');
        }
    }


    return (
        <>
            {messageComponent}
            <Typography.Title level={4} style={{marginBottom: '2rem'}}>创建订单/Create Orders</Typography.Title>
            <Form
                form={form}
                validateMessages={{required: "${label} 未填写"}}
                onFinish={handleFinish}
                onValuesChange={saveFormToLocalStorage} // 添加值变化时的回调
            >
                {/*<Typography.Title level={5} style={{marginBottom: '1rem'}}>运单号/Order</Typography.Title>*/}
                {/*<Row>*/}
                {/*    <Col span={6}>*/}
                {/*        <Item name={'order_id'} label={'运单号/Tracking Number'}*/}
                {/*              rules={[{pattern: /^[0-9|A-z]*$/, message: '请输入数字或英文', required: false}]}>*/}
                {/*            <Input placeholder={'8510324...32'}/>*/}
                {/*        </Item>*/}
                {/*    </Col>*/}
                {/*</Row>*/}
                <Typography.Title level={5} style={{marginBottom: '1rem'}}>
                    基本信息/Basic Information
                    <Button
                        type={'danger'}
                        icon={<BookOutlined/>}
                        onClick={handleModalOpen}
                    >
                        通讯录
                    </Button>
                </Typography.Title>
                <Row gutter={16}>
                    <Col span={6}>
                        <Item name={'customer_name'} label={'客户姓名/Customer Name'} rules={[{required: true}]}>
                            <AutoComplete
                                onSearch={(value => {
                                    let res = [];
                                    if (value !== '') {
                                        res = options.customerNames.filter(val => val.label.toLowerCase().includes(value.toLowerCase()));
                                    } else {
                                        res = options.customerNames
                                    }
                                    setCustomerNameOptions(res)
                                })}
                                onSelect={handleSelect}
                                options={customerNameOptions.length === 0 ? options.customerNames : customerNameOptions}
                                placeholder={'Steven Curry'}/>
                        </Item>
                    </Col>
                    <Col span={1}/>
                    <Col span={8}>
                        <Item name={'transportation'} label={'运输方式/Transportation'}>
                            <Transportation onChange={(value) => {
                                form.setFieldValue('transportation', value);
                            }}/>
                        </Item>
                    </Col>
                </Row>
                <Row gutter={16}>
                    <Col span={6}>
                        <Item label={'收货人/Receiver'} name={'receiver'} rules={[{required: true}]}>
                            <AutoComplete
                                filterOption={((inputValue, option) => option.label.toLowerCase().includes(inputValue.toLowerCase()))}
                                options={options.receiverList}
                                placeholder={'Black'}
                                onSelect={handleReceiverSelect}
                            />
                        </Item>
                    </Col>
                    <Col span={1}/>
                    <Col span={8}>
                        <Item label={'收货人电话/Receiver Phone Number'} name={'receiver_phone'}
                              rules={[{required: true}]}>
                            <AutoComplete
                                filterOption={((inputValue, option) => option.toString().toLowerCase().includes(inputValue.toString().toLowerCase()))}
                                options={options.formKey.map(v => ({label: v.receiver_phone, value: v.receiver_phone}))}
                                placeholder={'6032...231'}
                            />
                        </Item>
                    </Col>
                    <Col span={1}/>
                    <Col span={6}>
                        <Item label={'收货人邮箱/Mail'} rules={[{type: 'email'}]} name={'mail'}>
                            <Input placeholder={'abc@efg.hij'}/>
                        </Item>
                    </Col>
                </Row>
                <Row gutter={16}>
                    <Col span={7}>
                        <Item label={'国家/Destination Country'} name={'country'} rules={[{required: true}]}>
                            <Select showSearch placeholder={'中国/China, CN'} options={options.country}/>
                        </Item>
                    </Col>

                    <Col span={6}>
                        <Item label={'州,省/State,Province'} name={'province'}>
                            <Input placeholder={'ALICANTE'}/>
                        </Item>
                    </Col>
                    <Col span={3}/>
                    <Col span={6}>
                        <Item label={'城市/City'} name={'city'}>
                            <Input placeholder={'New York'}/>
                        </Item>
                    </Col>

                </Row>
                <Row gutter={16}>
                    <Col span={15}>
                        <Item label={'详细地址/Full Address'} name={'address'} rules={[{required: true}]}>
                            <AutoComplete
                                options={options.formKey.map(v => ({label: v.address, value: v.address}))}
                                placeholder={'CALLE CONCORD......ANTE SPAIN'}
                                filterOption={(inputValue, option) =>
                                    option.label.toLowerCase().includes(inputValue.toLowerCase())
                                }
                                onSelect={(value) => {
                                    form.setFieldsValue({address: value});
                                }}
                            />
                        </Item>
                    </Col>
                    <Col span={1}/>
                    <Col span={6}>
                        <Item name={'zip_code'} label={'收件人邮编/Zip Code'} style={{marginBottom: "0.2rem"}} rules={[{required: true}]}>
                            <AutoComplete
                                options={options.formKey.map(v => ({label: v.zip_code, value: v.zip_code}))}
                                filterOption={(inputValue, option) =>
                                    option.label.toLowerCase().includes(inputValue.toLowerCase())
                                }
                                onSelect={(value) => {
                                    form.setFieldsValue({zip_code: value});
                                }}
                                onChange={(value) => {
                                    form.setFieldsValue({zip_code: value});
                                    setZipCode(value);
                                }}
                            />
                        </Item>
                        <div>
                        <Typography style={{color: 'lightgray', marginInlineStart: "8rem"}}>点击查询{form.getFieldValue("zip_code") && <><Typography.Link
                            onClick={() => window.open(`https://www.nowmsg.com/findzip/${form
                                .getFieldValue("country") === 'USA' ? "findzip.asp" : `${countryList
                                .find(v => v.value === form.getFieldValue("country"))
                                .label.split(", ")[1]}_postal_code.asp`}?CityName=${zip_code}`)}> {form.getFieldValue("zip_code")} </Typography.Link></>}邮编</Typography>
                        </div>
                    </Col>
                </Row>
                <Typography.Title level={5} style={{marginBottom: '1rem'}}>货物信息/Cargo Information</Typography.Title>
                <Row gutter={16}>
                    <Col span={8}>
                        <Item label={'报关品名/Customs Product Description'} name={'en_name'}>
                            {/*<Input placeholder={'CLOTHES'}/>*/}
                            <GoodInput onChange={(value)=>{
                                form.setFieldValue('en_name', value);
                            }} />
                        </Item>
                    </Col>
                    <Col span={4}>
                        <Item label={'中文品名'} name={'cn_name'}>
                            <Input onChange={(e) => {
                                form.setFieldValue('cn_name', e.target.value);
                                set_hs_keyword(e.target.value);
                            }}
                                   placeholder={'衣服'} style={{marginBottom: '0.2rem'}}/>
                            <Typography style={{color: 'lightgray'}}>查询{hs_keyword && <><Typography.Link
                                onClick={() => window.open(`https://www.hsbianma.com/search?keywords=${hs_keyword}`)}> {hs_keyword} </Typography.Link></>}海关编码</Typography>
                        </Item>
                    </Col>
                    <Col span={6}>
                        <Item label={'海关编码/Post Code'} name={'post_code'}>
                            <Input/>
                        </Item>
                    </Col>
                    <Col span={5}>
                        <Item label={'唛头'} name={'tag_all'}>
                            <Input/>
                        </Item>
                    </Col>
                </Row>
                <Row style={{marginTop: 16}} gutter={16}>
                    <Col>
                        <Button type={'primary'} onClick={handleExportPreview}>导出预览</Button>
                    </Col>
                    <Col>
                        <Item>
                            <Button type={'primary'} loading={loading} htmlType={'submit'}>创建/Submit</Button>
                        </Item>
                    </Col>
                    <Col>
                        <Button
                            type="danger"
                            icon={<DeleteOutlined/>}
                            onClick={handleClearForm}
                        >
                            清空表单
                        </Button>
                    </Col>
                </Row>
            </Form>
            <Modal open={modalVisible} onOk={handleModalClose} onCancel={handleModalClose} footer={null}
                   title={'通讯录'}>
                <Row align="middle">
                    <Col span={4}>
                        客人姓名
                    </Col>
                    <Col span={12}>
                        <AutoComplete
                            onSearch={(value => {
                                let res = [];
                                if (value !== '') {
                                    res = options.customerNames.filter(val => val.label.toLowerCase().includes(value.toLowerCase()));
                                } else {
                                    res = options.customerNames
                                }
                                setModalCustomerOptions(res)
                            })}

                            style={{width: '100%'}}
                            value={modalCustomer}
                            onChange={(value) => {
                                setModalCustomer(value)
                            }}
                            onSelect={handleModalSelect}
                            options={modalCustomerOptions.length === 0 ? options.customerNames : modalCustomerOptions}
                            placeholder={'Steven Curry'}/>
                    </Col>
                </Row>
                {!!ReceiverList.length &&
                    <Row align="middle" style={{marginTop: 16}}>
                        <Col span={4}>
                            邮编
                        </Col>
                        <Col span={12}>
                            <Select
                                style={{ width: '100%' }}
                                onSelect={(value) => {setZipCodeFilter(value)}}
                                options={zipCodeList} />
                        </Col>
                    </Row>
                }
                {
                    !!modalCustomer &&
                    <div style={{marginTop: 16}}>
                        <Button
                            type="text"
                            danger
                            size="small"
                            icon={<DeleteOutlined />}
                            onClick={async (e) => {
                                const sure = window.confirm("确认删除该客人所有信息吗？")
                                if (!sure) return;
                                e.stopPropagation();
                                try {
                                    const res = await fetch(`${endpoint}/del_customer/${modalCustomer}`, {
                                        method: 'POST',
                                        headers: getSafeHeader()
                                    });
                                    const result = await res.json();
                                    if (result.code === 200) {
                                        messageX.success('删除成功');
                                        // 重新加载列表
                                        await handleModalSelect(modalCustomer);
                                    } else {
                                        messageX.error('删除失败');
                                    }
                                } catch (err) {
                                    messageX.error('删除失败');
                                }
                            }}
                        >
                            删除全部
                        </Button>
                    </div>
                }
                <Typography.Title level={5}>收件地址列表</Typography.Title>
                <List
                    itemLayout="vertical"
                    dataSource={zipCodeFilter ? ReceiverList.filter(e => e['zip_code'] === zipCodeFilter) : ReceiverList}
                    renderItem={(item) => (
                        <List.Item key={item['receiver_id']} style={{cursor: 'pointer'}} >

                            <Space direction="vertical" style={{width: '100%'}} className={styles.li} onClick={() => {
                                // 将当前的地址信息复制填充到表单中
                                form.setFieldsValue(item);
                                form.setFieldValue('customer_name', modalCustomer);
                                handleModalClose();
                            }}>
                                <div>
                                    <Typography.Text type='secondary' style={{float: 'left'}}>邮编：<Typography.Text
                                        className={styles.link}
                                        strong>{item['zip_code']}</Typography.Text></Typography.Text>
                                    <Typography.Text type="secondary"
                                                     style={{float: 'right'}}>国家：{item['country']}</Typography.Text>
                                </div>
                                <Typography.Text className={styles.link} strong style={{fontSize: 18}}>
                                    📍 {item.address}
                                </Typography.Text>
                                <div>
                                    <Typography.Text type="secondary" style={{float: 'left'}}>👤
                                        收件人：{item['receiver']}</Typography.Text>
                                    <Typography.Text type="secondary" style={{float: 'right'}}>📱
                                        手机号：{item['receiver_phone']}</Typography.Text>

                                </div>
                            </Space>
                            <Space>
                                <Button style={{marginTop: '1rem'}} danger onClick={async (e) => {
                                    const sure = window.confirm(`是否删除${item['receiver']}/${item['zip_code']}`)
                                    if (!sure) return;
                                    try {
                                        const res = await fetch(`${endpoint}/del/${modalCustomer}/${item['receiver_id']}`, {
                                            method: 'POST',
                                            headers: getSafeHeader()
                                        });
                                        const result = await res.json();
                                        if (result.code === 200) {
                                            messageX.success('删除成功');
                                            // 重新加载列表
                                            await handleModalSelect(modalCustomer);
                                        } else {
                                            messageX.error('删除失败');
                                        }
                                    } catch (err) {
                                        messageX.error('删除失败');
                                    }
                                }} size={"small"}>删除该项</Button>
                            </Space>
                        </List.Item>
                    )}
                />
            </Modal>
        </>
    )
}