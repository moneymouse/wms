import React, {useEffect, useState} from 'react';
import { Dropdown, Button, message } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import { endpoint } from '../config.js';
import getSafeHeader from '../common/safeHeader';
import genWayBill from "../common/genWayBill";

const exportTypeItems = [
    {
        key: 'jifei',
        label: '极飞订单'
    }, {
        key: 'tongcang',
        label: '统仓订单'
    }, {
        key: 'tongcangups',
        label: '统仓(UPS)订单'
    }, {
        key: 'jinfeiqi',
        label: '金飞旗订单'
    }, {
        key: 'huanshitong',
        label: '环世通订单'
    }, {
        key: 'xinghang',
        label: '星航订单'
    }, {
        key: 'jinlong',
        label: '金龙订单'
    }, {
        key: 'jinlong_kuaidi',
        label: '金龙快递订单'
    }, {
        key: 'yaxuan',
        label: '亚轩订单'
    }, {
        key: 'WE',
        label: '亚轩WE订单'
    }, {
        key: 'wayBill',
        label: '面单'
    }, {
        key: 'kehu',
        label: "转单号列表"
    },
];


const ExportButton = ({ selectedKeys, selectedCargos = [], data, onSuccess }) => {
    const [loading, setLoading] = useState(false);
    const [exportType, setExportType] = useState('jifei');

    const handleExportPreview = async () => {
        if (selectedKeys.length > 1) {
            message.error("无法打印多个运单！");
            return;
        }
        console.log(data)
        const selectedData = data.find((v) => v.key === selectedKeys[0]);
        if (!selectedData) return;
        await genWayBill(selectedData);
        message.success("运单导出成功！");
    };

    const handleDownload = async () => {
        if (selectedKeys.length <= 0) {
            message.warning('请先选择要导出的订单');
            return;
        }
        setLoading(true);

        try {
            if (exportType === 'kehu') {
                const res = await fetch(`${endpoint}/cargo/excel/${exportType}`, {
                    body: JSON.stringify({ uid_list: selectedKeys, cargo_list: selectedCargos }),
                    headers: getSafeHeader(),
                    method: 'POST'
                });
                // console.log(await res.text());text
                const fileUrl = URL.createObjectURL(await res.blob());
                const a = document.createElement('a');
                a.href = fileUrl;
                const date = new Date();
                a.download = `客户转单号_${date.getSeconds()}` + '.txt';
                document.body.appendChild(a);
                a.click();
                a.remove();
                return ;
            }
            if (exportType === 'wayBill') {
                await handleExportPreview();
            } else {
                const result = await fetch(`${endpoint}/cargo/excel/${exportType}`, {
                    body: JSON.stringify({ uid_list: selectedKeys, cargo_list: selectedCargos }),
                    headers: getSafeHeader(),
                    method: 'POST'
                });
                const { data: { document_id } } = await result.json();
                const res = await fetch(`${endpoint}/cargo/excel/${document_id}`, { headers: getSafeHeader() });
                const blob = await res.blob();
                const fileUrl = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = fileUrl;
                a.download = document_id + '.xlsx';
                document.body.appendChild(a);
                a.click();
                a.remove();
                message.success(`导出成功`);
            }
            if (onSuccess) {
                onSuccess();
            }
        } catch (error) {
            console.log(error);
            message.error("导出失败");
        } finally {
            setLoading(false);
        }
    };

    const currentExportType = exportTypeItems.find(item => item.key === exportType);

    return (
        <Dropdown.Button
            menu={{
                items: exportTypeItems,
                onClick(e) {
                    setExportType(e.key);
                }
            }}
            loading={loading}
            type={"primary"}
            onClick={handleDownload}
        >
            <DownloadOutlined />导出{currentExportType ? currentExportType.label : ''}
        </Dropdown.Button>
    );
};

export default ExportButton;

