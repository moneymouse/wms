import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import PackingListDetail from './packingListDetail';

jest.setTimeout(15000);

const boxes = [
    { uid: 'box-1', box_number: 1, transfer_id: 'OLD-1', weight: 2, item_name: '鞋子', piece_count: 1, target_order_uid: null },
    { uid: 'box-2', box_number: 2, transfer_id: 'OLD-2', weight: 3, item_name: '服装', piece_count: 2, target_order_uid: 'order-1' },
];
const baseDetail = { uid: 'pl-1', list_number: 'MARK-1', customer_id: 42, customer_name: '客户甲', status: 'completed', boxes };
const response = data => ({ ok: true, json: async () => ({ code: 200, data }) });
let currentDetail;
const writes = () => global.fetch.mock.calls.filter(([, options]) => options?.method === 'POST');

function login(roles, extra = {}) { localStorage.setItem('jwt', `header.${window.btoa(JSON.stringify({ user_id: 7, roles, ...extra }))}.signature`); }
function Navigation() { const navigate = useNavigate(); return <button onClick={() => navigate('/packing-lists/pl-2')}>切换装箱单</button>; }
function renderDetail() { return render(<MemoryRouter initialEntries={['/packing-lists/pl-1']}><Navigation /><Routes><Route path="/packing-lists/:uid" element={<PackingListDetail />} /></Routes></MemoryRouter>); }
async function openEditor() { fireEvent.click(await screen.findByRole('button', { name: '登记收付款' })); return screen.findByRole('dialog', { name: '登记收付款' }); }
async function chooseCustomer(dialog, name = '客户甲') {
    fireEvent.mouseDown(within(dialog).getByRole('combobox', { name: '收付款客户' }));
    fireEvent.click(await screen.findByText(name, { selector: '.ant-select-item-option-content' }));
}
async function fillPayment(dialog) {
    fireEvent.mouseDown(within(dialog).getByLabelText('收付款账户'));
    fireEvent.click(await screen.findByText('银行账户', { selector: '.ant-select-item-option-content' }));
    fireEvent.change(within(dialog).getByLabelText('金额(CNY)'), { target: { value: '25' } });
}
beforeEach(() => {
    localStorage.clear(); login(['salesperson']); currentDetail = baseDetail;
    window.matchMedia = jest.fn(query => ({ matches: false, media: query, addListener: jest.fn(), removeListener: jest.fn(), addEventListener: jest.fn(), removeEventListener: jest.fn() }));
    global.fetch = jest.fn(async (rawUrl, options = {}) => {
        const url = String(rawUrl);
        if (url.endsWith('/packing-list/pl-1')) return response(currentDetail);
        if (url.endsWith('/packing-list/pl-2')) return response({ ...baseDetail, uid: 'pl-2', list_number: 'MARK-2', customer_id: 43, customer_name: '客户乙', boxes: [{ ...boxes[0], uid: 'box-new' }] });
        if (url.includes('/payment-options/accounts')) return response({ items: [{ id: 1, name: '银行账户', active: true }], total: 1 });
        if (url.includes('/payment-options/customers')) return response({ items: [{ id: 42, name: '客户甲' }, { id: 43, name: '客户乙' }], total: 2 });
        if (url.includes('/payment-options/packing-boxes')) {
            const params = new URL(url, 'https://example.test').searchParams;
            const detail = params.get('packing_list_uid') === 'pl-2' ? { ...baseDetail, uid: 'pl-2', list_number: 'MARK-2', customer_id: 43, boxes: [{ ...boxes[0], uid: 'box-new' }] } : currentDetail;
            const matching = detail.customer_id == null || String(detail.customer_id) === params.get('customer_id');
            const items = matching ? detail.boxes.map(box => ({ ...box, box_uid: box.uid, packing_list_uid: detail.uid, list_number: detail.list_number, customer_id: detail.customer_id })) : [];
            return response({ items, total: items.length, page: 1, page_size: 200 });
        }
        if (url.includes('/payment-options/orders')) return response({ items: [], total: 0 });
        if (url.endsWith('/finance/v2/payments') && options.method === 'POST') return response({ ...JSON.parse(options.body), id: 8, number: 'PAY-8', status: 'draft', version: 1 });
        if (url.endsWith('/payments/8/submit')) return response({ id: 8, number: 'PAY-8', status: 'pending', version: 2 });
        return response([]);
    });
});
afterEach(() => { jest.restoreAllMocks(); localStorage.clear(); });

test.each(['admin', 'finance', 'salesperson'])('%s can register customer payments from packing-list details', async role => {
    login([role]); renderDetail(); expect(await screen.findByRole('button', { name: '登记收付款' })).toBeEnabled();
    expect(writes()).toHaveLength(0);
});
test.each(['clerk', 'store_manager', 'worker'])('%s does not gain payment registration permission', async role => {
    login([role]); renderDetail(); await screen.findByText('MARK-1');
    expect(screen.queryByRole('button', { name: '登记收付款' })).not.toBeInTheDocument();
});

test.each([['保存', false], ['提交', true]])('%s reuses finance payments with the bound customer and all current boxes', async (label, submit) => {
    renderDetail(); const dialog = await openEditor();
    expect(within(dialog).getByRole('button', { name: '移除备注箱子 MARK-1 / 箱 1' })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: '移除备注箱子 MARK-1 / 箱 2' })).toBeInTheDocument();
    expect(within(dialog).getByLabelText('金额(CNY)')).toHaveValue('');
    await fillPayment(dialog);
    fireEvent.change(within(dialog).getByRole('textbox', { name: '文字备注' }), { target: { value: '当前装箱单的实际收款' } });
    fireEvent.click(within(dialog).getByRole('button', { name: label }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '登记收付款' })).not.toBeInTheDocument());
    expect(writes()).toHaveLength(submit ? 2 : 1);
    expect(JSON.parse(writes()[0][1].body)).toMatchObject({ partner_type: 'customer', partner_id: 42, direction: 'incoming', amount: '25', reference_box_uids: ['box-1', 'box-2'], reference_order_uids: [], memo: '当前装箱单的实际收款', is_opening: false });
    expect(writes().some(([url]) => /\/payments\/8\/submit$/.test(String(url)))).toBe(submit);
    expect(global.fetch.mock.calls.some(([url]) => /\/receipts|\/order-allocations|\/documents/.test(String(url)))).toBe(false);
    expect(await screen.findByText('MARK-1')).toBeInTheDocument();
});

test('finance can select a specific box for registration without receiving editing actions', async () => {
    login(['finance']); renderDetail(); await screen.findByText('MARK-1');
    fireEvent.click(screen.getByRole('checkbox', { name: '箱子 2' }));
    expect(screen.queryByRole('button', { name: '生成原单号' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '添加箱子' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /批量操作|归档已选|编辑装箱单/ })).not.toBeInTheDocument();
    const dialog = await openEditor();
    expect(within(dialog).queryByRole('button', { name: '移除备注箱子 MARK-1 / 箱 1' })).not.toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: '移除备注箱子 MARK-1 / 箱 2' })).toBeInTheDocument();
    await fillPayment(dialog); fireEvent.click(within(dialog).getByRole('button', { name: '保存' }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(JSON.parse(writes()[0][1].body).reference_box_uids).toEqual(['box-2']);
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '登记收付款' })).not.toBeInTheDocument());
});

test('an unbound packing list requires a customer and retains its boxes after an explicit choice', async () => {
    currentDetail = { ...baseDetail, customer_id: null, customer_name: '' };
    renderDetail(); const dialog = await openEditor();
    expect(within(dialog).getByRole('combobox', { name: '收付款客户' })).toHaveValue('');
    expect(within(dialog).getByRole('button', { name: '移除备注箱子 MARK-1 / 箱 1' })).toBeInTheDocument();
    await fillPayment(dialog); fireEvent.click(within(dialog).getByRole('button', { name: '保存' }));
    expect(await within(dialog).findByText('请填写客户')).toBeInTheDocument();
    expect(writes()).toHaveLength(0);
    await chooseCustomer(dialog); await chooseCustomer(dialog, '客户乙');
    expect(within(dialog).getByRole('button', { name: '移除备注箱子 MARK-1 / 箱 1' })).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: '保存' }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(JSON.parse(writes()[0][1].body)).toMatchObject({ partner_id: 43, reference_box_uids: ['box-1', 'box-2'] });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '登记收付款' })).not.toBeInTheDocument());
});

test('switching to an incompatible customer clears the bound-list box references', async () => {
    renderDetail(); const dialog = await openEditor();
    await chooseCustomer(dialog, '客户乙');
    await waitFor(() => expect(within(dialog).queryByRole('button', { name: '移除备注箱子 MARK-1 / 箱 1' })).not.toBeInTheDocument());
    await fillPayment(dialog); fireEvent.click(within(dialog).getByRole('button', { name: '保存' }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(JSON.parse(writes()[0][1].body)).toMatchObject({ partner_id: 43, reference_box_uids: [] });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '登记收付款' })).not.toBeInTheDocument());
});

test('an empty unbound list opens registration without inventing a customer or box', async () => {
    currentDetail = { ...baseDetail, customer_id: null, customer_name: '', boxes: [] };
    renderDetail(); const dialog = await openEditor();
    expect(within(dialog).getByRole('combobox', { name: '收付款客户' })).toHaveValue('');
    expect(within(dialog).queryByRole('button', { name: /移除备注箱子/ })).not.toBeInTheDocument();
    await chooseCustomer(dialog); await fillPayment(dialog); fireEvent.click(within(dialog).getByRole('button', { name: '保存' }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(JSON.parse(writes()[0][1].body)).toMatchObject({ partner_id: 42, reference_box_uids: [], reference_order_uids: [] });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '登记收付款' })).not.toBeInTheDocument());
});

test('route changes close the old registration and use only the next packing-list snapshot', async () => {
    renderDetail(); await openEditor(); fireEvent.click(screen.getByRole('button', { name: '切换装箱单' }));
    await screen.findByText('MARK-2');
    expect(screen.queryByRole('dialog', { name: '登记收付款' })).not.toBeInTheDocument();
    const dialog = await openEditor();
    expect(within(dialog).getByRole('button', { name: '移除备注箱子 MARK-2 / 箱 1' })).toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: '移除备注箱子 MARK-1 / 箱 1' })).not.toBeInTheDocument();
    await fillPayment(dialog); fireEvent.click(within(dialog).getByRole('button', { name: '保存' }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(JSON.parse(writes()[0][1].body)).toMatchObject({ partner_id: 43, reference_box_uids: ['box-new'] });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '登记收付款' })).not.toBeInTheDocument());
});

test('a late detail response cannot replace the new packing-list payment context', async () => {
    let finishOld;
    const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => String(url).endsWith('/packing-list/pl-1') ? new Promise(resolve => { finishOld = resolve; }) : original(url, options));
    renderDetail(); await waitFor(() => expect(finishOld).toBeDefined());
    fireEvent.click(screen.getByRole('button', { name: '切换装箱单' })); await screen.findByText('MARK-2');
    await act(async () => finishOld(response(baseDetail)));
    expect(screen.queryByText('MARK-1')).not.toBeInTheDocument();
    const dialog = await openEditor();
    expect(within(dialog).getByRole('button', { name: '移除备注箱子 MARK-2 / 箱 1' })).toBeInTheDocument();
    expect(writes()).toHaveLength(0);
});
