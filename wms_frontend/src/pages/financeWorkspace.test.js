import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AllocationDialog, DocumentEditor, FinanceDocuments, FinancePayments, PaymentEditor, RecordDetail } from './financeWorkspace';

jest.mock('./financeAccounting', () => () => null);
jest.mock('../components/FinanceHistoryDrawer', () => function History({ open, historyUrl }) {
    return open ? <div>历史路径 {historyUrl}</div> : null;
});
const response = data => Promise.resolve({ ok: true, status: 200, json: async () => ({ code: 200, data }) });
const doc = {
    id: 7, number: 'INV-0007', document_type: 'customer_invoice', partner_type: 'customer', partner_id: 2,
    partner_name: '客户甲', document_date: '2026-10-05', due_date: '2026-10-31', status: 'draft',
    version: 3, total_amount: '120.00', residual_amount: '120.00', allocated_amount: '0.00', payment_status: 'unpaid',
    lines: [{ id: 1, description: '运输服务', quantity: '1', unit_price: '120', tax_rate: '0', total_amount: '120', tax_amount: '0' }],
};
const payment = { id: 8, number: 'PAY-0008', partner_type: 'customer', partner_id: 2, partner_name: '客户甲', direction: 'incoming', account_id: 1, account_name: '银行账户', payment_date: '2026-10-05', amount: '100.00', unallocated_amount: '50.00', allocated_amount: '50.00', status: 'posted', version: 4 };
function list(items, total = items.length, page = 1) { return { items, total, page, page_size: 20 }; }

beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({ matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }) });
    window.localStorage.setItem('jwt', 'header.payload.signature');
    global.fetch = jest.fn(url => {
        const path = String(url).split('/finance/v2')[1];
        if (path.startsWith('/payment-options/orders')) return response(list([]));
        if (path.startsWith('/partners')) return response({ items: [{ id: 2, name: '客户甲', partner_type: 'customer' }], total: 1 });
        if (path.startsWith('/accounts')) return response(list([{ id: 1, name: '银行账户', active: true }]));
        if (path.startsWith('/allocations')) return response(list([]));
        if (path === '/documents/7') return response(doc);
        if (path.startsWith('/documents')) return response(list([doc]));
        if (path === '/payments/8') return response(payment);
        if (path.startsWith('/payments')) return response(list([payment]));
        throw new Error(`Unexpected request ${path}`);
    });
});
afterEach(() => { jest.restoreAllMocks(); });

test.each([
    ['ORDER-REF', '/orders/order-ref', '订单详情已打开'],
    ['MARK-REF / 箱 2', '/packing-lists/packing-ref', '装箱单详情已打开'],
    ['ORDER-CURRENT', '/orders/order-current', '当前订单详情已打开'],
])('payment reference %s links directly to its detail page', async (label, path, destination) => {
    global.fetch.mockImplementation(() => response({ ...payment,
        reference_orders: [{ order_uid: 'order-ref', order_number: 'ORDER-REF' }],
        reference_packing_boxes: [{ box_uid: 'box-ref', packing_list_uid: 'packing-ref', list_number: 'MARK-REF', box_number: 2 }],
        packing_order_references: [{ order_uid: 'order-current', order_number: 'ORDER-CURRENT' }],
    }));
    render(<MemoryRouter initialEntries={['/payment']}><Routes>
        <Route path="/payment" element={<RecordDetail entity="payments" recordId={8} onClose={() => {}} />} />
        <Route path={path} element={<div>{destination}</div>} />
    </Routes></MemoryRouter>);
    const link = await screen.findByRole('link', { name: label });
    expect(link).toHaveAttribute('href', path);
    fireEvent.click(link);
    expect(await screen.findByText(destination)).toBeInTheDocument();
});

test.each([true, false])('pending payment can be cancelled with a reason and retained history (business=%s)', async business => {
    let current = { ...payment, status: 'pending', allocated_amount: '0.00', unallocated_amount: '0.00' };
    global.fetch.mockImplementation((url, options) => {
        if (String(url).endsWith('/payments/8/cancel')) {
            current = { ...current, status: 'cancelled', version: 5, cancellation_reason: '金额登记错误' };
            return response(current);
        }
        return response(current);
    });
    render(<RecordDetail entity="payments" recordId={8} business={business} onClose={() => {}} />);
    fireEvent.click(await screen.findByRole('button', { name: '撤销收付款' }));
    const dialog = screen.getAllByRole('dialog').find(item => within(item).queryByLabelText('操作原因'));
    fireEvent.click(within(dialog).getByRole('button', { name: '撤销收付款' }));
    expect(await within(dialog).findByText('请填写原因，供后续审计核对')).toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
    fireEvent.change(within(dialog).getByLabelText('操作原因'), { target: { value: '金额登记错误' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '撤销收付款' }));
    await screen.findByText('收付款已撤销，原收据无效。撤销原因：金额登记错误');
    const [, options] = global.fetch.mock.calls.find(([url]) => String(url).endsWith('/payments/8/cancel'));
    expect(JSON.parse(options.body)).toMatchObject({ version: 4, reason: '金额登记错误', idempotency_key: expect.any(String) });
    expect(screen.queryByRole('button', { name: '撤销收付款' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /修改历史/ }));
    expect(await screen.findByText('历史路径 /finance/v2/payments/8/history')).toBeInTheDocument();
});

test.each(['posted', 'reversed', 'cancelled'])('%s payments cannot be cancelled from the detail page', async status => {
    global.fetch.mockImplementation(() => response({ ...payment, status }));
    render(<RecordDetail entity="payments" recordId={8} onClose={() => {}} />);
    await screen.findByText('PAY-0008');
    expect(screen.queryByRole('button', { name: '撤销收付款' })).not.toBeInTheDocument();
});

test('unsettled documents default to every date and pagination requests the server', async () => {
    global.fetch.mockImplementation(url => response(list([{ ...doc, status: 'posted' }], 45, Number(new URL(String(url), 'https://test').searchParams.get('p')))));
    render(<FinanceDocuments />);
    await screen.findByText('INV-0007');
    const first = String(global.fetch.mock.calls[0][0]);
    expect(first).toContain('open_only=1');
    expect(first).not.toContain('date_from');
    fireEvent.click(screen.getByTitle('2'));
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => String(url).includes('p=2'))).toBe(true));
    const search = screen.getByPlaceholderText('账单号 / 往来单位 / 参考号');
    fireEvent.change(search, { target: { value: '合同-23' } });
    fireEvent.keyDown(search, { key: 'Enter', code: 'Enter', keyCode: 13 });
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => {
        const query = new URL(String(url), 'https://test').searchParams;
        return query.get('q') === '合同-23' && query.get('p') === '1' && query.get('open_only') === '1';
    })).toBe(true));
});

test('posting a document is explicit, version checked, and refreshes its immutable state', async () => {
    let current = { ...doc };
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => {
        if (String(url).endsWith('/documents/7/post')) { current = { ...doc, status: 'posted', version: 4 }; return response(current); }
        if (String(url).endsWith('/documents/7')) return response(current);
        return original(url, options);
    });
    render(<FinanceDocuments />);
    fireEvent.click(await screen.findByRole('button', { name: 'INV-0007' }));
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => String(url).endsWith('/documents/7'))).toBe(true));
    fireEvent.click(await screen.findByRole('button', { name: /确认生效/ }));
    expect(global.fetch.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(0);
    await screen.findByText('请核对往来单位、日期和费用明细。确认后生成会计凭证，账单金额锁定。');
    const dialog = screen.getAllByRole('dialog').find(item => within(item).queryByText('请核对往来单位、日期和费用明细。确认后生成会计凭证，账单金额锁定。'));
    fireEvent.click(within(dialog).getByRole('button', { name: '确认生效' }));
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => String(url).endsWith('/documents/7/post'))).toBe(true));
    const [, options] = global.fetch.mock.calls.find(([url]) => String(url).endsWith('/documents/7/post'));
    expect(JSON.parse(options.body)).toMatchObject({ version: 3, idempotency_key: expect.any(String) });
    await waitFor(() => expect(screen.queryByRole('button', { name: '编辑草稿' })).not.toBeInTheDocument());
    fireEvent.click(await screen.findByRole('button', { name: /修改历史/ }));
    expect(await screen.findByText('历史路径 /finance/v2/documents/7/history')).toBeInTheDocument();
});

test('draft edits preserve the server version and keep form inputs after a conflict', async () => {
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => options?.method === 'PATCH'
        ? Promise.resolve({ ok: false, status: 409, json: async () => ({ code: 409, msg: '账单已被其他人修改，请刷新' }) }) : original(url, options));
    const onSaved = jest.fn();
    render(<DocumentEditor open document={doc} onClose={jest.fn()} onSaved={onSaved} />);
    expect(await screen.findByDisplayValue('运输服务')).toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue('运输服务'), { target: { value: '运输服务修订' } });
    fireEvent.click(screen.getByRole('button', { name: '保存草稿' }));
    expect(await screen.findByText('账单已被其他人修改，请刷新')).toBeInTheDocument();
    expect(screen.getByDisplayValue('运输服务修订')).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
    const [, options] = global.fetch.mock.calls.find(([, options]) => options.method === 'PATCH');
    expect(JSON.parse(options.body)).toMatchObject({ version: 3, document_type: 'customer_invoice', document_date: '2026-10-05', lines: [{ description: '运输服务修订' }] });
});

test('partial allocation uses the source version, partner scope, and actual selected amount', async () => {
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => {
        if (options?.method === 'POST') return response(list([]));
        return original(url, options);
    });
    const onSuccess = jest.fn();
    render(<AllocationDialog source={payment} sourceType="payments" onClose={jest.fn()} onSuccess={onSuccess} />);
    await screen.findByText('INV-0007');
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('partner_id=2') && String(url).includes('document_type=customer_invoice'))).toBe(true);
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    const input = screen.getByRole('spinbutton', { name: 'INV-0007 核销金额' });
    fireEvent.change(input, { target: { value: '25' } });
    fireEvent.blur(input);
    fireEvent.click(screen.getByRole('button', { name: '确认核销' }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    const [, options] = global.fetch.mock.calls.find(([, options]) => options.method === 'POST');
    expect(JSON.parse(options.body)).toMatchObject({ payment_id: 8, version: 4, allocations: [{ document_id: 7, amount: 25 }] });
});

test('allocation rejects amounts exceeding available funds without a write', async () => {
    global.fetch.mockImplementation(() => response(list([{ ...doc, residual_amount: '120' }, { ...doc, id: 9, number: 'INV-0009', residual_amount: '120' }])));
    render(<AllocationDialog source={payment} sourceType="payments" onClose={jest.fn()} onSuccess={jest.fn()} />);
    await screen.findByText('INV-0007');
    fireEvent.click(screen.getAllByRole('checkbox')[0]);
    fireEvent.click(screen.getByRole('button', { name: '确认核销' }));
    expect(await screen.findByText('核销合计不能超过可用余额')).toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([, options]) => options.method === 'POST')).toBe(false);
});

test('payment reversal requires a reason and never treats it as deleting the payment', async () => {
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => options?.method === 'POST' ? response({ ...payment, status: 'reversed' }) : original(url, options));
    render(<FinancePayments />);
    fireEvent.click(await screen.findByRole('button', { name: 'PAY-0008' }));
    fireEvent.click(await screen.findByRole('button', { name: /^冲\s*销$/ }));
    await screen.findByText('冲销会保留原资金记录并生成反向凭证。请先撤销此收付款的所有有效核销。');
    const dialog = screen.getAllByRole('dialog').find(item => within(item).queryByText('冲销会保留原资金记录并生成反向凭证。请先撤销此收付款的所有有效核销。'));
    fireEvent.click(within(dialog).getByRole('button', { name: '冲销收付款' }));
    expect(await screen.findByText('请填写原因，供后续审计核对')).toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([, options]) => options.method === 'POST')).toBe(false);
    fireEvent.change(within(dialog).getByLabelText('操作原因'), { target: { value: '重复登记，按原路冲销' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '冲销收付款' }));
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => String(url).endsWith('/payments/8/reverse'))).toBe(true));
    const [, options] = global.fetch.mock.calls.find(([url]) => String(url).endsWith('/payments/8/reverse'));
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body)).toMatchObject({ version: 4, reason: '重复登记，按原路冲销' });
});


test('opening customer balances retain their opening flag when saved', async () => {
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => options?.method === 'PATCH' ? response(doc) : original(url, options));
    const onSaved = jest.fn();
    render(<DocumentEditor open document={{ ...doc, is_opening: true }} onClose={jest.fn()} onSaved={onSaved} />);
    expect(await screen.findByRole('checkbox', { name: '期初账单' })).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: '保存草稿' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const [, options] = global.fetch.mock.calls.find(([, options]) => options.method === 'PATCH');
    expect(JSON.parse(options.body)).toMatchObject({ is_opening: true, version: 3 });
});

test('customer refunds cannot be saved as opening advances even with a stale opening flag', async () => {
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => options?.method === 'PATCH' ? response(payment) : original(url, options));
    const onSaved = jest.fn();
    render(<PaymentEditor open payment={{ ...payment, status: 'draft', direction: 'outgoing', is_opening: true }} onClose={jest.fn()} onSaved={onSaved} />);
    await screen.findByDisplayValue('100.00');
    expect(screen.queryByRole('checkbox', { name: '期初预收 / 预付' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const [, options] = global.fetch.mock.calls.find(([, options]) => options.method === 'PATCH');
    expect(JSON.parse(options.body)).toMatchObject({ direction: 'outgoing', partner_type: 'customer', is_opening: false, version: 4 });
});


test('refund-reserved balances are shown separately and cannot offer an unusable allocation action', async () => {
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => String(url).endsWith('/payments/8') ? response({ ...payment, available_amount: '0.00' }) : original(url, options));
    render(<FinancePayments />);
    fireEvent.click(await screen.findByRole('button', { name: 'PAY-0008' }));
    expect(await screen.findByText('可核销余额')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /核销账单/ })).not.toBeInTheDocument();
    const drawer = screen.getByRole('dialog');
    expect(within(drawer).getAllByText('¥ 50.00').length).toBeGreaterThan(0);
    expect(within(drawer).getByText('¥ 0.00')).toBeInTheDocument();
});

test('finance confirms the exact submitted payment instead of creating another cash record', async () => {
    const payload = window.btoa(JSON.stringify({ user_id: 9, roles: ['finance'] })); window.localStorage.setItem('jwt', `h.${payload}.s`);
    let current = { ...payment, status: 'pending', created_by_id: 7, version: 6, requires_submission: true };
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => {
        if (String(url).endsWith('/payments/8/post')) { current = { ...current, status: 'posted', version: 7 }; return response(current); }
        if (String(url).endsWith('/payments/8')) return response(current);
        return original(url, options);
    });
    render(<FinancePayments />); fireEvent.click(await screen.findByRole('button', { name: 'PAY-0008' }));
    fireEvent.click(await screen.findByRole('button', { name: '确认收付款' }));
    await screen.findByText('请核对实际资金收付和账户。确认后在本记录生成会计凭证，随后可独立核销。');
    const modal = screen.getAllByRole('dialog').find(item => within(item).queryByText('请核对实际资金收付和账户。确认后在本记录生成会计凭证，随后可独立核销。'));
    fireEvent.click(within(modal).getByRole('button', { name: '确认收付款' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: '退回修改' })).not.toBeInTheDocument());
    const writes = global.fetch.mock.calls.filter(([, options]) => options?.method === 'POST');
    expect(writes).toHaveLength(1); expect(String(writes[0][0])).toContain('/payments/8/post'); expect(JSON.parse(writes[0][1].body).version).toBe(6);
});

test('finance cannot approve or return its own pending payment', async () => {
    window.localStorage.setItem('jwt', `h.${window.btoa(JSON.stringify({ user_id: 7, roles: ['admin'] }))}.s`);
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => String(url).endsWith('/payments/8') ? response({ ...payment, status: 'pending', created_by_id: 7 }) : original(url, options));
    render(<FinancePayments />); fireEvent.click(await screen.findByRole('button', { name: 'PAY-0008' }));
    expect(await screen.findByRole('button', { name: '确认收付款' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '退回修改' })).toBeDisabled();
    expect(screen.getByText('不能审核本人登记的收付款，请由另一位财务人员处理。')).toBeInTheDocument();
});

test('business-origin finance draft requires submission and cannot be directly posted', async () => {
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => String(url).endsWith('/payments/8') ? response({ ...payment, status: 'draft', requires_submission: true }) : original(url, options));
    render(<FinancePayments />); fireEvent.click(await screen.findByRole('button', { name: 'PAY-0008' }));
    expect(await screen.findByRole('button', { name: '提交' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: '确认生效' })).not.toBeInTheDocument();
});

test('returning a submitted payment requires an audit reason and targets the same versioned record', async () => {
    window.localStorage.setItem('jwt', `h.${window.btoa(JSON.stringify({ user_id: 9, roles: ['finance'] }))}.s`);
    const original = global.fetch.getMockImplementation();
    let current = { ...payment, status: 'pending', created_by_id: 7, version: 6 };
    global.fetch.mockImplementation((url, options) => {
        if (String(url).endsWith('/payments/8/return')) { current = { ...current, status: 'draft', review_remark: JSON.parse(options.body).reason, version: 7, requires_submission: true }; return response(current); }
        if (String(url).endsWith('/payments/8')) return response(current);
        return original(url, options);
    });
    render(<FinancePayments />); fireEvent.click(await screen.findByRole('button', { name: 'PAY-0008' })); fireEvent.click(await screen.findByRole('button', { name: '退回修改' }));
    await screen.findByText('退回为草稿，登记人修改后可重新提交；退回原因保留在历史中。');
    const modal = screen.getAllByRole('dialog').find(item => within(item).queryByText('退回为草稿，登记人修改后可重新提交；退回原因保留在历史中。'));
    fireEvent.click(within(modal).getByRole('button', { name: '退回修改' })); await screen.findByText('请填写原因，供后续审计核对');
    expect(global.fetch.mock.calls.some(([url]) => String(url).endsWith('/payments/8/return'))).toBe(false);
    fireEvent.change(within(modal).getByLabelText('操作原因'), { target: { value: '账户与流水不符' } }); fireEvent.click(await within(modal).findByRole('button', { name: '退回修改' }));
    await screen.findByText('退回原因：账户与流水不符');
    const post = global.fetch.mock.calls.find(([url]) => String(url).endsWith('/payments/8/return'));
    expect(JSON.parse(post[1].body)).toMatchObject({ version: 6, reason: '账户与流水不符', idempotency_key: expect.any(String) });
});

test('order-managed bills cannot bypass current order settlement through generic allocation', async () => {
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => String(url).includes('/documents') ? response(list([{ ...doc, order_managed: true, managed_order_uid: 'order-1' }])) : original(url, options));
    render(<AllocationDialog source={payment} sourceType="payments" onClose={jest.fn()} onSuccess={jest.fn()} />); await screen.findByText('INV-0007');
    expect(screen.getAllByRole('checkbox')[1]).toBeDisabled(); expect(screen.getByText('订单账单，请使用核销订单')).toBeInTheDocument();
});

test('order-managed invoice detail directs quote changes back to order settlement instead of manual reversal', async () => {
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => String(url).endsWith('/documents/7') ? response({ ...doc, status: 'posted', order_managed: true, managed_order_uid: 'order-1' }) : original(url, options));
    render(<FinanceDocuments />); fireEvent.click(await screen.findByRole('button', { name: 'INV-0007' }));
    expect(await screen.findByText('此账单由订单报价生成。报价变更请在「订单应收」确认，收付款请通过「核销订单」办理；不能手工创建贷项或冲销此账单。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^冲\s*销$/ })).not.toBeInTheDocument();
});
