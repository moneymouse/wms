import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import { ReceiptAudit, ReceivableLedger } from './financeReceivables';

jest.mock('../components/FeatureTour', () => () => null);

jest.setTimeout(15000);

const pendingReceipt = {
    id: 21, receipt_no: 'RC-PENDING', customer_name: '客户A',
    receipt_date: '2026-09-09', creator_name: '业务员A', total_amount: 70,
    status: 'pending', settlement_status: 'settled',
};
const secondReceipt = { ...pendingReceipt, id: 22, receipt_no: 'RC-SECOND', settlement_status: 'unsettled' };
const approvedReceipt = { ...pendingReceipt, id: 23, receipt_no: 'RC-APPROVED', status: 'approved', total_amount: 80 };
const legacyReceipt = { ...approvedReceipt, id: 24, receipt_no: 'RC-LEGACY', settlement_status: null };
const item = {
    id: 1, order_uid: 'order-1', order_id: 'ORDER-1', receivable_snapshot: 100,
    received_before: 0, amount: 70, remaining_after: 30,
    preview_settlement_difference: 30, settlement_difference: null,
};

function detail(receipt = pendingReceipt, items = [item]) {
    return { ...receipt, items };
}

function response(data) {
    return { ok: true, json: async () => ({ code: 200, data }) };
}

function deferred() {
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    return { promise, resolve };
}

function mockApi({ receipts = [pendingReceipt], loadDetail, ledger, review } = {}) {
    global.fetch = jest.fn(async (url, options) => {
        const path = new URL(url, 'http://localhost').pathname;
        if (path.endsWith('/review')) return review ? review(url, options) : response(detail({ ...pendingReceipt, status: 'approved' }));
        const detailMatch = path.match(/\/receipts\/(\d+)$/);
        if (detailMatch) {
            const id = Number(detailMatch[1]);
            return loadDetail ? loadDetail(id) : response(detail(receipts.find(receipt => receipt.id === id)));
        }
        if (path.endsWith('/receipts')) return response(receipts);
        if (path.endsWith('/finance/accounts-receivable')) return response(ledger || { items: [], totals: {} });
        if (path.endsWith('/customer_list') || path.endsWith('/work/workers')) return response([]);
        throw new Error(`Unexpected request: ${url}`);
    });
}

function receiptRow(receipt = pendingReceipt) {
    return rowForText(receipt.receipt_no);
}

function rowForText(text) {
    return screen.getByText(text).closest('tr');
}

function expandReceipt(receipt = pendingReceipt) {
    fireEvent.click(within(receiptRow(receipt)).getByRole('button', { name: 'Expand row' }));
}

function openReview(receipt = pendingReceipt) {
    fireEvent.click(within(receiptRow(receipt)).getByRole('button', { name: /审\s*核/ }));
}

function detailCalls(id = 21) {
    return global.fetch.mock.calls.filter(([url]) => url.endsWith(`/receipts/${id}`));
}

beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    const payload = window.btoa(JSON.stringify({ user_id: 9, roles: ['finance'] }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
    window.matchMedia = jest.fn(query => ({
        matches: false, media: query, addListener: jest.fn(), removeListener: jest.fn(),
        addEventListener: jest.fn(), removeEventListener: jest.fn(),
    }));
    mockApi();
});

afterEach(() => jest.restoreAllMocks());

test('ledger displays settlement differences separately from actual receipts and outstanding totals', async () => {
    mockApi({ ledger: {
        items: [{
            order_uid: 'order-1', order_id: 'ORDER-SETTLED', receivable_amount: 100,
            received_amount: 70, settlement_difference: 30, outstanding_amount: 0,
            pending_amount: 0, settlement_status: 'paid', billing_weight: 10,
        }],
        totals: { receivable_amount: 100, received_amount: 70, settlement_difference: 30, outstanding_amount: 0, pending_amount: 0 },
        total: 1, page: 1, page_size: 20,
    } });
    render(<ReceivableLedger />);
    await screen.findByText('ORDER-SETTLED');
    const row = rowForText('ORDER-SETTLED');
    expect(within(row).getByText('已结清')).toBeInTheDocument();
    expect(within(row).getByText('70.00')).toBeInTheDocument();
    expect(within(row).getByText('30.00')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '结清差额' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: '结清差额合计' })).toHaveTextContent('30.00');
    expect(screen.getByRole('group', { name: '已收账款' })).toHaveTextContent('70.00');
    expect(screen.getByRole('group', { name: '未收账款' })).toHaveTextContent('0.00');
});

test('receipt summaries separate settlement and review states and lazily load true item details', async () => {
    mockApi({ receipts: [pendingReceipt, secondReceipt, legacyReceipt] });
    render(<ReceiptAudit />);
    await screen.findByText('RC-PENDING');
    expect(screen.getByRole('columnheader', { name: '结清状态' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '审核状态' })).toBeInTheDocument();
    expect(within(receiptRow()).getByText('已结清')).toBeInTheDocument();
    expect(within(receiptRow()).getByText('待审核')).toBeInTheDocument();
    expect(within(receiptRow(secondReceipt)).getByText('未结清')).toBeInTheDocument();
    expect(within(receiptRow(legacyReceipt)).getByText('未设置')).toBeInTheDocument();
    expect(detailCalls()).toHaveLength(0);
    expandReceipt();
    await screen.findByText('ORDER-1');
    const order = rowForText('ORDER-1');
    expect(detailCalls()).toHaveLength(1);
    expect(screen.getByRole('columnheader', { name: '预计结清差额' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '可收余额快照' })).toBeInTheDocument();
    expect(within(order).getByText('70.00')).toBeInTheDocument();
});

test('opening review refreshes the pending preview even after expanded details were loaded', async () => {
    const fresh = deferred();
    let requests = 0;
    mockApi({ loadDetail: () => (++requests === 1 ? response(detail()) : fresh.promise) });
    render(<ReceiptAudit />);
    await screen.findByText('RC-PENDING');
    expandReceipt();
    await screen.findByText('ORDER-1');
    openReview();
    const dialog = screen.getByRole('dialog');
    expect(detailCalls()).toHaveLength(2);
    expect(within(dialog).getByRole('button', { name: '审核通过' })).toBeDisabled();
    await act(async () => fresh.resolve(response(detail(pendingReceipt, [{ ...item, preview_settlement_difference: 18.25 }]))));
    expect(await within(dialog).findByText('18.25')).toBeInTheDocument();
    expect(within(dialog).getByRole('columnheader', { name: '本次实收' })).toBeInTheDocument();
    expect(within(dialog).getByText('70.00')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: '审核通过' })).toBeEnabled();
});

test('failed review detail loading blocks approval and supports a successful retry and review', async () => {
    let requests = 0;
    mockApi({ loadDetail: () => (++requests === 1
        ? { ok: false, json: async () => ({ code: 500, msg: '明细读取失败' }) }
        : response(detail())) });
    render(<ReceiptAudit />);
    await screen.findByText('RC-PENDING');
    openReview();
    const dialog = screen.getByRole('dialog');
    await within(dialog).findByText('明细读取失败');
    const approve = within(dialog).getByRole('button', { name: '审核通过' });
    expect(approve).toBeDisabled();
    fireEvent.click(approve);
    expect(global.fetch.mock.calls.some(([, options]) => options?.method === 'PUT')).toBe(false);
    fireEvent.click(within(dialog).getByRole('button', { name: '重试加载明细' }));
    await waitFor(() => expect(approve).toBeEnabled());
    fireEvent.change(within(dialog).getByPlaceholderText('审核意见（驳回时必填）'), { target: { value: '实收核对完成' } });
    fireEvent.click(approve);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    const reviews = global.fetch.mock.calls.filter(([, options]) => options?.method === 'PUT');
    expect(reviews).toHaveLength(1);
    expect(reviews[0][0]).toContain('/finance/receipts/21/review');
    expect(JSON.parse(reviews[0][1].body)).toEqual({ action: 'approve', review_remark: '实收核对完成' });
});

test('a late detail response from a closed review cannot overwrite the next receipt review', async () => {
    const oldRequest = deferred();
    mockApi({ receipts: [pendingReceipt, secondReceipt], loadDetail: id => id === 21
        ? oldRequest.promise
        : response(detail(secondReceipt, [{ ...item, id: 2, order_id: 'ORDER-SECOND' }])) });
    render(<ReceiptAudit />);
    await screen.findByText('RC-PENDING');
    openReview();
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Close' }));
    openReview(secondReceipt);
    const dialog = screen.getByRole('dialog');
    await within(dialog).findByText('ORDER-SECOND');
    await act(async () => oldRequest.resolve(response(detail(pendingReceipt, [{ ...item, order_id: 'STALE-ORDER' }]))));
    expect(within(dialog).getByText('收款审核 - RC-SECOND')).toBeInTheDocument();
    expect(within(dialog).getByText('ORDER-SECOND')).toBeInTheDocument();
    expect(within(dialog).queryByText('STALE-ORDER')).not.toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: '审核通过' })).toBeEnabled();
});

test('approved receipt details display the fixed settlement difference instead of a preview', async () => {
    mockApi({ receipts: [approvedReceipt], loadDetail: () => response(detail(approvedReceipt, [{
        ...item, amount: 80, settlement_difference: 20, preview_settlement_difference: 999,
    }])) });
    render(<ReceiptAudit />);
    await screen.findByText('RC-APPROVED');
    expandReceipt(approvedReceipt);
    await screen.findByText('ORDER-1');
    expect(screen.getByRole('columnheader', { name: '已生效结清差额' })).toBeInTheDocument();
    expect(screen.getByText('20.00')).toBeInTheDocument();
    expect(screen.queryByText('999.00')).not.toBeInTheDocument();
});

test('expanded detail errors can be retried and a receipt already reviewed elsewhere cannot be approved', async () => {
    let requests = 0;
    mockApi({ loadDetail: () => (++requests === 1
        ? Promise.reject(new Error('连接中断'))
        : response(detail({ ...pendingReceipt, status: 'approved' }))) });
    render(<ReceiptAudit />);
    await screen.findByText('RC-PENDING');
    expandReceipt();
    await screen.findByText('连接中断');
    fireEvent.click(screen.getByRole('button', { name: '重试加载明细' }));
    await screen.findByText('ORDER-1');
    openReview();
    const dialog = screen.getByRole('dialog');
    await within(dialog).findByText('该收款单已完成审核，请刷新列表查看最新状态。');
    expect(within(dialog).getByRole('button', { name: '审核通过' })).toBeDisabled();
});
