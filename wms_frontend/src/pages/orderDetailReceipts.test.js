import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import OrderDetail from './orderDetail';

jest.mock('antd/es/input/Input', () => ({ __esModule: true, default: jest.requireActual('antd').Input }));
jest.mock('../components/ExportButton', () => () => null);
jest.mock('../components/BoxAssignmentModal', () => () => null);
jest.mock('../components/FeatureTour', () => () => null);
jest.mock('../components/transportation', () => () => null);
jest.setTimeout(15000);
const order = { uid: 'order-uid', order_id: 'ORDER-1', transportation: 'DHL', total_weight: 0, salesman: { id: 7, name: '业务员甲' }, customer_ids: [42], customer_name: '客户甲' };
const quote = { id: 12, version_no: 1, unit_price: 10, receivable_amount: 100, quoter_id: 7, is_final: true, is_effective: true };
const response = data => ({ ok: true, json: async () => ({ code: 200, data }) });
function setJwt(roles) { window.localStorage.setItem('jwt', `header.${window.btoa(JSON.stringify({ user_id: 7, roles }))}.signature`); }
function mockApi({ quotes = [quote], orderData = order } = {}) {
    global.fetch = jest.fn(async (rawUrl, options = {}) => {
        const pathname = new URL(rawUrl, 'http://localhost').pathname;
        if (pathname.endsWith('/payment-options/accounts')) return response({ items: [{ id: 1, name: '银行账户' }], total: 1 });
        if (pathname.endsWith('/payment-options/customers')) return response({ items: [{ id: 42, name: '客户甲' }], total: 1 });
        if (pathname.endsWith('/payment-options/orders')) return response({ items: [{ order_uid: order.uid, order_number: order.order_id, customer_name: '客户甲', order_date: '2026-10-06 10:00:00', transportation: 'DHL' }], total: 1 });
        if (pathname.endsWith('/finance/v2/payments') && options.method === 'POST') return response({ ...JSON.parse(options.body), id: 8, number: 'PAY-8', status: 'draft', version: 1 });
        if (pathname.endsWith('/payments/8/submit')) return response({ id: 8, number: 'PAY-8', status: 'pending', version: 2 });
        if (pathname.endsWith('/orders/order-uid/quotes')) return response(quotes);
        if (pathname.endsWith('/orders/order-uid/salesman')) return response(orderData.salesman);
        if (pathname.endsWith('/orders/order-uid')) return response(orderData);
        return response([]);
    });
}
function CurrentLocation() { return <span data-testid="current-location">{useLocation().pathname}</span>; }
function renderOrder() { return render(<MemoryRouter initialEntries={['/orders/order-uid']}><CurrentLocation /><Routes><Route path="/orders/:order_id" element={<OrderDetail />} /><Route path="/receipts" element={<span>收付款页面</span>} /></Routes></MemoryRouter>); }
beforeEach(() => {
    window.localStorage.clear(); window.sessionStorage.clear(); setJwt(['salesperson']);
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({ matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }) });
    mockApi();
});
afterEach(() => jest.restoreAllMocks());

test.each([
    ['空订单、无报价', []],
    ['报价失效', [{ ...quote, is_effective: false }]],
    ['其他业务员报价', [{ ...quote, quoter_id: 99 }]],
    ['有效报价，余额已结清', [quote]],
])('%s 仍可登记独立收付款，不查询旧订单余额', async (_, quotes) => {
    mockApi({ quotes }); renderOrder();
    fireEvent.click(await screen.findByRole('button', { name: '登记收付款' }, { timeout: 5000 }));
    const dialog = await screen.findByRole('dialog', { name: '登记收付款' });
    expect(dialog).toHaveClass('ant-modal');
    expect(within(dialog).getByRole('combobox', { name: '收付款客户' }).closest('.ant-select')).toHaveTextContent('客户甲');
    expect(within(dialog).getByRole('button', { name: '移除参考订单 ORDER-1' })).toBeInTheDocument();
    expect(within(await within(dialog).findByRole('row', { name: /ORDER-1/ })).getByRole('checkbox')).toBeChecked();
    expect(within(dialog).getByLabelText('金额(CNY)')).toHaveValue('');
    expect(screen.getByTestId('current-location')).toHaveTextContent('/orders/order-uid');
    expect(global.fetch.mock.calls.some(([url]) => /receivables|receivable-adjustments|\/receipts/.test(String(url)))).toBe(false);
    expect(global.fetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
});

test.each(['admin', 'finance', 'salesperson'])('%s can open unified payment registration', async role => {
    setJwt([role]); renderOrder(); expect(await screen.findByRole('button', { name: '登记收付款' })).toBeEnabled();
});
test.each(['store_manager', 'clerk', 'worker'])('%s does not gain payment registration access', async role => {
    setJwt([role]); renderOrder(); await screen.findByText('DHL');
    expect(screen.queryByRole('button', { name: '登记收付款' })).not.toBeInTheDocument();
});
test('missing customer opens the modal and requires choosing a customer before selecting orders', async () => {
    mockApi({ quotes: [], orderData: { ...order, customer_ids: null, customer_name: '' } }); renderOrder();
    fireEvent.click(await screen.findByRole('button', { name: '登记收付款' }));
    const dialog = await screen.findByRole('dialog', { name: '登记收付款' });
    expect(within(dialog).getByRole('combobox', { name: '收付款客户' }).closest('.ant-select')).not.toHaveTextContent('客户甲');
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/payment-options/orders'))).toBe(false);
    expect(screen.getByTestId('current-location')).toHaveTextContent('/orders/order-uid');
});

test.each([['保存', false], ['提交', true]])('%s registers the prefilled order inside its modal and stays on order details', async (label, submit) => {
    renderOrder(); fireEvent.click(await screen.findByRole('button', { name: '登记收付款' }));
    const dialog = await screen.findByRole('dialog', { name: '登记收付款' });
    fireEvent.mouseDown(within(dialog).getByLabelText('收付款账户'));
    fireEvent.click(await screen.findByText('银行账户', { selector: '.ant-select-item-option-content' }));
    fireEvent.change(within(dialog).getByLabelText('金额(CNY)'), { target: { value: '25' } });
    fireEvent.click(within(dialog).getByRole('button', { name: label }));
    await screen.findByText(submit ? '收付款已提交' : '收付款已保存');
    const writes = global.fetch.mock.calls.filter(([, options]) => options?.method === 'POST');
    expect(writes).toHaveLength(submit ? 2 : 1);
    expect(JSON.parse(writes[0][1].body)).toMatchObject({ partner_id: 42, reference_order_uids: ['order-uid'], amount: '25' });
    if (submit) expect(String(writes[1][0])).toMatch(/\/payments\/8\/submit$/);
    expect(screen.getByTestId('current-location')).toHaveTextContent('/orders/order-uid');
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '登记收付款' })).not.toBeInTheDocument());
});

test('canceling registration keeps order details open without creating a payment', async () => {
    renderOrder(); fireEvent.click(await screen.findByRole('button', { name: '登记收付款' }));
    const dialog = await screen.findByRole('dialog', { name: '登记收付款' });
    fireEvent.click(within(dialog).getByRole('button', { name: '取消' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '登记收付款' })).not.toBeInTheDocument());
    expect(screen.getByTestId('current-location')).toHaveTextContent('/orders/order-uid');
    expect(global.fetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
});
