import React, { useCallback, useEffect, useState } from 'react';
import { Button, Card, Input, message, Modal, Space, Table, Typography, Upload } from 'antd';
import { UploadOutlined } from '@ant-design/icons';

import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import useUrlState from '../common/useUrlState';
import {
    CustomsCodeExcelError,
    readCustomsCodeExcelFile,
} from '../common/customsCodeExcel';

const EMPTY_EDITING = { id: null, name: '', code: '' };

export default function CustomsCodeManagement() {
    const [pagination, setPagination] = useUrlState('customsPagination', { current: 1, pageSize: 10 });
    const [records, setRecords] = useState([]);
    const [loading, setLoading] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [editing, setEditing] = useState(EMPTY_EDITING);
    const [preview, setPreview] = useState(null);

    const fetchRecords = useCallback(async () => {
        setLoading(true);
        try {
            const response = await fetch(`${endpoint}/customs-codes`, { headers: getSafeHeader() });
            const result = await response.json();
            if (result.code === 200) setRecords(result.data || []);
            else message.error(result.msg || '获取海关编码失败');
        } catch (error) {
            console.error('Fetch customs codes error:', error);
            message.error('获取海关编码失败');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchRecords();
    }, [fetchRecords]);

    const handleExcelSelect = async (file) => {
        if (!/\.(xlsx|xls)$/i.test(file.name)) {
            message.error('请选择 .xlsx 或 .xls 文件');
            return Upload.LIST_IGNORE;
        }
        try {
            const parsed = await readCustomsCodeExcelFile(file);
            setPreview({ ...parsed, fileName: file.name });
        } catch (error) {
            const rowText = error instanceof CustomsCodeExcelError && error.row ? `（第 ${error.row} 行）` : '';
            message.error(`${error.message || 'Excel 解析失败'}${rowText}`);
            setPreview(null);
        }
        return Upload.LIST_IGNORE;
    };

    const handleImport = async () => {
        if (!preview) return;
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/customs-codes/import`, {
                method: 'POST',
                headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ items: preview.items }),
            });
            const result = await response.json();
            if (result.code !== 200) {
                message.error(result.msg || '导入失败');
                return;
            }
            const data = result.data || {};
            message.success(
                `导入完成：新增 ${data.created_count || 0} 个，更新 ${data.updated_count || 0} 个，跳过 ${data.skipped_count || 0} 个`
            );
            setPreview(null);
            await fetchRecords();
        } catch (error) {
            console.error('Import customs codes error:', error);
            message.error('导入失败');
        } finally {
            setSubmitting(false);
        }
    };

    const handleUpdate = async (record) => {
        const name = editing.name.trim();
        const code = editing.code.trim();
        if (!name || !code) {
            message.warning('品名和海关编码不能为空');
            return;
        }
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/customs-codes/${record.id}`, {
                method: 'PUT',
                headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, code }),
            });
            const result = await response.json();
            if (result.code === 200) {
                message.success('更新成功');
                setEditing(EMPTY_EDITING);
                await fetchRecords();
            } else {
                message.error(result.msg || '更新失败');
            }
        } catch (error) {
            console.error('Update customs code error:', error);
            message.error('更新失败');
        } finally {
            setSubmitting(false);
        }
    };

    const handleDelete = async (id) => {
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/customs-codes/${id}`, {
                method: 'DELETE',
                headers: getSafeHeader(),
            });
            const result = await response.json();
            if (result.code === 200) {
                message.success('删除成功');
                await fetchRecords();
            } else {
                message.error(result.msg || '删除失败');
            }
        } catch (error) {
            console.error('Delete customs code error:', error);
            message.error('删除失败');
        } finally {
            setSubmitting(false);
        }
    };

    const columns = [
        {
            title: 'Name（品名）',
            dataIndex: 'name',
            key: 'name',
            render: (value, record) => editing.id === record.id ? (
                <Input value={editing.name} onChange={event => setEditing(current => ({ ...current, name: event.target.value }))} />
            ) : value,
        },
        {
            title: 'Code（海关编码）',
            dataIndex: 'code',
            key: 'code',
            render: (value, record) => editing.id === record.id ? (
                <Input value={editing.code} onChange={event => setEditing(current => ({ ...current, code: event.target.value }))} />
            ) : value,
        },
        {
            title: '操作',
            key: 'action',
            width: 180,
            render: (_, record) => editing.id === record.id ? (
                <Space>
                    <Button type="primary" size="small" loading={submitting} onClick={() => handleUpdate(record)}>保存</Button>
                    <Button size="small" onClick={() => setEditing(EMPTY_EDITING)}>取消</Button>
                </Space>
            ) : (
                <Space>
                    <Button size="small" onClick={() => setEditing({ id: record.id, name: record.name, code: record.code })}>编辑</Button>
                    <Button danger size="small" loading={submitting} onClick={() => handleDelete(record.id)}>删除</Button>
                </Space>
            ),
        },
    ];

    return (
        <>
            <Card title="海关编码管理">
                <Space direction="vertical" style={{ width: '100%' }}>
                    <Space wrap>
                        <Upload accept=".xlsx,.xls" showUploadList={false} beforeUpload={handleExcelSelect}>
                            <Button type="primary" icon={<UploadOutlined />}>上传海关编码 Excel</Button>
                        </Upload>
                        <Typography.Text type="secondary">第一行必须包含 Name 和 Code 两列</Typography.Text>
                    </Space>
                    <Table
                        rowKey="id"
                        loading={loading}
                        dataSource={records}
                        columns={columns}
                        pagination={{ ...pagination, onChange: (current, pageSize) => setPagination({ current, pageSize }) }}
                        scroll={{ y: 400 }}
                    />
                </Space>
            </Card>

            <Modal
                title={`海关编码导入预览${preview ? `：${preview.fileName}` : ''}`}
                open={Boolean(preview)}
                onCancel={() => setPreview(null)}
                onOk={handleImport}
                okText="确认导入"
                cancelText="取消"
                confirmLoading={submitting}
                width={720}
                destroyOnClose
            >
                {preview && (
                    <Space direction="vertical" style={{ width: '100%' }}>
                        <Typography.Text>工作表：{preview.sheetName}；共 {preview.items.length} 条映射</Typography.Text>
                        <Table
                            rowKey={(_, index) => index}
                            size="small"
                            pagination={false}
                            dataSource={preview.items}
                            columns={[
                                { title: 'Name', dataIndex: 'name', key: 'name' },
                                { title: 'Code', dataIndex: 'code', key: 'code' },
                            ]}
                            scroll={{ y: 400 }}
                        />
                    </Space>
                )}
            </Modal>
        </>
    );
}
