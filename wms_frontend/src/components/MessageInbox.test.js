import React from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import MessageInbox from './MessageInbox';
import {
    fetchMessage, fetchMessages, fetchUnreadCount, markAllMessagesRead, markMessageRead,
} from '../common/messageApi';

jest.mock('../config', () => ({ endpoint: '/api' }));
jest.mock('../common/messageApi', () => ({
    ...jest.requireActual('../common/messageApi'),
    fetchMessage: jest.fn(), fetchMessages: jest.fn(), fetchUnreadCount: jest.fn(),
    markAllMessagesRead: jest.fn(), markMessageRead: jest.fn(),
}));
jest.mock('antd', () => {
    const React = require('react');
    const Empty = ({ description }) => <div>{description}</div>;
    Empty.PRESENTED_IMAGE_SIMPLE = null;
    return {
        Alert: ({ message, action }) => <div role="alert">{message}{action}</div>,
        Badge: ({ count, children }) => <div data-testid="unread-badge" data-count={count}>{children}</div>,
        Button: ({ children, icon, loading, shape, size, type, ...props }) => <button type="button" {...props}>{icon}{children}</button>,
        Drawer: ({ open, title, extra, onClose, children }) => open ? <div role="dialog" aria-label="收件箱">
            {title}{extra}<button onClick={onClose}>关闭收件箱</button>{children}</div> : null,
        Empty,
        Pagination: ({ total, current, pageSize, onChange }) => total > pageSize ? <button onClick={() => onChange(current + 1)}>下一页</button> : null,
        Segmented: ({ options, value, onChange }) => <div>{options.map(option => <button key={option.value}
            aria-pressed={value === option.value} onClick={() => onChange(option.value)}>{option.label}</button>)}</div>,
        Space: ({ children }) => <div>{children}</div>,
        Spin: ({ children }) => <>{children}</>,
        Tag: ({ children }) => <span>{children}</span>,
    };
});

const message = {
    uid: 'message-1', title: '收款凭证需要修改', body: '请核对金额\n补充付款凭证',
    source_name: '财务部', category: 'finance_return', created_at: '2026-10-07T10:00:00',
    action_path: '/receipts?payment_uid=payment-1', is_read: false,
};
const LocationProbe = () => { const location = useLocation(); return <output data-testid="location">{location.pathname}{location.search}</output>; };
const showInbox = () => render(<MemoryRouter><MessageInbox /><LocationProbe /></MemoryRouter>);
const settle = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });
const openInbox = async () => { fireEvent.click(screen.getByRole('button', { name: /^打开收件箱/ })); await settle(); };
let unread;
let hidden;

beforeEach(() => {
    jest.useFakeTimers();
    localStorage.setItem('jwt', 'employee-a');
    hidden = false;
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden });
    unread = 1;
    jest.clearAllMocks();
    fetchUnreadCount.mockImplementation(async () => ({ unread_count: unread }));
    fetchMessages.mockImplementation(async () => ({ items: [{ ...message, is_read: !unread }], total: 1, unread_count: unread }));
    fetchMessage.mockResolvedValue(message);
    markMessageRead.mockImplementation(async () => { unread = 0; return { ...message, is_read: true, read_at: '2026-10-07T10:01:00' }; });
    markAllMessagesRead.mockImplementation(async () => { unread = 0; return { updated_count: 1, unread_count: 0 }; });
});

afterEach(() => {
    cleanup();
    localStorage.clear();
    jest.useRealTimers();
});

test('polls counts every three minutes, loads lists only on opening, and cancels on unmount', async () => {
    const { unmount } = showInbox();
    await settle();
    expect(fetchUnreadCount).toHaveBeenCalledTimes(1);
    expect(fetchMessages).not.toHaveBeenCalled();
    await act(async () => { jest.advanceTimersByTime(179999); });
    expect(fetchUnreadCount).toHaveBeenCalledTimes(1);
    await act(async () => { jest.advanceTimersByTime(1); });
    expect(fetchUnreadCount).toHaveBeenCalledTimes(2);
    await openInbox();
    expect(fetchMessages).toHaveBeenCalledWith(expect.objectContaining({ page: 1, pageSize: 20, status: 'all', token: 'employee-a' }));
    const lastSignal = fetchUnreadCount.mock.calls.at(-1)[0].signal;
    unmount();
    expect(lastSignal.aborted).toBe(true);
    const calls = fetchUnreadCount.mock.calls.length;
    await act(async () => { jest.advanceTimersByTime(360000); });
    fireEvent.focus(window);
    expect(fetchUnreadCount).toHaveBeenCalledTimes(calls);
});

test('does not overlap an unfinished poll with focus or another poll', async () => {
    let resolveCount;
    fetchUnreadCount.mockImplementationOnce(() => new Promise(resolve => { resolveCount = resolve; }));
    showInbox();
    fireEvent.focus(window);
    await act(async () => { jest.advanceTimersByTime(360000); });
    expect(fetchUnreadCount).toHaveBeenCalledTimes(1);
    await act(async () => { resolveCount({ unread_count: 1 }); });
    await act(async () => { jest.advanceTimersByTime(180000); });
    expect(fetchUnreadCount).toHaveBeenCalledTimes(2);
});

test('pauses while the page is hidden and refreshes on visibility and focus', async () => {
    showInbox();
    await settle();
    const signal = fetchUnreadCount.mock.calls[0][0].signal;
    hidden = true;
    fireEvent(document, new Event('visibilitychange'));
    expect(signal.aborted).toBe(true);
    await act(async () => { jest.advanceTimersByTime(540000); });
    expect(fetchUnreadCount).toHaveBeenCalledTimes(1);
    hidden = false;
    fireEvent(document, new Event('visibilitychange'));
    await settle();
    expect(fetchUnreadCount).toHaveBeenCalledTimes(2);
    fireEvent.focus(window);
    await settle();
    expect(fetchUnreadCount).toHaveBeenCalledTimes(3);
});

test('late responses from the previous account never appear after an account switch', async () => {
    let resolvePrevious;
    fetchUnreadCount.mockImplementationOnce(() => new Promise(resolve => { resolvePrevious = resolve; }));
    showInbox();
    const signal = fetchUnreadCount.mock.calls[0][0].signal;
    localStorage.setItem('jwt', 'employee-b');
    fireEvent(window, new StorageEvent('storage', { key: 'jwt' }));
    await settle();
    expect(signal.aborted).toBe(true);
    expect(fetchUnreadCount).toHaveBeenLastCalledWith(expect.objectContaining({ token: 'employee-b' }));
    await act(async () => { resolvePrevious({ unread_count: 99 }); });
    expect(screen.getByTestId('unread-badge')).toHaveAttribute('data-count', '1');
    localStorage.removeItem('jwt');
    fireEvent(window, new StorageEvent('storage', { key: 'jwt' }));
    expect(screen.queryByRole('button', { name: /^打开收件箱/ })).not.toBeInTheDocument();
});

test('shows mail-like details, marks only the opened message read, then navigates to its processing page', async () => {
    showInbox();
    await settle();
    await openInbox();
    fireEvent.click(screen.getByRole('button', { name: `查看消息：${message.title}` }));
    await settle();
    expect(fetchMessage).toHaveBeenCalledWith('message-1', expect.objectContaining({ token: 'employee-a' }));
    expect(markMessageRead).toHaveBeenCalledWith('message-1', expect.objectContaining({ token: 'employee-a' }));
    expect(screen.getByRole('heading', { name: message.title })).toBeInTheDocument();
    expect(screen.getByText('财务部')).toBeInTheDocument();
    expect(screen.getByText('请核对金额 补充付款凭证')).toBeInTheDocument();
    expect(screen.getByTestId('unread-badge')).toHaveAttribute('data-count', '0');
    fireEvent.click(screen.getByRole('button', { name: '前往处理' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/receipts?payment_uid=payment-1');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

test('failed read mutations keep the unread badge and allow retry without losing the message', async () => {
    markMessageRead.mockRejectedValueOnce(new Error('网络繁忙，请重试'));
    showInbox();
    await settle();
    await openInbox();
    fireEvent.click(screen.getByRole('button', { name: `查看消息：${message.title}` }));
    await settle();
    expect(screen.getByRole('alert')).toHaveTextContent('网络繁忙，请重试');
    expect(screen.getByRole('heading', { name: message.title })).toBeInTheDocument();
    expect(screen.getByTestId('unread-badge')).toHaveAttribute('data-count', '1');
    fireEvent.click(screen.getByRole('button', { name: '重试标记已读' }));
    await settle();
    expect(screen.getByTestId('unread-badge')).toHaveAttribute('data-count', '0');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

test('filters and pagination request the appropriate server page, and failed read-all keeps unread counts', async () => {
    fetchMessages.mockResolvedValue({ items: [message], total: 45 });
    markAllMessagesRead.mockRejectedValueOnce(new Error('暂时无法标记已读'));
    showInbox();
    await settle();
    await openInbox();
    fireEvent.click(screen.getByRole('button', { name: '下一页' }));
    await settle();
    expect(fetchMessages).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, status: 'all' }));
    fireEvent.click(screen.getByRole('button', { name: '未读', exact: true }));
    await settle();
    expect(fetchMessages).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, status: 'unread' }));
    fireEvent.click(screen.getByRole('button', { name: '全部已读' }));
    await settle();
    expect(screen.getByTestId('unread-badge')).toHaveAttribute('data-count', '1');
    expect(screen.getByRole('alert')).toHaveTextContent('暂时无法标记已读');
    fireEvent.click(screen.getByRole('button', { name: '全部已读' }));
    await settle();
    expect(screen.getByTestId('unread-badge')).toHaveAttribute('data-count', '0');
});

test('authentication failures clear the expired account and route to login', async () => {
    fetchUnreadCount.mockRejectedValueOnce(Object.assign(new Error('请重新登录'), { status: 401 }));
    showInbox();
    await settle();
    expect(localStorage.getItem('jwt')).toBeNull();
    expect(screen.getByTestId('location')).toHaveTextContent('/login');
    expect(screen.queryByRole('button', { name: /^打开收件箱/ })).not.toBeInTheDocument();
});

test('reading the final unread message on a later page returns to a valid page instead of leaving an empty inbox', async () => {
    unread = 21;
    fetchMessages.mockImplementation(async ({ page, status }) => ({
        items: status === 'unread' && page === 2 && unread === 20 ? [] : [message],
        total: unread, unread_count: unread,
    }));
    markMessageRead.mockImplementation(async () => { unread = 20; return { ...message, is_read: true }; });
    showInbox();
    await settle();
    await openInbox();
    fireEvent.click(screen.getByRole('button', { name: '未读', exact: true }));
    await settle();
    fireEvent.click(screen.getByRole('button', { name: '下一页' }));
    await settle();
    expect(fetchMessages).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, status: 'unread' }));
    fireEvent.click(screen.getByRole('button', { name: `查看消息：${message.title}` }));
    await settle();
    expect(fetchMessages).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, status: 'unread' }));
    fireEvent.click(screen.getByRole('button', { name: /返回消息列表/ }));
    await settle();
    expect(screen.getByRole('button', { name: `查看消息：${message.title}` })).toBeInTheDocument();
    expect(screen.queryByText('暂无未读消息')).not.toBeInTheDocument();
});

test('detail errors retain retry and unsafe action paths never expose navigation', async () => {
    fetchMessage.mockRejectedValueOnce(new Error('消息已不存在'));
    fetchMessage.mockResolvedValue({ ...message, action_path: '//external.test', is_read: true });
    showInbox();
    await settle();
    await openInbox();
    fireEvent.click(screen.getByRole('button', { name: `查看消息：${message.title}` }));
    await settle();
    expect(screen.getByRole('alert')).toHaveTextContent('消息已不存在');
    fireEvent.click(screen.getByRole('button', { name: '重试', exact: true }));
    await settle();
    expect(screen.getByRole('heading', { name: message.title })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '前往处理' })).not.toBeInTheDocument();
});
