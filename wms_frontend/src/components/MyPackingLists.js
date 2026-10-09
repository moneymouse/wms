import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Alert, Button, Card, Empty, Grid, Input, Pagination, Spin, Table, Tag, Typography } from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { intakeRequest } from '../common/intakeApi';
import styles from './MyPackingLists.module.css';

const PAGE_SIZE = 20;
const LOAD_ERROR = '装箱单加载失败，请重试';
const displayTime = value => String(value || '-').replace('T', ' ');
const STATUS = {
    uploading: { label: '上传未完成', color: 'gold' },
    draft: { label: '草稿', color: 'default' },
    completed: { label: '已创建', color: 'green' },
};

export default function MyPackingLists({ refreshKey = 0 }) {
    const navigate = useNavigate();
    const screens = Grid.useBreakpoint();
    const compactView = screens.xs === true || (screens.sm === true && screens.md !== true);
    const [records, setRecords] = useState([]);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [searchInput, setSearchInput] = useState('');
    const [markQuery, setMarkQuery] = useState('');
    const [reloadKey, setReloadKey] = useState(0);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const query = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE), mark: markQuery }).toString();

    useEffect(() => {
        const controller = new AbortController();
        let active = true;
        setRecords([]);
        setTotal(0);
        setLoading(true);
        setError('');

        const load = async () => {
            try {
                const data = await intakeRequest(`/my-packing-lists?${query}`, { signal: controller.signal });
                if (!active) return;
                if (!Array.isArray(data?.items) || !Number.isFinite(data.total) || data.total < 0
                    || data.items.some(item => !item || !item.uid)) {
                    throw new Error(LOAD_ERROR);
                }
                setRecords(data.items);
                setTotal(data.total);
                setError('');
            } catch {
                if (!active) return;
                setError(LOAD_ERROR);
            } finally {
                if (active) setLoading(false);
            }
        };
        load();
        return () => {
            active = false;
            controller.abort();
        };
    }, [query, reloadKey, refreshKey]);

    const reload = () => setReloadKey(value => value + 1);
    const renderStatus = record => {
        const status = record.source === 'paper' && record.status === 'completed'
            ? { label: '已核对', color: 'green' } : STATUS[record.status];
        return status ? <Tag className={styles.status} color={status.color}>{status.label}</Tag> : '-';
    };
    const renderAction = record => (
        record.status === 'uploading'
            ? <Link to={`/packing-list/upload/${encodeURIComponent(record.intake_uid || record.uid)}`}>继续检查并上传</Link>
            : record.packing_list_uid
            ? <Link to={`/packing-lists/${encodeURIComponent(record.packing_list_uid)}`}>查看装箱单</Link>
            : <Typography.Text type="secondary">-</Typography.Text>
    );
    const columns = [
        {
            title: '唛头', key: 'mark', render: (_, record) => (
                <span className={styles.mark}>{record.mark || '唛头待填写'}</span>
            ),
        },
        { title: '来源', key: 'source', render: (_, record) => record.source === 'paper' ? '拍照上传' : '手动录入' },
        { title: '状态', key: 'status', render: (_, record) => renderStatus(record) },
        { title: '箱数', key: 'boxes', render: (_, record) => record.box_count ?? '-' },
        { title: '创建时间', dataIndex: 'created_at', render: displayTime },
        { title: '操作', key: 'action', render: (_, record) => renderAction(record) },
    ];

    return <div className={styles.page}>
        <div className={styles.header}>
            <div>
                <Typography.Title level={3} className={styles.title}>我的装箱单</Typography.Title>
                <Typography.Text type="secondary">查看你创建的装箱单和上传的纸单。</Typography.Text>
            </div>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/packing-list/new')}>创建装箱单</Button>
        </div>
        <Card>
            <div className={styles.toolbar}>
                <Input.Search aria-label="按唛头查找我的装箱单" placeholder="输入唛头查找" value={searchInput}
                    allowClear enterButton="查找" className={styles.search}
                    onChange={event => setSearchInput(event.target.value)}
                    onSearch={value => { setMarkQuery(value.trim()); setPage(1); }} />
                <Button icon={<ReloadOutlined />} aria-label="刷新我的装箱单" onClick={reload}>刷新</Button>
            </div>
            {error && <Alert className={styles.error} type="error" showIcon message={error}
                action={<Button size="small" onClick={reload}>重试</Button>} />}
            {compactView ? <Spin spinning={loading}>
                <div className={styles.mobileList}>
                    {records.length ? records.map(record => <article key={record.uid} aria-label={`装箱单 ${record.mark || '唛头待填写'}`} className={styles.mobileCard}>
                        <div className={styles.mobileHeader}>
                            <span className={`${styles.mark} ${styles.mobileMark}`}>{record.mark || '唛头待填写'}</span>
                            {renderStatus(record)}
                        </div>
                        <div className={styles.mobileInfo}>
                            <span>{record.source === 'paper' ? '拍照上传' : '手动录入'}</span>
                            <span>箱数：{record.box_count ?? '-'}</span>
                        </div>
                        <span className={styles.mobileTime}>创建时间：{displayTime(record.created_at)}</span>
                        <div className={styles.mobileAction}>{renderAction(record)}</div>
                    </article>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无装箱单" />}
                </div>
            </Spin> : <Table columns={columns} dataSource={records} rowKey="uid" loading={loading} pagination={false}
                scroll={{ x: 760 }} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无装箱单" /> }} />}
            <Pagination className={styles.pagination} current={page} pageSize={PAGE_SIZE} total={total}
                showSizeChanger={false} hideOnSinglePage onChange={setPage} showTotal={count => `共 ${count} 份装箱单`} />
        </Card>
    </div>;
}
