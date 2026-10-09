import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Badge, Button, Drawer, Empty, Pagination, Segmented, Space, Spin, Tag } from 'antd';
import { ArrowLeftOutlined, CheckOutlined, InboxOutlined, ReloadOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import dayjs from 'dayjs';
import {
    fetchMessage, fetchMessages, fetchUnreadCount, isInternalMessagePath,
    markAllMessagesRead, markMessageRead, MESSAGE_POLL_INTERVAL,
} from '../common/messageApi';
import './MessageInbox.css';

const PAGE_SIZE = 20;
const categories = {
    finance_return: { label: '财务退回', color: 'orange' },
    logistics_exception: { label: '物流异常', color: 'red' },
    system: { label: '系统通知', color: 'blue' },
};
const formatTime = value => value && dayjs(value).isValid() ? dayjs(value).format('YYYY-MM-DD HH:mm') : '—';

function MessageCategory({ category }) {
    const { label, color } = categories[category] || { label: '事务提醒', color: 'blue' };
    return <Tag color={color}>{label}</Tag>;
}

function InboxSession({ token }) {
    const navigate = useNavigate();
    const [open, setOpen] = useState(false);
    const [count, setCount] = useState(0);
    const [items, setItems] = useState([]);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [status, setStatus] = useState('all');
    const [refreshVersion, setRefreshVersion] = useState(0);
    const [refreshing, setRefreshing] = useState(false);
    const [refreshError, setRefreshError] = useState('');
    const [selectedUid, setSelectedUid] = useState(null);
    const [detail, setDetail] = useState(null);
    const [detailVersion, setDetailVersion] = useState(0);
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailError, setDetailError] = useState('');
    const [readError, setReadError] = useState('');
    const [markingAll, setMarkingAll] = useState(false);
    const [sessionExpired, setSessionExpired] = useState(false);
    const mutationController = useRef(null);

    const ownsSession = useCallback(() => localStorage.getItem('jwt') === token, [token]);
    const handleError = useCallback(error => {
        if (!ownsSession() || error?.name === 'AbortError') return false;
        if (error?.status === 401 || error?.code === 401) {
            localStorage.removeItem('jwt');
            setOpen(false);
            setCount(0);
            setItems([]);
            setDetail(null);
            setSessionExpired(true);
            navigate('/login');
            return false;
        }
        return true;
    }, [navigate, ownsSession]);

    // Keep message transport here so a future push transport can trigger the same refresh.
    useEffect(() => {
        let disposed = false;
        let busy = false;
        let refreshWhenFinished = false;
        let timer;
        let controller;
        const canUpdate = () => !disposed && ownsSession();
        const refresh = async () => {
            if (!canUpdate() || document.hidden) return;
            if (busy) return;
            window.clearTimeout(timer);
            busy = true;
            refreshWhenFinished = false;
            controller = new AbortController();
            const signal = controller.signal;
            setRefreshing(true);
            const results = await Promise.allSettled([
                fetchUnreadCount({ token, signal }),
                ...(open ? [fetchMessages({ token, signal, page, pageSize: PAGE_SIZE, status })] : []),
            ]);
            if (canUpdate() && !signal.aborted) {
                let errorText = '';
                results.forEach((result, index) => {
                    if (result.status === 'rejected') {
                        if (handleError(result.reason)) errorText = result.reason.message || '消息加载失败，请重试';
                        return;
                    }
                    if (!ownsSession()) return;
                    if (index === 0) setCount(result.value.unread_count);
                    else {
                        const nextTotal = result.value.total || 0;
                        const lastPage = Math.max(1, Math.ceil(nextTotal / PAGE_SIZE));
                        setTotal(nextTotal);
                        if (page > lastPage) {
                            setItems([]);
                            setPage(lastPage);
                        } else setItems(result.value.items || []);
                        if (results[0].status === 'rejected' && typeof result.value.unread_count === 'number') {
                            setCount(result.value.unread_count);
                        }
                    }
                });
                if (ownsSession()) setRefreshError(errorText);
            }
            busy = false;
            if (canUpdate()) {
                setRefreshing(false);
                if (!document.hidden) {
                    if (refreshWhenFinished) {
                        refreshWhenFinished = false;
                        refresh();
                    } else timer = window.setTimeout(refresh, MESSAGE_POLL_INTERVAL);
                }
            }
        };
        const onVisibility = () => {
            window.clearTimeout(timer);
            if (document.hidden) controller?.abort();
            else if (busy) refreshWhenFinished = true;
            else refresh();
        };
        const onFocus = () => refresh();
        refresh();
        document.addEventListener('visibilitychange', onVisibility);
        window.addEventListener('focus', onFocus);
        return () => {
            disposed = true;
            window.clearTimeout(timer);
            controller?.abort();
            document.removeEventListener('visibilitychange', onVisibility);
            window.removeEventListener('focus', onFocus);
        };
    }, [token, ownsSession, handleError, open, page, status, refreshVersion]);

    useEffect(() => {
        if (!selectedUid || !open) return;
        let disposed = false;
        const controller = new AbortController();
        const options = { token, signal: controller.signal };
        const canUpdate = () => !disposed && !controller.signal.aborted && ownsSession();
        setDetail(null);
        setDetailError('');
        setReadError('');
        setDetailLoading(true);
        const load = async () => {
            try {
                const message = await fetchMessage(selectedUid, options);
                if (!canUpdate()) return;
                setDetail(message);
                if (!message.is_read) {
                    try {
                        const readMessage = await markMessageRead(selectedUid, options);
                        if (!canUpdate()) return;
                        setDetail(readMessage);
                        setRefreshVersion(value => value + 1);
                    } catch (error) {
                        if (canUpdate() && handleError(error)) setReadError(error.message || '标记已读失败，请重试');
                    }
                }
            } catch (error) {
                if (canUpdate() && handleError(error)) setDetailError(error.message || '消息加载失败，请重试');
            } finally {
                if (canUpdate()) setDetailLoading(false);
            }
        };
        load();
        return () => { disposed = true; controller.abort(); };
    }, [selectedUid, token, ownsSession, handleError, detailVersion, open]);

    useEffect(() => () => mutationController.current?.abort(), []);

    const markAllRead = async () => {
        if (markingAll || !ownsSession()) return;
        const controller = new AbortController();
        mutationController.current = controller;
        setMarkingAll(true);
        try {
            const result = await markAllMessagesRead({ token, signal: controller.signal });
            if (!ownsSession() || controller.signal.aborted) return;
            setCount(result.unread_count);
            setRefreshError('');
            setRefreshVersion(value => value + 1);
        } catch (error) {
            if (!controller.signal.aborted && handleError(error)) setRefreshError(error.message || '标记已读失败，请重试');
        } finally {
            if (ownsSession() && !controller.signal.aborted) setMarkingAll(false);
        }
    };

    const close = () => { setOpen(false); setSelectedUid(null); setDetail(null); };

    if (sessionExpired) return null;

    return <>
        <div className="message-inbox-launcher">
            <Badge count={count} overflowCount={99}>
                <Button type="primary" size="large" shape="round" icon={<InboxOutlined />}
                    aria-label={`打开收件箱${count > 0 ? `，${count} 条未读` : ''}`}
                    onClick={() => setOpen(true)}>收件箱</Button>
            </Badge>
        </div>
        <Drawer title={<Space><InboxOutlined /><span>收件箱</span><Tag>{count} 条未读</Tag></Space>}
            extra={<Button type="text" icon={<ReloadOutlined />} aria-label="刷新收件箱" loading={refreshing}
                onClick={() => setRefreshVersion(value => value + 1)} />}
            open={open} onClose={close} width={480} rootClassName="message-inbox-drawer">
            {refreshError && <Alert type="error" showIcon message={refreshError} className="message-inbox-alert" />}
            {selectedUid ? <div className="message-inbox-detail">
                <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => setSelectedUid(null)}>返回消息列表</Button>
                {detailError && <Alert type="error" showIcon message={detailError}
                    action={<Button size="small" onClick={() => setDetailVersion(value => value + 1)}>重试</Button>} />}
                {detailLoading && !detail && <div className="message-inbox-loading" role="status" aria-label="正在加载消息"><Spin /></div>}
                {detail && <>
                    <h2 className="message-inbox-subject">{detail.title}</h2>
                    <Space wrap><MessageCategory category={detail.category} /><Tag>{detail.is_read ? '已读' : '未读'}</Tag></Space>
                    <dl className="message-inbox-metadata">
                        <div><dt>发件人</dt><dd>{detail.source_name || '系统通知'}</dd></div>
                        <div><dt>发送时间</dt><dd>{formatTime(detail.created_at)}</dd></div>
                    </dl>
                    <div className="message-inbox-body">{detail.body}</div>
                    {readError && <Alert type="warning" showIcon message={readError}
                        action={<Button size="small" onClick={() => setDetailVersion(value => value + 1)}>重试标记已读</Button>} />}
                    {isInternalMessagePath(detail.action_path) && <div className="message-inbox-actions">
                        <Button type="primary" onClick={() => { close(); navigate(detail.action_path); }}>前往处理</Button>
                        <p>已读表示您已查看消息，事务请前往对应页面处理。</p>
                    </div>}
                </>}
            </div> : <>
                <div className="message-inbox-toolbar">
                    <Segmented options={[{ label: '全部', value: 'all' }, { label: '未读', value: 'unread' }]}
                        value={status} onChange={value => { setStatus(value); setPage(1); setItems([]); setTotal(0); }} />
                    <Button type="text" icon={<CheckOutlined />} aria-label="全部已读" disabled={!count || markingAll} loading={markingAll}
                        onClick={markAllRead}>全部已读</Button>
                </div>
                <Spin spinning={refreshing}>
                    {items.length ? <div role="list" className="message-inbox-list">
                        {items.map(item => <div key={item.uid} role="listitem">
                            <button type="button" className={`message-inbox-item${item.is_read ? '' : ' message-inbox-item-unread'}`}
                                aria-label={`查看消息：${item.title}`} onClick={() => setSelectedUid(item.uid)}>
                                <div className="message-inbox-item-heading"><span className="message-inbox-item-title">{item.title}</span>
                                    {!item.is_read && <span className="message-inbox-unread-dot" aria-label="未读消息" />}</div>
                                <div className="message-inbox-preview">{item.body}</div>
                                <div className="message-inbox-item-meta"><span>{item.source_name || '系统通知'}</span>
                                    <time>{formatTime(item.created_at)}</time></div>
                            </button>
                        </div>)}
                    </div> : !refreshing && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={status === 'unread' ? '暂无未读消息' : '暂无消息'} />}
                </Spin>
                <Pagination className="message-inbox-pagination" current={page} pageSize={PAGE_SIZE} total={total}
                    size="small" hideOnSinglePage showSizeChanger={false}
                    onChange={value => { setPage(value); setItems([]); }} />
            </>}
        </Drawer>
    </>;
}

export default function MessageInbox() {
    const [, refreshSession] = useState(0);
    useEffect(() => {
        const updateSession = () => refreshSession(value => value + 1);
        const onStorage = event => { if (event.key === 'jwt' || event.key === null) updateSession(); };
        window.addEventListener('storage', onStorage);
        window.addEventListener('focus', updateSession);
        document.addEventListener('visibilitychange', updateSession);
        return () => {
            window.removeEventListener('storage', onStorage);
            window.removeEventListener('focus', updateSession);
            document.removeEventListener('visibilitychange', updateSession);
        };
    }, []);
    const token = localStorage.getItem('jwt');
    return token ? <InboxSession key={token} token={token} /> : null;
}
