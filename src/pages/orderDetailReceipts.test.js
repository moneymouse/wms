import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import dayjs from 'dayjs';

import OrderDetail from './orderDetail';

jest.mock('antd/es/input/Input', () => ({
    __esModule: true,
    default: jest.requireActual('antd').Input,
}));
jest.mock('../components/ExportButton', () => () => null);
jest.mock('../components/BoxAssignmentModal', () => () => null);
jest.mock('../components/FeatureTour', () => () => null);
jest.mock('../components/transportation', () => () => null);

jest.setTimeout(15000);

const order = {
    uid: 'order-uid', order_id: 'ORDER-1', transportation: 'DHL', total_weight: 10,
    salesman: { id: 7, name: '业务员甲' }, customer_ids: null,
    customer_id: 99, customer_name: '旧客户',
};
const effectiveQuote = {
    id: 12, version_no: 1, unit_price: 10, surcharge: 0,
    receivable_amount: 100, quoter_id: 7, quoter_name: '业务员甲',
    is_final: true, is_effective: true, validity_status: 'effective',
};
const collectibleOrder = {
    uid: 'order-uid', order_id: 'ORDER-1', customer_id: 42, customer_name: '收款客户',
    quoter_id: 7, quoter_name: '业务员甲', billing_weight: 10,
    receivable_amount: 100, approved_received: 10, pending_amount: 15,
    available_amount: 75,
};

function response(data, extra = {}) {
    return { ok: true, json: async () => ({ code: 200, data, ...extra }) };
}

function setJwt(roles = ['salesperson'], userId = 7) {
    const payload = window.btoa(JSON.stringify({ user_id: userId, roles }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
}

function mockApi(overrides = {}) {
    global.fetch = jest.fn(async (rawUrl, options) => {
        const url = new URL(rawUrl, 'http://localhost');
        const pathname = url.pathname;
        if (pathname.endsWith('/receipts') && options?.method === 'POST') {
            return overrides.submit ? overrides.submit(options) : response({ id: 23, receipt_no: 'RC-23' });
        }
        if (pathname.endsWith('/receipts/23/pdf')) return response('cGRm', { mime_type: 'application/pdf' });
        if (pathname.endsWith('/receivables/orders')) {
            const rows = overrides.orders === undefined ? [collectibleOrder] : overrides.orders;
            return response(rows, { page: 1, page_size: 20, total: rows.length });
        }
        if (pathname.endsWith('/receivable-adjustments')) {
            const rows = overrides.adjustments || [];
            return response(rows, { page: 1, page_size: 20, total: rows.length });
        }
        if (pathname.endsWith('/orders/order-uid/quotes')) {
            return response(typeof overrides.quotes === 'function'
                ? overrides.quotes()
                : overrides.quotes === undefined ? [effectiveQuote] : overrides.quotes);
        }
        if (pathname.endsWith('/orders/order-uid/salesman')) return response((overrides.order || order).salesman);
        if (pathname.endsWith('/orders/order-uid')) return response(overrides.order || order);
        return response([]);
    });
}

function renderOrder() {
    return render(<MemoryRouter initialEntries={['/orders/order-uid']}>
        <Routes><Route path="/orders/:order_id" element={<OrderDetail />} /></Routes>
    </MemoryRouter>);
}

function callsFor(pathname) {
    return global.fetch.mock.calls.filter(([url]) => new URL(url, 'http://localhost').pathname.endsWith(pathname));
}

function receiptPosts() {
    return callsFor('/receipts').filter(([, options]) => options?.method === 'POST');
}

async function waitForInitialOrder() {
    await screen.findByText('DHL');
    await waitFor(() => expect(callsFor('/orders/order-uid/quotes').length).toBeGreaterThan(0));
}

async function openReceiptModal() {
    fireEvent.click(await screen.findByRole('button', { name: /收\s*款/ }));
    return screen.findByRole('dialog', { name: '确认收款信息' });
}

async function selectOption(label, option) {
    const modal = within(screen.getByRole('dialog'));
    fireEvent.mouseDown(modal.getByLabelText(label));
    fireEvent.click(await screen.findByText(option, { selector: '.ant-select-item-option-content' }));
}

async function changeReceiptDate(date) {
    const modal = within(screen.getByRole('dialog'));
    const input = modal.getByLabelText('收款日期');
    fireEvent.mouseDown(input);
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: date } });
    fireEvent.keyDown(input, { key: 'Enter', keyCode: 13 });
    await waitFor(() => expect(input).toHaveValue(date));
}

let preview;
const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;

beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    setJwt();
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({
        matches: false, media: query, onchange: null,
        addListener: () => {}, removeListener: () => {}, addEventListener: () => {},
        removeEventListener: () => {}, dispatchEvent: () => false,
    }) });
    preview = { document: { write: jest.fn() }, location: {}, close: jest.fn() };
    jest.spyOn(window, 'open').mockReturnValue(preview);
    URL.createObjectURL = jest.fn(() => 'blob:order-receipt');
    URL.revokeObjectURL = jest.fn();
    mockApi();
});

afterEach(() => {
    jest.restoreAllMocks();
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
});

test('initial effective quote exposes the receipt action beside quote without opening the quote dialog', async () => {
    renderOrder();
    const receiptButton = await screen.findByRole('button', { name: /收\s*款/ });
    const quoteButton = screen.getByRole('button', { name: /报\s*价/ });
    expect(receiptButton).not.toBeDisabled();
    // Inspect Ant Design's shared toolbar wrapper to verify the action's placement.
    // eslint-disable-next-line testing-library/no-node-access
    expect(within(quoteButton.closest('.ant-space')).getByRole('button', { name: /收\s*款/ })).toBe(receiptButton);
    expect(quoteButton.compareDocumentPosition(receiptButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(callsFor('/orders/order-uid/quotes').length).toBeGreaterThan(0);
    expect(callsFor('/receivables/orders')).toHaveLength(0);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

test.each([
    ['no quote', []],
    ['pending quote', [{ ...effectiveQuote, is_final: false, is_effective: false, validity_status: 'pending' }]],
    ['stale final quote', [{ ...effectiveQuote, is_effective: false, validity_status: 'stale' }]],
])('%s does not expose receipt collection', async (_, quotes) => {
    mockApi({ quotes });
    renderOrder();
    await waitForInitialOrder();
    expect(screen.queryByRole('button', { name: /收\s*款/ })).not.toBeInTheDocument();
    expect(receiptPosts()).toHaveLength(0);
});

test.each([
    ['other salesperson', ['salesperson'], 99],
    ['finance user', ['finance'], 7],
])('%s cannot collect an effective quote outside receipt permissions', async (_, roles, userId) => {
    setJwt(roles, userId);
    renderOrder();
    await waitForInitialOrder();
    expect(screen.queryByRole('button', { name: /收\s*款/ })).not.toBeInTheDocument();
});

test('a clerk loads the order without requesting quotes or exposing collection', async () => {
    setJwt(['clerk']);
    renderOrder();
    await screen.findByText('DHL');
    expect(callsFor('/orders/order-uid/quotes')).toHaveLength(0);
    expect(screen.queryByRole('button', { name: /收\s*款/ })).not.toBeInTheDocument();
});

test('the quote owner can collect when the assigned order salesperson has changed', async () => {
    mockApi({ order: { ...order, salesman: { id: 99, name: '其他业务员' } } });
    renderOrder();
    expect(await screen.findByRole('button', { name: /收\s*款/ })).not.toBeDisabled();
    expect(screen.queryByRole('button', { name: /报\s*价/ })).not.toBeInTheDocument();
});

test('admin can collect another salespersons effective quote', async () => {
    setJwt(['admin'], 99);
    renderOrder();
    expect(await screen.findByRole('button', { name: /收\s*款/ })).not.toBeDisabled();
});

test('partial collection submits current receivable customer and date, opens the receipt PDF, and refreshes quote validity', async () => {
    let submitted = false;
    mockApi({
        quotes: () => [{ ...effectiveQuote, is_effective: !submitted }],
        submit: () => {
            submitted = true;
            return response({ id: 23, receipt_no: 'RC-23' });
        },
    });
    renderOrder();
    const modal = within(await openReceiptModal());
    const orderQuery = new URL(callsFor('/receivables/orders')[0][0], 'http://localhost').searchParams;
    expect(orderQuery.get('order_uid')).toBe('order-uid');
    expect(orderQuery.has('order_id')).toBe(false);
    expect(modal.getByText('客户：收款客户')).toBeInTheDocument();
    expect(Number(modal.getByLabelText('本次收款(CNY)').value)).toBe(75);
    expect(modal.getByLabelText('收款日期')).toHaveValue(dayjs().format('YYYY-MM-DD'));
    fireEvent.change(modal.getByLabelText('本次收款(CNY)'), { target: { value: '35' } });
    await changeReceiptDate('2026-10-04');
    await selectOption('收款方式', '银行转账 / Bank Transfer');
    await selectOption('结清状态', '已结清');
    fireEvent.change(modal.getByLabelText('备注'), { target: { value: '订单页部分收款' } });
    const initialQuoteRequests = callsFor('/orders/order-uid/quotes').length;
    fireEvent.click(modal.getByRole('button', { name: '确认提交' }));
    await waitFor(() => expect(receiptPosts()).toHaveLength(1));
    expect(JSON.parse(receiptPosts()[0][1].body)).toEqual({
        customer_id: 42, receipt_date: '2026-10-04', payment_method: 'bank_transfer',
        settlement_status: 'settled', remark: '订单页部分收款',
        items: [{ order_uid: 'order-uid', amount: 35 }],
    });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() => expect(preview.location.href).toBe('blob:order-receipt'));
    expect(window.open).toHaveBeenCalledWith('', '_blank');
    expect(callsFor('/receipts/23/pdf')).toHaveLength(1);
    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    await waitFor(() => expect(callsFor('/orders/order-uid/quotes').length).toBeGreaterThan(initialQuoteRequests));
    await waitFor(() => expect(screen.queryByRole('button', { name: /收\s*款/ })).not.toBeInTheDocument());
});

test('historical settlement difference reduces the remaining balance and defaults a partial collection to settled', async () => {
    mockApi({ orders: [{
        ...collectibleOrder, receivable_amount: 165, approved_received: 127,
        settlement_difference: 5, pending_amount: 0, available_amount: 33,
    }] });
    renderOrder();
    const modal = within(await openReceiptModal());
    fireEvent.change(modal.getByLabelText('本次收款(CNY)'), { target: { value: '4' } });
    expect(await modal.findByText('本次收款后剩余应收合计：29.00 CNY')).toBeInTheDocument();
    expect(modal.getByText('已结清', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
    fireEvent.click(modal.getByRole('button', { name: '确认提交' }));
    await waitFor(() => expect(receiptPosts()).toHaveLength(1));
    expect(JSON.parse(receiptPosts()[0][1].body)).toEqual({
        customer_id: 42, receipt_date: dayjs().format('YYYY-MM-DD'), payment_method: 'cash',
        settlement_status: 'settled', remark: '', items: [{ order_uid: 'order-uid', amount: 4 }],
    });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});

test.each([
    ['missing collectible row', []],
    ['exhausted available balance', [{ ...collectibleOrder, available_amount: 0 }]],
])('%s warns and never submits a receipt', async (_, orders) => {
    mockApi({ orders });
    renderOrder();
    fireEvent.click(await screen.findByRole('button', { name: /收\s*款/ }));
    expect(await screen.findByText('当前订单没有可收余额')).toBeInTheDocument();
    const adjustmentQueries = callsFor('/receivable-adjustments').map(([url]) => new URL(url, 'http://localhost').searchParams);
    expect(adjustmentQueries.some(params => params.get('order_uid') === 'order-uid' && params.get('status') === 'pending')).toBe(true);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(receiptPosts()).toHaveLength(0);
    expect(callsFor('/receipts/23/pdf')).toHaveLength(0);
});

test('a pending collection adjustment opens the shared adjustment form and submits its partial receipt with a PDF', async () => {
    mockApi({
        orders: [],
        adjustments: [{
            id: 31, order_uid: 'order-uid', order_id: 'ORDER-1',
            customer_id: 42, customer_name: '收款客户', quoter_id: 7,
            old_receivable: 100, new_receivable: 140, delta_amount: 40,
            direction: 'collect', status: 'pending', approved_received: 15,
            pending_amount: 0, available_amount: 25,
        }],
    });
    renderOrder();
    fireEvent.click(await screen.findByRole('button', { name: /收\s*款/ }));
    const modal = within(await screen.findByRole('dialog'));
    expect(modal.getByText('登记差价补收')).toBeInTheDocument();
    expect(modal.getByText('客户：收款客户')).toBeInTheDocument();
    expect(Number(modal.getByLabelText('本次补收(CNY)').value)).toBe(25);
    fireEvent.change(modal.getByLabelText('本次补收(CNY)'), { target: { value: '12.5' } });
    fireEvent.change(modal.getByLabelText('备注'), { target: { value: '订单页差价补收' } });
    await selectOption('收款方式', '微信 / WeChat Pay');
    fireEvent.click(modal.getByRole('button', { name: '确认提交' }));
    await waitFor(() => expect(receiptPosts()).toHaveLength(1));
    expect(JSON.parse(receiptPosts()[0][1].body)).toEqual({
        customer_id: 42, receipt_date: dayjs().format('YYYY-MM-DD'), payment_method: 'wechat',
        settlement_status: 'unsettled', remark: '订单页差价补收',
        items: [{ order_uid: 'order-uid', amount: 12.5, adjustment_id: 31 }],
    });
    const query = new URL(callsFor('/receivable-adjustments')[0][0], 'http://localhost').searchParams;
    expect(query.get('order_uid')).toBe('order-uid');
    expect(query.get('status')).toBe('pending');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() => expect(preview.location.href).toBe('blob:order-receipt'));
    expect(callsFor('/receipts/23/pdf')).toHaveLength(1);
});

test.each(['0', '76'])('an invalid collection amount %s cannot create a receipt', async amount => {
    renderOrder();
    const modal = within(await openReceiptModal());
    fireEvent.change(modal.getByLabelText('本次收款(CNY)'), { target: { value: amount } });
    fireEvent.click(modal.getByRole('button', { name: '确认提交' }));
    expect(await modal.findByText('本次收款必须大于 0 且不超过可收余额')).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: '确认收款信息' })).toBeInTheDocument();
    expect(receiptPosts()).toHaveLength(0);
    expect(callsFor('/receipts/23/pdf')).toHaveLength(0);
});

test('submission error preserves amount and form fields for a successful retry', async () => {
    let attempts = 0;
    let finishRetry;
    mockApi({ submit: () => {
        attempts += 1;
        if (attempts === 1) return { ok: false, json: async () => ({ code: 400, msg: '可收余额已变化' }) };
        return new Promise(resolve => { finishRetry = resolve; });
    } });
    renderOrder();
    const modal = within(await openReceiptModal());
    fireEvent.change(modal.getByLabelText('本次收款(CNY)'), { target: { value: '35' } });
    fireEvent.change(modal.getByLabelText('备注'), { target: { value: '保留后重试' } });
    await selectOption('结清状态', '未结清');
    fireEvent.click(modal.getByRole('button', { name: '确认提交' }));
    expect(await screen.findByText('可收余额已变化')).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: '确认收款信息' })).toBeInTheDocument();
    expect(Number(modal.getByLabelText('本次收款(CNY)').value)).toBe(35);
    expect(modal.getByLabelText('备注')).toHaveValue('保留后重试');
    expect(modal.getByText('未结清', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
    expect(callsFor('/receipts/23/pdf')).toHaveLength(0);
    const confirm = modal.getByRole('button', { name: '确认提交' });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await waitFor(() => expect(receiptPosts()).toHaveLength(2));
    expect(JSON.parse(receiptPosts()[1][1].body)).toEqual(JSON.parse(receiptPosts()[0][1].body));
    await act(async () => finishRetry(response({ id: 23, receipt_no: 'RC-23' })));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() => expect(preview.location.href).toBe('blob:order-receipt'));
    expect(receiptPosts()).toHaveLength(2);
});
