import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import Receipts from './receipts';
import MessageInbox from '../components/MessageInbox';
import { fetchMessage, fetchMessages, fetchUnreadCount, markMessageRead } from '../common/messageApi';

jest.mock('../config', () => ({ endpoint: '/api' }));
jest.mock('../components/FinanceHistoryDrawer', () => () => null);
jest.mock('../common/messageApi', () => ({
    ...jest.requireActual('../common/messageApi'),
    fetchMessage: jest.fn(), fetchMessages: jest.fn(), fetchUnreadCount: jest.fn(),
    markMessageRead: jest.fn(), markAllMessagesRead: jest.fn(),
}));

const context = { customerId: 2, customerName: '客户甲', orderUid: 'order-1', orderNumber: 'ORDER-1' };
const payment = id => ({
    id, number: `PAY-${String(id).padStart(4, '0')}`, partner_type: 'customer', partner_id: 2, partner_name: '客户甲',
    direction: 'incoming', account_id: 1, account_name: '银行账户', payment_date: '2026-10-07', amount: '100.00',
    unallocated_amount: '100.00', allocated_amount: '0.00', status: 'draft', version: 4,
    created_by_id: 7, created_by_name: '业务员甲', requires_submission: true, review_remark: `凭证金额需核对 ${id}`,
    reference_order_uids: [], reference_orders: [],
});
const response = data => Promise.resolve({ ok: true, status: 200, json: async () => ({ code: 200, data }) });
const list = items => ({ items, total: items.length, page: 1, page_size: 20 });
const notification = { uid: 'return-42', title: '收付款 PAY-0042 退回修改', body: '财务请您核对凭证金额',
    source_name: '财务部', category: 'finance_return', action_path: '/receipts?payment_id=42', is_read: false };

function NavigationHarness({ inbox = false }) {
    const location = useLocation();
    const navigate = useNavigate();
    return <>
        <Receipts />{inbox && <MessageInbox />}
        <output data-testid="location">{location.pathname}{location.search}{location.hash}</output>
        <output data-testid="navigation-state">{JSON.stringify(location.state)}</output>
        <button onClick={() => navigate('/receipts?payment_id=42', { state: location.state })}>打开消息关联 42</button>
        <button onClick={() => navigate('/receipts?payment_id=43', { state: location.state })}>打开消息关联 43</button>
        <button onClick={() => navigate('/receipts', { state: { paymentContext: context } })}>新登记上下文</button>
        <button onClick={() => navigate(-1)}>浏览器后退</button>
        <button onClick={() => navigate(1)}>浏览器前进</button>
    </>;
}

function showPage(initialEntries = ['/receipts?payment_id=42'], options = {}) {
    return render(<MemoryRouter initialEntries={initialEntries} initialIndex={initialEntries.length - 1}>
        <NavigationHarness {...options} />
    </MemoryRouter>);
}
const detailCalls = () => global.fetch.mock.calls.filter(([url]) => /\/payments\/\d+$/.test(String(url)));

beforeEach(() => {
    localStorage.clear(); sessionStorage.clear();
    localStorage.setItem('jwt', `h.${btoa(JSON.stringify({ user_id: 7, roles: ['salesperson'] }))}.s`);
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({ matches: false, media: query,
        onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {} }) });
    global.fetch = jest.fn(rawUrl => {
        const url = new URL(rawUrl, 'http://localhost');
        const path = url.pathname.replace('/api/finance/v2', '');
        if (path === '/payments') return response(list([payment(1)]));
        if (/^\/payments\/\d+$/.test(path)) return response(payment(Number(path.split('/').pop())));
        if (path === '/payment-options/customers') return response(list([{ id: 2, name: '客户甲' }]));
        if (path === '/payment-options/accounts') return response(list([{ id: 1, name: '银行账户', currency: 'CNY' }]));
        if (path === '/payment-options/orders') return response(list([{ order_uid: 'order-1', order_number: 'ORDER-1', customer_id: 2 }]));
        if (path === '/payment-options/packing-boxes') return response(list([]));
        if (url.pathname === '/api/receipts') return response([]);
        throw new Error(`Unexpected request ${rawUrl}`);
    });
    let unread = 1;
    fetchUnreadCount.mockImplementation(async () => ({ unread_count: unread }));
    fetchMessages.mockResolvedValue({ items: [notification], total: 1, unread_count: 1 });
    fetchMessage.mockResolvedValue(notification);
    markMessageRead.mockImplementation(async () => { unread = 0; return { ...notification, is_read: true }; });
});
afterEach(() => jest.restoreAllMocks());

test('a message link loads the exact payment outside the filtered first page and shows its return reason without auto-editing', async () => {
    showPage();
    const drawer = await screen.findByRole('dialog', { name: 'PAY-0042' });
    expect(within(drawer).getByText('退回原因：凭证金额需核对 42')).toBeInTheDocument();
    expect(within(drawer).getByRole('button', { name: '编辑草稿' })).toBeEnabled();
    expect(screen.queryByRole('dialog', { name: '登记收付款' })).not.toBeInTheDocument();
    expect(detailCalls().map(([url]) => url)).toEqual(['/api/finance/v2/payments/42']);
    const listRequest = global.fetch.mock.calls.find(([url]) => new URL(url, 'http://localhost').pathname === '/api/finance/v2/payments');
    expect(new URL(listRequest[0], 'http://localhost').searchParams.get('created_by_id')).toBe('7');
    expect(new URL(listRequest[0], 'http://localhost').searchParams.get('partner_type')).toBe('customer');
    expect(detailCalls()[0][1].headers['x-token']).toBe(localStorage.getItem('jwt'));
    expect(global.fetch.mock.calls.some(([, options]) => options.method !== 'GET')).toBe(false);
});

test('closing consumes only payment_id, preserves unrelated query/hash/state, and never opens a retained creation context', async () => {
    const state = { paymentContext: context, previousSection: 'orders' };
    showPage([{ pathname: '/receipts', search: '?payment_id=42&view=returned', hash: '#record', state }]);
    const drawer = await screen.findByRole('dialog', { name: 'PAY-0042' });
    fireEvent.click(within(drawer).getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByTestId('location')).toHaveTextContent('/receipts?view=returned#record');
    expect(screen.getByTestId('navigation-state')).toHaveTextContent(JSON.stringify(state));
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/payment-options/'))).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: '打开消息关联 42' }));
    expect(await screen.findByRole('dialog', { name: 'PAY-0042' })).toBeInTheDocument();
    expect(detailCalls()).toHaveLength(2);
    expect(screen.queryByRole('dialog', { name: '登记收付款' })).not.toBeInTheDocument();
});

test('a repeated navigation to the same payment refreshes its detail', async () => {
    showPage();
    await screen.findByRole('dialog', { name: 'PAY-0042' });
    fireEvent.click(screen.getByRole('button', { name: '打开消息关联 42' }));
    await waitFor(() => expect(detailCalls()).toHaveLength(2));
    expect(await screen.findByText('退回原因：凭证金额需核对 42')).toBeInTheDocument();
});

test('a newer target cancels the older request and never displays the older response', async () => {
    const original = global.fetch.getMockImplementation();
    let resolvePrevious;
    global.fetch.mockImplementation((url, options) => String(url).endsWith('/payments/42')
        ? new Promise(resolve => { resolvePrevious = resolve; }) : original(url, options));
    showPage();
    await waitFor(() => expect(detailCalls()).toHaveLength(1));
    const firstSignal = detailCalls()[0][1].signal;
    fireEvent.click(screen.getByRole('button', { name: '打开消息关联 43' }));
    expect(await screen.findByRole('dialog', { name: 'PAY-0043' })).toBeInTheDocument();
    expect(firstSignal.aborted).toBe(true);
    await act(async () => { resolvePrevious(await response(payment(42))); });
    expect(screen.queryByText('退回原因：凭证金额需核对 42')).not.toBeInTheDocument();
    expect(screen.getByText('退回原因：凭证金额需核对 43')).toBeInTheDocument();
});

test.each(['0', '-1', '1.5', '1e2', '9007199254740992', 'anything', ''])('invalid payment id %s is ignored without a detail or creation request', async paymentId => {
    showPage([{ pathname: '/receipts', search: `?payment_id=${encodeURIComponent(paymentId)}`, state: { paymentContext: context } }]);
    await screen.findByRole('button', { name: 'PAY-0001' });
    expect(detailCalls()).toHaveLength(0);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/payment-options/'))).toBe(false);
});

test.each([[403, '无权查看此收付款'], [404, '收付款记录不存在']])('server HTTP %s remains visible without broadening the list or opening a new payment', async (status, msg) => {
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => String(url).endsWith('/payments/42')
        ? Promise.resolve({ ok: false, status, json: async () => ({ code: status, msg }) }) : original(url, options));
    showPage([{ pathname: '/receipts', search: '?payment_id=42', state: { paymentContext: context } }]);
    expect(await screen.findByText(msg)).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: '收付款详情' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '编辑草稿' })).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: '登记收付款' })).not.toBeInTheDocument();
    const params = new URL(global.fetch.mock.calls.find(([url]) => String(url).includes('/payments?'))[0], 'http://localhost').searchParams;
    expect(params.get('created_by_id')).toBe('7');
});

test('an inbox jump on the receipts path selects the current records tab and opens the linked detail', async () => {
    showPage(['/receipts'], { inbox: true });
    fireEvent.click(screen.getByRole('tab', { name: '历史收款（只读）' }));
    fireEvent.click(screen.getByRole('button', { name: /^打开收件箱/ }));
    fireEvent.click(await screen.findByRole('button', { name: `查看消息：${notification.title}` }));
    fireEvent.click(await screen.findByRole('button', { name: '前往处理' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/receipts?payment_id=42');
    await waitFor(() => expect(detailCalls().map(([url]) => url)).toEqual(['/api/finance/v2/payments/42']));
    // Ant Design uses the same test-mode title ID for both the closed inbox and the new drawer.
    await screen.findByText('退回原因：凭证金额需核对 42');
    const detailDrawer = screen.getAllByRole('dialog').find(dialog => within(dialog).queryByText('退回原因：凭证金额需核对 42'));
    expect(detailDrawer).toBeVisible();
    expect(within(detailDrawer).getByText('PAY-0042')).toBeInTheDocument();
    expect(within(detailDrawer).getByRole('button', { name: '编辑草稿' })).toBeEnabled();
    expect(screen.getByRole('tab', { name: '收付款记录' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('location')).toHaveTextContent('/receipts?payment_id=42');
    expect(detailCalls()).toHaveLength(1);
});

test('ordinary creation context remains usable after a deep link has been closed', async () => {
    showPage();
    const drawer = await screen.findByRole('dialog', { name: 'PAY-0042' });
    fireEvent.click(within(drawer).getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: '新登记上下文' }));
    expect(await screen.findByRole('dialog', { name: '登记收付款' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '移除参考订单 ORDER-1' })).toBeInTheDocument();
    expect(screen.getByLabelText('金额(CNY)')).toHaveValue('');
});

test('closing replaces the current history entry so browser forward does not reopen a consumed link', async () => {
    showPage(['/receipts?view=list', '/receipts?payment_id=42&view=returned']);
    const drawer = await screen.findByRole('dialog', { name: 'PAY-0042' });
    fireEvent.click(within(drawer).getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: '浏览器后退' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/receipts?view=list');
    fireEvent.click(screen.getByRole('button', { name: '浏览器前进' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/receipts?view=returned');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(detailCalls()).toHaveLength(1);
});
