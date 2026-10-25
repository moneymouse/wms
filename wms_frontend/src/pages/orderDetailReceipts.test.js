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
    let registeredPayment;
    global.fetch = jest.fn(async (rawUrl, options = {}) => {
        const pathname = new URL(rawUrl, 'http://localhost').pathname;
        if (pathname.endsWith('/order-payments/order-uid')) return response({
            items: registeredPayment ? [registeredPayment] : [], total: registeredPayment ? 1 : 0, page: 1, page_size: 10, visibility: 'own',
            summary: { received_amount: '0.00', refunded_amount: '0.00', net_received_amount: '0.00', related_received_amount: '0.00', related_refunded_amount: '0.00', draft_count: registeredPayment?.status === 'draft' ? 1 : 0, pending_count: registeredPayment?.status === 'pending' ? 1 : 0 },
        });
        if (pathname.endsWith('/orders/order-uid/costs')) return response({ items: [], total: 0, confirmed_net_amount: '0.00', confirmed_amount: '0.00', pending_amount: '0.00' });
        if (pathname.endsWith('/payment-options/accounts')) return response({ items: [{ id: 1, name: '银行账户' }], total: 1 });
        if (pathname.endsWith('/payment-options/customers')) return response({ items: [{ id: 42, name: '客户甲' }], total: 1 });
        if (pathname.endsWith('/payment-options/orders')) return response({ items: [{ order_uid: order.uid, order_number: order.order_id, customer_name: '客户甲', order_date: '2026-10-06 10:00:00', transportation: 'DHL' }], total: 1 });
        if (pathname.endsWith('/finance/v2/payments') && options.method === 'POST') {
            registeredPayment = { ...JSON.parse(options.body), id: 8, number: 'PAY-8', status: 'draft', version: 1, account_name: '银行账户', created_by_name: '业务员甲', relation_types: ['reference'], order_allocated_amount: '0.00' };
            return response(registeredPayment);
        }
        if (pathname.endsWith('/payments/8/submit')) {
            registeredPayment = { ...registeredPayment, status: 'pending', version: 2 };
            return response(registeredPayment);
        }
        if (pathname.endsWith('/orders/order-uid/quotes')) return response(quotes);
        if (pathname.endsWith('/orders/order-uid/salesman')) return response(orderData.salesman);
        if (pathname.endsWith('/orders/order-uid')) return response(orderData);
        return response([]);
    });
}
function CurrentLocation() { return <span data-testid="current-location">{useLocation().pathname}</span>; }
function renderOrder() { return render(<MemoryRouter initialEntries={['/orders/order-uid']}><CurrentLocation /><Routes><Route path="/orders/:order_id" element={<OrderDetail />} /><Route path="/receipts" element={<span>收付款页面</span>} /></Routes></MemoryRouter>); }
function financialSection() { return within(screen.getByRole('region', { name: '费用与收付款' })); }
async function openPaymentRecords() {
    fireEvent.click(financialSection().getByRole('button', { name: /收付款记录/, expanded: false }));
    return screen.findByRole('region', { name: '本单收付款' });
}
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

test.each([
    ['admin', true, true],
    ['finance', true, true],
    ['salesperson', true, false],
    ['clerk', false, true],
    ['store_manager', false, false],
    ['worker', false, false],
])('%s sees only permitted financial panels, initially collapsed', async (role, canRecord, canSeeCosts) => {
    setJwt([role]); renderOrder(); await screen.findByText('DHL');
    if (canRecord) expect(screen.getByRole('button', { name: '登记收付款' })).toBeEnabled();
    else expect(screen.queryByRole('button', { name: '登记收付款' })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: '本单收付款' })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: '本单第三方成本' })).not.toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/order-payments/'))).toBe(false);
    expect(global.fetch.mock.calls.some(([url]) => String(url).endsWith('/orders/order-uid/costs'))).toBe(false);
    if (!canRecord && !canSeeCosts) {
        expect(screen.queryByRole('region', { name: '费用与收付款' })).not.toBeInTheDocument();
        return;
    }
    const section = financialSection();
    expect(section.queryByRole('button', { name: /收付款记录/, expanded: false }) !== null).toBe(canRecord);
    expect(section.queryByRole('button', { name: /第三方成本/, expanded: false }) !== null).toBe(canSeeCosts);
    if (canRecord) {
        await openPaymentRecords();
        await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/order-payments/order-uid'))).toBe(true));
    }
    if (canSeeCosts) {
        fireEvent.click(section.getByRole('button', { name: /第三方成本/, expanded: false }));
        const costs = within(await section.findByRole('region', { name: '本单第三方成本' }));
        expect(await costs.findByText('已确认成本（不含税）')).toBeInTheDocument();
    }
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
    renderOrder(); await screen.findByRole('button', { name: '登记收付款' }); await openPaymentRecords();
    await waitFor(() => expect(global.fetch.mock.calls.filter(([url]) => String(url).includes('/order-payments/order-uid'))).toHaveLength(1));
    fireEvent.click(await screen.findByRole('button', { name: '登记收付款' }));
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
    const paymentPanel = within(screen.getByRole('region', { name: '本单收付款' }));
    const savedRow = await paymentPanel.findByRole('row', { name: /PAY-8/ });
    expect(within(savedRow).getByText(submit ? '待财务确认' : '草稿')).toBeInTheDocument();
    expect(within(savedRow).getByText('25.00')).toBeInTheDocument();
    expect(within(savedRow).getByText('0.00')).toBeInTheDocument();
    expect(global.fetch.mock.calls.filter(([url]) => String(url).includes('/order-payments/order-uid'))).toHaveLength(2);
});

test('saving with records collapsed keeps them folded and refreshes records when reopened', async () => {
    renderOrder(); await screen.findByRole('button', { name: '登记收付款' });
    await openPaymentRecords();
    await screen.findByText('暂无本单收付款记录');
    fireEvent.click(financialSection().getByRole('button', { name: /收付款记录/, expanded: true }));
    fireEvent.click(screen.getByRole('button', { name: '登记收付款' }));
    const dialog = await screen.findByRole('dialog', { name: '登记收付款' });
    fireEvent.mouseDown(within(dialog).getByLabelText('收付款账户'));
    fireEvent.click(await screen.findByText('银行账户', { selector: '.ant-select-item-option-content' }));
    fireEvent.change(within(dialog).getByLabelText('金额(CNY)'), { target: { value: '25' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '保存' }));
    await screen.findByText('收付款已保存');
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '登记收付款' })).not.toBeInTheDocument());
    expect(financialSection().getByRole('button', { name: /收付款记录/, expanded: false })).toBeInTheDocument();
    const paymentPanel = within(await openPaymentRecords());
    expect(await paymentPanel.findByRole('row', { name: /PAY-8/ })).toHaveTextContent('25.00');
    expect(global.fetch.mock.calls.filter(([url]) => String(url).includes('/order-payments/order-uid'))).toHaveLength(2);
});

test('canceling registration keeps order details open without creating a payment', async () => {
    renderOrder(); fireEvent.click(await screen.findByRole('button', { name: '登记收付款' }));
    const dialog = await screen.findByRole('dialog', { name: '登记收付款' });
    fireEvent.click(within(dialog).getByRole('button', { name: '取消' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '登记收付款' })).not.toBeInTheDocument());
    expect(screen.getByTestId('current-location')).toHaveTextContent('/orders/order-uid');
    expect(global.fetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
});
