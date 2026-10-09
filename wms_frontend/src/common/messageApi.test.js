import {
    fetchMessage, fetchMessages, fetchUnreadCount, isInternalMessagePath,
    markAllMessagesRead, markMessageRead, sendMessage, MESSAGE_POLL_INTERVAL,
} from './messageApi';

jest.mock('../config', () => ({ endpoint: '/api' }));
jest.mock('./safeHeader', () => () => ({ 'x-token': 'current-user', 'x-time': '123' }));

beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ code: 200, data: { unread_count: 2 } }) });
});
afterEach(() => jest.restoreAllMocks());

test('messages request the correct page/filter and preserve the captured account token and cancellation', async () => {
    const controller = new AbortController();
    await fetchMessages({ page: 2, pageSize: 20, status: 'unread', signal: controller.signal, token: 'request-owner' });
    expect(global.fetch).toHaveBeenCalledWith('/api/messages?page=2&page_size=20&status=unread', {
        method: 'GET', signal: controller.signal, headers: { 'x-token': 'request-owner', 'x-time': '123' },
    });
    expect(MESSAGE_POLL_INTERVAL).toBe(180000);
});

test('detail and read requests encode identifiers and use authenticated server mutations', async () => {
    await fetchUnreadCount();
    await fetchMessage('message / 1');
    await markMessageRead('message / 1');
    await markAllMessagesRead();
    expect(global.fetch.mock.calls.map(([url, options]) => [url, options.method, options.headers['x-token']])).toEqual([
        ['/api/messages/unread-count', 'GET', 'current-user'],
        ['/api/messages/message%20%2F%201', 'GET', 'current-user'],
        ['/api/messages/message%20%2F%201/read', 'POST', 'current-user'],
        ['/api/messages/read-all', 'POST', 'current-user'],
    ]);
});

test('server errors retain status and business code so expired accounts can leave the inbox', async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 401, json: async () => ({ code: 401, msg: '请重新登录' }) });
    await expect(fetchUnreadCount()).rejects.toMatchObject({ message: '请重新登录', status: 401, code: 401 });
    global.fetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({ code: 403, msg: '无权查看此消息' }) });
    await expect(fetchMessage('someone-elses-message')).rejects.toThrow('无权查看此消息');
});

test('non-JSON responses report the failure and keep authentication status', async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 401, json: async () => { throw new Error('invalid json'); } });
    await expect(fetchUnreadCount()).rejects.toMatchObject({ message: '服务器返回格式错误，请稍后重试', status: 401 });
});

test('authorized producers send JSON reminders with recipient, processing context, and an idempotency key', async () => {
    const body = { recipient_id: 7, title: '物流异常', body: '请联系客户核实地址',
        action_path: '/orders/order-1', category: 'logistics_exception', event_key: 'tracking:order-1:delivery-failed' };
    const controller = new AbortController();
    await sendMessage(body, { token: 'producer-account', signal: controller.signal });
    expect(global.fetch).toHaveBeenCalledWith('/api/messages', {
        method: 'POST', signal: controller.signal,
        headers: { 'x-token': 'producer-account', 'x-time': '123', 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
});

test('producer conflicts remain errors when the HTTP response succeeds', async () => {
    global.fetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({ code: 409, msg: '事件标识已用于不同内容' }) });
    await expect(sendMessage({ event_key: 'existing-event', recipient_id: 7 })).rejects.toMatchObject({
        code: 409, message: '事件标识已用于不同内容',
    });
});

test.each(['/receipts?payment_uid=payment-1', '/orders/order-1', '/orders/order-1#tracking'])('allows internal processing path %s', path => {
    expect(isInternalMessagePath(path)).toBe(true);
});

const scriptPath = ['javascript', 'alert(1)'].join(':');
test.each(['https://external.test', '//external.test', '/\\external.test', scriptPath, '/orders/\nitem', '', null])('rejects unsafe message path %s', path => {
    expect(isInternalMessagePath(path)).toBe(false);
});
