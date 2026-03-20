import React from 'react';
import {InboxOutlined} from '@ant-design/icons';
import {message, Tabs, Typography, Upload} from 'antd';
import {endpoint} from "../config.js";
import getSafeHeader from "../common/safeHeader";

function downloadArrayAsText(array, filename='上传结果记录') {
    // 纯文本，每行一项
    const text = array.join('\n');

    // 创建 Blob
    const blob = new Blob([text], {type: 'text/plain;charset=utf-8'});

    // 创建下载链接
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename + '.txt';

    // 触发点击
    // link.click();
    return link;

    // 释放 URL 对象
    // URL.revokeObjectURL(link.href);
}

const {Dragger} = Upload;
const FileComponent = ({mode}) => {
    const [fileList, setFileList] = React.useState([]);
    const props = (mode) => ({
        name: 'file',
        multiple: true,
        headers: getSafeHeader(),
        action: `${endpoint}/order/upload/${mode}`,
        async onChange(info) {
            const newFileList = [];
            let total = 0;
            for (const file of info.fileList) {
                const status = file.status;
                if (status === 'done' && file.xhr) {
                    const responseBody = JSON.parse(file.xhr.response);
                    responseBody.code !== 200 && await message.error("转单号在17Track注册失败。");
                    total += Number(responseBody.cargo_count);
                    const successful_list = responseBody['success_list'].map(item => item[1]);
                    const cargo_list = Object.values(responseBody['cargo_list']);
                    const successSet = new Set(successful_list);
                    // 因为格式问题或者是未在系统中存储原单号导致录入系统失败的转单号列表
                    const fail_list = cargo_list.filter(item => !successSet.has(item))
                        .map(item => item === false ? "转单号未填" : item);
                    // 订单跟踪失败的列表
                    const rejected_list = responseBody['code'] === 502 ? responseBody['rejected']
                        .map(item => item['number']) : [];

                    const result_link = downloadArrayAsText([`上传成功订单数: ${Number(responseBody.cargo_count)}单`,
                            '上传失败订单:', ...fail_list, '\n跟踪失败订单:', ...rejected_list],
                        `${file.name}上传结果记录`);

                    file.status = responseBody.code === 200 && fail_list.length === 0
                        && rejected_list.length === 0 ? 'done' : 'error';
                    file.url = result_link;
                    newFileList.push(file);
                }
                if (status === 'error') {
                    await message.error(`${info.file.name} 上传失败！`);
                }
            }
            // if (total > 0) await message.success(`共${total}单上传。`)
            setFileList([...fileList, ...newFileList]);

        },
        onDrop(e) {
            console.log('Dropped files', e.dataTransfer.files);
        },
        data: (file) => ({'filename': file.name}),
    });

    return (<Dragger loading={true} {...props(mode)} style={{maxHeight: '80vh', margin: '2rem 0'}}>
        <p className="ant-upload-drag-icon">
            <InboxOutlined/>
        </p>
        <p className="ant-upload-text">点击或拖拽文件到此处上传</p>
        <p className="ant-upload-hint">
            Support for a single or bulk upload. Strictly prohibited from uploading company data or other
            banned files.
        </p>
    </Dragger>)
}
const UploadOrder = () => (<>
    <Typography.Title level={4} style={{marginBottom: '2rem'}}>上传文件</Typography.Title>
    <Typography.Text style={{marginBottom: '2rem'}}>原单号-转单号表中，请将原单号列名改为`<Typography.Text
        style={{color: "#1677ff"}}>origin_id</Typography.Text>`, 转单号名改为`<Typography.Text
        style={{color: "#1677ff"}}>transfer_id</Typography.Text>`</Typography.Text>
    <Tabs style={{marginTop: '1rem'}} items={[{
        key: 'transfer_table', label: '原单号-转单号表', children: <FileComponent mode={'transfer_table'}/>
    }, // {
        //     key: 'customer_table',
        //     label: '客户收件人信息',
        //     children: <FileComponent mode={'customer_table'}/>
        // }
    ]}/>

</>);
export default UploadOrder;