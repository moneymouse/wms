import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { PaymentEditor } from './financeWorkspace';

const response = data => Promise.resolve({ ok: true, status: 200, json: async () => ({ code: 200, data }) });
const draft = { id: 8, number: 'PAY-8', status: 'draft', version: 3, partner_type: 'customer', partner_id: 2, partner_name: '客户甲', direction: 'incoming', account_id: 1, account_name: '公司银行', payment_date: '2026-10-06', amount: '100.00', reference_order_uids: [], reference_orders: [], reference_box_uids: [], reference_packing_boxes: [] };
const box = { box_uid: 'packing-box-1', packing_list_uid: 'packing-a', list_number: 'MARK-A', box_number: 1, transfer_id: 'XD123456L', item_name: '服装', weight: 5, target_order_uid: null };
beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({ matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }) });
    global.fetch = jest.fn((url, options) => {
        if (options?.method === 'PATCH') return response({ ...draft, version: 4, reference_box_uids: [box.box_uid], reference_packing_boxes: [box] });
        const path = String(url);
        if (path.includes('/payment-options/packing-boxes')) return response({ items: [box], total: 1 });
        if (path.includes('/payment-options/orders')) return response({ items: [], total: 0 });
        if (path.includes('/payment-options/accounts')) return response({ items: [{ id: 1, name: '公司银行' }], total: 1 });
        if (path.includes('/payment-options/customers')) return response({ items: [{ id: 2, name: '客户甲' }], total: 1 });
        throw new Error(`Unexpected request ${url}`);
    });
});
afterEach(() => jest.restoreAllMocks());

test('receipt editor saves packing boxes without an order or allocating money', async () => {
    const saved = jest.fn();
    render(<PaymentEditor open business payment={draft} onClose={jest.fn()} onSaved={saved} />);
    await screen.findByDisplayValue('100.00');
    fireEvent.click(screen.getByRole('tab', { name: /装箱单备注/ }));
    const picker = screen.getByRole('group', { name: '备注装箱单箱子' });
    fireEvent.click(await within(picker).findByRole('button', { name: '展开装箱单 MARK-A' }));
    const boxes = within(picker).getByRole('group', { name: '装箱单 MARK-A 的箱子' });
    await within(boxes).findByText('XD123456L');
    fireEvent.click(within(boxes).getAllByRole('checkbox')[1]);
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => expect(saved).toHaveBeenCalledTimes(1));
    const [, options] = global.fetch.mock.calls.find(([, options]) => options?.method === 'PATCH');
    expect(JSON.parse(options.body)).toMatchObject({ version: 3, amount: '100.00', reference_order_uids: [], reference_box_uids: [box.box_uid] });
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/order-allocations') || String(url).includes('/documents'))).toBe(false);
});
