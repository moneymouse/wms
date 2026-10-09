import React, { useCallback, useEffect, useState } from 'react';
import { Button, Card, Input, message, Modal, Space, Table, Tabs, Tag, Typography, Upload } from 'antd';
import { UploadOutlined } from '@ant-design/icons';

import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import { GoodsNameTxtParseError, readGoodsNameTxtFile } from '../common/goodsNameTxt';

const EMPTY_EDITING = { id: null, name: '', category: '' };

export default function GoodsNameManagement() {
    const [goodsNames, setGoodsNames] = useState([]);
    const [loading, setLoading] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [newCnName, setNewCnName] = useState('');
    const [newEnName, setNewEnName] = useState('');
    const [newEnCategory, setNewEnCategory] = useState('');
    const [editing, setEditing] = useState(EMPTY_EDITING);
    const [importPreview, setImportPreview] = useState(null);
    const [importSubmitting, setImportSubmitting] = useState(false);

    const fetchGoodsNames = useCallback(async () => {
        setLoading(true);
        try {
            const response = await fetch(`${endpoint}/goods-names`, { headers: getSafeHeader() });
            const result = await response.json();
            if (result.code === 200) {
                setGoodsNames(result.data || []);
            } else {
                message.error(result.msg || '获取品名列表失败');
            }
        } catch (error) {
            console.error('Fetch goods names error:', error);
            message.error('获取品名列表失败');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchGoodsNames();
    }, [fetchGoodsNames]);

    const handleAdd = async (lang) => {
        const raw = lang === 'cn' ? newCnName : newEnName;
        const names = raw.split(/[、\n]+/).map(value => value.trim()).filter(Boolean);
        if (names.length === 0) {
            message.warning('请输入品名');
            return;
        }

        setSubmitting(true);
        try {
            const category = lang === 'en' ? newEnCategory.trim() : undefined;
            const results = await Promise.allSettled(names.map(name =>
                fetch(`${endpoint}/goods-names`, {
                    method: 'POST',
                    headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({ lang, name, category }),
                }).then(response => response.json())
            ));
            const successCount = results.filter(result => result.status === 'fulfilled' && result.value.code === 200).length;
            const failCount = names.length - successCount;
            if (successCount) message.success(`成功添加 ${successCount} 个品名`);
            if (failCount) message.warning(`${failCount} 个品名添加失败（可能已存在）`);
            if (lang === 'cn') {
                setNewCnName('');
            } else {
                setNewEnName('');
                setNewEnCategory('');
            }
            await fetchGoodsNames();
        } catch (error) {
            console.error('Add goods name error:', error);
            message.error('添加失败');
        } finally {
            setSubmitting(false);
        }
    };

    const handleUpdate = async (record) => {
        const name = editing.name.trim();
        if (!name) {
            message.warning('品名不能为空');
            return;
        }

        setSubmitting(true);
        try {
            const body = { name };
            if (record.lang === 'en') body.category = editing.category.trim();
            const response = await fetch(`${endpoint}/goods-names/${record.id}`, {
                method: 'PUT',
                headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const result = await response.json();
            if (result.code === 200) {
                message.success('更新成功');
                setEditing(EMPTY_EDITING);
                await fetchGoodsNames();
            } else {
                message.error(result.msg || '更新失败');
            }
        } catch (error) {
            console.error('Update goods name error:', error);
            message.error('更新失败');
        } finally {
            setSubmitting(false);
        }
    };

    const handleDelete = async (id) => {
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/goods-names/${id}`, {
                method: 'DELETE',
                headers: getSafeHeader(),
            });
            const result = await response.json();
            if (result.code === 200) {
                message.success('删除成功');
                await fetchGoodsNames();
            } else {
                message.error(result.msg || '删除失败');
            }
        } catch (error) {
            console.error('Delete goods name error:', error);
            message.error('删除失败');
        } finally {
            setSubmitting(false);
        }
    };

    const handleTxtSelect = async (file) => {
        if (!file.name.toLowerCase().endsWith('.txt')) {
            message.error('请选择 TXT 文件');
            return Upload.LIST_IGNORE;
        }
        try {
            const parsed = await readGoodsNameTxtFile(file);
            setImportPreview({ ...parsed, fileName: file.name });
        } catch (error) {
            const lineText = error instanceof GoodsNameTxtParseError && error.line ? `（第 ${error.line} 行）` : '';
            message.error(`${error.message || 'TXT 文件解析失败'}${lineText}`);
            setImportPreview(null);
        }
        return Upload.LIST_IGNORE;
    };

    const handleImport = async () => {
        if (!importPreview) return;
        setImportSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/goods-names/import`, {
                method: 'POST',
                headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ items: importPreview.items }),
            });
            const result = await response.json();
            if (result.code !== 200) {
                message.error(result.msg || '导入失败');
                return;
            }
            const data = result.data || {};
            message.success(`导入完成：新增 ${data.created_count || 0} 个，跳过 ${data.skipped_count || 0} 个`);
            setImportPreview(null);
            await fetchGoodsNames();
        } catch (error) {
            console.error('Import goods names error:', error);
            message.error('导入失败');
        } finally {
            setImportSubmitting(false);
        }
    };

    const columnsFor = (lang) => {
        const columns = [{
            title: '品名',
            dataIndex: 'name',
            key: 'name',
            render: (text, record) => editing.id === record.id ? (
                <Input
                    value={editing.name}
                    onChange={event => setEditing(current => ({ ...current, name: event.target.value }))}
                    onPressEnter={() => handleUpdate(record)}
                    style={{ width: 220 }}
                />
            ) : text,
        }];

        if (lang === 'en') {
            columns.push({
                title: '子标题',
                dataIndex: 'category',
                key: 'category',
                render: (category, record) => editing.id === record.id ? (
                    <Input
                        value={editing.category}
                        placeholder="未分类"
                        onChange={event => setEditing(current => ({ ...current, category: event.target.value }))}
                        onPressEnter={() => handleUpdate(record)}
                        style={{ width: 180 }}
                    />
                ) : (category || <Typography.Text type="secondary">未分类</Typography.Text>),
            });
        }

        columns.push({
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
                    <Button size="small" onClick={() => setEditing({ id: record.id, name: record.name, category: record.category || '' })}>编辑</Button>
                    <Button danger size="small" loading={submitting} onClick={() => handleDelete(record.id)}>删除</Button>
                </Space>
            ),
        });
        return columns;
    };

    const cnColumns = columnsFor('cn');
    const enColumns = columnsFor('en');

    const managementTable = (lang, columns) => (
        <Table
            dataSource={goodsNames.filter(item => item.lang === lang)}
            rowKey="id"
            loading={loading}
            pagination={{ pageSize: 10 }}
            scroll={{ y: 400 }}
            columns={columns}
        />
    );

    return (
        <>
            <Card title="品名管理">
                <Tabs items={[
                    {
                        key: 'cn',
                        label: '中文品名',
                        children: (
                            <Space direction="vertical" style={{ width: '100%' }}>
                                <Space align="start" wrap>
                                    <Input.TextArea
                                        placeholder="输入中文品名，支持顿号、换行分隔批量输入"
                                        value={newCnName}
                                        onChange={event => setNewCnName(event.target.value)}
                                        style={{ width: 300 }}
                                        rows={1}
                                    />
                                    <Button type="primary" onClick={() => handleAdd('cn')} loading={submitting}>添加</Button>
                                </Space>
                                {managementTable('cn', cnColumns)}
                            </Space>
                        ),
                    },
                    {
                        key: 'en',
                        label: '英文品名',
                        children: (
                            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                                <Space align="start" wrap>
                                    <Input.TextArea
                                        placeholder="输入英文品名，支持顿号、换行分隔批量输入"
                                        value={newEnName}
                                        onChange={event => setNewEnName(event.target.value)}
                                        style={{ width: 300 }}
                                        rows={1}
                                    />
                                    <Input
                                        placeholder="子标题（可选）"
                                        value={newEnCategory}
                                        onChange={event => setNewEnCategory(event.target.value)}
                                        style={{ width: 200 }}
                                    />
                                    <Button type="primary" onClick={() => handleAdd('en')} loading={submitting}>添加</Button>
                                </Space>
                                <Space wrap>
                                    <Upload accept=".txt,text/plain" showUploadList={false} beforeUpload={handleTxtSelect}>
                                        <Button icon={<UploadOutlined />}>上传英文品名 TXT</Button>
                                    </Upload>
                                    <Typography.Text type="secondary">格式：#子标题，随后每行一个英文品名</Typography.Text>
                                </Space>
                                {managementTable('en', enColumns)}
                            </Space>
                        ),
                    },
                ]} />
            </Card>

            <Modal
                title={`导入预览${importPreview ? `：${importPreview.fileName}` : ''}`}
                open={Boolean(importPreview)}
                onCancel={() => setImportPreview(null)}
                onOk={handleImport}
                okText="确认导入"
                cancelText="取消"
                confirmLoading={importSubmitting}
                width={760}
                destroyOnClose
            >
                {importPreview && (
                    <Space direction="vertical" style={{ width: '100%' }}>
                        <Typography.Text>
                            编码：{importPreview.encoding}；共 {importPreview.groups.length} 个子标题、{importPreview.items.length} 个品名
                        </Typography.Text>
                        <Table
                            rowKey="category"
                            size="small"
                            pagination={false}
                            dataSource={importPreview.groups}
                            columns={[
                                { title: '子标题', dataIndex: 'category', key: 'category', width: 180 },
                                {
                                    title: '英文品名',
                                    dataIndex: 'names',
                                    key: 'names',
                                    render: names => <Space wrap>{names.map((name, index) => <Tag key={`${name}-${index}`}>{name}</Tag>)}</Space>,
                                },
                            ]}
                            scroll={{ y: 400 }}
                        />
                    </Space>
                )}
            </Modal>
        </>
    );
}
