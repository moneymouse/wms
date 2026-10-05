import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import dayjs from 'dayjs';

import Receipts from './receipts';

jest.mock('../components/FeatureTour', () => () => null);

jest.setTimeout(15000);

const order = {
    uid: 'regular-order', order_id: 'ORDER-REGULAR', customer_id: 1, customer_name: '客户A',
    create_date: '2026-09-17 09:00:00', quoter_name: '业务员A',
    billing_weight: 10, receivable_amount: 100, approved_received: 20,
    pending_amount: 0, available_amount: 80,
};

const adjustment = {
    id: 3, order_uid: 'adjustment-order', order_id: 'ORDER-ADJUSTMENT',
    customer_id: 1, customer_name: '客户A', old_receivable: 100, new_receivable: 140,
    delta_amount: 40, direction: 'collect', status: 'pending',
    approved_received: 15, pending_amount: 0, available_amount: 25,
    collection_blocked_reason: null, quoter_name: '业务员A', create_date: '2026-09-17 10:00:00',
};

const rejectedAdjustmentReceipt = {
    id: 9, receipt_no: 'RC-ADJUSTMENT-REJECTED', customer_id: 1, customer_name: '客户A',
    receipt_date: '2026-09-16', total_amount: 30, status: 'rejected',
    settlement_status: 'unsettled', payment_method: 'bank_transfer', remark: '驳回后重新补收',
    items: [{ order_uid: 'adjustment-order', amount: 30, adjustment_id: 3 }],
};

function response(data, extra = {}) {
    return { ok: true, json: async () => ({ code: 200, data, ...extra }) };
}

function mockApi(overrides = {}) {
    global.fetch = jest.fn(async (url, options) => {
        const parsed = new URL(url, 'http://localhost');
        if (parsed.pathname.endsWith('/receivables/orders')) {
            return response(overrides.orders ? overrides.orders() : [order], { page: 1, page_size: 20, total: 1 });
        }
        if (parsed.pathname.endsWith('/receivable-adjustments')) {
            const rows = typeof overrides.adjustments === 'function'
                ? overrides.adjustments() : overrides.adjustments || [adjustment];
            return response(rows, { page: 1, page_size: 20, total: rows.length });
        }
        if (parsed.pathname.endsWith('/receivable-adjustments/3')) {
            return response(overrides.adjustmentDetail || adjustment);
        }
        if (parsed.pathname.endsWith('/receipts') && options?.method === 'POST') {
            return overrides.submit ? overrides.submit(options) : response({ id: 10, receipt_no: 'RC-ADJUSTMENT' });
        }
        if (parsed.pathname.endsWith('/customer_list')) return response([{ id: 1, name: '客户A' }]);
        if (parsed.pathname.endsWith('/receipts/9')) return response(rejectedAdjustmentReceipt);
        if (parsed.pathname.endsWith('/receipts')) {
            return response(overrides.receipts || [{
                id: 10, receipt_no: 'RC-ADJUSTMENT', customer_id: 1, customer_name: '客户A',
                receipt_date: dayjs().format('YYYY-MM-DD'), total_amount: 12.5,
                status: 'pending', settlement_status: 'unsettled',
            }], { page: 1, page_size: 20, total: 1 });
        }
        if (parsed.pathname.endsWith('/pdf')) return response('cGRm');
        throw new Error(`Unexpected request: ${url}`);
    });
}

function renderPage() {
    const payload = window.btoa(JSON.stringify({ user_id: 7, roles: ['salesperson'] }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
    return render(<MemoryRouter><Receipts /></MemoryRouter>);
}

function rowFor(id = 'ORDER-ADJUSTMENT') {
    return screen.getByRole('link', { name: id }).closest('tr');
}

async function openAdjustment() {
    await screen.findByRole('link', { name: 'ORDER-ADJUSTMENT' });
    fireEvent.click(within(rowFor()).getByRole('button', { name: '登记补收' }));
    const modal = within(await screen.findByRole('dialog'));
    expect(modal.getByText('登记差价补收')).toBeInTheDocument();
    return modal;
}

function adjustmentAmount(modal) {
    return modal.getByLabelText(/本次补收\s*[(（]CNY[)）]/);
}

async function selectPayment(modal, label) {
    fireEvent.mouseDown(modal.getByLabelText('收款方式'));
    fireEvent.click(await screen.findByText(label, { selector: '.ant-select-item-option-content' }));
}

function requestsFor(path, method = 'GET') {
    return global.fetch.mock.calls.filter(([url, options]) => (
        new URL(url, 'http://localhost').pathname.endsWith(path)
        && (options?.method || 'GET') === method
    ));
}

beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    window.matchMedia = jest.fn(query => ({
        matches: false, media: query, addListener: jest.fn(), removeListener: jest.fn(),
        addEventListener: jest.fn(), removeEventListener: jest.fn(),
    }));
    jest.spyOn(window, 'open').mockReturnValue(null);
    URL.createObjectURL = jest.fn(() => 'blob:adjustment-receipt');
    URL.revokeObjectURL = jest.fn();
    mockApi();
});

afterEach(() => jest.restoreAllMocks());

test('partial adjustment collection creates an associated receipt, prints it, and blocks further collection while pending', async () => {
    let latestOrder = { ...order };
    let latestAdjustment = { ...adjustment };
    mockApi({
        orders: () => [latestOrder],
        adjustments: () => [latestAdjustment],
        submit: () => {
            latestOrder = { ...order, pending_amount: 12.5, available_amount: 67.5 };
            latestAdjustment = {
                ...adjustment, pending_amount: 12.5, available_amount: 0,
                collection_blocked_reason: '差价收款单待审核',
            };
            return response({ id: 10, receipt_no: 'RC-ADJUSTMENT' });
        },
    });
    const preview = { document: { write: jest.fn() }, location: {}, close: jest.fn() };
    window.open.mockReturnValue(preview);
    renderPage();
    const modal = await openAdjustment();

    expect(modal.getByText('客户：客户A')).toBeInTheDocument();
    expect(modal.getByText(/ORDER-ADJUSTMENT/)).toBeInTheDocument();
    expect(adjustmentAmount(modal)).toHaveValue('25.00');
    expect(modal.getByLabelText('收款日期')).toHaveValue(dayjs().format('YYYY-MM-DD'));
    expect(modal.getByText('现金 / Cash')).toBeInTheDocument();
    fireEvent.change(adjustmentAmount(modal), { target: { value: '12.5' } });
    fireEvent.change(modal.getByLabelText('备注'), { target: { value: '差价分次补收' } });
    await selectPayment(modal, '银行转账 / Bank Transfer');
    fireEvent.click(modal.getByRole('button', { name: '确认提交' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(JSON.parse(requestsFor('/receipts', 'POST')[0][1].body)).toEqual({
        customer_id: 1, receipt_date: dayjs().format('YYYY-MM-DD'), payment_method: 'bank_transfer',
        settlement_status: 'unsettled', remark: '差价分次补收',
        items: [{ order_uid: 'adjustment-order', amount: 12.5, adjustment_id: 3 }],
    });
    await waitFor(() => {
        expect(screen.getByRole('tab', { name: '收款单记录' })).toHaveAttribute('aria-selected', 'true');
        expect(requestsFor('/receivables/orders')).toHaveLength(2);
        expect(requestsFor('/receivable-adjustments')).toHaveLength(2);
    });
    expect(preview.location.href).toBe('blob:adjustment-receipt');
    expect(requestsFor('/receipts/10/pdf')).toHaveLength(1);
    expect(await screen.findByText('RC-ADJUSTMENT')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: '收款登记' }));
    expect(within(rowFor('ORDER-REGULAR')).getByRole('spinbutton')).toHaveValue('67.50');
    expect(within(rowFor()).getByRole('button', { name: '登记补收' })).toBeDisabled();
    expect(within(rowFor()).getByText('差价收款单待审核')).toBeInTheDocument();
});

test('cancelling and reopening adjustment collection restores current balance and initial payment fields', async () => {
    renderPage();
    const modal = await openAdjustment();
    fireEvent.change(adjustmentAmount(modal), { target: { value: '12.5' } });
    fireEvent.change(modal.getByLabelText('备注'), { target: { value: '尚未提交的补收' } });
    await selectPayment(modal, '银行转账 / Bank Transfer');
    fireEvent.click(modal.getByRole('button', { name: /取\s*消/ }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    const reopenedModal = await openAdjustment();
    expect(adjustmentAmount(reopenedModal)).toHaveValue('25.00');
    expect(reopenedModal.getByLabelText('备注')).toHaveValue('');
    expect(reopenedModal.getByText('现金 / Cash')).toBeInTheDocument();
    expect(requestsFor('/receipts', 'POST')).toHaveLength(0);
});

test('a rejected adjustment submission preserves inputs and a retry is protected against double clicks', async () => {
    let finishSubmit;
    let attempts = 0;
    mockApi({ submit: () => {
        attempts += 1;
        if (attempts === 1) return { ok: false, json: async () => ({ code: 400, msg: '差价可补收余额已变化' }) };
        return new Promise(resolve => { finishSubmit = resolve; });
    } });
    renderPage();
    const modal = await openAdjustment();
    fireEvent.change(adjustmentAmount(modal), { target: { value: '16.75' } });
    fireEvent.change(modal.getByLabelText('备注'), { target: { value: '保留差价备注' } });
    await selectPayment(modal, '微信 / WeChat Pay');
    fireEvent.click(modal.getByRole('button', { name: '确认提交' }));

    await screen.findByText('差价可补收余额已变化');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(adjustmentAmount(modal)).toHaveValue('16.75');
    expect(modal.getByLabelText('备注')).toHaveValue('保留差价备注');
    expect(modal.getByText('微信 / WeChat Pay', { selector: '.ant-select-selection-item' })).toBeInTheDocument();

    const confirmButton = modal.getByRole('button', { name: '确认提交' });
    fireEvent.click(confirmButton);
    fireEvent.click(confirmButton);
    await waitFor(() => expect(requestsFor('/receipts', 'POST')).toHaveLength(2));
    expect(adjustmentAmount(modal)).toBeDisabled();
    expect(modal.getByRole('button', { name: /取\s*消/ })).toBeDisabled();
    expect(JSON.parse(requestsFor('/receipts', 'POST')[1][1].body)).toMatchObject({
        payment_method: 'wechat', remark: '保留差价备注', settlement_status: 'unsettled',
        items: [{ order_uid: 'adjustment-order', amount: 16.75, adjustment_id: 3 }],
    });
    await act(async () => finishSubmit(response({ id: 10, receipt_no: 'RC-ADJUSTMENT' })));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(requestsFor('/receipts', 'POST')).toHaveLength(2);
});

test('refunds, fully occupied adjustment balances, and missing customers cannot be registered as collection', async () => {
    mockApi({ adjustments: [
        {
            ...adjustment, id: 4, order_uid: 'refund-order', order_id: 'ORDER-REFUND',
            delta_amount: -15, direction: 'refund', available_amount: 0,
        },
        {
            ...adjustment, id: 5, order_uid: 'pending-order', order_id: 'ORDER-PENDING',
            approved_received: 10, pending_amount: 30, available_amount: 0,
            collection_blocked_reason: '差价已被待审核收款占用',
        },
        { ...adjustment, id: 6, order_uid: 'missing-customer', order_id: 'ORDER-NO-CUSTOMER', customer_id: null },
    ] });
    renderPage();
    await screen.findByRole('link', { name: 'ORDER-REFUND' });
    expect(within(rowFor('ORDER-REFUND')).getByText(/退款.*财务/)).toBeInTheDocument();
    expect(within(rowFor('ORDER-PENDING')).getByText('差价已被待审核收款占用')).toBeInTheDocument();
    for (const id of ['ORDER-REFUND', 'ORDER-PENDING', 'ORDER-NO-CUSTOMER']) {
        const action = within(rowFor(id)).queryByRole('button', { name: '登记补收' });
        if (action) {
            expect(action).toBeDisabled();
            fireEvent.click(action);
        }
    }
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(requestsFor('/receipts', 'POST')).toHaveLength(0);
});

test('empty or excessive adjustment amounts and missing dates cannot submit a receipt', async () => {
    renderPage();
    const modal = await openAdjustment();
    fireEvent.change(adjustmentAmount(modal), { target: { value: '' } });
    fireEvent.click(modal.getByRole('button', { name: '确认提交' }));
    await modal.findByText('本次补收必须大于 0 且不超过当前可补收金额');
    expect(requestsFor('/receipts', 'POST')).toHaveLength(0);

    fireEvent.change(adjustmentAmount(modal), { target: { value: '26' } });
    fireEvent.click(modal.getByRole('button', { name: '确认提交' }));
    await waitFor(() => expect(adjustmentAmount(modal)).not.toBeDisabled());
    expect(requestsFor('/receipts', 'POST')).toHaveLength(0);

    fireEvent.change(adjustmentAmount(modal), { target: { value: '12' } });
    fireEvent.click(modal.getByLabelText('收款日期').closest('.ant-picker').querySelector('.ant-picker-clear'));
    fireEvent.click(modal.getByRole('button', { name: '确认提交' }));
    await modal.findByText('请选择收款日期');
    expect(requestsFor('/receipts', 'POST')).toHaveLength(0);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
});

test('copying a rejected adjustment receipt refreshes its balance and retains the adjustment association', async () => {
    mockApi({ receipts: [{ ...rejectedAdjustmentReceipt, items: undefined }] });
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: '收款单记录' }));
    fireEvent.click(await screen.findByRole('button', { name: /复制新建/ }));
    const modal = within(await screen.findByRole('dialog'));

    expect(modal.getByText('登记差价补收')).toBeInTheDocument();
    expect(modal.getByText(/ORDER-ADJUSTMENT/)).toBeInTheDocument();
    expect(adjustmentAmount(modal)).toHaveValue('25.00');
    expect(modal.getByLabelText('收款日期')).toHaveValue(dayjs().format('YYYY-MM-DD'));
    expect(modal.getByLabelText('备注')).toHaveValue('驳回后重新补收');
    expect(modal.getByText('银行转账 / Bank Transfer')).toBeInTheDocument();
    expect(within(rowFor('ORDER-REGULAR')).getByRole('checkbox')).not.toBeChecked();
    expect(requestsFor('/receipts/9')).toHaveLength(1);
    expect(requestsFor('/receivable-adjustments/3')).toHaveLength(1);

    fireEvent.click(modal.getByRole('button', { name: '确认提交' }));
    await waitFor(() => expect(requestsFor('/receipts', 'POST')).toHaveLength(1));
    expect(JSON.parse(requestsFor('/receipts', 'POST')[0][1].body)).toEqual({
        customer_id: 1, receipt_date: dayjs().format('YYYY-MM-DD'), payment_method: 'bank_transfer',
        settlement_status: 'unsettled', remark: '驳回后重新补收',
        items: [{ order_uid: 'adjustment-order', amount: 25, adjustment_id: 3 }],
    });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});

test('copying a rejected adjustment receipt cannot reopen a fully occupied balance', async () => {
    mockApi({
        receipts: [{ ...rejectedAdjustmentReceipt, items: undefined }],
        adjustmentDetail: {
            ...adjustment, pending_amount: 30, available_amount: 0,
            collection_blocked_reason: '差价已被待审核收款占用',
        },
    });
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: '收款单记录' }));
    fireEvent.click(await screen.findByRole('button', { name: /复制新建/ }));
    await waitFor(() => expect(screen.getAllByText('差价已被待审核收款占用').some(element => (
        element.closest('.ant-message-notice')
    ))).toBe(true));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(requestsFor('/receipts', 'POST')).toHaveLength(0);
});
