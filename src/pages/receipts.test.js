import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Receipts from './receipts';
import { PaymentEditor, RecordDetail } from './financeWorkspace';

jest.mock('../components/FinanceHistoryDrawer', () => function History({ open, historyUrl }) { return open ? <div>历史路径 {historyUrl}</div> : null; });
jest.setTimeout(15000);
const response = data => Promise.resolve({ ok: true, status: 200, json: async () => ({ code: 200, data }) });
const fail = msg => Promise.resolve({ ok: false, status: 409, json: async () => ({ code: 409, msg }) });
const list = (items, total = items.length) => ({ items, total, page: 1, page_size: 20 });
const draft = { id: 8, number: 'PAY-0008', partner_type: 'customer', partner_id: 2, partner_name: '客户甲', direction: 'incoming', account_id: 1, account_name: '银行账户', payment_date: '2026-10-05', amount: '100.00', unallocated_amount: '100.00', allocated_amount: '0.00', status: 'draft', version: 1, created_by_id: 7, created_by_name: '业务员甲', requires_submission: true, reference_order_uids: [], reference_orders: [] };
function mockApi(overrides = {}) {
    let current = { ...draft, ...overrides.payment };
    global.fetch = jest.fn((rawUrl, options = {}) => {
        const url = new URL(rawUrl, 'http://localhost'); const path = url.pathname.split('/finance/v2')[1];
        if (path?.startsWith('/payment-options/customers')) return response(list([{ id: 2, name: '客户甲' }, { id: 3, name: '客户乙' }]));
        if (path?.startsWith('/payment-options/accounts')) return response(list([{ id: 1, name: '银行账户', currency: 'CNY' }]));
        if (path?.startsWith('/payment-options/orders')) return response(list([{ order_uid: 'empty-order', order_number: '空订单', customer_id: 2 }, { order_uid: 'settled-order', order_number: '已结清订单', customer_id: 2 }]));
        if (path === '/payments/8/submit') { if (overrides.submit) return overrides.submit(options); current = { ...current, status: 'pending', version: current.version + 1 }; return response(current); }
        if (path === '/payments/8/pdf') return response('cGRm');
        if (path === '/payments/8') { if (options.method === 'PATCH') current = { ...current, ...JSON.parse(options.body), version: current.version + 1 }; return response(current); }
        if (path === '/payments' && options.method === 'POST') { current = { ...current, ...JSON.parse(options.body) }; return response(current); }
        if (path === '/payments') return response(list(overrides.empty ? [] : [current]));
        throw new Error(`Unexpected request ${rawUrl}`);
    });
}
function setUser(roles = ['salesperson'], id = 7) { window.localStorage.setItem('jwt', `h.${window.btoa(JSON.stringify({ user_id: id, roles }))}.s`); }
function renderPage(context) { return render(<MemoryRouter initialEntries={[{ pathname: '/receipts', state: context ? { paymentContext: context } : undefined }]}><Receipts /></MemoryRouter>); }
async function select(input, text) { fireEvent.mouseDown(input); fireEvent.click(await screen.findByText(text, { selector: '.ant-select-item-option-content' })); }
async function fillNew({ withOrder = false } = {}) {
    await select(screen.getByRole('combobox', { name: '收付款客户' }), '客户甲');
    await select(screen.getByLabelText('收付款账户'), '银行账户');
    fireEvent.change(screen.getByLabelText('金额(CNY)'), { target: { value: '37.25' } });
    fireEvent.blur(screen.getByLabelText('金额(CNY)'));
    if (withOrder) {
        fireEvent.click(screen.getByRole('tab', { name: /订单备注/ }));
        fireEvent.click(within(await screen.findByRole('row', { name: /空订单/ })).getByRole('checkbox'));
    }
}
beforeEach(() => {
    window.localStorage.clear(); window.sessionStorage.clear(); setUser();
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({ matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }) });
    mockApi();
});
afterEach(() => jest.restoreAllMocks());

test('independent advance creates one payment then submits that same id without allocating an order', async () => {
    renderPage(); fireEvent.click(screen.getByRole('button', { name: /登记收款/ })); await fillNew();
    fireEvent.click(screen.getByRole('button', { name: '提交' }));
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => String(url).endsWith('/payments/8/submit'))).toBe(true));
    const create = global.fetch.mock.calls.find(([url, options]) => String(url).endsWith('/finance/v2/payments') && options.method === 'POST');
    expect(JSON.parse(create[1].body)).toMatchObject({ partner_type: 'customer', partner_id: 2, direction: 'incoming', amount: '37.25', account_id: 1, reference_order_uids: [], is_opening: false });
    expect(global.fetch.mock.calls.filter(([url, options]) => String(url).endsWith('/finance/v2/payments') && options.method === 'POST')).toHaveLength(1);
    expect(global.fetch.mock.calls.some(([url]) => /order-allocations|\/allocations|receivables|receivable-adjustments/.test(String(url)))).toBe(false);
    expect(global.fetch.mock.calls.some(([url, options]) => String(url).endsWith('/receipts') && options.method === 'POST')).toBe(false);
    expect((await screen.findAllByText('待财务确认')).length).toBeGreaterThan(0);
});

test('an empty order is optional reference only, while the payment amount remains independent', async () => {
    const saved = jest.fn(); render(<PaymentEditor open business onClose={jest.fn()} onSaved={saved} />); await fillNew({ withOrder: true });
    fireEvent.click(screen.getByRole('button', { name: '保存' })); await waitFor(() => expect(saved).toHaveBeenCalled());
    const body = JSON.parse(global.fetch.mock.calls.find(([, options]) => options.method === 'POST')[1].body);
    expect(body).toMatchObject({ amount: '37.25', reference_order_uids: ['empty-order'] });
    expect(body.items).toBeUndefined(); expect(body.allocations).toBeUndefined(); expect(body.order_uid).toBeUndefined();
});

test('navigation carries customer/reference context with no amount or implicit allocation', async () => {
    renderPage({ customerId: 2, customerName: '客户甲', orderUid: 'empty-order', orderNumber: '空订单' });
    expect(await screen.findByRole('dialog', { name: '登记收付款' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '移除参考订单 空订单' })).toBeInTheDocument();
    expect(within(await screen.findByRole('row', { name: /空订单/ })).getByRole('checkbox')).toBeChecked();
    expect(screen.getByLabelText('金额(CNY)')).toHaveValue('');
    expect(screen.queryByText('可收余额')).not.toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([url]) => /order-settlements|receivables/.test(String(url)))).toBe(false);
});

test('failed submit retains the created draft; retry updates and submits the same payment instead of duplicating cash', async () => {
    const submit = jest.fn().mockImplementationOnce(() => fail('连接中断')).mockImplementation(() => response({ ...draft, status: 'pending', version: 3 }));
    mockApi({ submit }); const saved = jest.fn(); render(<PaymentEditor open business onClose={jest.fn()} onSaved={saved} />); await fillNew();
    fireEvent.click(screen.getByRole('button', { name: '提交' })); await screen.findByText('草稿 PAY-0008 已保存，提交失败：连接中断');
    fireEvent.click(await screen.findByRole('button', { name: '提交' })); await waitFor(() => expect(saved).toHaveBeenCalledTimes(1));
    expect(global.fetch.mock.calls.filter(([url, options]) => String(url).endsWith('/payments') && options.method === 'POST')).toHaveLength(1);
    expect(global.fetch.mock.calls.filter(([url, options]) => String(url).endsWith('/payments/8') && options.method === 'PATCH')).toHaveLength(1);
    expect(JSON.parse(submit.mock.calls[1][0].body)).toMatchObject({ version: 2 });
});

test('returned business draft shows review reason and can resubmit but cannot post itself', async () => {
    mockApi({ payment: { review_remark: '流水号需核对', version: 4 } });
    render(<RecordDetail entity="payments" recordId={8} business onClose={jest.fn()} onChanged={jest.fn()} />);
    await screen.findByText('退回原因：流水号需核对');
    expect(screen.getByRole('button', { name: '编辑草稿' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: '确认生效' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '提交' }));
    await screen.findByText('提交后由另一位财务人员核对实际收付款。参考订单不会自动核销。');
    const modal = screen.getAllByRole('dialog').find(item => within(item).queryByText('提交后由另一位财务人员核对实际收付款。参考订单不会自动核销。'));
    fireEvent.click(within(modal).getByRole('button', { name: '提交' }));
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => String(url).endsWith('/payments/8/submit'))).toBe(true));
    const options = global.fetch.mock.calls.find(([url]) => String(url).endsWith('/payments/8/submit'))[1];
    expect(JSON.parse(options.body).version).toBe(4);
});

test('business view of posted funds supports history and print but never financial allocations or reversal', async () => {
    mockApi({ payment: { status: 'posted', review_remark: '到账一致' } });
    render(<RecordDetail entity="payments" recordId={8} business onClose={jest.fn()} onChanged={jest.fn()} />);
    await screen.findByText('财务处理意见：到账一致');
    expect(screen.queryByRole('button', { name: /核销|冲销|确认收付款|退回修改/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /打印/ })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: /修改历史/ }));
    expect(screen.getByText('历史路径 /finance/v2/payments/8/history')).toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/allocations'))).toBe(false);
});

test('zero amount cannot create or submit a draft', async () => {
    render(<PaymentEditor open business onClose={jest.fn()} onSaved={jest.fn()} />); await fillNew();
    fireEvent.change(screen.getByLabelText('金额(CNY)'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: '提交' })); await screen.findByText('请填写金额');
    expect(global.fetch.mock.calls.some(([, options]) => ['POST', 'PATCH'].includes(options.method))).toBe(false);
});

test('changing the customer clears reference orders before a draft is saved', async () => {
    const done = jest.fn(); render(<PaymentEditor open business initialContext={{ customerId: 2, customerName: '客户甲', orderUid: 'empty-order', orderNumber: '空订单' }} onClose={jest.fn()} onSaved={done} />);
    await select(screen.getByRole('combobox', { name: '收付款客户' }), '客户乙');
    expect(screen.queryByRole('button', { name: '移除参考订单 空订单' })).not.toBeInTheDocument();
    await select(screen.getByLabelText('收付款账户'), '银行账户'); fireEvent.change(screen.getByLabelText('金额(CNY)'), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' })); await waitFor(() => expect(done).toHaveBeenCalled());
    const body = JSON.parse(global.fetch.mock.calls.find(([, options]) => options.method === 'POST')[1].body);
    expect(body).toMatchObject({ partner_id: 3, reference_order_uids: [] });
});

test('closing after a failed submit surfaces the already saved draft instead of hiding the financial record', async () => {
    mockApi({ submit: () => fail('提交暂不可用') }); const saved = jest.fn(); const close = jest.fn();
    render(<PaymentEditor open business onClose={close} onSaved={saved} />); await fillNew();
    fireEvent.click(screen.getByRole('button', { name: '提交' })); await screen.findByText('草稿 PAY-0008 已保存，提交失败：提交暂不可用');
    fireEvent.click(await screen.findByRole('button', { name: 'Close' }));
    expect(saved).toHaveBeenCalledWith(expect.objectContaining({ id: 8, status: 'draft' })); expect(close).toHaveBeenCalledTimes(1);
    expect(global.fetch.mock.calls.filter(([url, options]) => String(url).endsWith('/payments') && options.method === 'POST')).toHaveLength(1);
});

test('business mine/all permissions honor mixed legacy role and roles JWTs consistently with navigation', async () => {
    window.localStorage.setItem('jwt', `h.${window.btoa(JSON.stringify({ user_id: 7, role: 'finance', roles: ['salesperson'] }))}.s`);
    renderPage();
    expect(screen.getByRole('combobox', { name: '登记人范围' })).toBeInTheDocument();
    await select(screen.getByRole('combobox', { name: '登记人范围' }), '全部收付款');
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => {
        const parsed = new URL(url, 'http://localhost'); return parsed.pathname.endsWith('/payments') && !parsed.searchParams.has('created_by_id');
    })).toBe(true));
});
