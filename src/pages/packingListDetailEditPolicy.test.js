import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import PackingListDetail from './packingListDetail';
import { ORDER_EDIT_POLICY_KEYS } from '../common/orderEditPolicy';

const editablePolicy = Object.fromEntries(ORDER_EDIT_POLICY_KEYS.map(key => [key, true]));
const detail = {
    uid: 'pl-1', list_number: 'MARK-1', status: 'completed',
    boxes: [{
        uid: 'box-1', box_number: 1, target_order_uid: 'order-1', target_order_id: 'ORDER-1',
        item_name: '鞋子', piece_count: 2,
        item_details: [{ item_name: '鞋子', customs_code: '1001', piece_count: 2 }],
        weight: 3.2, transfer_id: 'OLD-1', waybill_id: 'WB-1',
        workers: [{ worker_id: 7, worker_name: '操作员甲' }], status: 'outbound',
        edit_policy: editablePolicy, identity_editable: false,
    }],
};
let activeDetail;
let undoResponse;

function setJwt(roles = ['admin']) {
    const payload = window.btoa(JSON.stringify({ user_id: 1, roles }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
}
function renderDetail() {
    return render(<MemoryRouter initialEntries={['/packing-lists/pl-1']}>
        <Routes><Route path="/packing-lists/:uid" element={<PackingListDetail />} /></Routes>
    </MemoryRouter>);
}
async function openBoxEditor() {
    await screen.findByText('MARK-1');
    const buttons = screen.getAllByRole('button', { name: /编辑/ });
    fireEvent.click(buttons[buttons.length - 1]);
    return screen.findByRole('dialog', { name: /编辑箱子/ });
}

beforeEach(() => {
    activeDetail = detail;
    undoResponse = { code: 200 };
    setJwt();
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({
        matches: false, media: query, onchange: null,
        addListener: () => {}, removeListener: () => {}, addEventListener: () => {},
        removeEventListener: () => {}, dispatchEvent: () => false,
    }) });
    global.fetch = jest.fn((rawUrl, options = {}) => {
        const url = String(rawUrl);
        if (url.endsWith('/box/box-1/undo-ship')) {
            if (undoResponse.code === 200) {
                activeDetail = { ...activeDetail, boxes: activeDetail.boxes.map(box => ({
                    ...box, status: 'pending_outbound', waybill_id: '', date: null,
                    identity_editable: false,
                })) };
            }
            return Promise.resolve({ ok: undoResponse.code === 200, json: () => Promise.resolve(undoResponse) });
        }
        let data = [];
        if (url.includes('/packing-list/pl-1') && !options.method) data = activeDetail;
        else if (url.includes('/users/list')) data = [{ id: 7, name: '操作员甲' }];
        else if (url.includes('/box/box-1/workers')) data = [{ worker_id: 7 }];
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ code: 200, data }) });
    });
});
afterEach(() => {
    window.localStorage.clear();
    jest.restoreAllMocks();
});

test('outbound boxes allow content and waybill edits while identity and weight remain read only', async () => {
    renderDetail();
    const dialog = await openBoxEditor();
    expect(within(dialog).getByPlaceholderText('箱子已出库，重量不可修改')).toBeDisabled();
    expect(within(dialog).getByDisplayValue('1')).toBeDisabled();
    expect(within(dialog).getByDisplayValue('OLD-1')).toBeDisabled();
    expect(within(dialog).getByDisplayValue('WB-1')).not.toBeDisabled();
    expect(within(dialog).getByRole('button', { name: /添加品名明细/ })).not.toBeDisabled();
    fireEvent.change(within(dialog).getByDisplayValue('WB-1'), { target: { value: 'WB-NEW' } });
    fireEvent.click(within(dialog).getByRole('button', { name: /保\s*存/ }));
    await waitFor(() => {
        const call = global.fetch.mock.calls.find(([url, options]) => String(url).endsWith('/box/box-1') && options?.method === 'PUT');
        expect(call).toBeDefined();
        const body = JSON.parse(call[1].body);
        expect(body).toMatchObject({ waybill_id: 'WB-NEW' });
        expect(body).toHaveProperty('item_details');
        expect(body).not.toHaveProperty('weight');
        expect(body).not.toHaveProperty('box_number');
        expect(body).not.toHaveProperty('transfer_id');
    });
});

test.each(['admin', 'store_manager'])('%s can return an outbound box to stock directly from the packing list', async role => {
    setJwt([role]);
    activeDetail = { ...detail, boxes: detail.boxes.map(box => ({
        ...box, edit_policy: { ...editablePolicy, archive_or_delete: false },
    })) };
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: '撤销出库' }));
    fireEvent.click(await screen.findByRole('button', { name: /^重\s*新\s*入\s*库$/ }));
    await screen.findAllByText('待出库');
    expect(screen.queryByRole('button', { name: '撤销出库' })).not.toBeInTheDocument();
    expect(screen.getByText('OLD-1')).toBeInTheDocument();
    const call = global.fetch.mock.calls.find(([url]) => String(url).endsWith('/box/box-1/undo-ship'));
    expect(call[1]).toMatchObject({ method: 'POST' });
    const dialog = await openBoxEditor();
    expect(within(dialog).getByDisplayValue('1')).toBeDisabled();
    expect(within(dialog).getByDisplayValue('OLD-1')).toBeDisabled();
    expect(within(dialog).getByRole('textbox', { name: '转单号（运单号）' })).not.toBeDisabled();
    expect(within(dialog).getByDisplayValue('3.2')).not.toBeDisabled();
    fireEvent.change(within(dialog).getByDisplayValue('3.2'), { target: { value: '4.2' } });
    fireEvent.change(within(dialog).getByRole('textbox', { name: '转单号（运单号）' }), { target: { value: 'WB-NEW' } });
    fireEvent.click(within(dialog).getByRole('button', { name: /保\s*存/ }));
    await waitFor(() => {
        const updateCall = global.fetch.mock.calls.find(([url, options]) => String(url).endsWith('/box/box-1') && options?.method === 'PUT');
        expect(updateCall).toBeDefined();
        const body = JSON.parse(updateCall[1].body);
        expect(body).toMatchObject({ weight: 4.2, waybill_id: 'WB-NEW' });
        expect(body).not.toHaveProperty('box_number');
        expect(body).not.toHaveProperty('transfer_id');
    });
});

test('a rejected undo keeps the outbound box visible and does not refresh successful data', async () => {
    undoResponse = { code: 409, msg: '箱子状态已改变，请刷新后重试' };
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: '撤销出库' }));
    fireEvent.click(await screen.findByRole('button', { name: /^重\s*新\s*入\s*库$/ }));
    expect(await screen.findByText('箱子状态已改变，请刷新后重试')).toBeInTheDocument();
    expect(screen.getAllByText('已出库')).toHaveLength(2);
    expect(global.fetch.mock.calls.filter(([url]) => String(url).endsWith('/packing-list/pl-1'))).toHaveLength(1);
});

test.each(['salesperson', 'clerk', 'worker'])('%s has no undo shipment action', async role => {
    setJwt([role]);
    renderDetail();
    await screen.findByText('MARK-1');
    expect(screen.queryByRole('button', { name: '撤销出库' })).not.toBeInTheDocument();
});

test.each([
    ['admin', true],
    ['store_manager', true],
    ['clerk', false],
])('%s keeps edit and shipment actions separate from archive and delete actions', async (role, canUndo) => {
    setJwt([role]);
    renderDetail();
    await screen.findByText('MARK-1');
    const editingActions = screen.getByRole('group', { name: '编辑与出库操作' });
    const archiveActions = screen.getByRole('group', { name: '归档与删除操作' });
    expect(within(editingActions).getByRole('button', { name: /编\s*辑/ })).toBeInTheDocument();
    expect(within(editingActions).queryByRole('button', { name: '撤销出库' }) !== null).toBe(canUndo);
    expect(within(editingActions).queryByRole('button', { name: /归\s*档|删\s*除/ })).not.toBeInTheDocument();
    const archiveButton = within(archiveActions).getByRole('button', { name: /归\s*档/ });
    const deleteButton = within(archiveActions).getByRole('button', { name: /删\s*除/ });
    expect(within(archiveActions).queryByRole('button', { name: /编\s*辑|撤销出库/ })).not.toBeInTheDocument();
    expect(within(archiveButton).getByRole('img', { name: 'delete' })).toBeInTheDocument();
    expect(within(deleteButton).queryByRole('img')).not.toBeInTheDocument();
    expect(within(editingActions).getAllByRole('button')).toHaveLength(canUndo ? 2 : 1);
    expect(within(archiveActions).getAllByRole('button')).toHaveLength(2);
});

test('pending boxes have no undo shipment action and remain weighable', async () => {
    activeDetail = { ...detail, boxes: detail.boxes.map(box => ({ ...box, status: 'pending_outbound', identity_editable: true })) };
    renderDetail();
    const dialog = await openBoxEditor();
    expect(screen.queryByRole('button', { name: '撤销出库' })).not.toBeInTheDocument();
    expect(within(dialog).getByDisplayValue('1')).not.toBeDisabled();
    expect(within(dialog).getByDisplayValue('OLD-1')).not.toBeDisabled();
    expect(within(dialog).getByDisplayValue('3.2')).not.toBeDisabled();
});


test.each([
    ['numeric logistics status', { status: 2 }],
    ['string logistics status', { status: '3' }],
    ['outbound box with no waybill', { status: 1, waybill_id: '' }],
    ['later tracking status', { status: 'InTransit_Other' }],
])('%s is still outbound and exposes return-to-stock while keeping weight read only', async (_, overrides) => {
    activeDetail = { ...detail, boxes: detail.boxes.map(box => ({ ...box, identity_editable: true, ...overrides })) };
    renderDetail();
    expect(await screen.findByRole('button', { name: '撤销出库' })).toBeInTheDocument();
    const dialog = await openBoxEditor();
    expect(within(dialog).getByPlaceholderText('箱子已出库，重量不可修改')).toBeDisabled();
    expect(within(dialog).getByDisplayValue('1')).toBeDisabled();
    expect(within(dialog).getByDisplayValue('OLD-1')).toBeDisabled();
});
