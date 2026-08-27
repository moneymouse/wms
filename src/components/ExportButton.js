import React, {useEffect, useState} from 'react';
import { Dropdown, message } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import { endpoint } from '../config.js';
import getSafeHeader from '../common/safeHeader';
import genWayBill from "../common/genWayBill";

const FIXED_EXPORT_ITEMS = [
    { key: 'kehu', label: '转单号列表' },
    { key: 'wayBill', label: '面单' },
];

const ExportButton = ({ selectedKeys, selectedCargos = [], data, onSuccess }) => {
    const [loading, setLoading] = useState(false);
    const [exportType, setExportType] = useState('jifei');
    const [templates, setTemplates] = useState([]);

    useEffect(() => {
        fetch(`${endpoint}/excel-templates`, { headers: getSafeHeader() })
            .then(r => r.json())
            .then(res => {
                if (res.code === 200) {
                    const dynamicItems = (res.data || []).map(t => ({
                        key: t.mode_key,
                        label: t.label,
                        requiresValidQuote: t.requires_valid_quote !== false
                    }));
                    const allItems = [...dynamicItems, ...FIXED_EXPORT_ITEMS];
                    setTemplates(allItems);
                    if (allItems.length > 0 && !allItems.find(i => i.key === exportType)) {
                        setExportType(allItems[0].key);
                    }
                }
            })
            .catch(() => {
                message.error('获取导出模板失败');
            });
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

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
                a.download = `客户转单号_${date.getSeconds()}.txt`;
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
                const resultData = await result.json();
                if (!result.ok || resultData.code !== 200) {
                    const blocked = (resultData?.data?.blocked_orders || [])
                        .map(item => item.order_id)
                        .join('、');
                    throw new Error(blocked
                        ? `${resultData.msg || '导出失败'}：${blocked}`
                        : (resultData.msg || '导出失败'));
                }
                const document_id = resultData.data?.document_id;
                if (!document_id) throw new Error('导出文件生成失败');
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
            message.error(error?.message || "导出失败");
        } finally {
            setLoading(false);
        }
    };

    const currentExportType = templates.find(item => item.key === exportType);

    return (
        <Dropdown.Button
            menu={{
                items: templates,
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
