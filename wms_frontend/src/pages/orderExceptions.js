import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Descriptions, Drawer, Empty, Input, message, Modal, Select, Space, Spin, Table, Tag, Timeline, Typography } from 'antd';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { getUserRoles, hasPermission } from '../common/roleConfig';
import { addExceptionFollowup, exceptionSubmission, fetchExceptionSalespeople, fetchOrderException, fetchOrderExceptions, resolveOrderException } from '../common/orderExceptionApi';
import OrderExceptionRegistration, { exceptionCargoLabel } from '../components/OrderExceptionRegistration';
import useUrlState from '../common/useUrlState';
import styles from './orderExceptions.module.css';

const statusLabel = status => status === 'resolved' ? <Tag color="green">已解决</Tag> : <Tag color="red">待跟进</Tag>;
const sourceLabel = source => source === '17track' || source === 'webhook' ? '17TRACK' : '人工登记';
const historyLabels = { registered: '登记异常', followup: '业务跟进', resolved: '标记已解决' };

export default function OrderExceptions() {
    const actor = useMemo(() => {
        try { return JSON.parse(atob((localStorage.getItem('jwt') || '').split('.')[1])); } catch { return {}; }
    }, []);
    const roles = getUserRoles(actor);
    const isAdmin = roles.includes('admin');
    const canList = hasPermission(roles, ['admin', 'salesperson']);
    const canRegister = hasPermission(roles, ['admin', 'salesperson', 'clerk']);
    const actorId = actor.user_id;
    const location = useLocation();
    const navigate = useNavigate();
    const exceptionUid = new URLSearchParams(location.search).get('exception_uid');
    const [salespeople, setSalespeople] = useState([]);
    const [salesmanId, setSalesmanId] = useUrlState('exception_salesman', actorId, { validate: value => Number.isInteger(value) && value > 0 });
    const [salespeopleError, setSalespeopleError] = useState('');
    const [status, setStatus] = useUrlState('exception_status', 'open', { validate: value => ['open', 'resolved', 'all'].includes(value) });
    const [page, setPage] = useUrlState('exception_page', 1, { validate: value => Number.isInteger(value) && value > 0 });
    const [items, setItems] = useState([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [refresh, setRefresh] = useState(0);
    const [registrationOpen, setRegistrationOpen] = useState(false);
    const [detail, setDetail] = useState(null);
    const [detailError, setDetailError] = useState('');
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailRefresh, setDetailRefresh] = useState(0);
    const [note, setNote] = useState('');
    const [resolveNote, setResolveNote] = useState('');
    const [resolveOpen, setResolveOpen] = useState(false);
    const [mutation, setMutation] = useState('');
    const [mutationError, setMutationError] = useState('');
    const mutationLock = useRef(false);
    const followupSubmission = useRef(null);
    const resolveSubmission = useRef(null);
    const currentUid = useRef(exceptionUid);
    currentUid.current = exceptionUid;
    const [messageApi, messageContext] = message.useMessage();

    useEffect(() => {
        if (!isAdmin) return;
        const controller = new AbortController();
        fetchExceptionSalespeople({ signal: controller.signal }).then(data => {
            if (!controller.signal.aborted) setSalespeople(data || []);
        }).catch(cause => { if (!controller.signal.aborted) setSalespeopleError(cause.message); });
        return () => controller.abort();
    }, [isAdmin]);

    useEffect(() => {
        if (!canList) return;
        const controller = new AbortController();
        setLoading(true); setError(''); setItems([]);
        fetchOrderExceptions({ page, pageSize: 20, status, ...(isAdmin ? { salesmanId } : {}), signal: controller.signal }).then(data => {
            if (!controller.signal.aborted) { setItems(data?.items || []); setTotal(data?.total || 0); }
        }).catch(cause => { if (!controller.signal.aborted) { setError(cause.message); setTotal(0); } })
            .finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => controller.abort();
    }, [canList, isAdmin, page, status, salesmanId, refresh]);

    useEffect(() => {
        setDetail(null); setDetailError(''); setMutationError(''); setNote(''); setResolveNote(''); setResolveOpen(false);
        followupSubmission.current = null; resolveSubmission.current = null;
        if (!exceptionUid || !canList) { setDetailLoading(false); return; }
        const controller = new AbortController();
        setDetailLoading(true);
        fetchOrderException(exceptionUid, { signal: controller.signal }).then(data => {
            if (!controller.signal.aborted) setDetail(data);
        }).catch(cause => { if (!controller.signal.aborted) setDetailError(cause.message); })
            .finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
        return () => controller.abort();
    }, [exceptionUid, canList, detailRefresh]);

    const openDetail = uid => {
        const query = new URLSearchParams(location.search); query.set('exception_uid', uid);
        navigate({ pathname: location.pathname, search: `?${query}`, hash: location.hash }, { state: location.state });
    };
    const closeDetail = () => {
        if (mutationLock.current) return;
        const query = new URLSearchParams(location.search); query.delete('exception_uid');
        navigate({ pathname: location.pathname, search: query.toString() ? `?${query}` : '', hash: location.hash }, { replace: true, state: location.state });
    };

    const save = async action => {
        if (mutationLock.current || !detail || (action === 'followup' ? !detail.can_followup : !detail.can_resolve)) return;
        const trimmed = (action === 'followup' ? note : resolveNote).trim();
        if (action === 'followup' && !trimmed) { setMutationError('请填写跟进内容'); return; }
        const uid = detail.uid;
        mutationLock.current = true; setMutation(action); setMutationError('');
        try {
            const body = exceptionSubmission(action === 'followup' ? followupSubmission : resolveSubmission,
                action === 'followup' || trimmed ? { note: trimmed } : {});
            const updated = await (action === 'followup' ? addExceptionFollowup(uid, body) : resolveOrderException(uid, body));
            setRefresh(value => value + 1);
            if (currentUid.current === uid) {
                setDetail(updated);
                if (action === 'followup') { setNote(''); followupSubmission.current = null; }
                else { setResolveNote(''); setResolveOpen(false); resolveSubmission.current = null; }
                messageApi.success(action === 'followup' ? '跟进已保存' : '异常已标记为解决');
            }
        } catch (cause) { if (currentUid.current === uid) setMutationError(cause.message); }
        finally { mutationLock.current = false; setMutation(''); }
    };

    const columns = [
        { title: '订单', dataIndex: 'order_id', render: (_, row) => <Link to={`/orders/${encodeURIComponent(row.order_uid)}`}>{row.order_id || row.order_uid}</Link> },
        { title: '包裹', render: (_, row) => row.cargo_uid ? exceptionCargoLabel(row) : '整张订单' },
        { title: '异常理由', dataIndex: 'reason', render: value => <span style={{ whiteSpace: 'pre-wrap' }}>{value}</span> },
        { title: '业务员', dataIndex: 'salesman_name' },
        { title: '来源', dataIndex: 'source', render: sourceLabel },
        { title: '状态', dataIndex: 'status', render: statusLabel },
        { title: '登记时间', dataIndex: 'created_at' },
        { title: '操作', render: (_, row) => <Button type="link" onClick={() => openDetail(row.uid)}>查看跟进</Button> },
    ];

    return <div className={styles.page}>
        {messageContext}
        <div className={styles.header}>
            <Typography.Title className={styles.title} level={4}>异常订单</Typography.Title>
            {canRegister && <Button type="primary" onClick={() => setRegistrationOpen(true)}>登记异常</Button>}
        </div>
        {!canList ? <Alert type="info" showIcon message="登记后会通知对应业务员，由业务员查看异常并记录跟进。" /> : <>
            <Space wrap style={{ marginBottom: 16 }}>
                <Typography.Text>状态</Typography.Text>
                <Select aria-label="异常状态" style={{ width: 140 }} value={status} onChange={value => { setStatus(value); setPage(1); }}
                    options={[{ value: 'open', label: '待跟进' }, { value: 'resolved', label: '已解决' }, { value: 'all', label: '全部' }]} />
                {isAdmin && <><Typography.Text>业务员</Typography.Text><Select aria-label="查看业务员" style={{ minWidth: 180 }} value={salesmanId}
                    onChange={value => { setSalesmanId(value); setPage(1); }} options={[
                        { value: actorId, label: '本人' }, ...salespeople.filter(person => String(person.id) !== String(actorId)).map(person => ({ value: person.id, label: person.name || String(person.id) })),
                    ]} /></>}
                <Button onClick={() => setRefresh(value => value + 1)} loading={loading}>刷新</Button>
            </Space>
            {salespeopleError && <Alert type="error" showIcon message={salespeopleError} style={{ marginBottom: 16 }} />}
            {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
            <Table rowKey="uid" dataSource={items} columns={columns} loading={loading} scroll={{ x: 1050 }}
                pagination={{ current: page, total, pageSize: 20, showSizeChanger: false, showTotal: count => `共 ${count} 条`, onChange: setPage }} />
        </>}
        <OrderExceptionRegistration open={registrationOpen} onCancel={() => setRegistrationOpen(false)} onCreated={() => {
            setRegistrationOpen(false); setRefresh(value => value + 1); messageApi.success('异常已登记，已通知对应业务员');
        }} />
        <Drawer title={detail ? `异常跟进 · ${detail.order_id || detail.order_uid}` : '异常跟进'} open={Boolean(exceptionUid && canList)}
            onClose={closeDetail} maskClosable={!mutation} closable={!mutation} width="min(640px, 100vw)" destroyOnClose>
            {detailLoading && <Spin />}
            {detailError && <Alert type="error" showIcon message={detailError} action={<Button onClick={() => setDetailRefresh(value => value + 1)}>重试</Button>} />}
            {detail && <>
                <Descriptions column={1} size="small" bordered>
                    <Descriptions.Item label="订单"><Link to={`/orders/${encodeURIComponent(detail.order_uid)}`}>{detail.order_id || detail.order_uid}</Link></Descriptions.Item>
                    <Descriptions.Item label="包裹">{detail.cargo_uid ? exceptionCargoLabel(detail) : '整张订单'}</Descriptions.Item>
                    <Descriptions.Item label="业务员">{detail.salesman_name || '-'}</Descriptions.Item>
                    <Descriptions.Item label="异常理由"><span style={{ whiteSpace: 'pre-wrap' }}>{detail.reason}</span></Descriptions.Item>
                    <Descriptions.Item label="状态">{statusLabel(detail.status)}</Descriptions.Item>
                    <Descriptions.Item label="来源">{sourceLabel(detail.source)}</Descriptions.Item>
                    <Descriptions.Item label="登记时间">{detail.created_at}</Descriptions.Item>
                    {detail.resolved_at && <Descriptions.Item label="解决时间">{detail.resolved_at}</Descriptions.Item>}
                </Descriptions>
                <Typography.Title level={5}>跟进历史</Typography.Title>
                {detail.history?.length ? <Timeline items={detail.history.map(entry => ({
                    children: <><Typography.Text strong>{historyLabels[entry.action || entry.type] || '异常更新'}</Typography.Text>
                        <div><Typography.Text type="secondary">{entry.actor_name || sourceLabel(entry.source)} · {entry.created_at}</Typography.Text></div>
                        <div style={{ whiteSpace: 'pre-wrap' }}>{entry.note}</div>
                        {entry.tracking_status && <Typography.Text type="secondary">物流状态：{entry.tracking_status}</Typography.Text>}</>,
                }))} /> : <Empty description="暂无跟进记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
                {mutationError && <Alert type="error" showIcon message={mutationError} style={{ marginBottom: 16 }} />}
                {detail.can_followup && <><Typography.Text strong>跟进内容</Typography.Text>
                    <Input.TextArea aria-label="跟进内容" rows={4} maxLength={2000} showCount value={note} onChange={event => setNote(event.target.value)} disabled={Boolean(mutation)} style={{ marginTop: 8, marginBottom: 16 }} />
                    <Button aria-label="保存跟进" type="primary" onClick={() => save('followup')} loading={mutation === 'followup'} disabled={Boolean(mutation && mutation !== 'followup')}>保存跟进</Button></>}
                {detail.can_resolve && <Button style={{ marginLeft: 8 }} onClick={() => { setResolveOpen(true); setMutationError(''); }} disabled={Boolean(mutation)}>标记已解决</Button>}
                {!detail.can_followup && !detail.can_resolve && detail.status !== 'resolved' && <Alert type="info" showIcon message="仅对应业务员可跟进和标记已解决，当前记录为只读。" />}
            </>}
        </Drawer>
        <Modal title="标记已解决" open={resolveOpen && Boolean(detail?.can_resolve)} onCancel={() => { if (!mutation) setResolveOpen(false); }}
            closable={!mutation} maskClosable={!mutation} okText="确认已解决" cancelText="取消" onOk={() => save('resolve')} confirmLoading={mutation === 'resolve'}
            cancelButtonProps={{ disabled: Boolean(mutation) }}>
            <Typography.Paragraph>确认该异常已处理完成。物流状态更新不会自动关闭异常。</Typography.Paragraph>
            {mutationError && <Alert type="error" showIcon message={mutationError} style={{ marginBottom: 16 }} />}
            <Input.TextArea aria-label="解决说明" placeholder="解决说明（可选）" rows={3} maxLength={2000} value={resolveNote}
                onChange={event => setResolveNote(event.target.value)} disabled={Boolean(mutation)} />
        </Modal>
    </div>;
}
