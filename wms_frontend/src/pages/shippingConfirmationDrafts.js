import React, { useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Empty, Input, Modal, Popconfirm, Space, Table, Tag, Typography, message } from 'antd';
import { ArrowLeftOutlined, DeleteOutlined, DownOutlined, PlusOutlined, PrinterOutlined, ReloadOutlined, RightOutlined, SaveOutlined } from '@ant-design/icons';
import { useBlocker, useNavigate, useParams } from 'react-router-dom';
import styles from './shippingConfirmationDrafts.module.css';
import { fetchShippingConfirmationPdf, shippingConfirmationRequest } from '../common/shippingConfirmationApi';
import { isCargoOutboundOrLater } from '../common/cargoStatus';

const blankDraft = () => ({ uid: '', title: '', version: null, entries: [] });
const draftPayload = draft => ({
    title: draft.title.trim(),
    entries: draft.entries.map(entry => ({ cargo_uid: entry.cargo_uid, agent_name: entry.agent_name || '', remarks: entry.remarks || '' })),
});
const normalizeDraft = draft => ({ ...blankDraft(), ...draft, entries: draft?.entries || [] });
const packingRowPrefix = 'packing-list:';
const onlyBoxKeys = keys => keys.filter(key => !String(key).startsWith(packingRowPrefix));
const groupPackingBoxes = entries => {
    const groups = new Map();
    entries.forEach(entry => {
        const key = `${packingRowPrefix}${entry.packing_list_uid || `missing:${entry.cargo_uid}`}`;
        if (!groups.has(key)) groups.set(key, {
            row_key: key, isPackingList: true, list_number: entry.list_number || '-',
            customer_name: entry.customer_name || '', children: [],
        });
        groups.get(key).children.push({ ...entry, row_key: entry.cargo_uid });
    });
    return [...groups.values()].map(group => ({ ...group,
        box_number: `${group.children.length} 箱`,
        weight: group.children.reduce((total, entry) => total + (Number(entry.weight) || 0), 0),
        available: group.children.every(entry => entry.available !== false),
    }));
};
const groupFieldText = (group, field, mixedText) => {
    const values = [...new Set(group.children.map(entry => entry[field] || ''))];
    return values.length === 1 ? values[0] || '-' : mixedText;
};
const packingListExpandable = {
    expandIcon: ({ expanded, onExpand, record }) => record.isPackingList ? <Button type="text" size="small"
        aria-label={`${expanded ? '收起' : '展开'}装箱单 ${record.list_number}`}
        icon={expanded ? <DownOutlined /> : <RightOutlined />} onClick={event => onExpand(record, event)} /> : null,
};

export default function ShippingConfirmationDrafts() {
    const { uid } = useParams();
    const navigate = useNavigate();
    const [messageApi, contextHolder] = message.useMessage();
    const [draft, setDraft] = useState(blankDraft);
    const [drafts, setDrafts] = useState([]);
    const [dirty, setDirty] = useState(false);
    const [actionBusy, setBusy] = useState(false);
    const [draftLoading, setDraftLoading] = useState(Boolean(uid));
    const [draftLoadError, setDraftLoadError] = useState('');
    const [draftReloadTick, setDraftReloadTick] = useState(0);
    const [listLoading, setListLoading] = useState(false);
    const [listError, setListError] = useState('');
    const [draftSearch, setDraftSearch] = useState('');
    const busy = actionBusy || draftLoading;
    const [error, setError] = useState('');
    const [conflict, setConflict] = useState(false);
    const [catalog, setCatalog] = useState({ items: [], total: 0 });
    const [catalogLoading, setCatalogLoading] = useState(false);
    const [catalogError, setCatalogError] = useState('');
    const [keyword, setKeyword] = useState('');
    const [query, setQuery] = useState('');
    const [page, setPage] = useState(1);
    const [lookupTick, setLookupTick] = useState(0);
    const [selectedBoxUids, setSelectedBoxUids] = useState([]);
    const [pendingBoxUids, setPendingBoxUids] = useState([]);
    const [addAgent, setAddAgent] = useState('');
    const [addRemarks, setAddRemarks] = useState('');
    const [selectedDraftBoxUids, setSelectedDraftBoxUids] = useState([]);
    const [bulkAgent, setBulkAgent] = useState('');
    const [bulkRemarks, setBulkRemarks] = useState('');
    const requestSequence = useRef(0);
    const addBoxesSequence = useRef(0);
    const routeLoadState = useRef({ reloadTick: 0, failed: false });
    const currentDraft = useRef({ draft, dirty });
    const printLock = useRef(false);
    currentDraft.current = { draft, dirty };

    const blocker = useBlocker(() => currentDraft.current.dirty);

    const setCurrentDraft = (next, isDirty = false) => {
        currentDraft.current = { draft: next, dirty: isDirty };
        setDraft(next);
        setDirty(isDirty);
    };

    const loadDrafts = async () => {
        setListLoading(true);
        setListError('');
        try {
            const result = await shippingConfirmationRequest('/shipping-confirmation-drafts');
            setDrafts(result?.items || []);
        } catch (requestError) {
            setListError(requestError.message);
        } finally { setListLoading(false); }
    };

    useEffect(() => {
        let active = true;
        setListLoading(true);
        shippingConfirmationRequest('/shipping-confirmation-drafts')
            .then(result => { if (active) setDrafts(result?.items || []); })
            .catch(requestError => { if (active) setListError(requestError.message); })
            .finally(() => { if (active) setListLoading(false); });
        return () => { active = false; };
    }, []);

    useEffect(() => {
        const forceReload = routeLoadState.current.failed || routeLoadState.current.reloadTick !== draftReloadTick;
        routeLoadState.current = { reloadTick: draftReloadTick, failed: false };
        let active = true;
        if ((uid || '') === currentDraft.current.draft.uid && !forceReload) {
            setDraftLoading(false);
            return undefined;
        }
        setError('');
        setConflict(false);
        setDraftLoadError('');
        setSelectedDraftBoxUids([]);
        addBoxesSequence.current += 1;
        setPendingBoxUids([]);
        if (!uid) {
            setCurrentDraft(blankDraft());
            setDraftLoading(false);
            return undefined;
        }
        setDraftLoading(true);
        shippingConfirmationRequest(`/shipping-confirmation-drafts/${encodeURIComponent(uid)}`)
            .then(loaded => { if (active) setCurrentDraft(normalizeDraft(loaded)); })
            .catch(requestError => {
                if (active) {
                    routeLoadState.current.failed = true;
                    setDraftLoadError(requestError.message);
                }
            })
            .finally(() => { if (active) setDraftLoading(false); });
        return () => { active = false; };
    }, [uid, draftReloadTick]);

    useEffect(() => {
        const handler = event => {
            if (!currentDraft.current.dirty) return;
            event.preventDefault();
            event.returnValue = '';
        };
        window.addEventListener('beforeunload', handler);
        return () => {
            window.removeEventListener('beforeunload', handler);
            addBoxesSequence.current += 1;
        };
    }, []);

    useEffect(() => {
        const sequence = ++requestSequence.current;
        const controller = new AbortController();
        setCatalogLoading(true);
        setCatalogError('');
        const params = new URLSearchParams({ p: String(page), s: '10', ...(query ? { q: query } : {}) });
        shippingConfirmationRequest(`/packing-lists?${params}`, { signal: controller.signal }).then(result => {
            if (requestSequence.current === sequence) setCatalog({ items: result?.items || [], total: Number(result?.total || 0) });
        }).catch(requestError => {
            if (requestSequence.current === sequence && requestError.name !== 'AbortError') {
                setCatalog({ items: [], total: 0 });
                setCatalogError(requestError.message);
            }
        }).finally(() => { if (requestSequence.current === sequence) setCatalogLoading(false); });
        return () => { requestSequence.current += 1; controller.abort(); };
    }, [page, query, lookupTick]);

    const editDraft = updater => {
        setCurrentDraft(updater(currentDraft.current.draft), true);
        setError('');
    };

    const saveDraft = async ({ updateUrl = true } = {}) => {
        const { draft: current, dirty: hasChanges } = currentDraft.current;
        if (current.uid && !hasChanges) return current;
        const saved = await shippingConfirmationRequest(current.uid
            ? `/shipping-confirmation-drafts/${encodeURIComponent(current.uid)}` : '/shipping-confirmation-drafts', {
            method: current.uid ? 'PUT' : 'POST',
            body: { ...draftPayload(current), ...(current.uid ? { expected_version: current.version } : {}) },
        });
        const normalized = normalizeDraft(saved);
        setCurrentDraft(normalized);
        setConflict(false);
        setDrafts(previous => [{ ...normalized, box_count: normalized.entries.length }, ...previous.filter(item => item.uid !== normalized.uid)]);
        if (updateUrl && uid !== normalized.uid) navigate(`/shipping-confirmation-drafts/${encodeURIComponent(normalized.uid)}`, { replace: true });
        return normalized;
    };

    const runAction = async action => {
        setBusy(true);
        setError('');
        try { await action(); }
        catch (requestError) {
            setConflict(requestError.status === 409);
            setError(requestError.status === 409
                ? `${requestError.message}。当前填写内容已保留，可另存为新草稿后核对最新版本。`
                : requestError.message || '操作失败，请重试');
        } finally { setBusy(false); }
    };

    const handleSwitchDraft = selectedUid => runAction(async () => {
        if (selectedUid === currentDraft.current.draft.uid && selectedUid === uid && !draftLoadError) return;
        if (currentDraft.current.dirty) await saveDraft({ updateUrl: false });
        if (selectedUid === uid) setDraftReloadTick(value => value + 1);
        else navigate(`/shipping-confirmation-drafts/${encodeURIComponent(selectedUid)}`);
    });

    const handleNewDraft = () => runAction(async () => {
        if (currentDraft.current.dirty) await saveDraft({ updateUrl: false });
        setCurrentDraft(blankDraft());
        setError(''); setConflict(false); setDraftLoadError(''); setSelectedDraftBoxUids([]);
        navigate('/shipping-confirmation-drafts');
    });

    const handleDeleteDraft = () => runAction(async () => {
        await shippingConfirmationRequest(`/shipping-confirmation-drafts/${encodeURIComponent(draft.uid)}`, {
            method: 'DELETE', body: { expected_version: draft.version },
        });
        setCurrentDraft(blankDraft());
        setConflict(false); setSelectedDraftBoxUids([]);
        navigate('/shipping-confirmation-drafts', { replace: true });
        await loadDrafts();
        messageApi.success('出货单草稿已删除');
    });

    const handleSaveAndLeave = () => runAction(async () => {
        await saveDraft({ updateUrl: false });
        blocker.proceed?.();
    });

    const handleAddBoxes = () => {
        setPendingBoxUids([...selectedBoxUids]);
        setAddAgent('');
        setAddRemarks('');
        setError('');
    };

    const handleConfirmAddBoxes = () => {
        if (busy || !pendingBoxUids.length) return;
        return runAction(async () => {
            const sequence = ++addBoxesSequence.current;
            const current = currentDraft.current.draft;
            const existing = new Set(current.entries.map(entry => entry.cargo_uid));
            const newBoxUids = pendingBoxUids.filter(uid => !existing.has(uid));
            if (current.entries.length + newBoxUids.length > 500) throw new Error('每份出货单草稿最多可添加 500 个箱子');
            if (!newBoxUids.length) {
                setSelectedBoxUids([]);
                setPendingBoxUids([]);
                messageApi.info('所选箱子均已加入草稿');
                return;
            }
            let result;
            try {
                result = await shippingConfirmationRequest('/packing-lists/shipping-confirmation/boxes', {
                    method: 'POST', body: { cargo_uids: newBoxUids },
                });
            } catch (requestError) {
                if (sequence !== addBoxesSequence.current) return;
                throw requestError;
            }
            if (sequence !== addBoxesSequence.current) return;
            const latestExisting = new Set(currentDraft.current.draft.entries.map(entry => entry.cargo_uid));
            const additions = (result?.items || []).filter(entry => !latestExisting.has(entry.cargo_uid)).map(entry => ({ ...entry,
                ...(addAgent.trim() ? { agent_name: addAgent.trim() } : {}),
                ...(addRemarks.trim() ? { remarks: addRemarks.trim() } : {}),
            }));
            if (currentDraft.current.draft.entries.length + additions.length > 500) throw new Error('每份出货单草稿最多可添加 500 个箱子');
            if (additions.length) editDraft(previous => ({ ...previous, entries: [...previous.entries, ...additions] }));
            setSelectedBoxUids([]);
            setPendingBoxUids([]);
            messageApi.success(`已添加 ${additions.length} 个箱子到出货单草稿`);
        });
    };

    const updateEntry = (uid, field, value) => editDraft(previous => ({ ...previous,
        entries: previous.entries.map(entry => entry.cargo_uid === uid ? { ...entry, [field]: value } : entry),
    }));
    const applyBulk = field => {
        const targets = new Set(selectedDraftBoxUids);
        editDraft(previous => ({ ...previous, entries: previous.entries.map(entry => !targets.size || targets.has(entry.cargo_uid)
            ? { ...entry, [field]: field === 'agent_name' ? bulkAgent : bulkRemarks } : entry) }));
    };

    const handlePrint = () => {
        if (busy || printLock.current || draftLoadError || !printable) return;
        const cargoUids = [...selectedDraftBoxUids];
        const preview = window.open('', '_blank');
        if (!preview) { setError('浏览器拦截了新窗口，请允许弹窗后重试'); return; }
        printLock.current = true;
        preview.document.write('正在生成出货确认单 PDF...');
        runAction(async () => {
            try {
                const saved = await saveDraft();
                const targets = cargoUids.length ? cargoUids.map(cargoUid => saved.entries.find(entry => entry.cargo_uid === cargoUid)) : saved.entries;
                if (!targets.length || targets.some(entry => !entry || entry.available === false)) {
                    throw new Error('打印范围包含已删除、归档或不再可访问的箱子，请核对草稿后重试');
                }
                const blob = await (cargoUids.length
                    ? fetchShippingConfirmationPdf(saved.uid, saved.version, cargoUids)
                    : fetchShippingConfirmationPdf(saved.uid, saved.version));
                const url = URL.createObjectURL(blob);
                preview.location.href = url;
                window.setTimeout(() => URL.revokeObjectURL(url), 60 * 1000);
                messageApi.success('出货确认单 PDF 已打开，草稿已保存');
            } catch (requestError) { preview.close(); throw requestError; }
            finally { printLock.current = false; }
        });
    };

    const existingBoxUids = new Set(draft.entries.map(entry => entry.cargo_uid));
    const catalogBoxes = catalog.items.flatMap(list => (list.boxes || []).filter(box => !isCargoOutboundOrLater(box)).map(box => ({
        ...box, cargo_uid: box.uid, packing_list_uid: list.uid,
        list_number: list.list_number || list.mark || '-', customer_name: list.customer_name || '',
    })));
    const draftRows = groupPackingBoxes(draft.entries);
    const catalogRows = groupPackingBoxes(catalogBoxes);
    const unavailable = draft.entries.some(entry => entry.available === false);
    const printTargets = selectedDraftBoxUids.length ? selectedDraftBoxUids.map(cargoUid => draft.entries.find(entry => entry.cargo_uid === cargoUid)) : draft.entries;
    const printable = printTargets.length > 0 && printTargets.every(entry => entry && entry.available !== false);
    const totalWeight = draft.entries.reduce((total, entry) => total + (Number(entry.weight) || 0), 0);
    const identityColumns = [
        { title: '装箱单', dataIndex: 'list_number', width: 180, render: (text, entry) => entry.isPackingList ? <Typography.Text strong>{text}</Typography.Text> : null },
        { title: '客户', dataIndex: 'customer_name', width: 120, render: (text, entry) => entry.isPackingList ? text : null },
        { title: '箱号', dataIndex: 'box_number', width: 70 },
        { title: '唛头', dataIndex: 'tag', width: 160 },
        { title: '原单号', dataIndex: 'transfer_id', width: 160 },
    ];

    const visibleDrafts = drafts.filter(item => !draftSearch.trim() || (item.title || '未命名出货单').toLowerCase().includes(draftSearch.trim().toLowerCase()));

    return <div className={styles.page}>
        {contextHolder}
        <div className={styles.header}>
            <div>
                <Button aria-label="返回装箱单列表" type="link" icon={<ArrowLeftOutlined />} disabled={busy} className={styles.backButton} onClick={() => navigate('/packing-lists')}>返回装箱单列表</Button>
                <Typography.Title level={2}>出货确认单草稿</Typography.Title>
                <Typography.Text type="secondary">分次添加不同装箱单的箱子，填写渠道代理和地址、邮编等备注，准备好后打印出货确认单。</Typography.Text>
            </div>
            <Space wrap>
                <Button icon={<PlusOutlined />} disabled={busy} onClick={handleNewDraft}>新建出货单</Button>
                <Button icon={<SaveOutlined />} loading={actionBusy} disabled={draftLoading || Boolean(draftLoadError)} onClick={() => runAction(async () => {
                    await saveDraft(); messageApi.success('出货单草稿已保存，可稍后继续添加箱子');
                })}>保存草稿</Button>
                <Button type="primary" icon={<PrinterOutlined />} disabled={busy || Boolean(draftLoadError) || !printable} onClick={handlePrint}>保存并打印 PDF</Button>
            </Space>
        </div>
        {error && <Alert className={styles.pageAlert} type="error" showIcon message={error} action={conflict && <Button disabled={busy} onClick={() => runAction(async () => {
            const saved = normalizeDraft(await shippingConfirmationRequest('/shipping-confirmation-drafts', {
                method: 'POST', body: draftPayload({ ...draft, title: `${(draft.title || '出货单').slice(0, 125)} 副本` }),
            }));
            setCurrentDraft(saved); setConflict(false);
            setDrafts(previous => [{ ...saved, box_count: saved.entries.length }, ...previous.filter(item => item.uid !== saved.uid)]);
            navigate(`/shipping-confirmation-drafts/${encodeURIComponent(saved.uid)}`, { replace: true });
            messageApi.success('当前填写内容已另存为新草稿');
        })}>另存为新草稿</Button>} />}
        <div className={styles.workspace}>
            <Card className={styles.draftList} title="已保存的草稿" extra={<Button aria-label="刷新出货单草稿" icon={<ReloadOutlined />} loading={listLoading} disabled={busy} onClick={loadDrafts} />}>
                <Input.Search aria-label="搜索出货单草稿" placeholder="搜索草稿名称" allowClear value={draftSearch} onChange={event => setDraftSearch(event.target.value)} />
                {listError && <Alert className={styles.listAlert} type="error" showIcon message={listError} action={<Button size="small" onClick={loadDrafts}>重试</Button>} />}
                <div className={styles.draftItems}>
                    {visibleDrafts.map(item => <button key={item.uid} type="button" className={`${styles.draftItem} ${draft.uid === item.uid ? styles.activeDraft : ''}`}
                        aria-pressed={draft.uid === item.uid} disabled={busy} onClick={() => handleSwitchDraft(item.uid)}>
                        <span className={styles.draftTitle}>{item.title || '未命名出货单'}</span>
                        <span className={styles.draftMeta}>{item.box_count ?? item.entries?.length ?? 0} 箱</span>
                    </button>)}
                    {!listLoading && !visibleDrafts.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={draftSearch ? '没有匹配的草稿' : '还没有保存的草稿'} />}
                </div>
            </Card>
            <div className={styles.editor}>
                {draftLoadError ? <Card><Alert type="error" showIcon message={draftLoadError} action={<Button onClick={() => setDraftReloadTick(value => value + 1)}>重新加载草稿</Button>} /></Card> : <>
                <Card title="出货单内容" loading={draftLoading} extra={draft.uid && <Popconfirm title="删除这份出货单草稿？" onConfirm={handleDeleteDraft} okText="删除" cancelText="取消" disabled={busy}>
                    <Button danger icon={<DeleteOutlined />} disabled={busy}>删除草稿</Button>
                </Popconfirm>}>
                    <Space direction="vertical" size={16} className={styles.section}>
                        <Input aria-label="出货单草稿名称" placeholder="草稿名称，例如：10 月 6 日下午出货" maxLength={128} disabled={busy}
                            value={draft.title} onChange={event => editDraft(previous => ({ ...previous, title: event.target.value }))} />
                        <Space wrap>
                            <Typography.Text strong>出货单草稿：{draft.entries.length} 箱，共 {totalWeight.toFixed(2)} kg</Typography.Text>
                            <Tag color={dirty ? 'gold' : 'green'}>{dirty ? '有未保存修改' : draft.uid ? '已保存' : '新草稿'}</Tag>
                        </Space>
                        <Typography.Text aria-label="当前打印范围" type="secondary">{selectedDraftBoxUids.length ? `打印范围：所选 ${selectedDraftBoxUids.length} 箱` : `打印范围：草稿全部 ${draft.entries.length} 箱（未勾选）`}</Typography.Text>
                        {unavailable && <Alert type="warning" showIcon message="部分箱子已删除、归档或不再可访问。可勾选有效箱子打印；保存修改前仍需移除失效箱子。" />}
                        <Space wrap>
                            <Input aria-label="批量渠道代理" placeholder="渠道代理，如 JF / TC / YX" value={bulkAgent} maxLength={128} disabled={busy} style={{ width: 210 }} onChange={event => setBulkAgent(event.target.value)} />
                            <Button disabled={busy || !draft.entries.length} onClick={() => applyBulk('agent_name')}>批量填写代理</Button>
                            <Input aria-label="批量出货备注" placeholder="地址、邮编等出货备注" value={bulkRemarks} maxLength={2000} disabled={busy} style={{ width: 250 }} onChange={event => setBulkRemarks(event.target.value)} />
                            <Button disabled={busy || !draft.entries.length} onClick={() => applyBulk('remarks')}>批量填写备注</Button>
                            <Typography.Text type="secondary">{selectedDraftBoxUids.length ? `应用至所选 ${selectedDraftBoxUids.length} 箱` : '未勾选时应用至草稿全部箱子'}</Typography.Text>
                        </Space>
                        <Table aria-label="出货单草稿箱子" size="small" rowKey="row_key" dataSource={draftRows} expandable={packingListExpandable}
                            pagination={{ pageSize: 20, hideOnSinglePage: true, showSizeChanger: false }} scroll={{ x: 1180 }}
                            locale={{ emptyText: '从下方选择箱子，加入出货单草稿' }} rowSelection={{ selectedRowKeys: selectedDraftBoxUids, checkStrictly: false,
                                onChange: keys => setSelectedDraftBoxUids(onlyBoxKeys(keys)), getCheckboxProps: () => ({ disabled: busy }) }}
                            columns={[...identityColumns,
                                { title: '渠道代理', key: 'agent_name', width: 140, render: (_, entry) => entry.isPackingList
                                    ? groupFieldText(entry, 'agent_name', '多种代理')
                                    : <Input aria-label={`箱子 ${entry.cargo_uid} 渠道代理`} value={entry.agent_name || ''} maxLength={128} disabled={busy} onChange={event => updateEntry(entry.cargo_uid, 'agent_name', event.target.value)} /> },
                                { title: '备注（地址、邮编等）', key: 'remarks', width: 250, render: (_, entry) => entry.isPackingList
                                    ? <span className={styles.groupRemarks} title={groupFieldText(entry, 'remarks', '多条备注')}>{groupFieldText(entry, 'remarks', '多条备注')}</span>
                                    : <Input.TextArea aria-label={`箱子 ${entry.cargo_uid} 出货备注`} value={entry.remarks || ''} maxLength={2000} autoSize={{ minRows: 1, maxRows: 3 }} disabled={busy} onChange={event => updateEntry(entry.cargo_uid, 'remarks', event.target.value)} /> },
                                { title: '操作', key: 'action', width: 100, render: (_, entry) => <Space direction="vertical" size={0}>
                                    {entry.available === false && <Tag color="red">{entry.isPackingList ? '含失效箱子' : '已失效'}</Tag>}
                                    {!entry.isPackingList && <Button type="link" danger disabled={busy} aria-label={`移除箱子 ${entry.cargo_uid}`} onClick={() => {
                                        editDraft(previous => ({ ...previous, entries: previous.entries.filter(item => item.cargo_uid !== entry.cargo_uid) }));
                                        setSelectedDraftBoxUids(previous => previous.filter(uid => uid !== entry.cargo_uid));
                                    }}>移除</Button>}
                                </Space> },
                            ]} />
                    </Space>
                </Card>
                <Card title="添加装箱单箱子">
                    <Space direction="vertical" size={16} className={styles.section}>
                        <Space wrap>
                            <Input.Search aria-label="搜索出货装箱单" placeholder="搜索唛头或客户名" allowClear value={keyword} enterButton="搜索" disabled={busy}
                                style={{ width: 330, maxWidth: '100%' }} onChange={event => { setKeyword(event.target.value); if (!event.target.value) { setQuery(''); setPage(1); } }}
                                onSearch={value => { setQuery(value.trim()); setPage(1); }} />
                            <Button icon={<PlusOutlined />} type="primary" disabled={busy || !selectedBoxUids.length} onClick={handleAddBoxes}>添加所选箱子（{selectedBoxUids.length}）</Button>
                            {selectedBoxUids.length > 0 && <Button disabled={busy} onClick={() => setSelectedBoxUids([])}>清空待添加选择</Button>}
                        </Space>
                        <Typography.Text type="secondary">勾选装箱单可选择其中全部可添加箱子，展开后可逐箱选择。搜索和翻页会保留选择；已加入的箱子不能重复添加。</Typography.Text>
                        {catalogError && <Alert type="error" message={catalogError} action={<Button size="small" onClick={() => setLookupTick(value => value + 1)}>重试</Button>} />}
                        <Table aria-label="可添加的装箱单箱子" size="small" rowKey="row_key" expandable={packingListExpandable} columns={[...identityColumns,
                            { title: '重量 (kg)', dataIndex: 'weight', width: 100, render: weight => (Number(weight) || 0).toFixed(2) },
                            { title: '订单分配', key: 'assigned', width: 130, render: (_, entry) => entry.isPackingList
                                ? <Typography.Text type="secondary">已加入 {entry.children.filter(box => existingBoxUids.has(box.cargo_uid)).length} / {entry.children.length} 箱</Typography.Text>
                                : existingBoxUids.has(entry.cargo_uid) ? <Tag>已加入</Tag> : <Tag color={entry.target_order_uid ? 'blue' : 'gold'}>{entry.target_order_uid ? '已分配' : '待分配'}</Tag> },
                        ]} dataSource={catalogRows} loading={catalogLoading} scroll={{ x: 910 }}
                            locale={{ emptyText: catalogError ? '装箱单加载失败' : '没有匹配的箱子' }}
                            rowSelection={{ selectedRowKeys: selectedBoxUids, preserveSelectedRowKeys: true, checkStrictly: false,
                                onChange: keys => setSelectedBoxUids(onlyBoxKeys(keys)),
                                getCheckboxProps: entry => ({ disabled: busy || catalogLoading || Boolean(catalogError) || (entry.isPackingList
                                    ? entry.children.every(box => existingBoxUids.has(box.cargo_uid)) : existingBoxUids.has(entry.cargo_uid)) }) }}
                            pagination={false} />
                        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                            <Space>
                                <Typography.Text type="secondary">共 {catalog.total} 个装箱单</Typography.Text>
                                <Button disabled={busy || catalogLoading || page <= 1} onClick={() => setPage(value => value - 1)}>上一页装箱单</Button>
                                <Typography.Text>第 {page} 页</Typography.Text>
                                <Button disabled={busy || catalogLoading || page * 10 >= catalog.total} onClick={() => setPage(value => value + 1)}>下一页装箱单</Button>
                            </Space>
                        </div>
                    </Space>
                </Card>
                </>}
            </div>
        </div>
        <Modal title="添加所选箱子" open={pendingBoxUids.length > 0} closable={!busy} keyboard={!busy} maskClosable={false}
            onCancel={() => { if (!busy) setPendingBoxUids([]); }} footer={<Space>
                <Button disabled={busy} onClick={() => setPendingBoxUids([])}>取消</Button>
                <Button type="primary" loading={actionBusy} disabled={draftLoading} onClick={handleConfirmAddBoxes}>确认添加</Button>
            </Space>}>
            <Space direction="vertical" size={16} className={styles.section}>
                <Typography.Text>本次添加 {pendingBoxUids.length} 个箱子。代理和备注均为选填，填写后应用至本次新增箱子；代理留空时沿用默认代理。</Typography.Text>
                <label className={styles.addField}>渠道代理（选填）
                    <Input aria-label="添加箱子渠道代理" placeholder="如 JF / TC / YX" value={addAgent} maxLength={128} disabled={busy} onChange={event => setAddAgent(event.target.value)} />
                </label>
                <label className={styles.addField}>备注（选填）
                    <Input.TextArea aria-label="添加箱子出货备注" placeholder="地址、邮编等出货备注" value={addRemarks} maxLength={2000} autoSize={{ minRows: 3, maxRows: 6 }} disabled={busy} onChange={event => setAddRemarks(event.target.value)} />
                </label>
                {error && <Alert type="error" showIcon message={error} />}
            </Space>
        </Modal>
        <Modal title="有未保存的出货单内容" open={blocker.state === 'blocked'} closable={!busy} keyboard={!busy} maskClosable={false} onCancel={() => { if (!busy) blocker.reset?.(); }}
            footer={<Space wrap>
                <Button disabled={busy} onClick={() => blocker.reset?.()}>继续编辑</Button>
                <Button danger disabled={busy} onClick={() => {
                    setCurrentDraft(currentDraft.current.draft);
                    blocker.proceed?.();
                }}>放弃修改并离开</Button>
                <Button type="primary" loading={actionBusy} onClick={handleSaveAndLeave}>保存并离开</Button>
            </Space>}>
            <Typography.Paragraph>保存后可以继续补箱。离开前请选择保存，或放弃本次修改。</Typography.Paragraph>
            {error && <Alert type="error" showIcon message={error} />}
        </Modal>
    </div>;
}
