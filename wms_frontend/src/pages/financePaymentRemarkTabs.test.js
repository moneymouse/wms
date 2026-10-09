import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { PaymentEditor } from './financeWorkspace';

const response = data => Promise.resolve({ ok: true, status: 200, json: async () => ({ code: 200, data }) });
const orders = [
    { order_uid: 'order-1', order_number: 'WMS-1001', customer_name: '客户甲', receiver: 'Alice', cargo_count: 1 },
    { order_uid: 'order-2', order_number: 'WMS-1002', customer_name: '客户甲', receiver: 'Bob', cargo_count: 2 },
];
const box = { box_uid: 'box-1', packing_list_uid: 'packing-1', list_number: 'MARK-A', box_number: 1, transfer_id: 'XD123456L', item_name: '服装', weight: 5, customer_id: 2, target_order_uid: null };
const draft = {
    id: 8, number: 'PAY-8', status: 'draft', version: 3, partner_type: 'customer', partner_id: 2, partner_name: '客户甲',
    direction: 'incoming', account_id: 1, account_name: '公司银行', payment_date: '2026-10-06', amount: '100.00', memo: '备注甲',
    reference_order_uids: ['order-1'], reference_orders: [orders[0]], reference_box_uids: ['box-1'], reference_packing_boxes: [box],
};

beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({ matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }) });
    global.fetch = jest.fn((url, options) => {
        if (options?.method === 'PATCH') return response({ ...draft, ...JSON.parse(options.body), version: 4 });
        const path = String(url);
        if (path.includes('/payment-options/packing-boxes')) return response({ items: [box], total: 1 });
        if (path.includes('/payment-options/orders')) return response({ items: orders, total: orders.length });
        if (path.includes('/payment-options/accounts') || path.includes('/accounts')) return response({ items: [{ id: 1, name: '公司银行', active: true }], total: 1 });
        if (path.includes('/payment-options/customers') || path.includes('/partners')) return response({ items: [{ id: 2, name: '客户甲' }, { id: 3, name: '客户乙' }], total: 2 });
        throw new Error(`Unexpected request ${url}`);
    });
});
afterEach(() => jest.restoreAllMocks());

const tab = label => screen.getByRole('tab', { name: new RegExp(label) });
const patchBody = () => JSON.parse(global.fetch.mock.calls.find(([, options]) => options?.method === 'PATCH')[1].body);

test('switching remark tabs preserves all three kinds together when saving from another tab', async () => {
    const saved = jest.fn();
    render(<PaymentEditor open business payment={draft} onClose={jest.fn()} onSaved={saved} />);
    await screen.findByDisplayValue('100.00');
    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(2);
    expect(tabs[0]).toHaveTextContent('装箱单备注');
    expect(tabs[1]).toHaveTextContent('订单备注');
    expect(tab('装箱单备注')).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('textbox', { name: '文字备注' })).toBeVisible();

    fireEvent.click(tab('订单备注'));
    await screen.findByText('WMS-1002');
    const secondOrder = screen.getByRole('row', { name: /WMS-1002/ });
    fireEvent.click(within(secondOrder).getByRole('checkbox'));

    const memo = screen.getByRole('textbox', { name: '文字备注' });
    expect(memo).toBeVisible();
    expect(memo).toHaveValue('备注甲');
    fireEvent.change(memo, { target: { value: '确认备注地址和邮编' } });
    fireEvent.click(tab('装箱单备注'));
    expect(screen.getByRole('button', { name: '移除备注箱子 MARK-A / 箱 1' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => expect(saved).toHaveBeenCalledTimes(1));
    expect(patchBody()).toMatchObject({
        version: 3, partner_type: 'customer', partner_id: 2, amount: '100.00', payment_date: '2026-10-06',
        reference_order_uids: ['order-1', 'order-2'], reference_box_uids: ['box-1'], memo: '确认备注地址和邮编',
    });
    expect(global.fetch.mock.calls.filter(([, options]) => options?.method === 'PATCH')).toHaveLength(1);
});

test.each([
    ['装箱单备注', draft],
    ['订单备注', { ...draft, reference_box_uids: [], reference_packing_boxes: [] }],
    ['装箱单备注', { ...draft, reference_box_uids: [], reference_packing_boxes: [], reference_order_uids: [], reference_orders: [] }],
])('saved remarks open their %s tab', async (label, payment) => {
    render(<PaymentEditor open business payment={payment} onClose={jest.fn()} onSaved={jest.fn()} />);
    await screen.findByDisplayValue('100.00');
    expect(tab(label)).toHaveAttribute('aria-selected', 'true');
});

test('changing the customer clears order and box remarks while retaining the text remark', async () => {
    const saved = jest.fn();
    render(<PaymentEditor open business payment={draft} onClose={jest.fn()} onSaved={saved} />);
    await screen.findByDisplayValue('100.00');
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '收付款客户' }));
    fireEvent.click(await screen.findByText('客户乙'));
    await waitFor(() => expect(screen.queryByRole('button', { name: '移除备注箱子 MARK-A / 箱 1' })).not.toBeInTheDocument());
    fireEvent.click(tab('订单备注'));
    expect(screen.queryByRole('button', { name: '移除参考订单 WMS-1001' })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '文字备注' })).toHaveValue('备注甲');
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => expect(saved).toHaveBeenCalledTimes(1));
    expect(patchBody()).toMatchObject({ partner_id: 3, reference_order_uids: [], reference_box_uids: [], memo: '备注甲' });
});

test('vendor payments keep the text remark visible and disable unsupported references', async () => {
    const payment = { ...draft, partner_type: 'vendor', direction: 'outgoing', reference_order_uids: [], reference_orders: [], reference_box_uids: [], reference_packing_boxes: [] };
    const saved = jest.fn();
    render(<PaymentEditor open payment={payment} onClose={jest.fn()} onSaved={saved} />);
    await screen.findByDisplayValue('100.00');
    expect(screen.queryByRole('tab', { name: /文字备注/ })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '文字备注' })).toBeVisible();
    expect(screen.getByRole('textbox', { name: '文字备注' })).toHaveValue('备注甲');
    expect(tab('订单备注')).toHaveAttribute('aria-disabled', 'true');
    expect(tab('装箱单备注')).toHaveAttribute('aria-disabled', 'true');
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/payment-options/orders') || String(url).includes('/payment-options/packing-boxes'))).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => expect(saved).toHaveBeenCalledTimes(1));
    expect(patchBody()).toMatchObject({ partner_type: 'vendor', reference_order_uids: [], reference_box_uids: [], memo: '备注甲' });
});
