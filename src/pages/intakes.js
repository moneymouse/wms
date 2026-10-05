import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, Navigate, useBlocker, useParams } from 'react-router-dom';
import { Alert, Button, Card, DatePicker, Empty, Input, InputNumber, Modal, Pagination, Select, Space, Spin, Table, Tag, Typography, message } from 'antd';
import { CameraOutlined, CheckOutlined, DeleteOutlined, PlusOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import { canReviewIntake, downloadPaperIntakeTemplate, emptyBox, intakeRequest, MAX_INTAKE_WORKERS, normalizeIntakeDraft, validateIntakeDraft } from '../common/intakeApi';
import styles from './intakes.module.css';

const { Title, Text } = Typography;
const MAX_PHOTOS = 8;
const MAX_PHOTO_BYTES = 24 * 1024 * 1024;
const MAX_SINGLE_PHOTO_BYTES = 10 * 1024 * 1024;
const RECOGNITION_POLL_MS = 3000;
const recognitionLabels = { idle: '等待识别', running: '正在识别', succeeded: '可以核对', failed: '识别失败', needs_review: '请核对疑点' };
const displayTime = value => String(value || '—').replace('T', ' ');
const paperName = record => record.display_name || record.draft?.mark || record.recognition_result?.mark || record.mark_hint || `纸单 ${record.uid.slice(0, 8)}`;
const hasManualDraft = record => record.draft_is_manual ?? (record.status === 'confirmed' || !!record.draft?.boxes?.length || Object.prototype.hasOwnProperty.call(record.draft || {}, 'operator_name') || Object.prototype.hasOwnProperty.call(record.draft || {}, 'worker_ids'));
const editableDraft = record => normalizeIntakeDraft(!hasManualDraft(record) && record.recognition_result ? record.recognition_result : record.draft);

function SelectedPhoto({ file, index, disabled, onRemove }) {
    const [url, setUrl] = useState('');
    const [previewOpen, setPreviewOpen] = useState(false);
    useEffect(() => {
        const objectUrl = URL.createObjectURL(file);
        setUrl(objectUrl);
        return () => URL.revokeObjectURL(objectUrl);
    }, [file]);
    return <div className={styles.thumbnail}>
        <button type="button" className={styles.previewButton} aria-label={`预览第${index + 1}张照片`} onClick={() => setPreviewOpen(true)}>
            {url && <img src={url} alt={file.name} />}
        </button>
        <Text className={styles.filename}>{file.name}</Text>
        <Button size="small" danger disabled={disabled} aria-label={`移除第${index + 1}张照片`} onClick={onRemove}>移除</Button>
        <Modal title={file.name} open={previewOpen} footer={null} onCancel={() => setPreviewOpen(false)}>
            {url && <img className={styles.photo} src={url} alt={`${file.name}预览`} />}
        </Modal>
    </div>;
}

function useLeaveWarning(dirty) {
    const blocker = useBlocker(dirty);
    useEffect(() => {
        const handler = event => {
            if (!dirty) return;
            event.preventDefault(); event.returnValue = '';
        };
        window.addEventListener('beforeunload', handler);
        return () => window.removeEventListener('beforeunload', handler);
    }, [dirty]);
    return <Modal title="有未保存的内容" open={blocker.state === 'blocked'} okText="放弃修改并离开" cancelText="继续编辑"
        onOk={() => blocker.proceed?.()} onCancel={() => blocker.reset?.()}>
        当前修改尚未保存，离开后会丢失。
    </Modal>;
}

export function PaperIntakeUpload({ onSubmitted } = {}) {
    const [files, setFiles] = useState([]);
    const [markHint, setMarkHint] = useState('');
    const [note, setNote] = useState('');
    const [operationAt, setOperationAt] = useState(null);
    const [submitting, setSubmitting] = useState(false);
    const [uploadError, setUploadError] = useState('');
    const [submitted, setSubmitted] = useState(false);
    const [templateDownloading, setTemplateDownloading] = useState(false);
    const [templateError, setTemplateError] = useState('');
    const inputRef = useRef(null);
    const cameraRef = useRef(null);
    const leaveWarning = useLeaveWarning(files.length > 0 || !!markHint || !!note || !!operationAt);

    const addPhotos = event => {
        const selected = Array.from(event.target.files || []);
        event.target.value = '';
        if (!selected.length) return;
        if (selected.some(file => !file.type.startsWith('image/'))) { setUploadError('请选择图片文件'); return; }
        if (selected.some(file => file.size > MAX_SINGLE_PHOTO_BYTES)) { setUploadError('每张照片不能超过 10MB，请选择较小的图片'); return; }
        const nextFiles = [...files, ...selected];
        if (nextFiles.length > MAX_PHOTOS) { setUploadError('每份纸单最多选择 8 张照片，请移除部分照片后再添加'); return; }
        if (nextFiles.reduce((sum, file) => sum + file.size, 0) > MAX_PHOTO_BYTES) { setUploadError('照片合计不能超过 24MB，请移除部分照片或选择较小的图片'); return; }
        setFiles(nextFiles); setUploadError(''); setSubmitted(false);
    };
    const submit = async () => {
        if (!files.length) { setUploadError('请至少选择一张纸单照片'); return; }
        setSubmitting(true); setUploadError(''); setSubmitted(false);
        const body = new FormData();
        files.forEach(file => body.append('photos', file));
        if (markHint.trim()) body.append('mark_hint', markHint.trim());
        if (note.trim()) body.append('note', note.trim());
        if (operationAt) body.append('operation_at', operationAt.format('YYYY-MM-DD HH:mm:ss'));
        try {
            const result = await intakeRequest('', { method: 'POST', body });
            setFiles([]); setMarkHint(''); setNote(''); setOperationAt(null); setSubmitted(true);
            onSubmitted?.(result);
        } catch (e) { setUploadError(e.message); }
        finally { setSubmitting(false); }
    };
    const downloadTemplate = async () => {
        setTemplateDownloading(true); setTemplateError('');
        try { await downloadPaperIntakeTemplate(); }
        catch (e) { setTemplateError(e.message); }
        finally { setTemplateDownloading(false); }
    };
    return <Card className={styles.uploadCard} title="上传手写装箱单">
        {leaveWarning}
        <p className={styles.uploadIntro}>拍清纸单并提交，文员会完成后续核对。</p>
        <input ref={cameraRef} aria-label="拍照照片" type="file" accept="image/*" capture="environment" hidden disabled={submitting} onChange={addPhotos} />
        <input ref={inputRef} aria-label="纸单照片" type="file" accept="image/*" multiple hidden disabled={submitting} onChange={addPhotos} />
        <Space wrap>
            <Button size="large" icon={<CameraOutlined />} disabled={submitting} onClick={() => cameraRef.current?.click()}>拍照</Button>
            <Button size="large" icon={<UploadOutlined />} disabled={submitting} onClick={() => inputRef.current?.click()}>选择照片</Button>
        </Space>
        <div className={styles.uploadHelp}><Text type="secondary">最多 8 张，每张不超过 10MB，合计不超过 24MB。可连续拍照，点击缩略图放大。</Text></div>
        <div className={styles.templateDownload}><Button type="link" size="small" loading={templateDownloading} onClick={downloadTemplate}>下载空白装箱单模板</Button></div>
        {templateError && <Alert type="error" showIcon message={templateError} className={styles.inlineAlert} />}
        {!!files.length && <>
            <Text>已选择 {files.length} / 8 张，合计 {(files.reduce((sum, file) => sum + file.size, 0) / 1024 / 1024).toFixed(1)} MB</Text>
            <div className={styles.thumbnails}>{files.map((file, index) => <SelectedPhoto key={`${file.name}-${index}`} file={file} index={index} disabled={submitting} onRemove={() => { setFiles(current => current.filter((_, i) => i !== index)); setUploadError(''); }} />)}</div>
        </>}
        <details className={styles.optionalInfo}>
            <summary>补充信息（选填）</summary>
            <div className={styles.metadata}>
                <label className={styles.field}>唛头提示<Input aria-label="唛头提示" value={markHint} onChange={e => setMarkHint(e.target.value)} disabled={submitting} /></label>
                <label className={styles.field}>备注<Input.TextArea aria-label="备注" value={note} onChange={e => setNote(e.target.value)} disabled={submitting} /></label>
                <label className={styles.field}>操作时间<DatePicker aria-label="操作时间" showTime value={operationAt} onChange={setOperationAt} disabled={submitting} /></label>
            </div>
        </details>
        {uploadError && <Alert type="error" showIcon message={uploadError} className={styles.inlineAlert} />}
        {submitted && <Alert type="success" showIcon message="照片已提交" description="等待文员核对，可继续上传下一份。" className={styles.inlineAlert} />}
        <Button type="primary" size="large" loading={submitting} onClick={submit}>提交照片</Button>
    </Card>;
}

export default function Intakes() {
    return canReviewIntake() ? <IntakeReviewList /> : <Navigate to="/packing-lists" replace />;
}

function IntakeReviewList() {
    const [records, setRecords] = useState([]);
    const [total, setTotal] = useState(0);
    const [pageSize, setPageSize] = useState(20);
    const [page, setPage] = useState(1);
    const [markSearch, setMarkSearch] = useState('');
    const [markQuery, setMarkQuery] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const requestRef = useRef(0);
    const queryRef = useRef('');
    const query = `?status=pending&page=${page}${markQuery ? `&mark=${encodeURIComponent(markQuery)}` : ''}`;
    queryRef.current = query;
    const load = useCallback(async ({ background = false } = {}) => {
        const requestId = ++requestRef.current;
        if (!background) setLoading(true);
        const currentRequest = () => requestId === requestRef.current && query === queryRef.current;
        try {
            const data = await intakeRequest(query);
            if (!currentRequest()) return;
            setRecords(data.items); setTotal(data.total); setPageSize(data.page_size || 20); setError('');
        } catch (e) { if (currentRequest()) setError(e.message); }
        finally { if (currentRequest()) setLoading(false); }
    }, [query]);
    useEffect(() => { load(); return () => { requestRef.current += 1; }; }, [load]);
    useEffect(() => {
        let active = true;
        let timer;
        const poll = async () => {
            await load({ background: true });
            if (active) timer = window.setTimeout(poll, RECOGNITION_POLL_MS);
        };
        timer = window.setTimeout(poll, RECOGNITION_POLL_MS);
        return () => { active = false; window.clearTimeout(timer); };
    }, [load]);
    const columns = [
        { title: '纸单 / 唛头', key: 'mark', render: (_, row) => <div className={styles.paperIdentity}><Link to={`/intakes/${row.uid}`} className={styles.paperName}>{paperName(row)}</Link><Text type="secondary">{row.photos?.length || 0} 张照片 · {row.draft?.boxes?.length || row.recognition_result?.boxes?.length || 0} 箱</Text></div> },
        { title: '回传人', dataIndex: 'submitted_by_name' },
        { title: '回传时间', dataIndex: 'created_at', render: displayTime },
        { title: '核对进度', key: 'recognition', render: (_, row) => <Tag color={row.recognition_status === 'failed' ? 'red' : row.recognition_status === 'running' ? 'blue' : 'default'}>{recognitionLabels[row.recognition_status] || '等待识别'}</Tag> },
        { title: '', key: 'action', render: (_, row) => <Link to={`/intakes/${row.uid}`}>核对纸单</Link> },
    ];
    return <div className={styles.page}>
        <header className={styles.pageHeader}><div><Link to="/packing-lists">返回装箱单列表</Link><Title level={3}>待核对纸质单</Title><Text type="secondary">对照原图，核对唛头、装箱内容和实际操作人员。</Text></div><Button icon={<ReloadOutlined />} onClick={load}>刷新</Button></header>
        <Card className={styles.reviewCard}>
            <div className={styles.filters}><Input.Search aria-label="按唛头查找纸单" placeholder="输入唛头查找纸单" value={markSearch} allowClear enterButton="查找" onChange={e => setMarkSearch(e.target.value)} onSearch={value => { setMarkQuery(value.trim()); setPage(1); }} /><Text type="secondary">共 {total} 份待核对</Text></div>
            {error && <Alert type="error" showIcon message={error} action={<Button onClick={load}>重试</Button>} className={styles.inlineAlert} />}
            <Table columns={columns} dataSource={records} rowKey="uid" loading={loading} pagination={false} scroll={{ x: 680 }} locale={{ emptyText: '暂无待核对纸质单' }} />
            <Pagination current={page} total={total} pageSize={pageSize} onChange={setPage} showSizeChanger={false} className={styles.pagination} />
        </Card>
    </div>;
}

function IntakePhoto({ intakeUid, photo, index }) {
    const [url, setUrl] = useState('');
    const [error, setError] = useState('');
    const [attempt, setAttempt] = useState(0);
    useEffect(() => {
        const controller = new AbortController();
        let objectUrl;
        setUrl(''); setError('');
        fetch(`${endpoint}/intakes/${encodeURIComponent(intakeUid)}/photos/${encodeURIComponent(photo.uid)}`, { headers: getSafeHeader(), signal: controller.signal }).then(async response => {
            if (!response.ok) {
                let result;
                try { result = await response.json(); } catch { /* 原图服务可能返回空响应 */ }
                throw new Error(result?.msg || '原图加载失败，请重试');
            }
            return response.blob();
        }).then(blob => {
            if (controller.signal.aborted) return;
            objectUrl = URL.createObjectURL(blob); setUrl(objectUrl);
        }).catch(e => { if (e.name !== 'AbortError') setError(e.message); });
        return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
    }, [intakeUid, photo.uid, attempt]);
    return <section className={styles.photoSheet}>
        <div className={styles.photoHeading}><Text strong>第 {index + 1} 页</Text><Text type="secondary" className={styles.filename}>{photo.filename || '纸单原图'}</Text></div>
        {error ? <Alert type="error" message={error} action={<Button onClick={() => setAttempt(value => value + 1)}>重试原图</Button>} /> : url ? <>
            <a href={url} target="_blank" rel="noreferrer"><img className={styles.photo} src={url} alt={photo.filename || '纸单原图'} /></a>
            <div className={styles.photoLinks}><a href={url} target="_blank" rel="noreferrer">放大查看</a><a href={url} download={photo.filename || '纸单原图'}>下载照片</a></div>
        </> : <Space><Spin /><Text>加载原图</Text></Space>}
    </section>;
}

export function IntakeDetail() {
    return canReviewIntake() ? <IntakeReviewDetail /> : <Navigate to="/packing-lists" replace />;
}

function IntakeReviewDetail() {
    const { uid } = useParams();
    const [record, setRecord] = useState(null);
    const [draft, setDraft] = useState(normalizeIntakeDraft(null));
    const [savedDraft, setSavedDraft] = useState(normalizeIntakeDraft(null));
    const [touched, setTouched] = useState(false);
    const [workers, setWorkers] = useState([]);
    const [workersLoaded, setWorkersLoaded] = useState(false);
    const [workersError, setWorkersError] = useState('');
    const [error, setError] = useState('');
    const [busy, setBusy] = useState('');
    const [conflict, setConflict] = useState(false);
    const [confirmOpen, setConfirmOpen] = useState(false);
    const [reloadOpen, setReloadOpen] = useState(false);
    const [messageApi, contextHolder] = message.useMessage();
    const detailEpochRef = useRef(0);
    const activeUidRef = useRef(uid);
    const currentDetailRef = useRef(null);
    activeUidRef.current = uid;
    currentDetailRef.current = { record, savedDraft, touched, draft };
    const dirty = JSON.stringify(draft) !== JSON.stringify(savedDraft);
    const leaveWarning = useLeaveWarning(touched && dirty);
    const acceptRecord = useCallback(data => {
        setRecord(data); setDraft(editableDraft(data)); setSavedDraft(normalizeIntakeDraft(data.draft)); setTouched(false); setConflict(false);
    }, []);
    const load = useCallback(async () => {
        const epoch = ++detailEpochRef.current;
        setError('');
        try {
            const next = await intakeRequest(`/${encodeURIComponent(uid)}`);
            if (epoch === detailEpochRef.current && activeUidRef.current === uid) acceptRecord(next);
        } catch (e) { if (epoch === detailEpochRef.current && activeUidRef.current === uid) setError(e.message); }
    }, [uid, acceptRecord]);
    const loadWorkers = useCallback(async () => {
        setWorkersError(''); setWorkersLoaded(false);
        try { setWorkers(await intakeRequest('/workers')); setWorkersLoaded(true); }
        catch (e) { setWorkersError(e.message); }
    }, []);
    useEffect(() => { loadWorkers(); }, [loadWorkers]);
    useEffect(() => {
        setRecord(null); setBusy(''); load();
        return () => { detailEpochRef.current += 1; };
    }, [load]);
    useEffect(() => {
        if (record?.recognition_status !== 'running' || conflict || busy) return undefined;
        let active = true;
        let timer;
        const poll = async () => {
            const epoch = detailEpochRef.current;
            try {
                const next = await intakeRequest(`/${encodeURIComponent(uid)}`);
                if (!active || epoch !== detailEpochRef.current || activeUidRef.current !== uid) return;
                const current = currentDetailRef.current;
                if (next.version < current.record.version) return;
                if (next.status !== current.record.status || hasManualDraft(next) !== hasManualDraft(current.record) || JSON.stringify(normalizeIntakeDraft(next.draft)) !== JSON.stringify(current.savedDraft)) {
                    setConflict(true); setError('纸单已被其他人更新，请重新加载后继续。当前核对内容已保留。'); return;
                }
                setRecord(next);
                if (!current.touched && !hasManualDraft(next)) setDraft(editableDraft(next));
                setError('');
            } catch (e) { if (active && epoch === detailEpochRef.current) setError(`识别进度获取失败：${e.message}`); }
            finally { if (active) timer = window.setTimeout(poll, RECOGNITION_POLL_MS); }
        };
        timer = window.setTimeout(poll, RECOGNITION_POLL_MS);
        return () => { active = false; window.clearTimeout(timer); };
    }, [record?.recognition_status, conflict, busy, uid]);

    const perform = async action => {
        const epoch = ++detailEpochRef.current;
        setBusy(action); setError('');
        const isCurrent = () => epoch === detailEpochRef.current && activeUidRef.current === uid;
        try {
            let latest = record;
            if (action === 'draft' || (action === 'confirm' && dirty)) {
                latest = await intakeRequest(`/${encodeURIComponent(uid)}/draft`, { method: 'PUT', body: { version: latest.version, draft } });
                if (!isCurrent()) return;
                acceptRecord(latest);
            }
            if (action === 'confirm') {
                latest = await intakeRequest(`/${encodeURIComponent(uid)}/confirm`, { method: 'POST', body: { version: latest.version } });
                if (!isCurrent()) return;
                acceptRecord(latest); setConfirmOpen(false); messageApi.success('已确认并生成装箱单');
            } else if (action === 'recognize') {
                latest = await intakeRequest(`/${encodeURIComponent(uid)}/recognize`, { method: 'POST', body: { version: latest.version } });
                if (!isCurrent()) return;
                setRecord(latest);
            } else messageApi.success('草稿已保存');
        } catch (e) { if (isCurrent()) setError(e.message); }
        finally { if (isCurrent()) setBusy(''); }
    };
    const editDraft = updater => { setTouched(true); setDraft(updater); };
    const updateBox = (index, field, value) => editDraft(current => ({ ...current, boxes: current.boxes.map((box, i) => i === index ? { ...box, [field]: value } : box) }));
    const editable = record?.status === 'pending';
    const totals = { count: draft.boxes.reduce((sum, box) => sum + (Number(box.count) || 0), 0), weight: draft.boxes.reduce((sum, box) => sum + (Number(box.weight) || 0), 0) };
    const unknownWorkerIds = draft.worker_ids.filter(id => !workers.some(worker => Number(worker.id) === id));
    const workerNameCounts = new Map();
    workers.forEach(worker => workerNameCounts.set(worker.name, (workerNameCounts.get(worker.name) || 0) + 1));
    const workerOptions = [...workers.map(worker => ({ value: Number(worker.id), label: workerNameCounts.get(worker.name) > 1 ? `${worker.name} · ID ${worker.id}` : worker.name })), ...unknownWorkerIds.map(id => ({ value: id, label: `人员 ${id}（请重新选择）`, disabled: true }))];
    const validationError = validateIntakeDraft(draft) || (workersLoaded && unknownWorkerIds.length ? '存在已停用或未审核的人员，请重新选择' : '');
    const warnings = record?.recognition_result?.warnings || [];
    const boxColumns = [
        { title: '箱号', width: 82, render: (_, box, index) => <Input aria-label={`第${index + 1}箱箱号`} value={box.box_number} disabled={!editable || !!busy} onChange={e => updateBox(index, 'box_number', e.target.value)} /> },
        { title: '品名', render: (_, box, index) => <Input aria-label={`第${index + 1}箱品名`} value={box.item_name} disabled={!editable || !!busy} onChange={e => updateBox(index, 'item_name', e.target.value)} /> },
        { title: '件数', width: 86, render: (_, box, index) => <InputNumber aria-label={`第${index + 1}箱件数`} value={box.count} min={1} precision={0} disabled={!editable || !!busy} onChange={value => updateBox(index, 'count', value)} /> },
        { title: '重量 (kg)', width: 110, render: (_, box, index) => <InputNumber aria-label={`第${index + 1}箱重量`} value={box.weight} min={0} disabled={!editable || !!busy} onChange={value => updateBox(index, 'weight', value)} /> },
        ...(editable ? [{ title: '', width: 46, render: (_, box, index) => <Button type="text" danger icon={<DeleteOutlined />} disabled={!!busy} aria-label={`删除第${index + 1}箱`} onClick={() => editDraft(current => ({ ...current, boxes: current.boxes.filter((_, i) => i !== index) }))} /> }] : []),
    ];
    return <div className={styles.page}>
        {contextHolder}{leaveWarning}
        <header className={styles.pageHeader}><div><Link to="/intakes">返回待核对纸质单</Link><Title level={3}>{record ? paperName(record) : '纸单核对'}</Title>{record && <Space wrap><Tag color={record.status === 'confirmed' ? 'green' : record.recognition_status === 'failed' ? 'red' : 'blue'}>{record.status === 'confirmed' ? '已确认' : recognitionLabels[record.recognition_status] || '等待识别'}</Tag><Text type="secondary">回传人：{record.submitted_by_name || '—'} · {displayTime(record.created_at)}</Text></Space>}</div>{record?.packing_list_uid && <Link to={`/packing-lists/${record.packing_list_uid}`}>查看生成的装箱单</Link>}</header>
        {error && <Alert type="error" showIcon message={error} className={styles.inlineAlert} action={<Button disabled={!!busy} onClick={() => touched && dirty ? setReloadOpen(true) : load()}>重新加载</Button>} />}
        {!record ? (error ? null : <Space><Spin /><Text>加载纸单</Text></Space>) : <div className={styles.layout}>
            <Card className={styles.photoPanel} title="纸单原图" extra={<Text type="secondary">{record.photos?.length || 0} 页</Text>}>
                <div className={styles.photos}>{record.photos?.length ? record.photos.map((photo, index) => <IntakePhoto key={photo.uid} intakeUid={uid} photo={photo} index={index} />) : <Empty description="暂无照片" />}</div>
            </Card>
            <Card className={styles.reviewCard} title={editable ? '核对装箱内容' : '已确认的装箱内容'} extra={<Text type="secondary">{dirty ? '待保存' : '已保存'}</Text>}>
                <div className={styles.reviewFields}>
                    <label className={styles.field}>唛头<Input aria-label="唛头" value={draft.mark} disabled={!editable || !!busy} onChange={e => editDraft(current => ({ ...current, mark: e.target.value }))} /></label>
                    <label className={styles.field}>实际操作人员<Select aria-label="实际操作人员" mode="multiple" showSearch optionFilterProp="label" placeholder="选择实际参与装箱的工人" value={draft.worker_ids} options={workerOptions} loading={!workersLoaded && !workersError} disabled={!editable || !!busy || !workersLoaded} onChange={workerIds => { if (workerIds.length > MAX_INTAKE_WORKERS) { messageApi.warning(`最多选择 ${MAX_INTAKE_WORKERS} 名操作人员`); return; } editDraft(current => ({ ...current, worker_ids: workerIds })); }} /></label>
                </div>
                <div className={styles.sourceNote}><Text type="secondary">纸面署名：{draft.operator_name || '未填写'}。请选择系统中的实际操作人员，最多 {MAX_INTAKE_WORKERS} 人。</Text></div>
                {workersError && <Alert type="error" message={`人员列表加载失败：${workersError}`} action={<Button onClick={loadWorkers}>重试</Button>} className={styles.inlineAlert} />}
                {!!warnings.length && <section className={styles.warnings} aria-label="待核对疑点"><div className={styles.warningHeading}><Text strong>待核对疑点</Text><Text>{warnings.length} 项</Text></div><div className={styles.warningScroll} role="region" aria-label="识别疑点列表"><ul>{warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div></section>}
                {record.recognition_status === 'running' && <div className={styles.progressNote}><Spin size="small" /><Text type="secondary">识别中，完成后会自动填入核对表。</Text></div>}
                {record.recognition_status === 'failed' && <Alert type="error" showIcon message="识别失败，可对照原图手动核对或重试" description={record.recognition_error || undefined} className={styles.inlineAlert} />}
                <Table className={styles.boxTable} size="small" rowKey="key" dataSource={draft.boxes.map((box, index) => ({ ...box, key: index }))} columns={boxColumns} pagination={false} scroll={{ x: 510 }} locale={{ emptyText: record.recognition_status === 'running' ? '正在读取装箱内容' : '暂无装箱内容，可添加一箱' }} />
                {editable && <Button className={styles.addBox} type="dashed" icon={<PlusOutlined />} disabled={!!busy} onClick={() => editDraft(current => ({ ...current, boxes: [...current.boxes, emptyBox()] }))}>添加一箱</Button>}
                <footer className={styles.reviewFooter}>
                    <div className={styles.summary}><span><strong>{draft.boxes.length}</strong> 箱</span><span><strong>{totals.count}</strong> 件</span><span><strong>{totals.weight.toFixed(3)}</strong> kg</span></div>
                    {editable && <><div className={styles.actions}><Button disabled={conflict || !!busy} loading={busy === 'draft'} onClick={() => perform('draft')}>保存草稿</Button>{['idle', 'failed'].includes(record.recognition_status) && <Button disabled={conflict || (touched && dirty) || !!busy} loading={busy === 'recognize'} onClick={() => perform('recognize')}>{record.recognition_status === 'failed' ? '重试识别' : '识别照片'}</Button>}<Button type="primary" icon={<CheckOutlined />} disabled={conflict || !!busy || !!validationError || !workersLoaded || record.recognition_status === 'running'} onClick={() => setConfirmOpen(true)}>确认生成装箱单</Button></div>{validationError && <Text type="secondary" className={styles.validation}>确认前需要补全：{validationError}</Text>}</>}
                </footer>
            </Card>
        </div>}
        <Modal title="确认生成装箱单" open={confirmOpen} okText="确认生成" cancelText="继续核对" confirmLoading={busy === 'confirm'} onCancel={() => { if (!busy) setConfirmOpen(false); }} onOk={() => perform('confirm')}>
            <p>唛头：{draft.mark}</p><p>操作人员：{draft.worker_ids.map(id => workerOptions.find(option => option.value === id)?.label || `人员 ${id}`).join('、')}</p><p>箱数：{draft.boxes.length}；总件数：{totals.count}；总重量：{totals.weight.toFixed(3)} kg</p>
            <p>请确认原图与核对表一致。{dirty ? '确认时会先保存当前核对内容，再生成装箱单。' : '确认后将生成装箱单。'}</p>{error && <Alert type="error" message={error} />}
        </Modal>
        <Modal title="重新加载纸单" open={reloadOpen} okText="放弃修改并重新加载" cancelText="继续编辑" onCancel={() => setReloadOpen(false)} onOk={() => { setReloadOpen(false); load(); }}>重新加载会丢弃当前未保存的修改。</Modal>
    </div>;
}
