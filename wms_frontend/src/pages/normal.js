import React, {useEffect, useRef, useState} from "react";
import {Button, InputNumber, Layout, Modal, Space, Table, Tabs, theme, Typography} from "antd";
import Input from "antd/es/input/Input";
import {BrowserMultiFormatReader, NotFoundException} from "@zxing/library";
import {endpoint} from "../config.js";
import {useLocation, useParams} from "react-router-dom";

function useVideo(action) {
    const [isOpen, setIsOpen] = useState(false);
    const videoRef = useRef(null); // ref
    const [result, setResult] = useState('');

    //初始化Barcode识别器
    const codeReader = new BrowserMultiFormatReader();
    const [deviceId, setDevice] = useState();

    useEffect(() => {
        (async () => {
            const _device = await codeReader.listVideoInputDevices();
            setDevice(_device[0].deviceId);
        })();
    }, []);

    const handleScan = async () => {
        setIsOpen(true);
        codeReader.reset();
        setTimeout(async () => {
            await codeReader.decodeFromVideoDevice(deviceId, videoRef.current, (result, err) => {
                if (result) {
                    setResult(result.getText());
                    action(result.getText());
                    //震动
                    navigator.vibrate(200);
                    codeReader.reset();
                    setIsOpen(false)
                    return;
                }
                if (err && !(err instanceof NotFoundException)) {
                    console.error(err);
                    codeReader.reset();
                    return;
                }
                console.log(`Started continous decode from camera with id ${deviceId}`)
            });
        }, 0)
    }

    const handleCancel = () => {
        codeReader.reset();
        setIsOpen(false);
    }

    const videoModal = (
        <Modal open={isOpen} title={'识别二维码'} footer={null} onCancel={handleCancel}>
            <video ref={videoRef} style={{width: '100%'}}/>
        </Modal>
    )

    return [videoModal, handleScan, result];
}

function useInputModal() {
    const [open, setOpen] = useState(false);
    const [origin_id, set_origin_id] = useState(0);
    const [order, setOrder] = useState({});

    const [result, setResult] = useState({});

    useEffect(() => {
        if (!open) return;
        (async () => {
            const {data} = await (await fetch(`${endpoint}/cargo/${origin_id}/input`)).json();
            setOrder(data);
        })();
    }, [open])

    const inputModal = (
        <Modal open={open} title={'订单信息'} onCancel={() => setOpen(false)} onOk={() => {
            setResult({...order, flag: true, origin_id});
            setOpen(false);
        }}>
            <Typography>订单号码：{order['origin_id']}</Typography>
            <Typography>唛头：{order['tag']}</Typography>
            <Typography>客户名：{order['customer_name']}</Typography>
            <Space style={{marginBottom: '1rem'}}>
                <Typography>件数（件）</Typography>
                <InputNumber value={order['count']} onChange={(e) => setOrder(p => ({...p, count: e}))}
                             addonAfter={'件'}/>
            </Space>
            <Space>
                <Typography>重量（KG）</Typography>
                <InputNumber value={order['weight']} onChange={(e) => setOrder(p => ({...p, weight: e}))}
                             addonAfter={'kg'}/>
            </Space>
        </Modal>
    );

    return [inputModal, (origin_id) => {
        if (!origin_id) return;
        set_origin_id(origin_id);
        setOpen(true);
    }, result];
}

export default function Normal() {
    const {status} = useParams();
    const [input, setInput] = useState(status === 'input');
    const [originId, setOriginId] = useState('');

    const {
        token: {colorBgContainer},
    } = theme.useToken();

    const [data, setData] = useState({
        'input': [],
        'output': []
    })

    const handleOutput = async (origin_id) => {
        setOriginId('');
        if (data['output'].filter(v => v && v['origin_id'] === origin_id).length > 0) return;
        const res = await (await fetch(`${endpoint}/cargo/${origin_id}/output`, {method: 'POST'})).json();
        if (!res['data']) return;
        setData(prevState => {
            const _outputData = [...prevState['output'], res['data']]
            return {...prevState, output: _outputData};
        })
    }

    const [inputModal, handleOpenInputModal, inputResult] = useInputModal();
    // 发起请求修改重量
    useEffect(() => {
        (async () => {
            const {origin_id} = inputResult;
            if (data['input'].filter(v => v && v['origin_id'] === origin_id).length > 0) return;
            if (!inputResult.flag) return
            const res = await (await fetch(`${endpoint}/cargo/${origin_id}/input`, {
                body: JSON.stringify(inputResult),
                method: 'POST'
            })).json();
            setData(prevState => {
                const _inputData = [...prevState['input'], inputResult]
                return {...prevState, input: _inputData};
            });
        })()
    }, [inputResult])
    //
    const handleInput = async (origin_id) => {
        setOriginId('');
        handleOpenInputModal(origin_id);
    }

    const handleAction = {
        input: handleInput,
        output: handleOutput
    }

    // 如果是扫码进来直接打开
    const location = useLocation();
    useEffect(() => {
        const search = location.search.replace('?', '').split('&').reduce(
            (pre, cur) => {
                const temp = cur.split('=');
                pre[temp[0]] = temp[1];
                return pre;
            }, {});
        if (search['origin_id']) {
            setOriginId(search['origin_id']);
            // handleAction[status](search['origin_id']);
        }
    })

    // const [VideoModal, scan, scanResult] = useVideo(handleAction[input ? 'input' : 'output']);
    // useEffect(() => {
    // 	setOriginId(scanResult)
    // }, [scanResult])

    //表格
    const Columns = [
        {
            key: 0,
            title: '包裹识别码',
            dataIndex: 'origin_id',
        }, {
            key: 1,
            title: '唛头',
            dataIndex: 'tag',
        }, {
            key: 4,
            title: '客户名',
            dataIndex: 'customer_name'
        }, {
            key: 2,
            title: '件数（件）',
            dataIndex: 'count'
        }, {
            key: 3,
            title: '重量（KG）',
            dataIndex: 'weight'
        }
    ];


    return (
        <Layout.Content
            style={{
                margin: '0 0',
                padding: '0 24px',
                minHeight: '100vh',
                background: colorBgContainer,
                overflowY: 'auto'
            }}
        >
            <Tabs items={[{key: 'in', label: '收货'}, {key: 'out', label: '出货'}]}
                  onChange={(e) => setInput(e === 'in')}/>
            <Typography.Title level={3}>{input ? '收货' : '出货'}单号</Typography.Title>
            <Space style={{marginBottom: '1rem'}}>
                <Input value={originId} onChange={e => setOriginId(e.target.value)} placeholder={'请输入货单号码...'}/>
                <Button type={'primary'}
                        onClick={() => handleAction[input ? 'input' : 'output'](originId)}>{input ? '收货' : '出货'}</Button>
                {/*<Button icon={<ScanOutlined/>} onClick={scan}>扫码</Button>*/}
            </Space>
            <Typography.Title level={3}>{input ? '收货' : '出货'}列表</Typography.Title>
            <Table columns={Columns} dataSource={data[input ? 'input' : 'output']} scroll={{x: 3000, y: 430}}/>
            {/*{VideoModal}*/}
            {inputModal}
        </Layout.Content>
    )

}

// export default function (){
// 	const imgRef = useRef(null);
//
// 	useEffect(()=>{
// 		const constraints = { audio: true, video: { width: 1280, height: 720 } };
// 		navigator.getUserMedia = navigator.getUserMedia ||
// 			navigator.webkitGetUserMedia ||
// 			navigator.mozGetUserMedia ||
// 			navigator.msGetUserMedia;
// 		alert(navigator.getUserMedia)
// 		navigator.mediaDevices
// 			.getUserMedia(constraints)
// 			.then(function (mediaStream) {
// 				const video = imgRef.current;
// 				video.srcObject = mediaStream;
// 				video.onloadedmetadata = function (e) {
// 					video.play();
// 				};
// 			})
// 			.catch(function (err) {
// 				console.log(err.name + ": " + err.message);
// 			});
// 	},[])
//
// 	return (<>
//
// 			<video ref={imgRef} width={1280} height={720} playsInline autoPlay controls />
// 		</>
// 	)
// }
