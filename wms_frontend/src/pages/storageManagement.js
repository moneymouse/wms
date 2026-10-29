import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Empty, Grid, Image, Input, message, Modal, Result, Space, Spin, Statistic, Table, Tag, Typography } from 'antd';
import { DatabaseOutlined, DeleteOutlined, EyeOutlined, ReloadOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import dayjs from 'dayjs';
import { getIntakeRoles } from '../common/intakeApi';
import { hasPermission, routePermissions } from '../common/roleConfig';
import { formatStorageBytes, storagePhotoRequest, storageRequest } from '../common/storageApi';
import useUrlState from '../common/useUrlState';
import styles from './storageManagement.module.css';

const RETENTION_DAYS = 90;
const PAGE_SIZE = 20;

export default function StorageManagement() {
    const screens = Grid.useBreakpoint();
    const canManage = hasPermission(getIntakeRoles(), routePermissions['/storage-management']);
    const [filters, setFilters] = useUrlState('storage_filters', { page: 1, page_size: PAGE_SIZE, q: '' }, {
        validate: value => value && Number.isInteger(value.page) && value.page > 0 && value.page_size === PAGE_SIZE && typeof value.q === 'string',
    });
    const [search, setSearch] = useState(filters.q);
    useEffect(() => { setSearch(filters.q); }, [filters.q]);
    const [summary, setSummary] = useState(null);
    const [items, setItems] = useState([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [loadErrors, setLoadErrors] = useState({});
    const [actionError, setActionError] = useState('');
    const [removingId, setRemovingId] = useState(null);
    const [cleaning, setCleaning] = useState(false);
    const [previewRecord, setPreviewRecord] = useState(null);
    const [photos, setPhotos] = useState([]);
    const [photoSourceUid, setPhotoSourceUid] = useState(null);
    const [selectedPhotoUid, setSelectedPhotoUid] = useState(null);
    const [photoListLoading, setPhotoListLoading] = useState(false);
    const [photoListError, setPhotoListError] = useState('');
    const [photoLoading, setPhotoLoading] = useState(false);
    const [photoError, setPhotoError] = useState('');
    const [photoUrl, setPhotoUrl] = useState('');
    const [previewRetry, setPreviewRetry] = useState(0);
    const [photoRetry, setPhotoRetry] = useState(0);
    const requestId = useRef(0);
    const mutationLock = useRef(false);
    const confirmationOpen = useRef(false);
    const confirmation = useRef(null);
    const busy = Boolean(removingId || cleaning);
    const selectedPhoto = photoSourceUid === previewRecord?.intake_uid ? photos.find(photo => photo.uid === selectedPhotoUid) : undefined;

    const loadStorage = useCallback(async (params, signal) => {
        const id = ++requestId.current;
        setLoading(true);
        setLoadErrors({});
        setSummary(null);
        setItems([]);
        setTotal(0);
        const results = await Promise.allSettled([
            storageRequest('/summary', { signal }),
            storageRequest('/packing-lists', { params, signal }),
        ]);
        if (signal?.aborted || id !== requestId.current) return;
        const errors = {};
        if (results[0].status === 'fulfilled') setSummary(results[0].value);
        else errors.summary = results[0].reason.message || '统计加载失败';
        if (results[1].status === 'fulfilled') {
            const result = results[1].value;
            const lastPage = Math.max(1, Math.ceil(result.total / params.page_size));
            if (params.page > lastPage) {
                setFilters(previous => ({ ...previous, page: lastPage }));
            } else {
                setItems(result.items);
                setTotal(result.total);
            }
        } else errors.list = results[1].reason.message || '照片列表加载失败';
        setLoadErrors(errors);
        setLoading(false);
    }, [setFilters]);

    useEffect(() => {
        if (!canManage) return undefined;
        const controller = new AbortController();
        loadStorage(filters, controller.signal);
        return () => controller.abort();
    }, [canManage, filters, loadStorage]);

    useEffect(() => () => {
        requestId.current += 1;
        confirmation.current?.destroy();
    }, []);

    useEffect(() => {
        setPhotos([]);
        setPhotoSourceUid(null);
        setSelectedPhotoUid(null);
        setPhotoListError('');
        setPhotoListLoading(Boolean(previewRecord));
        if (!previewRecord || !canManage) return undefined;
        const controller = new AbortController();
        storageRequest(`/intakes/${encodeURIComponent(previewRecord.intake_uid)}/photos`, { signal: controller.signal })
            .then(result => {
                if (controller.signal.aborted) return;
                setPhotos(result.photos || []);
                setPhotoSourceUid(previewRecord.intake_uid);
                setSelectedPhotoUid(result.photos?.[0]?.uid || null);
            })
            .catch(error => {
                if (!controller.signal.aborted) setPhotoListError(error.message || '照片列表加载失败，请重试');
            })
            .finally(() => { if (!controller.signal.aborted) setPhotoListLoading(false); });
        return () => controller.abort();
    }, [canManage, previewRecord, previewRetry]);

    useEffect(() => {
        setPhotoUrl('');
        setPhotoError('');
        setPhotoLoading(Boolean(previewRecord && selectedPhoto));
        if (!canManage || !previewRecord || !selectedPhoto) return undefined;
        if (selectedPhoto.missing) {
            setPhotoError('照片文件已缺失，无法查看原图');
            setPhotoLoading(false);
            return undefined;
        }
        const controller = new AbortController();
        let objectUrl;
        storagePhotoRequest(previewRecord.intake_uid, selectedPhoto.uid, { signal: controller.signal })
            .then(blob => {
                if (controller.signal.aborted) return;
                objectUrl = URL.createObjectURL(blob);
                setPhotoUrl(objectUrl);
            })
            .catch(error => {
                if (!controller.signal.aborted) setPhotoError(error.message || '照片加载失败，请重试');
            })
            .finally(() => { if (!controller.signal.aborted) setPhotoLoading(false); });
        return () => {
            controller.abort();
            if (objectUrl) URL.revokeObjectURL(objectUrl);
        };
    }, [canManage, previewRecord, selectedPhoto, photoRetry]);

    const applySearch = query => {
        if (busy) return;
        setActionError('');
        const q = query.trim();
        setFilters(previous => previous.q === q && previous.page === 1 ? previous : { page: 1, page_size: PAGE_SIZE, q });
    };

    const confirmDelete = record => {
        if (!record.intake_uid || mutationLock.current || confirmationOpen.current || loading) return;
        const warning = record.deletion_warning || record.cleanup_reason;
        confirmationOpen.current = true;
        confirmation.current = Modal.confirm({
            title: `删除 ${record.list_number} 的纸单照片？`,
            content: <>
                {warning && <Alert type="warning" showIcon message="尚未满足照片保留期限或出货条件，仍可删除" description={`${warning}。请确认现在删除。`} />}
                {record.archived ? <p>该装箱单已归档。</p> :
                    <p>最后出货时间：{record.last_shipped_at ? dayjs(record.last_shipped_at).format('YYYY-MM-DD HH:mm') : '未记录'}
                        {record.days_since_shipped !== null && record.days_since_shipped !== undefined ? `（距今 ${record.days_since_shipped} 天）` : ''}。</p>}
                <p>将删除当前上传来源的全部纸单照片，共 {record.photo_count} 张，占用 {formatStorageBytes(record.photo_bytes)}。</p>
                <p>删除后不可恢复，请确认不再需要原图。</p>
                <p>装箱单、箱子和财务记录会保留。</p>
            </>,
            okText: '确认删除照片',
            okButtonProps: { danger: true },
            cancelText: '取消',
            maskClosable: false,
            afterClose: () => { confirmationOpen.current = false; confirmation.current = null; },
            onOk: async () => {
                if (mutationLock.current) return;
                mutationLock.current = true;
                setRemovingId(record.intake_uid);
                setActionError('');
                confirmation.current?.update({ cancelButtonProps: { disabled: true }, keyboard: false });
                try {
                    const result = await storageRequest(`/intakes/${encodeURIComponent(record.intake_uid)}/photos`, {
                        method: 'DELETE', body: { days: RETENTION_DAYS },
                    });
                    if (result.pending_files) {
                        setActionError(`照片已从上传来源移除；仍有 ${result.pending_files} 个文件等待清理，请点击“重试清理待清理文件”。`);
                    } else message.success(`已删除 ${result.deleted_files} 张照片，释放 ${formatStorageBytes(result.deleted_bytes)}`);
                    setPreviewRecord(current => current?.intake_uid === record.intake_uid ? null : current);
                    await loadStorage(filters);
                } catch (error) {
                    setActionError(error.message || '删除照片失败，请重试');
                } finally {
                    mutationLock.current = false;
                    setRemovingId(null);
                }
            },
        });
    };

    const retryCleanup = async () => {
        if (mutationLock.current || confirmationOpen.current) return;
        mutationLock.current = true;
        setCleaning(true);
        setActionError('');
        try {
            const result = await storageRequest('/cleanup', { method: 'POST' });
            if (result.pending_files) {
                setActionError(`仍有 ${result.pending_files} 个文件未能清理，请稍后重试或联系管理员检查文件权限。`);
            } else message.success(`已清理 ${result.deleted_files} 个文件，释放 ${formatStorageBytes(result.deleted_bytes)}`);
            await loadStorage(filters);
        } catch (error) {
            setActionError(error.message || '清理失败，请重试');
        } finally {
            mutationLock.current = false;
            setCleaning(false);
        }
    };

    if (!canManage) return <Result status="403" title="无权访问存储管理" subTitle="仅管理员和店长可以查看和清理纸单照片。" />;

    const columns = [
        { title: '装箱单唛头', dataIndex: 'list_number', width: 260, render: (value, record) => <Space wrap>
            {!record.archived && record.detail_url ? <Link to={record.detail_url}>{value}</Link> : <span>{value}</span>}
            {record.archived && <Tag>已归档</Tag>}
        </Space> },
        {
            title: '照片数', dataIndex: 'photo_count', width: 110,
            render: (value, record) => <div>{value} 张{record.missing_photo_count > 0 &&
                <Typography.Text className={styles.missingNote} type="warning">缺失文件 {record.missing_photo_count} 张</Typography.Text>}</div>,
        },
        { title: '占用空间', dataIndex: 'photo_bytes', width: 120, render: formatStorageBytes },
        { title: '最后出货时间', dataIndex: 'last_shipped_at', width: 180, render: value => value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '—' },
        { title: '详情', key: 'detail', width: 120, render: (_, record) => record.archived ? '—' :
            record.detail_url ? <Link to={record.detail_url}>{record.detail_label || '查看装箱单'}</Link> :
                <Typography.Text type="secondary">未生成装箱单</Typography.Text> },
        {
            title: '操作', key: 'action', width: 250, fixed: screens.md === false ? undefined : 'right',
            render: (_, record) => <Space wrap>
                <Button aria-label="查看照片" icon={<EyeOutlined />} disabled={busy || loading}
                    onClick={() => setPreviewRecord(record)}>查看照片</Button>
                <Button danger aria-label="删除照片" icon={<DeleteOutlined />} loading={removingId === record.intake_uid}
                    disabled={busy || loading} onClick={() => confirmDelete(record)}>删除照片</Button>
            </Space>,
        },
    ];

    return <div className={styles.page}>
        <Modal title={`${previewRecord?.list_number || ''} 的纸单照片`} open={Boolean(previewRecord)} width={900}
            footer={null} onCancel={() => setPreviewRecord(null)}>
            {photoListLoading ? <div className={styles.photoLoading}><Spin tip="正在加载照片列表" /></div> :
                photoListError ? <Alert type="error" showIcon message={photoListError}
                    action={<Button onClick={() => setPreviewRetry(value => value + 1)}>重试加载照片</Button>} /> :
                    !photos.length ? <Empty description="该上传来源暂无照片" /> : <>
                        <Space wrap className={styles.photoSelector}>
                            {photos.map((photo, index) => <Button key={photo.uid} type={photo.uid === selectedPhotoUid ? 'primary' : 'default'}
                                aria-label={`查看第${index + 1}张照片`} onClick={() => setSelectedPhotoUid(photo.uid)}>
                                第 {index + 1} 张{photo.missing ? '（文件缺失）' : ''}
                            </Button>)}
                        </Space>
                        {selectedPhoto && <Typography.Paragraph type="secondary">{selectedPhoto.original_filename || selectedPhoto.filename}</Typography.Paragraph>}
                        {photoLoading && <div className={styles.photoLoading}><Spin tip="正在加载原图" /></div>}
                        {photoError && <Alert type="error" showIcon message={photoError}
                            action={!selectedPhoto?.missing && <Button onClick={() => setPhotoRetry(value => value + 1)}>重试加载照片</Button>} />}
                        {photoUrl && !photoError && <div className={styles.photoPreview}><Image src={photoUrl}
                            alt={`纸单照片：${selectedPhoto?.original_filename || selectedPhoto?.filename || ''}`}
                            onError={() => setPhotoError('照片无法显示，文件可能已损坏，请重试')} /></div>}
                    </>}
        </Modal>
        <div className={styles.header}>
            <div>
                <Typography.Title level={3} style={{ margin: '0 0 4px' }}><DatabaseOutlined /> 存储管理</Typography.Title>
                <Typography.Text type="secondary">查看纸单照片的磁盘占用和所属装箱单。</Typography.Text>
            </div>
            <Button icon={<ReloadOutlined />} loading={loading} disabled={busy} onClick={() => loadStorage(filters)}>刷新</Button>
        </div>

        {Object.keys(loadErrors).length > 0 && <Alert className={styles.notice} type="error" showIcon message="存储数据加载失败"
            description={<Space direction="vertical">{loadErrors.summary && <span>统计：{loadErrors.summary}</span>}{loadErrors.list && <span>照片列表：{loadErrors.list}</span>}</Space>}
            action={<Button disabled={busy || loading} onClick={() => loadStorage(filters)}>重试加载</Button>} />}
        {actionError && <Alert className={styles.notice} type="error" showIcon message={actionError} closable onClose={() => setActionError('')} />}

        <div className={styles.stats}>
            <Card loading={loading && !summary}>
                <Statistic title="照片磁盘占用" value={formatStorageBytes(summary?.total_bytes)} />
                <Typography.Text className={styles.statNote} type="secondary">包含待清理及无来源文件</Typography.Text>
            </Card>
            <Card loading={loading && !summary}>
                <Statistic title="照片文件数" value={summary?.total_files ?? '—'} suffix="个" />
                <Typography.Text className={styles.statNote} type="secondary">服务器上保存的纸单照片</Typography.Text>
            </Card>
            <Card loading={loading && !summary}>
                <Statistic title="照片组数" value={summary?.photo_groups ?? '—'} suffix="组" />
                <Typography.Text className={styles.statNote} type="secondary">按纸单上传来源分组</Typography.Text>
            </Card>
            <Card loading={loading && !summary}>
                <Statistic title="待清理文件" value={summary?.pending_cleanup_files ?? '—'} suffix="个" />
                <Typography.Text className={styles.statNote} type="secondary">{formatStorageBytes(summary?.pending_cleanup_bytes)}</Typography.Text>
                {summary?.pending_cleanup_files > 0 && <Button style={{ marginTop: 8 }} loading={cleaning} disabled={Boolean(removingId) || loading}
                    onClick={retryCleanup}>重试清理待清理文件</Button>}
            </Card>
        </div>

        <Card title="照片列表">
            <div className={styles.filters}>
                <Input.Search className={styles.search} aria-label="搜索装箱单唛头" placeholder="搜索装箱单唛头" allowClear enterButton="搜索" maxLength={64}
                    value={search} onChange={event => { const value = event.target.value; setSearch(value); if (!value) applySearch(''); }}
                    onSearch={applySearch} disabled={busy} />
            </div>
            <Table rowKey="intake_uid" columns={columns} dataSource={items} loading={loading} scroll={{ x: 1040 }}
                pagination={{ current: filters.page, pageSize: PAGE_SIZE, total, showSizeChanger: false, disabled: busy,
                    showTotal: value => `共 ${value} 组照片`, onChange: page => setFilters(previous => ({ ...previous, page })) }}
                locale={{ emptyText: loadErrors.list ? '列表加载失败，请点击重试加载' : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={filters.q ? '没有匹配唛头的照片' : '暂无纸单照片'} /> }} />
        </Card>
    </div>;
}
