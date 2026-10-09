import React from 'react';
import {InboxOutlined} from '@ant-design/icons';
import {message, Tabs, Typography, Upload} from 'antd';
import {endpoint} from "../config.js";
import getSafeHeader from "../common/safeHeader";
import SupplierReconciliation from '../pages/supplierReconciliation';
import { decodeJwtPayload } from './featureTourState';
import { getUserRoles, hasPermission } from './roleConfig';
import { getWaybillUploadResult } from './waybillUploadResult';

function downloadArrayAsText(array) {
    const blob = new Blob([array.join('\n')], {type: 'text/plain;charset=utf-8'});
    return URL.createObjectURL(blob);
}

const {Dragger} = Upload;
const FileComponent = ({mode}) => {
    const [fileList, setFileList] = React.useState([]);
    const completedFiles = React.useRef(new Map());
    React.useEffect(() => () => {
        completedFiles.current.forEach(file => URL.revokeObjectURL(file.url));
        completedFiles.current.clear();
    }, []);
    const parseResponseBody = (file) => {
        const raw = file.response || file.xhr?.response;
        if (!raw) return {code: file.xhr?.status || 500, msg: `${file.name} 上传失败！`};
        if (typeof raw === 'object') return raw;
        try {
            return JSON.parse(raw);
        } catch (e) {
            return {code: file.xhr?.status || 500, msg: raw || '上传失败'};
        }
    };

    const props = (mode) => ({
        name: 'file',
        multiple: true,
        fileList,
        headers: getSafeHeader(),
        action: `${endpoint}/order/upload/${mode}`,
        onChange(info) {
            const nextFileList = info.fileList.filter(file => file.status !== 'removed').map(file => {
                const status = file.status;
                if (status === 'done' || status === 'error') {
                    if (completedFiles.current.has(file.uid)) return completedFiles.current.get(file.uid);
                    const responseBody = parseResponseBody(file);
                    const result = getWaybillUploadResult(responseBody, file.name);
                    message[result.toast.type](result.toast.message);
                    const completedFile = {
                        ...file,
                        status: result.status,
                        url: downloadArrayAsText(result.reportLines),
                        linkProps: { download: `${file.name}上传结果记录.txt` },
                    };
                    completedFiles.current.set(file.uid, completedFile);
                    return completedFile;
                }
                return file;
            });
            const activeUids = new Set(nextFileList.map(file => file.uid));
            completedFiles.current.forEach((file, uid) => {
                if (!activeUids.has(uid)) {
                    URL.revokeObjectURL(file.url);
                    completedFiles.current.delete(uid);
                }
            });
            setFileList(nextFileList);
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
const UploadOrder = () => {
    const roles = getUserRoles(decodeJwtPayload(localStorage.getItem('jwt')) || {});
    const canUploadReconciliation = hasPermission(roles, ['admin', 'clerk']);
    return <>
    <Typography.Title level={4} style={{marginBottom: '2rem'}}>上传文件</Typography.Title>
    <Tabs style={{marginTop: '1rem'}} items={[{
        key: 'transfer_table', label: '原单号-转单号表', children: <>
            <Typography.Text style={{marginBottom: '2rem'}}>原单号-转单号表中，请将原单号列名改为`<Typography.Text
                style={{color: "#1677ff"}}>transfer_id</Typography.Text>`, 转单号（运单号）列名改为`<Typography.Text
                style={{color: "#1677ff"}}>waybill_id</Typography.Text>`</Typography.Text>
            <FileComponent mode={'transfer_table'}/>
        </>
    },
        ...(canUploadReconciliation ? [{ key: 'supplier_reconciliation', label: '上传对账明细', children: <SupplierReconciliation /> }] : []), // {
        //     key: 'customer_table',
        //     label: '客户收件人信息',
        //     children: <FileComponent mode={'customer_table'}/>
        // }
    ]}/>

</>;
};
export default UploadOrder;
