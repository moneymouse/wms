import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import OrderPayments from './OrderPayments';
import { financeRequest } from '../common/financeApi';

jest.mock('../common/financeApi', () => ({
    ...jest.requireActual('../common/financeApi'),
    financeRequest: jest.fn(),
}));

const payment = {
    id: 8, number: 'PAY-8', payment_date: '2026-10-09', direction: 'incoming',
    amount: '120.00', status: 'posted', account_name: '银行账户', reference: '银行流水 008',
    memo: '两单共用的收款', created_by_name: '业务员甲', relation_types: ['reference', 'allocation'],
    order_allocated_amount: '30.00',
};
const summary = {
    received_amount: '30.00', refunded_amount: '5.00', net_received_amount: '25.00',
    related_received_amount: '120.00', related_refunded_amount: '20.00', draft_count: 2, pending_count: 3,
};
const result = (items = [payment], overrides = {}) => ({
    items, total: items.length, page: 1, page_size: 10, visibility: 'all', summary, ...overrides,
});
function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((resolvePromise, rejectPromise) => { resolve = resolvePromise; reject = rejectPromise; });
    return { promise, resolve, reject };
}
function panel() { return screen.getByRole('region', { name: '本单收付款' }); }
function renderPayments(props = { orderUid: 'order-1' }) {
    const view = render(<MemoryRouter><OrderPayments {...props} /></MemoryRouter>);
    return { ...view, rerender: nextProps => view.rerender(<MemoryRouter><OrderPayments {...nextProps} /></MemoryRouter>) };
}
beforeEach(() => {
    jest.clearAllMocks();
    Object.defineProperty(window, 'matchMedia', {
        writable: true,
        value: query => ({ matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }),
    });
    financeRequest.mockResolvedValue(result());
});

test('shows associated payment amounts separately from the amount actually allocated to this order', async () => {
    renderPayments({ orderUid: 'order/1' });
    await screen.findByText('PAY-8');
    expect(financeRequest).toHaveBeenCalledWith('/order-payments/order%2F1', {
        params: { p: 1, s: 10 }, signal: expect.any(AbortSignal),
    });
    const region = within(panel());
    expect(region.getByText(/关联收款.*已生效/)).toBeInTheDocument();
    expect(region.getByText(/关联付款.*已生效/)).toBeInTheDocument();
    expect(region.getByText('本单已核销收款')).toBeInTheDocument();
    expect(region.getByText('本单已核销付款')).toBeInTheDocument();
    for (const [label, value] of [['关联收款（已生效）', '120.00'], ['关联付款（已生效）', '20.00'], ['本单已核销收款', '30.00'], ['本单已核销付款', '5.00']]) {
        expect(region.getByText(label).parentElement).toHaveTextContent(value);
    }
    const row = region.getByRole('row', { name: /PAY-8/ });
    expect(within(row).getByText('120.00')).toBeInTheDocument();
    expect(within(row).getByText('30.00')).toBeInTheDocument();
    for (const value of ['2026-10-09', '银行账户', '银行流水 008', '两单共用的收款', '业务员甲', '已生效']) expect(within(row).getByText(value)).toBeInTheDocument();
    expect(region.getByRole('columnheader', { name: /本单.*核销/ })).toBeInTheDocument();
});

test('shows outgoing refunds and payments linked only through order allocations', async () => {
    financeRequest.mockResolvedValue(result([
        { ...payment, relation_types: ['allocation'] },
        { ...payment, id: 9, number: 'PAY-REFUND', direction: 'outgoing', amount: '20.00', order_allocated_amount: '5.00', relation_types: ['packing', 'allocation'] },
    ]));
    renderPayments();
    await screen.findByText('PAY-REFUND');
    const allocationOnly = within(panel()).getByRole('row', { name: /PAY-8/ });
    expect(within(allocationOnly).getByText('本单核销')).toBeInTheDocument();
    expect(within(allocationOnly).queryByText('订单备注')).not.toBeInTheDocument();
    const refund = within(panel()).getByRole('row', { name: /PAY-REFUND/ });
    for (const value of ['付款', '20.00', '5.00', '箱子备注', '本单核销']) expect(within(refund).getByText(value)).toBeInTheDocument();
});

test('marks opening balances without marking normal payments', async () => {
    financeRequest.mockResolvedValue(result([payment, { ...payment, id: 9, number: 'PAY-OPENING', is_opening: true }]));
    renderPayments();
    await screen.findByText('PAY-OPENING');
    const region = within(panel());
    expect(within(region.getByRole('row', { name: /PAY-OPENING/ })).getByText('期初余额')).toBeInTheDocument();
    expect(within(region.getByRole('row', { name: /PAY-8/ })).queryByText('期初余额')).not.toBeInTheDocument();
});

test('keeps draft, pending, cancelled and reversed records visible without deriving posted totals from their amounts', async () => {
    const statuses = ['draft', 'pending', 'cancelled', 'reversed'];
    financeRequest.mockResolvedValue(result(statuses.map((status, index) => ({
        ...payment, id: index + 10, number: `PAY-${status}`, status, amount: '900.00', order_allocated_amount: '0.00',
    })), { summary: { ...summary, received_amount: '0.00', refunded_amount: '0.00', net_received_amount: '0.00', related_received_amount: '0.00', related_refunded_amount: '0.00' } }));
    renderPayments();
    await screen.findByText('PAY-draft');
    const region = within(panel());
    for (const [status, label] of [['draft', '草稿'], ['pending', '待财务确认'], ['cancelled', '已取消'], ['reversed', '已冲销']]) {
        expect(within(region.getByRole('row', { name: new RegExp(`PAY-${status}`) })).getByText(label)).toBeInTheDocument();
    }
    expect(region.getAllByText('0.00').length).toBeGreaterThan(0);
    expect(region.queryByText('3,600.00')).not.toBeInTheDocument();
    expect(region.getByText(/草稿.*2/)).toBeInTheDocument();
    expect(region.getByText(/待.*确认.*3/)).toBeInTheDocument();
});

test('uses the full server summary on every page and clears the preceding page while loading', async () => {
    const next = deferred();
    const fullSummary = { ...summary, received_amount: '730.00', related_received_amount: '1200.00' };
    financeRequest.mockResolvedValueOnce(result([payment], { total: 12, summary: fullSummary })).mockImplementationOnce(() => next.promise);
    renderPayments();
    await screen.findByText('PAY-8');
    expect(within(panel()).getByText('730.00')).toBeInTheDocument();
    expect(within(panel()).getByText('1,200.00')).toBeInTheDocument();
    fireEvent.click(within(panel()).getByTitle('2'));
    expect(screen.queryByText('PAY-8')).not.toBeInTheDocument();
    expect(financeRequest).toHaveBeenLastCalledWith('/order-payments/order-1', expect.objectContaining({ params: { p: 2, s: 10 } }));
    await act(async () => next.resolve(result([{ ...payment, id: 9, number: 'PAY-9', amount: '10.00', order_allocated_amount: '10.00' }], { page: 2, total: 12, summary: fullSummary })));
    expect(screen.getByText('PAY-9')).toBeInTheDocument();
    expect(within(panel()).getByText('730.00')).toBeInTheDocument();
    expect(within(panel()).getByText('1,200.00')).toBeInTheDocument();
});

test('explicitly identifies a salesperson summary as limited to their visible payments', async () => {
    financeRequest.mockResolvedValue(result([payment], { visibility: 'own' }));
    renderPayments();
    await screen.findByText('PAY-8');
    expect(within(panel()).getByText(/仅.*(本人|自己)|本人.*(登记|可见)/)).toBeInTheDocument();
});

test('a request failure does not report zero collected and can be retried', async () => {
    financeRequest.mockRejectedValueOnce(new Error('收付款服务暂不可用')).mockResolvedValueOnce(result());
    renderPayments();
    expect(await screen.findByText('收付款服务暂不可用')).toBeInTheDocument();
    expect(within(panel()).queryByText('0.00')).not.toBeInTheDocument();
    fireEvent.click(within(panel()).getByRole('button', { name: /^重\s*试$/ }));
    await screen.findByText('PAY-8');
    expect(screen.queryByText('收付款服务暂不可用')).not.toBeInTheDocument();
    expect(financeRequest).toHaveBeenCalledTimes(2);
});

test('a malformed summary is reported as an error instead of a zero balance', async () => {
    financeRequest.mockResolvedValue(result([], { summary: { draft_count: 1, pending_count: 0 } }));
    renderPayments();
    expect(await screen.findByText('收付款记录返回格式错误，请重试')).toBeInTheDocument();
    expect(within(panel()).queryByText('0.00')).not.toBeInTheDocument();
    expect(within(panel()).getByRole('button', { name: /^重\s*试$/ })).toBeInTheDocument();
});

test('refreshing clears the old list and summary before displaying the new result', async () => {
    const refreshed = deferred();
    financeRequest.mockResolvedValueOnce(result()).mockImplementationOnce(() => refreshed.promise);
    const view = renderPayments({ orderUid: 'order-1', refreshKey: 0 });
    await screen.findByText('PAY-8');
    view.rerender({ orderUid: 'order-1', refreshKey: 1 });
    expect(screen.queryByText('PAY-8')).not.toBeInTheDocument();
    expect(within(panel()).queryByText('120.00')).not.toBeInTheDocument();
    await act(async () => refreshed.resolve(result([{ ...payment, id: 9, number: 'PAY-NEW', status: 'pending', amount: '25.00', order_allocated_amount: '0.00' }], { summary: { ...summary, pending_count: 4 } })));
    expect(screen.getByText('PAY-NEW')).toBeInTheDocument();
    expect(within(panel()).getByText(/待.*确认.*4/)).toBeInTheDocument();
    expect(financeRequest).toHaveBeenCalledTimes(2);
});

test('switching orders clears old totals and ignores a previous order response arriving late', async () => {
    const old = deferred();
    const next = deferred();
    financeRequest.mockImplementation(path => path.endsWith('/order-1') ? old.promise : next.promise);
    const view = renderPayments({ orderUid: 'order-1' });
    await waitFor(() => expect(financeRequest).toHaveBeenCalledTimes(1));
    const oldSignal = financeRequest.mock.calls[0][1].signal;
    view.rerender({ orderUid: 'order-2' });
    expect(oldSignal.aborted).toBe(true);
    await act(async () => next.resolve(result([{ ...payment, id: 9, number: 'PAY-ORDER-2' }], { summary: { ...summary, received_amount: '77.00' } })));
    expect(screen.getByText('PAY-ORDER-2')).toBeInTheDocument();
    await act(async () => old.resolve(result()));
    expect(screen.queryByText('PAY-8')).not.toBeInTheDocument();
    expect(within(panel()).getByText('77.00')).toBeInTheDocument();
    expect(financeRequest).toHaveBeenLastCalledWith('/order-payments/order-2', expect.objectContaining({ params: { p: 1, s: 10 } }));
});

test('does not request an empty order and resets pagination when the order changes', async () => {
    financeRequest.mockResolvedValue(result([payment], { total: 12 }));
    const view = renderPayments({ orderUid: '' });
    expect(financeRequest).not.toHaveBeenCalled();
    view.rerender({ orderUid: 'order-1' });
    await screen.findByText('PAY-8');
    fireEvent.click(within(panel()).getByTitle('2'));
    await waitFor(() => expect(financeRequest).toHaveBeenLastCalledWith('/order-payments/order-1', expect.objectContaining({ params: { p: 2, s: 10 } })));
    await screen.findByText('PAY-8');
    view.rerender({ orderUid: 'order-2' });
    await waitFor(() => expect(financeRequest).toHaveBeenLastCalledWith('/order-payments/order-2', expect.objectContaining({ params: { p: 1, s: 10 } })));
    await screen.findByText('PAY-8');
});
