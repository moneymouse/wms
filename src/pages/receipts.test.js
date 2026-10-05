import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import dayjs from 'dayjs';

import Receipts from './receipts';

jest.mock('../components/FeatureTour', () => () => null);

jest.setTimeout(15000);

const order = {
    uid: 'order-1', order_id: 'ORDER-1', customer_id: 1, customer_name: '客户A',
    create_date: '2026-08-27 09:12:34', quoter_name: '业务员A',
    billing_weight: 10, receivable_amount: 100, approved_received: 0,
    pending_amount: 0, available_amount: 100,
};
const secondOrder = { ...order, uid: 'order-2', order_id: 'ORDER-2', create_date: null };
const thirdOrder = { ...order, uid: 'order-3', order_id: 'ORDER-3', customer_id: 2, customer_name: '客户B' };
const rejectedReceipt = {
    id: 9, receipt_no: 'RC-REJECTED', customer_id: 1, customer_name: '客户A',
    receipt_date: '2026-08-26', total_amount: 45, status: 'rejected',
    payment_method: 'bank_transfer', remark: '重新登记', settlement_status: 'settled',
    items: [{ order_uid: 'order-1', amount: 45 }],
};

function response(data, extra = {}) {
    return { ok: true, json: async () => ({ code: 200, data, ...extra }) };
}

function mockApi(overrides = {}) {
    global.fetch = jest.fn(async (url, options) => {
        const parsed = new URL(url, 'http://localhost');
        if (parsed.pathname.endsWith('/receivables/orders')) {
            if (overrides.orders) return overrides.orders(parsed.searchParams);
            return response([order, secondOrder, thirdOrder], { page: 1, page_size: 20, total: 3 });
        }
        if (parsed.pathname.endsWith('/receivable-adjustments')) {
            return response(overrides.adjustments || [], { page: 1, page_size: 20, total: (overrides.adjustments || []).length });
        }
        if (options?.method === 'POST') {
            return overrides.submit ? overrides.submit(options) : response({ id: 10, receipt_no: 'RC-NEW' });
        }
        if (parsed.pathname.endsWith('/customer_list')) return response([{ id: 1, name: '客户A' }, { id: 2, name: '客户B' }]);
        if (parsed.pathname.endsWith('/work/workers')) return response([{ id: 7, name: '业务员A' }]);
        if (parsed.pathname.endsWith('/receipts/9')) return response(overrides.detail ? overrides.detail() : rejectedReceipt);
        if (parsed.pathname.endsWith('/receipts')) return response(overrides.receipts || [rejectedReceipt], { page: 1, page_size: 20, total: 1 });
        if (parsed.pathname.endsWith('/pdf')) return response('cGRm');
        throw new Error(`Unexpected request: ${url}`);
    });
}

test('shows pending re-quote adjustments as non-cash tasks', async () => {
    mockApi({
        adjustments: [{
            id: 3,
            order_uid: 'order-1',
            order_id: 'ORDER-1',
            customer_name: '客户A',
            old_receivable: 100,
            new_receivable: 85,
            delta_amount: -15,
            direction: 'refund',
            status: 'pending',
            quoter_name: '业务员A',
            create_date: '2026-09-17 10:00:00',
        }],
    });
    renderPage();

    expect(await screen.findByText('待退款')).toBeInTheDocument();
    expect(screen.getByText('-15.00')).toBeInTheDocument();
    expect(screen.getByText(/不代表现金已经收取或退还/)).toBeInTheDocument();
});

function renderPage(admin = false) {
    const payload = window.btoa(JSON.stringify({ user_id: 7, roles: [admin ? 'admin' : 'salesperson'] }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
    return render(<MemoryRouter><Receipts /></MemoryRouter>);
}

function rowFor(id = 'ORDER-1') {
    return screen.getByRole('link', { name: id }).closest('tr');
}

async function selectOrder(id = 'ORDER-1') {
    await screen.findByRole('link', { name: id });
    fireEvent.click(within(rowFor(id)).getByRole('checkbox'));
}

async function selectOption(label, option) {
    fireEvent.mouseDown(screen.getByLabelText(label));
    fireEvent.click(await screen.findByText(option, { selector: '.ant-select-item-option-content' }));
}

async function setDateRange() {
    const start = screen.getByPlaceholderText('开始日期');
    const end = screen.getByPlaceholderText('结束日期');
    fireEvent.mouseDown(start);
    fireEvent.focus(start);
    fireEvent.change(start, { target: { value: '2026-08-01' } });
    fireEvent.keyDown(start, { key: 'Enter', keyCode: 13 });
    fireEvent.focus(end);
    fireEvent.change(end, { target: { value: '2026-08-31' } });
    fireEvent.keyDown(end, { key: 'Enter', keyCode: 13 });
    await waitFor(() => expect(lastOrderQuery().get('date_to')).toBe('2026-08-31'));
}

function lastOrderQuery() {
    const calls = global.fetch.mock.calls.filter(([url]) => url.includes('/receivables/orders'));
    return new URL(calls[calls.length - 1][0], 'http://localhost').searchParams;
}

function postCalls() {
    return global.fetch.mock.calls.filter(([, options]) => options?.method === 'POST');
}

beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    window.matchMedia = jest.fn(query => ({
        matches: false, media: query, addListener: jest.fn(), removeListener: jest.fn(),
        addEventListener: jest.fn(), removeEventListener: jest.fn(),
    }));
    jest.spyOn(window, 'open').mockReturnValue(null);
    mockApi();
});

afterEach(() => jest.restoreAllMocks());

test('filters default to all dates, only admins load owners, and the action is above the order table', async () => {
    const { container } = renderPage();
    await screen.findByRole('link', { name: 'ORDER-1' });
    expect(screen.queryByLabelText('业务员')).not.toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([url]) => url.includes('/work/workers'))).toBe(false);
    expect(lastOrderQuery().has('date_from')).toBe(false);
    expect(lastOrderQuery().has('customer_id')).toBe(false);
    expect(within(rowFor()).getByText('2026-08-27 09:12:34')).toBeInTheDocument();
    expect(within(rowFor('ORDER-2')).getByText('-')).toBeInTheDocument();
    const action = screen.getByRole('button', { name: '生成并提交收款单' });
    expect(action).toBeDisabled();
    const orderTable = container.querySelector('[data-tour="receipt-orders"] .ant-table');
    expect(action.compareDocumentPosition(orderTable) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(container.querySelector('[data-tour="receipt-basics"]')).not.toHaveTextContent('收款日期');
});

test('admin filters combine, reset selection/page, and can be cleared', async () => {
    renderPage(true);
    await selectOrder();
    await selectOption('客户', '客户A');
    expect(lastOrderQuery().get('customer_id')).toBe('1');
    expect(screen.getByRole('button', { name: '生成并提交收款单' })).toBeDisabled();
    await selectOption('业务员', '业务员A');
    await setDateRange();
    expect(Object.fromEntries(lastOrderQuery())).toMatchObject({
        customer_id: '1', owner_id: '7', date_from: '2026-08-01', date_to: '2026-08-31', p: '1', s: '20',
    });
    fireEvent.mouseDown(screen.getByLabelText('业务员').closest('.ant-select').querySelector('.ant-select-clear'));
    await waitFor(() => expect(lastOrderQuery().has('owner_id')).toBe(false));
    fireEvent.mouseDown(screen.getByLabelText('客户').closest('.ant-select').querySelector('.ant-select-clear'));
    fireEvent.click(document.querySelector('.ant-picker-clear'));
    await waitFor(() => {
        expect(lastOrderQuery().has('date_from')).toBe(false);
        expect(lastOrderQuery().has('customer_id')).toBe(false);
    });
});

test('pagination preserves filters, cross-page selection and edited amounts', async () => {
    mockApi({ orders: params => response(
        params.get('p') === '2' ? [secondOrder] : [order],
        { page: Number(params.get('p')), page_size: 20, total: 21 },
    ) });
    renderPage();
    await selectOption('客户', '客户A');
    await selectOrder();
    fireEvent.change(within(rowFor()).getByRole('spinbutton'), { target: { value: '35' } });
    fireEvent.click(screen.getByTitle('2'));
    await selectOrder('ORDER-2');
    expect(lastOrderQuery().get('customer_id')).toBe('1');
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    let modal = within(screen.getByRole('dialog'));
    expect(modal.getByText('本次收款后剩余应收合计：65.00 CNY')).toBeInTheDocument();
    await selectOption('结清状态', '已结清');
    fireEvent.click(modal.getByRole('button', { name: /取\s*消/ }));
    fireEvent.click(screen.getByTitle('1'));
    await screen.findByRole('link', { name: 'ORDER-1' });
    expect(within(rowFor()).getByRole('spinbutton')).toHaveValue('35.00');
    expect(within(rowFor()).getByRole('checkbox')).toBeChecked();
    expect(within(document.querySelector('[data-tour="receipt-submit"]')).getByText('本次合计：135.00 CNY')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    modal = within(screen.getByRole('dialog'));
    expect(modal.getByText('已结清', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
});

test('late filter responses cannot replace the latest order list', async () => {
    let finishOldRequest;
    mockApi({ orders: params => params.get('customer_id') === '1'
        ? new Promise(resolve => { finishOldRequest = resolve; })
        : response(params.get('customer_id') === '2' ? [thirdOrder] : [order]) });
    renderPage();
    await selectOption('客户', '客户A');
    await selectOption('客户', '客户B');
    await screen.findByRole('link', { name: 'ORDER-3' });
    await act(async () => finishOldRequest(response([order])));
    expect(screen.queryByRole('link', { name: 'ORDER-1' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'ORDER-3' })).toBeInTheDocument();
});

test('a refreshed approved amount recalculates settlement while a pending-only change preserves a manual choice', async () => {
    let latestOrder = { ...order };
    mockApi({ orders: params => response(
        params.get('p') === '2' ? [secondOrder] : [latestOrder],
        { page: Number(params.get('p')), page_size: 20, total: 21 },
    ) });
    renderPage();
    await selectOrder();
    fireEvent.change(within(rowFor()).getByRole('spinbutton'), { target: { value: '60' } });
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    await selectOption('结清状态', '已结清');
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /取\s*消/ }));
    fireEvent.click(screen.getByTitle('2'));
    await screen.findByRole('link', { name: 'ORDER-2' });
    latestOrder = { ...order, pending_amount: 10, available_amount: 90 };
    fireEvent.click(screen.getByTitle('1'));
    await screen.findByRole('link', { name: 'ORDER-1' });
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    expect(within(screen.getByRole('dialog')).getByText('已结清', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /取\s*消/ }));
    fireEvent.click(screen.getByTitle('2'));
    await screen.findByRole('link', { name: 'ORDER-2' });
    latestOrder = { ...order, approved_received: 10, available_amount: 90 };
    fireEvent.click(screen.getByTitle('1'));
    await screen.findByRole('link', { name: 'ORDER-1' });
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    const modal = within(screen.getByRole('dialog'));
    expect(modal.getByText('本次收款后剩余应收合计：30.00 CNY')).toBeInTheDocument();
    expect(modal.getByText('未结清', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
});

test('opening/cancelling the modal does not submit, preserves inputs, and restricts customer selection', async () => {
    renderPage();
    await selectOrder();
    expect(within(rowFor('ORDER-3')).getByRole('checkbox')).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    const modal = within(await screen.findByRole('dialog'));
    expect(modal.getByText('客户：客户A')).toBeInTheDocument();
    expect(modal.getByLabelText('收款日期')).toHaveValue(dayjs().format('YYYY-MM-DD'));
    expect(modal.getByText('现金 / Cash')).toBeInTheDocument();
    expect(modal.getByText('已结清', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
    await selectOption('结清状态', '未结清');
    fireEvent.change(modal.getByLabelText('备注'), { target: { value: '保留备注' } });
    fireEvent.click(modal.getByRole('button', { name: /取\s*消/ }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    expect(within(screen.getByRole('dialog')).getByLabelText('备注')).toHaveValue('保留备注');
    expect(within(screen.getByRole('dialog')).getByText('未结清', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
    expect(postCalls()).toHaveLength(0);
});

test('empty amounts and missing receipt dates are rejected before submission', async () => {
    renderPage();
    await selectOrder();
    fireEvent.change(within(rowFor()).getByRole('spinbutton'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    let modal = within(screen.getByRole('dialog'));
    fireEvent.click(modal.getByRole('button', { name: '确认提交' }));
    await screen.findByText(/本次收款必须大于 0/);
    expect(postCalls()).toHaveLength(0);
    fireEvent.click(modal.getByRole('button', { name: /取\s*消/ }));
    fireEvent.change(within(rowFor()).getByRole('spinbutton'), { target: { value: '25' } });
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    modal = within(screen.getByRole('dialog'));
    fireEvent.click(modal.getByLabelText('收款日期').closest('.ant-picker').querySelector('.ant-picker-clear'));
    fireEvent.click(modal.getByRole('button', { name: '确认提交' }));
    await screen.findByText('请选择收款日期');
    expect(postCalls()).toHaveLength(0);
});

test('submission errors retain the dialog and successful retry submits once, refreshes, and resets the form', async () => {
    let finishSubmit;
    let attempts = 0;
    mockApi({ submit: () => {
        attempts += 1;
        if (attempts === 1) return { ok: false, json: async () => ({ code: 400, msg: '可收余额已变化' }) };
        return new Promise(resolve => { finishSubmit = resolve; });
    } });
    const preview = { document: { write: jest.fn() }, location: {}, close: jest.fn() };
    window.open.mockReturnValue(preview);
    URL.createObjectURL = jest.fn(() => 'blob:receipt');
    URL.revokeObjectURL = jest.fn();
    renderPage();
    await selectOrder();
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    const modal = within(screen.getByRole('dialog'));
    fireEvent.change(modal.getByLabelText('备注'), { target: { value: '收款测试' } });
    await selectOption('结清状态', '未结清');
    fireEvent.click(modal.getByRole('button', { name: '确认提交' }));
    await screen.findByText('可收余额已变化');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(modal.getByLabelText('备注')).toHaveValue('收款测试');
    expect(modal.getByText('未结清', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
    const confirmButton = modal.getByRole('button', { name: '确认提交' });
    fireEvent.click(confirmButton);
    fireEvent.click(confirmButton);
    await waitFor(() => expect(postCalls()).toHaveLength(2));
    expect(JSON.parse(postCalls()[1][1].body)).toEqual({
        customer_id: 1, receipt_date: dayjs().format('YYYY-MM-DD'), payment_method: 'cash',
        remark: '收款测试', settlement_status: 'unsettled', items: [{ order_uid: 'order-1', amount: 100 }],
    });
    await act(async () => finishSubmit(response({ id: 10, receipt_no: 'RC-NEW' })));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByRole('tab', { name: '收款单记录' })).toHaveAttribute('aria-selected', 'true');
    expect(preview.location.href).toBe('blob:receipt');
    fireEvent.click(screen.getByRole('tab', { name: '收款登记' }));
    await selectOrder();
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    expect(within(screen.getByRole('dialog')).getByLabelText('备注')).toHaveValue('');
});

test('copying a rejected receipt clears date/owner filters and prefills the modal', async () => {
    renderPage(true);
    await selectOption('业务员', '业务员A');
    await setDateRange();
    fireEvent.click(screen.getByRole('tab', { name: '收款单记录' }));
    fireEvent.click(await screen.findByRole('button', { name: /复制新建/ }));
    await waitFor(() => expect(screen.getByRole('tab', { name: '收款登记' })).toHaveAttribute('aria-selected', 'true'));
    expect(lastOrderQuery().get('customer_id')).toBe('1');
    expect(lastOrderQuery().has('date_from')).toBe(false);
    expect(lastOrderQuery().has('owner_id')).toBe(false);
    expect(within(rowFor()).getByRole('spinbutton')).toHaveValue('45.00');
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    const modal = within(screen.getByRole('dialog'));
    expect(modal.getByLabelText('备注')).toHaveValue('重新登记');
    expect(modal.getByText('银行转账 / Bank Transfer')).toBeInTheDocument();
    expect(modal.getByText('本次收款后剩余应收合计：55.00 CNY')).toBeInTheDocument();
    expect(modal.getByText('已结清', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
    fireEvent.click(modal.getByRole('button', { name: /取\s*消/ }));
    fireEvent.change(within(rowFor()).getByRole('spinbutton'), { target: { value: '40' } });
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    expect(within(screen.getByRole('dialog')).getByText('未结清', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
    expect(postCalls()).toHaveLength(0);
});

test('the modal recalculates the strict 30 CNY default when payment changes without changing actual amounts', async () => {
    renderPage();
    await selectOrder();
    fireEvent.change(within(rowFor()).getByRole('spinbutton'), { target: { value: '70.01' } });
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    let modal = within(screen.getByRole('dialog'));
    expect(modal.getByText('本次收款后剩余应收合计：29.99 CNY')).toBeInTheDocument();
    expect(modal.getByText('已结清', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
    await selectOption('结清状态', '未结清');
    fireEvent.click(modal.getByRole('button', { name: /取\s*消/ }));
    expect(within(rowFor()).getByRole('spinbutton')).toHaveValue('70.01');
    fireEvent.change(within(rowFor()).getByRole('spinbutton'), { target: { value: '70' } });
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    modal = within(screen.getByRole('dialog'));
    expect(modal.getByText('本次收款后剩余应收合计：30.00 CNY')).toBeInTheDocument();
    expect(modal.getByText('未结清', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
    await selectOption('结清状态', '已结清');
    fireEvent.click(modal.getByRole('button', { name: /取\s*消/ }));
    fireEvent.change(within(rowFor()).getByRole('spinbutton'), { target: { value: '50' } });
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    expect(within(screen.getByRole('dialog')).getByText('未结清', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
});

test('changing selected orders recalculates the aggregate default and ignores other pending amounts', async () => {
    mockApi({ orders: () => response([
        { ...order, pending_amount: 20, available_amount: 80 },
        { ...secondOrder, pending_amount: 20, available_amount: 80 },
    ]) });
    renderPage();
    await selectOrder();
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    let modal = within(screen.getByRole('dialog'));
    expect(modal.getByText('本次收款后剩余应收合计：20.00 CNY')).toBeInTheDocument();
    expect(modal.getByText('已结清', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
    await selectOption('结清状态', '未结清');
    fireEvent.click(modal.getByRole('button', { name: /取\s*消/ }));
    await selectOrder('ORDER-2');
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    modal = within(screen.getByRole('dialog'));
    expect(modal.getByText('本次收款后剩余应收合计：40.00 CNY')).toBeInTheDocument();
    expect(modal.getByText('未结清', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
    await selectOption('结清状态', '已结清');
    fireEvent.click(modal.getByRole('button', { name: /取\s*消/ }));
    fireEvent.click(within(rowFor('ORDER-2')).getByRole('checkbox'));
    fireEvent.change(within(rowFor()).getByRole('spinbutton'), { target: { value: '60' } });
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    expect(within(screen.getByRole('dialog')).getByText('未结清', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
});

test('copying a historic rejected receipt calculates a default without applying a historic settlement', async () => {
    mockApi({ receipts: [{ ...rejectedReceipt, settlement_status: null }] });
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: '收款单记录' }));
    expect(await screen.findByText('未设置')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /复制新建/ }));
    await waitFor(() => expect(screen.getByRole('tab', { name: '收款登记' })).toHaveAttribute('aria-selected', 'true'));
    fireEvent.click(screen.getByRole('button', { name: '生成并提交收款单' }));
    expect(within(screen.getByRole('dialog')).getByText('未结清', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
});

test('receipt details refresh their preview and keep settlement differences separate from received amounts', async () => {
    let previewDifference = 55;
    const pending = { ...rejectedReceipt, items: undefined, status: 'pending' };
    mockApi({
        receipts: [pending],
        detail: () => ({ ...pending, items: [{
            id: 1, order_uid: 'order-1', order_id: 'ORDER-DETAIL', amount: 45,
            receivable_snapshot: 100, remaining_after: 40, settlement_difference: null,
            preview_settlement_difference: previewDifference,
        }] }),
    });
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: '收款单记录' }));
    await screen.findByText('RC-REJECTED');
    expect(screen.getByRole('columnheader', { name: '审核状态' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '结清状态' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Expand row' }));
    await screen.findByRole('link', { name: 'ORDER-DETAIL' });
    expect(screen.getByRole('columnheader', { name: '预计结清差额' })).toBeInTheDocument();
    const detailRow = rowFor('ORDER-DETAIL');
    expect(within(detailRow).getByText('45.00')).toBeInTheDocument();
    expect(within(detailRow).getByText('55.00')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Collapse row' }));
    previewDifference = 35;
    fireEvent.click(screen.getByRole('button', { name: 'Expand row' }));
    await waitFor(() => expect(within(rowFor('ORDER-DETAIL')).getByText('35.00')).toBeInTheDocument());
    expect(global.fetch.mock.calls.filter(([url]) => url.endsWith('/receipts/9'))).toHaveLength(2);
});
