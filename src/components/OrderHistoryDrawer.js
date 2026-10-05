import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
    Alert,
    Button,
    Descriptions,
    Drawer,
    Empty,
    Input,
    List,
    Pagination,
    Space,
    Spin,
    Table,
    Tag,
    Typography,
    message,
} from 'antd';
import { ArrowLeftOutlined, HistoryOutlined, SearchOutlined } from '@ant-design/icons';

import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import { ROLE_LABEL_MAP } from '../common/roleConfig';
import styles from './OrderHistoryDrawer.module.css';

const { Text, Title } = Typography;

const ENTITY_LABELS = { order: '订单', cargo: '普通货物', box: '箱子' };
const OPERATION_LABELS = { create: '新增', update: '修改', delete: '删除/解绑' };
const ACTION_LABELS = {
    baseline_import: '基线导入',
    order_created: '创建订单',
    order_updated: '修改订单',
    order_transportation_updated: '更新订单运输方式',
    order_deleted: '删除订单',
    order_archived: '归档订单',
    order_unlocked: '开启修订',
    order_relocked: '完成修订',
    salesman_updated: '修改业务员',
    customer_updated: '修改客户归属',
    customer_removed: '移除客户归属',
    cargo_added: '新增货物',
    cargo_updated: '修改货物',
    cargo_unbound: '解绑货物',
    cargo_archived: '归档货物',
    cargo_deleted: '删除货物',
    cargos_archived: '批量归档货物/箱子',
    cargos_deleted: '批量删除货物/箱子',
    cargos_unbound: '批量解绑货物/箱子',
    box_assigned: '分配箱子',
    boxes_assigned: '批量分配箱子',
    box_updated: '修改箱子',
    box_unassigned: '解绑箱子',
    box_archived: '归档箱子',
    box_deleted: '删除箱子',
    box_workers_updated: '修改箱子操作员',
    box_mark_updated: '修改箱子唛头',
    box_shipment_undone: '撤销箱子出库',
    waybills_imported: '批量更新转单号',
    packing_list_deleted: '删除装箱单',
    operator_removed: '删除用户并清理关联',
};

const FIELD_LABELS = {
    uid: 'UID',
    order_id: '订单号',
    customer_name: '客户',
    customers: '客户归属',
    salesman: '业务员',
    transportation: '运输方式',
    receiver: '收货人',
    receiver_phone: '收货人电话',
    mail: '邮箱',
    country: '国家',
    province: '州/省',
    city: '城市',
    address: '地址',
    zip_code: '邮编',
    en_name: '报关品名',
    cn_name: '中文品名',
    post_code: '海关编码',
    tag_all: '订单唛头',
    mark: '箱子唛头',
    origin_id: '包裹识别码',
    transfer_id: '原单号',
    waybill_id: '转单号（运单号）',
    tag: '唛头',
    real_en_name: '英文品名',
    item_name: '品名',
    item_details: '箱内明细',
    count: '件数',
    piece_count: '件数',
    weight: '重量',
    total_weight: '总重量',
    price: '价格',
    status: '状态',
    date: '出库日期',
    archive: '归档状态',
    workers: '操作员',
    remark: '备注',
    box_number: '箱号',
    revision_status: '修订状态',
    revision_reason: '修订原因',
};

const jsonEqual = (a, b) => JSON.stringify(a) === JSON.stringify(b);

function displayValue(value) {
    if (value === null || value === undefined || value === '') return '-';
    if (typeof value === 'boolean') return value ? '是' : '否';
    if (Array.isArray(value)) {
        if (value.length === 0) return '-';
        return value.map(item => {
            if (item && typeof item === 'object') {
                return item.name || item.worker_name || item.item_name || JSON.stringify(item);
            }
            return String(item);
        }).join('、');
    }
    if (typeof value === 'object') {
        return value.name || value.worker_name || JSON.stringify(value, null, 2);
    }
    return String(value);
}

function ItemDetailsTable({ value }) {
    const rows = Array.isArray(value) ? value : [];
    if (rows.length === 0) return <Text type="secondary">无</Text>;
    return (
        <Table
            size="small"
            pagination={false}
            rowKey="__rowKey"
            dataSource={rows.map((row, index) => ({ ...row, __rowKey: index }))}
            columns={[
                { title: '品名', dataIndex: 'item_name', key: 'item_name' },
                { title: '海关编码', dataIndex: 'customs_code', key: 'customs_code', render: displayValue },
                { title: '件数', dataIndex: 'piece_count', key: 'piece_count', width: 80, render: displayValue },
            ]}
        />
    );
}

function ChangeValue({ field, value }) {
    if (field === 'item_details') return <ItemDetailsTable value={value} />;
    const rendered = displayValue(value);
    return (
        <Text style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {rendered}
        </Text>
    );
}

function VersionChanges({ changes }) {
    if (!Array.isArray(changes) || changes.length === 0) {
        return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本版本没有字段差异" />;
    }
    return (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            {changes.map((change, index) => {
                const before = change.before_data || {};
                const after = change.after_data || {};
                const fields = Array.from(new Set([
                    ...(change.fields || []),
                    ...Object.keys(before),
                    ...Object.keys(after),
                ]));
                return (
                    <div key={`${change.sequence_no || index}-${change.entity_type}-${change.entity_uid}`} style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: 12 }}>
                        <Space wrap style={{ marginBottom: 10 }}>
                            <Tag color="blue">{ENTITY_LABELS[change.entity_type] || change.entity_type}</Tag>
                            <Tag>{OPERATION_LABELS[change.operation] || change.operation}</Tag>
                            <Text type="secondary">{change.entity_uid}</Text>
                        </Space>
                        {fields.map(field => (
                            <div key={field} style={{ marginTop: 8 }}>
                                <Text strong>{FIELD_LABELS[field] || field}</Text>
                                {field === 'item_details' ? (
                                    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 12, marginTop: 6 }}>
                                        <div><Text type="secondary">旧值</Text><ChangeValue field={field} value={before[field]} /></div>
                                        <div><Text type="secondary">新值</Text><ChangeValue field={field} value={after[field]} /></div>
                                    </div>
                                ) : (
                                    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginTop: 4 }}>
                                        <div style={{ flex: 1, minWidth: 0 }}><ChangeValue field={field} value={before[field]} /></div>
                                        <Text type="secondary">→</Text>
                                        <div style={{ flex: 1, minWidth: 0 }}><ChangeValue field={field} value={after[field]} /></div>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                );
            })}
        </Space>
    );
}

function SnapshotEntityTable({ title, rows }) {
    const data = Array.isArray(rows) ? rows : [];
    return (
        <div style={{ marginTop: 18 }}>
            <Title level={5}>{title}（{data.length}）</Title>
            <Table
                size="small"
                rowKey={row => row.uid || JSON.stringify(row)}
                dataSource={data}
                pagination={false}
                scroll={{ x: 900 }}
                expandable={{
                    rowExpandable: row => Array.isArray(row.item_details) && row.item_details.length > 0,
                    expandedRowRender: row => <ItemDetailsTable value={row.item_details} />,
                }}
                columns={[
                    { title: 'UID', dataIndex: 'uid', key: 'uid', width: 150, ellipsis: true },
                    { title: '原单号', dataIndex: 'transfer_id', key: 'transfer_id', width: 150, render: displayValue },
                    { title: '转单号（运单号）', dataIndex: 'waybill_id', key: 'waybill_id', width: 180, render: displayValue },
                    { title: '品名', key: 'name', width: 150, render: (_, row) => displayValue(row.item_name || row.real_en_name) },
                    { title: '件数', key: 'count', width: 80, render: (_, row) => displayValue(row.piece_count ?? row.count) },
                    { title: '重量', dataIndex: 'weight', key: 'weight', width: 90, render: value => value === null || value === undefined ? '-' : `${value} kg` },
                    { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: displayValue },
                    { title: '操作员', dataIndex: 'workers', key: 'workers', width: 150, render: displayValue },
                ]}
            />
        </div>
    );
}

function VersionSnapshot({ detail }) {
    const rawSnapshot = detail?.snapshot;
    const snapshot = rawSnapshot?.order ? rawSnapshot : detail?.last_existing_snapshot || rawSnapshot;
    if (!snapshot?.order) {
        return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该版本没有可展示的订单快照" />;
    }
    const orderEntries = Object.entries(snapshot.order).filter(([field]) => field !== 'uid');
    return (
        <div>
            {rawSnapshot?.deleted && (
                <Alert type="warning" showIcon message="该版本订单已删除，以下展示删除前最后一份完整快照" style={{ marginBottom: 12 }} />
            )}
            <Descriptions bordered size="small" column={{ xs: 1, sm: 1, md: 2 }}>
                <Descriptions.Item label="订单 UID" span={2}>{snapshot.order.uid || detail?.order_uid || '-'}</Descriptions.Item>
                {orderEntries.map(([field, value]) => (
                    <Descriptions.Item key={field} label={FIELD_LABELS[field] || field}>
                        <ChangeValue field={field} value={value} />
                    </Descriptions.Item>
                ))}
            </Descriptions>
            <SnapshotEntityTable title="普通货物" rows={snapshot.cargos} />
            <SnapshotEntityTable title="箱子" rows={snapshot.boxes} />
        </div>
    );
}

async function fetchJson(url) {
    const response = await fetch(url, { headers: getSafeHeader() });
    let payload = {};
    try {
        payload = await response.json();
    } catch (_) {
        throw new Error('服务器返回格式错误');
    }
    if (!response.ok || payload.code !== 200) {
        throw new Error(payload.msg || payload.message || '请求失败');
    }
    return payload.data;
}

export default function OrderHistoryDrawer({
    open,
    onClose,
    orderUid,
    orderId,
    customerName,
    deletedMode = false,
    refreshKey = 0,
}) {
    const [messageApi, contextHolder] = message.useMessage();
    const [selectedDeletedOrder, setSelectedDeletedOrder] = useState(null);
    const activeUid = orderUid || selectedDeletedOrder?.order_uid;
    const [versions, setVersions] = useState([]);
    const [versionPage, setVersionPage] = useState(1);
    const [versionPageSize] = useState(10);
    const [versionTotal, setVersionTotal] = useState(0);
    const [versionsLoading, setVersionsLoading] = useState(false);
    const [selectedVersion, setSelectedVersion] = useState(null);
    const [selectedVersionNo, setSelectedVersionNo] = useState(null);
    const [detailMode, setDetailMode] = useState('changes');
    const [detailLoading, setDetailLoading] = useState(false);
    const detailPaneRef = useRef(null);
    const [deletedOrders, setDeletedOrders] = useState([]);
    const [deletedPage, setDeletedPage] = useState(1);
    const [deletedPageSize] = useState(10);
    const [deletedTotal, setDeletedTotal] = useState(0);
    const [deletedLoading, setDeletedLoading] = useState(false);
    const [deletedQuery, setDeletedQuery] = useState('');
    const [submittedDeletedQuery, setSubmittedDeletedQuery] = useState('');

    const activeOrderId = orderId || selectedDeletedOrder?.order_id;
    const activeCustomerName = customerName || selectedDeletedOrder?.customer_name;

    useEffect(() => {
        if (!open) {
            setSelectedVersion(null);
            setSelectedVersionNo(null);
            setDetailMode('changes');
            if (deletedMode) setSelectedDeletedOrder(null);
        }
    }, [deletedMode, open]);

    useEffect(() => {
        if (!selectedVersion || !detailPaneRef.current) return;
        detailPaneRef.current.scrollTop = 0;
        detailPaneRef.current.focus({ preventScroll: true });
    }, [detailMode, selectedVersion]);

    useEffect(() => {
        if (!open || !deletedMode || selectedDeletedOrder) return undefined;
        let active = true;
        setDeletedLoading(true);
        const params = new URLSearchParams({
            deleted_only: '1',
            q: submittedDeletedQuery,
            p: String(deletedPage),
            s: String(deletedPageSize),
        });
        fetchJson(`${endpoint}/order-history?${params.toString()}`)
            .then(data => {
                if (!active) return;
                setDeletedOrders(data?.items || []);
                setDeletedTotal(data?.total || 0);
            })
            .catch(error => active && messageApi.error(error.message))
            .finally(() => active && setDeletedLoading(false));
        return () => { active = false; };
    }, [deletedMode, deletedPage, deletedPageSize, messageApi, open, refreshKey, selectedDeletedOrder, submittedDeletedQuery]);

    useEffect(() => {
        if (!open || !activeUid) return undefined;
        let active = true;
        setVersionsLoading(true);
        const params = new URLSearchParams({ p: String(versionPage), s: String(versionPageSize) });
        fetchJson(`${endpoint}/orders/${activeUid}/versions?${params.toString()}`)
            .then(data => {
                if (!active) return;
                setVersions(data?.items || []);
                setVersionTotal(data?.total || 0);
            })
            .catch(error => active && messageApi.error(error.message))
            .finally(() => active && setVersionsLoading(false));
        return () => { active = false; };
    }, [activeUid, messageApi, open, refreshKey, versionPage, versionPageSize]);

    const loadVersion = async (version, mode) => {
        setSelectedVersionNo(version.version_no);
        setSelectedVersion(null);
        setDetailMode(mode);
        setDetailLoading(true);
        try {
            const detail = await fetchJson(`${endpoint}/orders/${activeUid}/versions/${version.version_no}`);
            setSelectedVersion(detail);
        } catch (error) {
            messageApi.error(error.message);
        } finally {
            setDetailLoading(false);
        }
    };

    const drawerTitle = useMemo(() => {
        if (deletedMode && !selectedDeletedOrder && !orderUid) return '已删除订单历史';
        const suffix = [activeOrderId, activeCustomerName].filter(Boolean).join(' / ');
        return `修改历史${suffix ? ` - ${suffix}` : ''}`;
    }, [activeCustomerName, activeOrderId, deletedMode, orderUid, selectedDeletedOrder]);

    const showDeletedIndex = deletedMode && !activeUid;

    return (
        <Drawer
            title={drawerTitle}
            open={open}
            onClose={onClose}
            width="min(1120px, 100vw)"
            destroyOnClose
            styles={{ body: { padding: 0, overflow: 'hidden' } }}
        >
            {contextHolder}
            {showDeletedIndex ? (
                <div className={styles.deletedIndex}>
                    <Input.Search
                        allowClear
                        value={deletedQuery}
                        prefix={<SearchOutlined />}
                        placeholder="按订单 UID、订单号或客户查询"
                        onChange={event => setDeletedQuery(event.target.value)}
                        onSearch={() => {
                            setDeletedPage(1);
                            setSubmittedDeletedQuery(deletedQuery.trim());
                        }}
                        style={{ marginBottom: 16 }}
                    />
                    <Table
                        size="small"
                        loading={deletedLoading}
                        rowKey="order_uid"
                        dataSource={deletedOrders}
                        pagination={{
                            current: deletedPage,
                            pageSize: deletedPageSize,
                            total: deletedTotal,
                            showSizeChanger: false,
                            onChange: setDeletedPage,
                        }}
                        columns={[
                            { title: '订单号', dataIndex: 'order_id', key: 'order_id', render: displayValue },
                            { title: '客户', dataIndex: 'customer_name', key: 'customer_name', render: displayValue },
                            { title: '订单 UID', dataIndex: 'order_uid', key: 'order_uid', ellipsis: true },
                            { title: '最后版本', dataIndex: 'version_no', key: 'version_no', width: 90, render: value => `V${value}` },
                            { title: '删除时间', dataIndex: 'created_at', key: 'created_at', width: 170 },
                            {
                                title: '操作', key: 'operation', width: 90,
                                render: (_, record) => (
                                    <Button type="link" icon={<HistoryOutlined />} onClick={() => {
                                        setSelectedDeletedOrder(record);
                                        setVersionPage(1);
                                        setSelectedVersion(null);
                                        setSelectedVersionNo(null);
                                        setVersions([]);
                                    }}>查看</Button>
                                ),
                            },
                        ]}
                    />
                </div>
            ) : (
                <div className={styles.masterDetail}>
                    <section className={styles.versionPane} aria-label="版本记录">
                        {deletedMode && selectedDeletedOrder && (
                            <Button
                                type="link"
                                icon={<ArrowLeftOutlined />}
                                onClick={() => {
                                    setSelectedDeletedOrder(null);
                                    setSelectedVersion(null);
                                    setSelectedVersionNo(null);
                                    setVersions([]);
                                }}
                                className={styles.backButton}
                            >返回已删除订单列表</Button>
                        )}
                        <div className={styles.paneHeading}>
                            <Title level={5} className={styles.paneTitle}>版本记录</Title>
                            <Text type="secondary">共 {versionTotal} 条</Text>
                        </div>
                        <Text type="secondary" className={styles.paneHint}>
                            选择一个版本，差异或完整快照会显示在右侧。
                        </Text>
                        <Spin spinning={versionsLoading}>
                            <List
                                className={styles.versionList}
                                dataSource={versions}
                                locale={{ emptyText: '暂无版本记录' }}
                                renderItem={version => {
                                    const selected = selectedVersionNo === version.version_no;
                                    return (
                                        <List.Item
                                            className={`${styles.versionItem} ${selected ? styles.selectedVersionItem : ''}`}
                                            actions={[
                                                <Button
                                                    key="changes"
                                                    type="link"
                                                    size="small"
                                                    aria-pressed={selected && detailMode === 'changes'}
                                                    onClick={() => loadVersion(version, 'changes')}
                                                >查看差异</Button>,
                                                <Button
                                                    key="snapshot"
                                                    type="link"
                                                    size="small"
                                                    aria-pressed={selected && detailMode === 'snapshot'}
                                                    onClick={() => loadVersion(version, 'snapshot')}
                                                >查看该版本</Button>,
                                            ]}
                                        >
                                            <List.Item.Meta
                                                title={(
                                                    <Space wrap>
                                                        <Tag color="blue">V{version.version_no}</Tag>
                                                        <Text strong>{version.summary || ACTION_LABELS[version.action] || version.action}</Text>
                                                        {version.deleted && <Tag color="red">已删除</Tag>}
                                                    </Space>
                                                )}
                                                description={(
                                                    <Space direction="vertical" size={2}>
                                                        <Text type="secondary">
                                                            {version.created_at || '-'} · {version.operator_name || '系统'}
                                                            {(version.operator_roles || []).length > 0
                                                                ? `（${version.operator_roles.map(role => ROLE_LABEL_MAP[role] || role).join('、')}）`
                                                                : ''}
                                                        </Text>
                                                        {version.reason && <Text>原因：{version.reason}</Text>}
                                                        <Space wrap>
                                                            {(version.change_summary || []).map((change, index) => (
                                                                <Tag key={`${change.sequence_no || index}-${change.entity_uid}`}>
                                                                    {ENTITY_LABELS[change.entity_type] || change.entity_type}
                                                                    ·{OPERATION_LABELS[change.operation] || change.operation}
                                                                    {change.fields?.length ? `·${change.fields.length}项` : ''}
                                                                </Tag>
                                                            ))}
                                                        </Space>
                                                    </Space>
                                                )}
                                            />
                                        </List.Item>
                                    );
                                }}
                            />
                        </Spin>
                        {versionTotal > versionPageSize && (
                            <Pagination
                                current={versionPage}
                                pageSize={versionPageSize}
                                total={versionTotal}
                                showSizeChanger={false}
                                onChange={page => {
                                    setVersionPage(page);
                                    setSelectedVersion(null);
                                    setSelectedVersionNo(null);
                                }}
                                className={styles.pagination}
                            />
                        )}
                    </section>

                    <section
                        ref={detailPaneRef}
                        className={styles.detailPane}
                        aria-label={selectedVersion
                            ? `V${selectedVersion.version_no} ${detailMode === 'snapshot' ? '完整快照' : '本次差异'}`
                            : '版本详情'}
                        aria-live="polite"
                        tabIndex={-1}
                    >
                        <Spin spinning={detailLoading}>
                            {selectedVersion ? (
                                <>
                                    <div className={styles.detailHeading}>
                                        <Title level={4} className={styles.detailTitle}>
                                            V{selectedVersion.version_no} {detailMode === 'snapshot' ? '完整快照' : '本次差异'}
                                        </Title>
                                        <Tag color={detailMode === 'snapshot' ? 'geekblue' : 'green'}>
                                            {detailMode === 'snapshot' ? '完整版本' : '变更内容'}
                                        </Tag>
                                    </div>
                                    {detailMode === 'snapshot'
                                        ? <VersionSnapshot detail={selectedVersion} />
                                        : <VersionChanges changes={selectedVersion.changes} />}
                                </>
                            ) : (
                                <div className={styles.detailEmpty}>
                                    <Empty
                                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                                        description={detailLoading ? '正在加载版本详情' : '请从左侧选择要查看的差异或完整版本'}
                                    />
                                </div>
                            )}
                        </Spin>
                    </section>
                </div>
            )}
        </Drawer>
    );
}

export {
    FIELD_LABELS,
    ItemDetailsTable,
    VersionChanges,
    VersionSnapshot,
    displayValue,
    jsonEqual,
};
