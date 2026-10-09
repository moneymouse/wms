import React, { useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, DatePicker, Empty, Select, Space, Table, Tag, Typography, Upload } from 'antd';
import { DownloadOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import dayjs from 'dayjs';
import { decodeJwtPayload } from '../common/featureTourState';
import { getUserRoles, hasPermission, routePermissions } from '../common/roleConfig';
import { money } from '../common/financeApi';
import { downloadReconciliationTemplate, reconcileBatch, reconciliationRequest, uploadReconciliation } from '../common/supplierReconciliationApi';
import styles from './supplierReconciliation.module.css';

const { Text } = Typography;
const emptyList = { items: [], total: 0 };
const displayValue = value => value === null || value === undefined || value === '' ? '—' : value;
const displayWeight = value => value === null || value === undefined || value === '' ? '—' : `${value} kg`;
const displayInput = (row, field, sourceColumn, formatter = displayValue) => {
    const value = row[field];
    if (value !== null && value !== undefined && String(value).trim() !== '') return formatter(value);
    const raw = row.raw_values?.[sourceColumn];
    return raw !== null && raw !== undefined && String(raw).trim() !== '' ? '无效值：' + String(raw) : '—';
};

export default function SupplierReconciliation({ readOnly = false }) {
    const roles = getUserRoles(decodeJwtPayload(localStorage.getItem('jwt')) || {});
    const canOpenOrders = hasPermission(roles, routePermissions['/orders/:order_id']);
    const canOpenFinance = hasPermission(roles, ['admin', 'finance']);
    const [vendorId, setVendorId] = useState();
    const [selectedVendor, setSelectedVendor] = useState(null);
    const [vendorQuery, setVendorQuery] = useState('');
    const [vendors, setVendors] = useState([]);
    const [vendorsLoading, setVendorsLoading] = useState(false);
    const [vendorsError, setVendorsError] = useState('');
    const [vendorRevision, setVendorRevision] = useState(0);
    const [period, setPeriod] = useState(dayjs().startOf('month'));
    const [file, setFile] = useState(null);
    const [uploading, setUploading] = useState(false);
    const uploadInFlight = useRef(false);
    const [uploadError, setUploadError] = useState('');
    const [uploadNotice, setUploadNotice] = useState('');
    const [downloading, setDownloading] = useState(false);
    const [downloadError, setDownloadError] = useState('');
    const [batches, setBatches] = useState(emptyList);
    const [batchPage, setBatchPage] = useState(1);
    const [listLoading, setListLoading] = useState(false);
    const [listError, setListError] = useState('');
    const [revision, setRevision] = useState(0);
    const [selectedId, setSelectedId] = useState(null);
    const [detail, setDetail] = useState(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailError, setDetailError] = useState('');
    const [reconciling, setReconciling] = useState(false);
    const reconcileInFlight = useRef(false);
    const currentSelectedId = useRef(selectedId);
    currentSelectedId.current = selectedId;
    const [actionError, setActionError] = useState('');
    const [actionNotice, setActionNotice] = useState('');
    const [rowStatus, setRowStatus] = useState('all');
    const [rowPage, setRowPage] = useState(1);

    useEffect(() => {
        if (readOnly) return undefined;
        const controller = new AbortController();
        const timer = setTimeout(() => {
            setVendorsLoading(true); setVendorsError('');
            reconciliationRequest('/vendors', { params: { q: vendorQuery, p: 1, s: 50 }, signal: controller.signal })
                .then(data => { if (!controller.signal.aborted) setVendors(data.items || []); })
                .catch(error => { if (!controller.signal.aborted) { setVendorsError(error.message); setVendors([]); } })
                .finally(() => { if (!controller.signal.aborted) setVendorsLoading(false); });
        }, vendorQuery ? 250 : 0);
        return () => { clearTimeout(timer); controller.abort(); };
    }, [readOnly, vendorQuery, vendorRevision]);

    useEffect(() => {
        const controller = new AbortController();
        setListLoading(true); setListError('');
        reconciliationRequest('/batches', { params: { p: batchPage, s: 10 }, signal: controller.signal })
            .then(data => { if (!controller.signal.aborted) setBatches(data); })
            .catch(error => { if (!controller.signal.aborted) { setListError(error.message); setBatches(emptyList); } })
            .finally(() => { if (!controller.signal.aborted) setListLoading(false); });
        return () => controller.abort();
    }, [batchPage, revision]);

    useEffect(() => {
        if (!selectedId) return undefined;
        const controller = new AbortController();
        setDetailLoading(true); setDetailError('');
        reconciliationRequest(`/batches/${selectedId}`, {
            params: { row_status: rowStatus === 'all' ? undefined : rowStatus, p: rowPage, s: 20 }, signal: controller.signal,
        })
            .then(data => { if (!controller.signal.aborted) setDetail(data); })
            .catch(error => { if (!controller.signal.aborted) { setDetailError(error.message); setDetail(null); } })
            .finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
        return () => controller.abort();
    }, [selectedId, rowStatus, rowPage, revision]);

    const selectBatch = id => {
        setDetail(null); setSelectedId(id); setRowStatus('all'); setRowPage(1); setDetailError(''); setActionError(''); setActionNotice('');
        if (selectedId === id) setRevision(value => value + 1);
    };
    const downloadTemplate = async () => {
        setDownloading(true); setDownloadError('');
        try {
            const blob = await downloadReconciliationTemplate();
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url; link.download = '第三方对账明细模板.xlsx';
            document.body.appendChild(link); link.click(); link.remove();
            URL.revokeObjectURL(url);
        } catch (error) { setDownloadError(error.message); }
        finally { setDownloading(false); }
    };
    const submit = async () => {
        if (uploadInFlight.current || reconcileInFlight.current) return;
        setUploadError(''); setUploadNotice('');
        if (!vendorId || !period || !file) { setUploadError('请选择供应商、账期并上传 Excel 文件'); return; }
        uploadInFlight.current = true; setUploading(true);
        try {
            const result = await uploadReconciliation({ file, vendorId, period: period.format('YYYY-MM') });
            const batch = result.batch;
            selectBatch(batch.id); setDetail(result); setFile(null); setBatchPage(1); setRevision(value => value + 1);
            setUploadNotice(batch.documents?.length ? '对账完成，已生成供应商应付账单草稿，等待财务审核确认。' : '对账完成。本批次没有通过的明细，未生成应付账单草稿。');
        } catch (error) { setUploadError(error.message); }
        finally { uploadInFlight.current = false; setUploading(false); }
    };
    const batch = detail?.batch;
    const summary = batch?.summary || {};
    const vendorOptions = selectedVendor && !vendors.some(vendor => vendor.id === selectedVendor.id) ? [selectedVendor, ...vendors] : vendors;
    const retryExceptions = async () => {
        if (!batch || reconcileInFlight.current || uploadInFlight.current) return;
        reconcileInFlight.current = true; setReconciling(true); setActionError(''); setActionNotice('');
        try {
            const result = await reconcileBatch(batch.id, batch.version);
            if (currentSelectedId.current === batch.id) {
                setDetail(result); setRowStatus('all'); setRowPage(1);
                const newPassed = Number(result.batch.summary.passed_rows) - Number(batch.summary.passed_rows);
                setActionNotice(newPassed > 0 ? `重新核对完成，新增 ${newPassed} 行通过，已生成追加应付草稿。` : '重新核对完成，没有新增通过明细。请查看异常原因。');
            }
            setRevision(value => value + 1);
        } catch (error) { if (currentSelectedId.current === batch.id) setActionError(error.message); }
        finally { reconcileInFlight.current = false; setReconciling(false); }
    };

    return <section className={styles.workspace} aria-label={readOnly ? '第三方对账记录' : '上传对账明细'}>
        {!readOnly && <Card size="small" title="上传第三方对账明细" extra={<Button icon={<DownloadOutlined />} loading={downloading} onClick={downloadTemplate}>下载统一模板</Button>}>
            <p className={styles.help}>请将第三方账单整理到统一模板的「对账明细」工作表。必填：原单号、重量(kg)、最终费用(元)；选填：转单号、费用说明。原单号列也可填写订单号：先匹配包裹原单号，找不到包裹时再匹配订单。包裹级上传重量须不超过系统实重，且最多比实重少 0.5 kg，重量差（上传−实重）允许范围为 -0.5 至 0 kg（含边界）。订单级按未归档包裹总实重核对，上传重量必须小于订单总实重，最多少 5 kg；重量差允许 -5 至 0 kg（不含 0）。订单级费用整体归属订单，转单号仅保留原始账单信息。每次最多上传 5,000 行。</p>
            <div className={styles.uploadFields}>
                <label className={styles.field}><Text>供应商</Text><Select aria-label="对账供应商" showSearch filterOption={false} allowClear disabled={uploading || reconciling} value={vendorId} placeholder="选择供应商" loading={vendorsLoading} onSearch={setVendorQuery}
                    options={vendorOptions.map(vendor => ({ value: vendor.id, label: vendor.name }))}
                    onChange={value => { setVendorId(value); setSelectedVendor(vendorOptions.find(vendor => vendor.id === value) || null); }} notFoundContent={vendorsLoading ? '正在加载供应商…' : '没有可用供应商'} /></label>
                <label className={styles.field}><Text>账期</Text><DatePicker aria-label="对账账期" picker="month" value={period} onChange={setPeriod} disabled={uploading || reconciling} allowClear={false} /></label>
                <div className={`${styles.field} ${styles.fileField}`}><Text>账单文件</Text><Upload aria-label="上传账单文件" accept=".xlsx" maxCount={1} disabled={uploading || reconciling} showUploadList={false} beforeUpload={nextFile => {
                    if (!/\.xlsx$/i.test(nextFile.name)) { setUploadError('请上传 .xlsx 格式的统一对账明细'); return Upload.LIST_IGNORE; }
                    setFile(nextFile); setUploadError(''); setUploadNotice(''); return false;
                }}><Button icon={<UploadOutlined />} disabled={uploading || reconciling}>选择 Excel 文件</Button></Upload>{file && <Space><Text className={styles.fileName}>{file.name}</Text><Button type="link" size="small" disabled={uploading || reconciling} onClick={() => setFile(null)}>移除</Button></Space>}</div>
            </div>
            {vendorsError && <Alert className={styles.notice} type="error" showIcon message={vendorsError} action={<Button size="small" onClick={() => setVendorRevision(value => value + 1)}>重新加载供应商</Button>} />}
            {downloadError && <Alert type="error" showIcon message={downloadError} />}
            <div className={styles.actions}><Button type="primary" icon={<UploadOutlined />} loading={uploading} disabled={reconciling} onClick={submit}>上传并对账</Button><Text type="secondary">通过的费用生成应付草稿；异常明细暂不计入。单号和重量通过不代表供应商价格已经审核。</Text></div>
            {uploadError && <Alert style={{ marginTop: 12 }} type="error" showIcon message={uploadError} />}
            {uploadNotice && <Alert style={{ marginTop: 12 }} type="success" showIcon message={uploadNotice} />}
        </Card>}
        <Card role="region" aria-label="对账历史记录" aria-busy={listLoading} size="small" title="上传记录" extra={<Button icon={<ReloadOutlined />} aria-label="刷新对账记录" onClick={() => setRevision(value => value + 1)}>刷新</Button>}>
            {readOnly && <p className={styles.help}>查看文员上传的对账明细和异常。生成的供应商应付账单保持草稿状态，请核实费用后在「账单」中确认生效。</p>}
            {listError && <Alert className={styles.notice} type="error" showIcon message={listError} action={<Button size="small" onClick={() => setRevision(value => value + 1)}>重试</Button>} />}
            <Table aria-label="对账上传记录" size="small" rowKey="id" loading={listLoading} dataSource={batches.items || []} scroll={{ x: 850 }}
                locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有上传对账明细" /> }} columns={[
                    { title: '批次', dataIndex: 'number', width: 180, render: (value, row) => <Button type="link" onClick={() => selectBatch(row.id)}>{value}</Button> },
                    { title: '供应商', dataIndex: 'vendor_name', width: 140 }, { title: '账期', dataIndex: 'period', width: 90 },
                    { title: '原文件', dataIndex: 'filename', width: 180 },
                    { title: '通过 / 异常', width: 100, render: (_, row) => `${row.summary?.passed_rows || 0} / ${row.summary?.exception_rows || 0}` },
                    { title: '通过费用 / 元', align: 'right', width: 130, render: (_, row) => money(row.summary?.passed_amount) },
                    { title: '上传人', dataIndex: 'created_by_name', width: 110 },
                    { title: '', width: 75, render: (_, row) => <Button type="link" onClick={() => selectBatch(row.id)}>查看</Button> },
                ]} pagination={{ current: batchPage, pageSize: 10, total: batches.total, showSizeChanger: false, onChange: setBatchPage }} />
        </Card>
        {selectedId && <Card role="region" aria-label="批次对账结果" aria-busy={detailLoading} size="small" title={batch ? `${batch.number} · ${batch.vendor_name} · ${batch.period}` : '对账明细'} loading={detailLoading && !detail}>
            {detailError && <Alert type="error" showIcon message={detailError} action={<Button onClick={() => setRevision(value => value + 1)}>重新加载明细</Button>} />}
            {batch && <>
                <div className={styles.summary}>
                    {[['正数费用总额', summary.total_valid_amount, `${summary.total_rows || 0} 行；仅汇总有效的正数金额`], ['通过费用', summary.passed_amount, `${summary.passed_rows || 0} 行进入应付草稿`], ['暂未计入费用', Number(summary.total_valid_amount || 0) - Number(summary.passed_amount || 0), `${summary.exception_rows || 0} 行异常`]].map(([label, amount, note]) => <div key={label} className={styles.summaryItem} role="group" aria-label={label}><span className={styles.summaryLabel}>{label} / 元</span><strong className={styles.summaryValue}>{money(amount)}</strong><span className={styles.summaryNote}>{note}</span></div>)}
                </div>
                <Alert className={styles.notice} type={batch.documents?.length ? 'info' : 'warning'} showIcon message={batch.documents?.length ? `关联供应商应付账单：${batch.documents.map(document => `${document.number}（${document.status === 'draft' ? '草稿' : document.status === 'posted' ? '已生效' : document.status}）`).join('、')}` : '本批次没有可生成应付账单的通过明细'}
                    description="财务确认生效前，草稿不计入应付余额。异常明细不会写入订单成本或应付账单。" action={canOpenFinance && batch.documents?.length ? <Link to="/finance">查看财务账单</Link> : undefined} />
                {actionError && <Alert className={styles.notice} type="error" showIcon message={actionError} />}
                {actionNotice && <Alert className={styles.notice} type="success" showIcon message={actionNotice} />}
                <div className={styles.toolbar}><Space><Select aria-label="对账明细范围" value={rowStatus} style={{ width: 150 }} onChange={value => { setRowStatus(value); setRowPage(1); }} options={[{ value: 'all', label: '全部明细' }, { value: 'exception', label: '仅异常明细' }, { value: 'passed', label: '仅通过明细' }]} /><Text type="secondary">来源：{batch.filename}</Text></Space>{!readOnly && Number(summary.exception_rows) > 0 && <Button loading={reconciling} disabled={uploading || detailLoading} onClick={retryExceptions}>重新核对异常</Button>}</div>
                <Table aria-label="对账明细" size="small" rowKey="id" loading={detailLoading} dataSource={detail.rows?.items || []} scroll={{ x: 1730 }} columns={[
                    { title: 'Excel 行', dataIndex: 'source_row', width: 80 },
                    { title: '原单号 / 订单号', dataIndex: 'original_number', width: 170, render: (_, row) => displayInput(row, 'original_number', '原单号') },
                    { title: '对账层级', dataIndex: 'match_type', width: 100, render: (value, row) => value === 'order' ? <Tag color="blue">订单级</Tag> : value === 'cargo' || row.cargo_uid ? <Tag>包裹级</Tag> : '—' },
                    { title: '上传转单号', dataIndex: 'waybill_number', width: 170, render: (_, row) => displayInput(row, 'waybill_number', '转单号') },
                    { title: '系统转单号', dataIndex: 'system_waybill', width: 170, render: (value, row) => row.match_type === 'order' ? '订单级不按包裹核对' : displayValue(value) },
                    { title: '订单', dataIndex: 'order_number', width: 170, render: (value, row) => row.order_uid && canOpenOrders ? <Link to={`/orders/${encodeURIComponent(row.order_uid)}`}>{value || row.order_uid}</Link> : displayValue(value) },
                    { title: '上传重量', dataIndex: 'weight', width: 110, render: (_, row) => displayInput(row, 'weight', '重量(kg)', displayWeight) },
                    { title: '系统实重', dataIndex: 'system_weight', width: 160, render: (value, row) => row.match_type === 'order' ? `${displayWeight(value)}（订单总重）` : displayWeight(value) },
                    { title: '重量差（上传−实重）', dataIndex: 'weight_difference', width: 170, render: displayWeight },
                    { title: '最终费用 / 元', dataIndex: 'final_fee', align: 'right', width: 120, render: (_, row) => displayInput(row, 'final_fee', '最终费用(元)', money) },
                    { title: '费用说明', dataIndex: 'description', width: 160, render: displayValue },
                    { title: '核对结果', dataIndex: 'status', width: 100, render: value => <Tag color={value === 'passed' ? 'green' : 'red'}>{value === 'passed' ? '通过' : '异常'}</Tag> },
                    { title: '异常原因', dataIndex: 'issues', width: 250, render: issues => issues?.length ? <ul className={styles.issues}>{issues.map((issue, index) => <li key={`${issue.code}-${index}`}>{issue.message}</li>)}</ul> : '—' },
                ]} pagination={{ current: rowPage, pageSize: 20, total: detail.rows?.total || 0, showSizeChanger: false, onChange: setRowPage }} />
            </>}
        </Card>}
    </section>;
}
