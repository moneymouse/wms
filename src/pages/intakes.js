import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useBlocker, useParams } from 'react-router-dom';
import { Alert, Button, Card, Checkbox, DatePicker, Empty, Input, InputNumber, Modal, Pagination, Select, Space, Spin, Table, Tag, Typography, message } from 'antd';
import { CameraOutlined, CheckOutlined, DownOutlined, DeleteOutlined, PlusOutlined, ReloadOutlined, UploadOutlined, UpOutlined } from '@ant-design/icons';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import { downloadPaperIntakeTemplate, emptyBox, intakeRequest, MAX_INTAKE_WORKERS, normalizeIntakeDraft, validateIntakeDraft } from '../common/intakeApi';
import styles from './intakes.module.css';

const { Title, Text } = Typography;
const MAX_PHOTOS = 8;
const MAX_PHOTO_BYTES = 24 * 1024 * 1024;
const MAX_SINGLE_PHOTO_BYTES = 10 * 1024 * 1024;
const RECOGNITION_POLL_MS = 3000;
const MOBILE_QUERY = '(max-width: 600px)';
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
    const [uploaded, setUploaded] = useState(null);
    return uploaded
        ? <PaperIntakeCheck uid={uploaded.uid} initialRecord={uploaded} onCompleted={onSubmitted} onNext={() => setUploaded(null)} />
        : <PaperIntakePhotos onUploaded={setUploaded} />;
}

function ContinuePaperUploads() {
    const [records, setRecords] = useState([]);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [reloadKey, setReloadKey] = useState(0);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    useEffect(() => {
        const controller = new AbortController();
        let active = true;
        setLoading(true); setError(''); setRecords([]);
        intakeRequest(`/my-packing-lists?status=uploading&page=${page}&page_size=20`, { signal: controller.signal }).then(data => {
            if (!active) return;
            if (!Array.isArray(data?.items) || !Number.isFinite(data.total) || data.total < 0) throw new Error('未完成上传加载失败，请重试');
            setRecords(data.items); setTotal(data.total);
        }).catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
        return () => { active = false; controller.abort(); };
    }, [page, reloadKey]);
    if (!loading && !error && !total) return null;
    return <section className={styles.continueUploads} aria-label="我的未完成上传">
        <div className={styles.continueHeader}><Text strong>我的未完成上传</Text><Button type="text" icon={<ReloadOutlined />} aria-label="刷新未完成上传" onClick={() => setReloadKey(current => current + 1)}>刷新</Button></div>
        <Text type="secondary">之前上传的照片和已保存的检查进度可以继续使用。</Text>
        {error && <Alert type="error" message={error} className={styles.inlineAlert} action={<Button onClick={() => setReloadKey(current => current + 1)}>重试</Button>} />}
        <Spin spinning={loading}><ul className={styles.continueList}>{records.map(item => <li key={item.uid}><div><Text strong>{item.mark || '唛头待填写'}</Text><Text type="secondary">{item.box_count || 0} 箱 · {displayTime(item.created_at)}</Text></div><Link to={`/packing-list/upload/${encodeURIComponent(item.intake_uid || item.uid)}`}>继续检查并上传</Link></li>)}</ul></Spin>
        <Pagination current={page} total={total} pageSize={20} showSizeChanger={false} hideOnSinglePage onChange={setPage} className={styles.pagination} />
    </section>;
}

function PaperIntakePhotos({ onUploaded }) {
    const [files, setFiles] = useState([]);
    const [markHint, setMarkHint] = useState('');
    const [note, setNote] = useState('');
    const [operationAt, setOperationAt] = useState(null);
    const [submitting, setSubmitting] = useState(false);
    const [uploadError, setUploadError] = useState('');
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
        setFiles(nextFiles); setUploadError('');
    };
    const submit = async () => {
        if (!files.length) { setUploadError('请至少选择一张纸单照片'); return; }
        setSubmitting(true); setUploadError('');
        const body = new FormData();
        files.forEach(file => body.append('photos', file));
        if (markHint.trim()) body.append('mark_hint', markHint.trim());
        if (note.trim()) body.append('note', note.trim());
        if (operationAt) body.append('operation_at', operationAt.format('YYYY-MM-DD HH:mm:ss'));
        try {
            const result = await intakeRequest('', { method: 'POST', body });
            onUploaded(result);
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
        <p className={styles.uploadIntro}>拍清纸单后识别内容，由你对照原图检查并修改。核对完成后才会生成装箱单。</p>
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
        <Button type="primary" size="large" loading={submitting} onClick={submit}>识别照片并检查</Button>
        <ContinuePaperUploads />
    </Card>;
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

export function PaperIntakeUploadDetail() {
    const { uid } = useParams();
    return <PaperIntakeCheck key={uid} uid={uid} />;
}

function PaperIntakeCheck({ uid, initialRecord, onCompleted, onNext }) {
    const [isMobile, setIsMobile] = useState(() => window.matchMedia(MOBILE_QUERY).matches);
    const [photosExpanded, setPhotosExpanded] = useState(false);
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
    const [reviewed, setReviewed] = useState(false);
    const [reloadOpen, setReloadOpen] = useState(false);
    const [messageApi, contextHolder] = message.useMessage();
    const busyRef = useRef('');
    const detailEpochRef = useRef(0);
    const activeUidRef = useRef(uid);
    const currentDetailRef = useRef(null);
    activeUidRef.current = uid;
    currentDetailRef.current = { record, savedDraft, touched, draft };
    const dirty = JSON.stringify(draft) !== JSON.stringify(savedDraft);
    const showPhotos = !isMobile || photosExpanded;
    const leaveWarning = useLeaveWarning(touched && dirty);
    useEffect(() => {
        const media = window.matchMedia(MOBILE_QUERY);
        const update = event => setIsMobile(event.matches);
        setIsMobile(media.matches);
        media.addEventListener('change', update);
        return () => media.removeEventListener('change', update);
    }, []);
    useEffect(() => { setPhotosExpanded(false); }, [uid]);
    const acceptRecord = useCallback(data => {
        setRecord(data); setDraft(editableDraft(data)); setSavedDraft(normalizeIntakeDraft(data.draft)); setTouched(false); setConflict(false); setReviewed(false);
    }, []);
    const load = useCallback(async () => {
        if (busyRef.current) return;
        const epoch = ++detailEpochRef.current;
        const isCurrent = () => epoch === detailEpochRef.current && activeUidRef.current === uid;
        busyRef.current = 'load'; setBusy('load'); setReviewed(false); setError('');
        try {
            const next = await intakeRequest(`/${encodeURIComponent(uid)}`);
            if (isCurrent()) acceptRecord(next);
        } catch (e) { if (isCurrent()) setError(e.message); }
        finally { if (isCurrent()) { busyRef.current = ''; setBusy(''); } }
    }, [uid, acceptRecord]);
    const loadWorkers = useCallback(async () => {
        setWorkersError(''); setWorkersLoaded(false);
        try { setWorkers(await intakeRequest('/workers')); setWorkersLoaded(true); }
        catch (e) { setWorkersError(e.message); }
    }, []);
    useEffect(() => { loadWorkers(); }, [loadWorkers]);
    useEffect(() => {
        setRecord(null); busyRef.current = ''; setBusy('');
        if (initialRecord) acceptRecord(initialRecord); else load();
        return () => { detailEpochRef.current += 1; };
    }, [load, initialRecord, acceptRecord]);
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
                    setConflict(true); setReviewed(false); setError('纸单已在其他页面更新，请重新加载后继续。当前检查内容已保留。'); return;
                }
                setRecord(next); setReviewed(false);
                if (!current.touched && !hasManualDraft(next)) setDraft(editableDraft(next));
                setError('');
            } catch (e) { if (active && epoch === detailEpochRef.current) setError(`识别进度获取失败：${e.message}`); }
            finally { if (active) timer = window.setTimeout(poll, RECOGNITION_POLL_MS); }
        };
        timer = window.setTimeout(poll, RECOGNITION_POLL_MS);
        return () => { active = false; window.clearTimeout(timer); };
    }, [record?.recognition_status, conflict, busy, uid]);

    const perform = async action => {
        if (busyRef.current || conflict || record?.status !== 'pending') return;
        if (action === 'confirm' && (!reviewed || record?.recognition_status === 'running')) return;
        const epoch = ++detailEpochRef.current;
        busyRef.current = action; setBusy(action); setError('');
        const isCurrent = () => epoch === detailEpochRef.current && activeUidRef.current === uid;
        try {
            let latest = record;
            if (action === 'draft' || (action === 'confirm' && dirty)) {
                latest = await intakeRequest(`/${encodeURIComponent(uid)}/draft`, { method: 'PUT', body: { version: latest.version, draft } });
                if (!isCurrent()) return;
                acceptRecord(latest);
            }
            if (action === 'confirm') {
                latest = await intakeRequest(`/${encodeURIComponent(uid)}/confirm`, { method: 'POST', body: { version: latest.version, reviewed: true } });
                if (!isCurrent()) return;
                acceptRecord(latest); messageApi.success('核对完成，装箱单已上传'); onCompleted?.(latest);
            } else if (action === 'recognize') {
                latest = await intakeRequest(`/${encodeURIComponent(uid)}/recognize`, { method: 'POST', body: { version: latest.version } });
                if (!isCurrent()) return;
                setRecord(latest); setReviewed(false);
            } else messageApi.success('检查进度已保存');
        } catch (e) { if (isCurrent()) setError(e.message); }
        finally { if (isCurrent()) { busyRef.current = ''; setBusy(''); } }
    };
    const editDraft = updater => {
        if (busyRef.current) return;
        setTouched(true); setReviewed(false); setDraft(updater);
    };
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
        <header className={styles.pageHeader}><div><Link to="/packing-lists">返回装箱单列表</Link><Title level={3}>{record ? `检查纸质装箱单 · ${paperName(record)}` : '检查纸质装箱单'}</Title>{record && <Space wrap><Tag color={record.status === 'confirmed' ? 'green' : record.recognition_status === 'failed' ? 'red' : 'blue'}>{record.status === 'confirmed' ? '已核对' : recognitionLabels[record.recognition_status] || '等待识别'}</Tag><Text type="secondary">上传人：{record.submitted_by_name || '—'} · {displayTime(record.created_at)}</Text></Space>}</div>{record?.packing_list_uid && <Link to={`/packing-lists/${record.packing_list_uid}`}>查看装箱单</Link>}</header>
        {record?.status === 'confirmed' && <Alert type="success" showIcon message="核对完成，装箱单已上传" description="已核对的装箱内容已生成正式装箱单。" action={onNext ? <Button onClick={onNext}>上传下一份</Button> : <Link to="/packing-list/new">上传下一份</Link>} className={styles.inlineAlert} />}
        {!isMobile && record?.status === 'pending' && <Alert type="info" showIcon message="请对照纸单原图检查唛头、每箱内容和实际操作人员" description="检查并修改后，勾选核对确认，再完成上传。未完成的纸单可在拍照上传页的“我的未完成上传”中继续检查。" className={styles.inlineAlert} />}

        {error && <Alert type="error" showIcon message={error} className={styles.inlineAlert} action={<Button disabled={!!busy} onClick={() => touched && dirty ? setReloadOpen(true) : load()}>重新加载</Button>} />}
        {!record ? (error ? null : <Space><Spin /><Text>加载纸单</Text></Space>) : <div className={styles.layout}>
            <Card className={`${styles.photoPanel} ${isMobile ? styles.photoPanelCollapsible : ''} ${showPhotos ? '' : styles.photoPanelCollapsed}`}
                title={isMobile ? <button type="button" className={styles.photoToggle} aria-label={`${photosExpanded ? '收起' : '展开'}纸单原图`} aria-expanded={photosExpanded} aria-controls={`intake-photos-${uid}`} onClick={() => setPhotosExpanded(current => !current)}><span>纸单原图</span><span className={styles.photoToggleHint}>{record.photos?.length || 0} 页 · {photosExpanded ? '收起' : '展开'} {photosExpanded ? <UpOutlined /> : <DownOutlined />}</span></button> : '纸单原图'}
                extra={!isMobile && <Text type="secondary">{record.photos?.length || 0} 页</Text>}>
                <div id={`intake-photos-${uid}`} className={styles.photos} hidden={!showPhotos}>{showPhotos && (record.photos?.length ? record.photos.map((photo, index) => <IntakePhoto key={photo.uid} intakeUid={uid} photo={photo} index={index} />) : <Empty description="暂无照片" />)}</div>
            </Card>
            <Card className={styles.reviewCard} title={editable ? '检查识别结果' : '已核对的装箱内容'} extra={<Text type="secondary">{dirty ? '检查进度待保存' : '检查进度已保存'}</Text>}>
                <div className={styles.reviewFields}>
                    <label className={styles.field}>唛头<Input aria-label="唛头" value={draft.mark} disabled={!editable || !!busy} onChange={e => editDraft(current => ({ ...current, mark: e.target.value }))} /></label>
                    <label className={styles.field}>实际操作人员<Select aria-label="实际操作人员" mode="multiple" showSearch optionFilterProp="label" placeholder="选择实际参与装箱的工人" value={draft.worker_ids} options={workerOptions} loading={!workersLoaded && !workersError} disabled={!editable || !!busy || !workersLoaded} onChange={workerIds => { if (workerIds.length > MAX_INTAKE_WORKERS) { messageApi.warning(`最多选择 ${MAX_INTAKE_WORKERS} 名操作人员`); return; } editDraft(current => ({ ...current, worker_ids: workerIds })); }} /></label>
                </div>
                <div className={styles.sourceNote}><Text type="secondary">纸面署名：{draft.operator_name || '未填写'}。请选择系统中的实际操作人员，最多 {MAX_INTAKE_WORKERS} 人。</Text></div>
                {workersError && <Alert type="error" message={`人员列表加载失败：${workersError}`} action={<Button onClick={loadWorkers}>重试</Button>} className={styles.inlineAlert} />}
                {!isMobile && !!warnings.length && <section className={styles.warnings} aria-label="识别疑点"><div className={styles.warningHeading}><Text strong>识别疑点</Text><Text>{warnings.length} 项</Text></div><div className={styles.warningScroll} role="region" aria-label="识别疑点列表"><ul>{warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div></section>}
                {record.recognition_status === 'running' && <div className={styles.progressNote}><Spin size="small" /><Text type="secondary">识别中，完成后会自动填入核对表。</Text></div>}
                {record.recognition_status === 'failed' && <Alert type="error" showIcon message="识别失败，可对照原图手动核对或重试" description={record.recognition_error || undefined} className={styles.inlineAlert} />}
                <Table className={styles.boxTable} size="small" rowKey="key" dataSource={draft.boxes.map((box, index) => ({ ...box, key: index }))} columns={boxColumns} pagination={false} scroll={{ x: 510 }} locale={{ emptyText: record.recognition_status === 'running' ? '正在读取装箱内容' : '暂无装箱内容，可添加一箱' }} />
                {editable && <Button className={styles.addBox} type="dashed" icon={<PlusOutlined />} disabled={!!busy} onClick={() => editDraft(current => ({ ...current, boxes: [...current.boxes, emptyBox()] }))}>添加一箱</Button>}
                <footer className={styles.reviewFooter}>
                    <div className={styles.summary}><span><strong>{draft.boxes.length}</strong> 箱</span><span><strong>{totals.count}</strong> 件</span><span><strong>{totals.weight.toFixed(3)}</strong> kg</span></div>
                    {editable && <><Checkbox className={styles.reviewAcknowledgement} checked={reviewed} disabled={conflict || !!busy || record.recognition_status === 'running'} onChange={event => { if (!busyRef.current) setReviewed(event.target.checked); }}>我已对照纸质单核对以上内容，确认无误</Checkbox><div className={styles.actions}><Button disabled={conflict || !!busy} loading={busy === 'draft'} onClick={() => perform('draft')}>保存检查进度</Button>{['idle', 'failed'].includes(record.recognition_status) && <Button disabled={conflict || (touched && dirty) || !!busy} loading={busy === 'recognize'} onClick={() => perform('recognize')}>{record.recognition_status === 'failed' ? '重试识别' : '识别照片'}</Button>}<Button type="primary" icon={<CheckOutlined />} loading={busy === 'confirm'} disabled={conflict || !!busy || !!validationError || !workersLoaded || record.recognition_status === 'running' || !reviewed} onClick={() => perform('confirm')}>核对完成并上传</Button></div>{validationError && <Text type="secondary" className={styles.validation}>上传前需要补全：{validationError}</Text>}</>}
                </footer>
            </Card>
        </div>}
        <Modal title="重新加载纸单" open={reloadOpen} okText="放弃修改并重新加载" cancelText="继续编辑" onCancel={() => setReloadOpen(false)} onOk={() => { setReloadOpen(false); load(); }}>重新加载会丢弃当前未保存的修改。</Modal>
    </div>;
}
