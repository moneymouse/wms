import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import dayjs from 'dayjs';
import FinanceOrderSettlements, { OrderAllocationDialog } from './financeOrderSettlements';

const response = data => Promise.resolve({ ok: true, status: 200, json: async () => ({ code: 200, data }) });
const list = (items, total = items.length, page = 1) => ({ items, total, page, page_size: 20 });
const order = { order_uid: 'order-1', order_number: 'ORDER-1', customer_id: 2, customer_name: '客户甲', receivable_amount: '120.00', allocated_amount: '0.00', receivable_balance: '120.00', refundable_amount: '0.00', sync_delta: '20.00', source_hash: 'quote-v4', can_allocate: true, blockers: [], documents: [] };
const payment = { id: 8, number: 'PAY-8', direction: 'incoming', partner_type: 'customer', partner_id: 2, partner_name: '客户甲', version: 3, available_amount: '100.00', unallocated_amount: '100.00', reference_orders: [{ order_uid: 'order-1', order_number: 'ORDER-1' }] };
const wrap = component => render(<MemoryRouter>{component}</MemoryRouter>);
beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({ matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }) });
    global.fetch = jest.fn((url, options) => options?.method === 'POST' ? response({ source: payment, items: [] }) : String(url).includes('/partners') ? response(list([{ id: 2, name: '客户甲' }])) : response(list([order])));
});
afterEach(() => jest.restoreAllMocks());

test('reference orders never preselect financial allocations; explicit partial amount posts the quote hash and payment version', async () => {
    const onSuccess = jest.fn(); wrap(<OrderAllocationDialog payment={payment} onClose={jest.fn()} onSuccess={onSuccess} />);
    await screen.findByText('ORDER-1');
    expect(screen.getAllByRole('checkbox').every(input => !input.checked)).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: '确认订单核销' })); await screen.findByText('请选择实际核销的订单');
    expect(global.fetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    fireEvent.change(screen.getByRole('spinbutton', { name: 'ORDER-1 订单核销金额' }), { target: { value: '25.35' } });
    fireEvent.blur(screen.getByRole('spinbutton', { name: 'ORDER-1 订单核销金额' }));
    fireEvent.click(screen.getByRole('button', { name: '确认订单核销' })); await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    const post = global.fetch.mock.calls.find(([, options]) => options?.method === 'POST');
    expect(String(post[0])).toContain('/order-allocations');
    expect(JSON.parse(post[1].body)).toMatchObject({ payment_id: 8, version: 3, allocation_date: dayjs().format('YYYY-MM-DD'), allocations: [{ order_uid: 'order-1', amount: '25.35', source_hash: 'quote-v4' }] });
    expect(global.fetch.mock.calls[0][0]).toContain('partner_id=2');
});

test('multi-order amount exceeding available cash cannot post', async () => {
    global.fetch.mockImplementation(() => response(list([order, { ...order, order_uid: 'order-2', order_number: 'ORDER-2' }])));
    wrap(<OrderAllocationDialog payment={payment} onClose={jest.fn()} onSuccess={jest.fn()} />); await screen.findByText('ORDER-1');
    fireEvent.click(screen.getAllByRole('checkbox')[0]); fireEvent.click(screen.getByRole('button', { name: '确认订单核销' }));
    await screen.findByText('核销合计不能超过收付款可用余额');
    expect(global.fetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
});

test('packing receipts default to live associated orders and retain unresolved box notices', async () => {
    global.fetch.mockImplementation((url, options) => options?.method === 'POST' ? response({}) : response({
        ...list([{ ...order, receivable_balance: '60.00' }]),
        unresolved_packing_boxes: [{ box_uid: 'waiting-box', list_number: 'MARK-B', box_number: 2, reason: '箱子尚未分配订单' }],
    }));
    const done = jest.fn();
    wrap(<OrderAllocationDialog payment={{ ...payment, reference_packing_boxes: [{ box_uid: 'box-1', list_number: 'MARK-A', box_number: 1 }] }} onClose={jest.fn()} onSuccess={done} />);
    await screen.findByText('ORDER-1');
    expect(global.fetch.mock.calls[0][0]).toContain('payment_id=8');
    expect(screen.getByText('MARK-B / 箱 2：箱子尚未分配订单')).toBeInTheDocument();
    expect(screen.getAllByRole('checkbox').every(input => !input.checked)).toBe(true);
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    fireEvent.click(screen.getByRole('button', { name: '确认订单核销' }));
    await waitFor(() => expect(done).toHaveBeenCalled());
    const options = global.fetch.mock.calls.find(([, options]) => options?.method === 'POST')[1];
    expect(JSON.parse(options.body)).toMatchObject({ payment_id: 8, packing_only: true, allocations: [{ order_uid: 'order-1', amount: '60.00' }] });
});

test('outgoing customer payment allocates refundable balance and no-quote order stays disabled', async () => {
    global.fetch.mockImplementation((url, options) => options?.method === 'POST' ? response({}) : response(list([{ ...order, refundable_amount: '30.00', receivable_balance: '0.00' }, { ...order, order_uid: 'empty', order_number: 'EMPTY', can_allocate: false, blockers: ['没有有效报价'] }])));
    const done = jest.fn(); wrap(<OrderAllocationDialog payment={{ ...payment, direction: 'outgoing' }} onClose={jest.fn()} onSuccess={done} />);
    await screen.findByText('ORDER-1'); expect(screen.getAllByRole('checkbox')[2]).toBeDisabled();
    fireEvent.click(screen.getAllByRole('checkbox')[1]); fireEvent.click(screen.getByRole('button', { name: '确认订单核销' })); await waitFor(() => expect(done).toHaveBeenCalled());
    expect(JSON.parse(global.fetch.mock.calls.find(([, options]) => options?.method === 'POST')[1].body).allocations[0].amount).toBe('30.00');
});

test('pagination keeps deliberate selections across pages', async () => {
    global.fetch.mockImplementation((url, options) => {
        if (options?.method === 'POST') return response({});
        const p = Number(new URL(url, 'http://localhost').searchParams.get('p'));
        return response(list([{ ...order, order_uid: `order-${p}`, order_number: `ORDER-${p}`, receivable_balance: '20.00' }], 30, p));
    });
    const done = jest.fn(); wrap(<OrderAllocationDialog payment={payment} onClose={jest.fn()} onSuccess={done} />);
    await screen.findByText('ORDER-1'); fireEvent.click(screen.getAllByRole('checkbox')[1]); fireEvent.click(screen.getByTitle('2'));
    await screen.findByText('ORDER-2'); fireEvent.click(screen.getAllByRole('checkbox')[1]); fireEvent.click(screen.getByRole('button', { name: '确认订单核销' })); await waitFor(() => expect(done).toHaveBeenCalled());
    expect(JSON.parse(global.fetch.mock.calls.find(([, options]) => options?.method === 'POST')[1].body).allocations.map(row => row.order_uid)).toEqual(['order-1', 'order-2']);
});

test('stale search response cannot replace the newest financial order list', async () => {
    let resolveOld;
    global.fetch.mockImplementation(url => String(url).includes('q=old') ? new Promise(resolve => { resolveOld = resolve; }) : response(list([{ ...order, order_number: String(url).includes('q=new') ? 'NEW' : 'ORDER-1' }])));
    wrap(<OrderAllocationDialog payment={payment} onClose={jest.fn()} onSuccess={jest.fn()} />); await screen.findByText('ORDER-1');
    const search = screen.getByRole('searchbox', { name: '核销订单搜索' });
    fireEvent.change(search, { target: { value: 'old' } }); fireEvent.keyDown(search, { key: 'Enter', code: 'Enter', keyCode: 13 }); fireEvent.keyUp(search, { key: 'Enter', code: 'Enter', keyCode: 13 });
    fireEvent.change(search, { target: { value: 'new' } }); fireEvent.keyDown(search, { key: 'Enter', code: 'Enter', keyCode: 13 }); await screen.findByText('NEW');
    await act(async () => resolveOld(await response(list([{ ...order, order_number: 'OLD' }]))));
    expect(screen.queryByText('OLD')).not.toBeInTheDocument(); expect(screen.getByText('NEW')).toBeInTheDocument();
});

test('quote sync is explicit and includes reason, today and source hash without creating a payment', async () => {
    wrap(<FinanceOrderSettlements />); fireEvent.click(await screen.findByRole('button', { name: '确认当前报价' }));
    const modal = screen.getByRole('dialog'); fireEvent.click(within(modal).getByRole('button', { name: '确认入账' })); await screen.findByText('请填写确认说明');
    fireEvent.change(within(modal).getByLabelText('确认说明'), { target: { value: '已核对新报价' } }); fireEvent.click(within(modal).getByRole('button', { name: '确认入账' }));
    await waitFor(() => expect(global.fetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(true));
    const [url, options] = global.fetch.mock.calls.find(([, options]) => options?.method === 'POST');
    expect(String(url)).toContain('/order-settlements/order-1/sync'); expect(JSON.parse(options.body)).toMatchObject({ source_hash: 'quote-v4', document_date: dayjs().format('YYYY-MM-DD'), reason: '已核对新报价' });
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/payments'))).toBe(false);
});
