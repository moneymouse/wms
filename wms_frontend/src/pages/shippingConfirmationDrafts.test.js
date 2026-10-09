import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import ShippingConfirmationDrafts from './shippingConfirmationDrafts';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { fetchShippingConfirmationPdf, shippingConfirmationRequest } from '../common/shippingConfirmationApi';

jest.mock('../common/shippingConfirmationApi', () => ({ shippingConfirmationRequest: jest.fn(), fetchShippingConfirmationPdf: jest.fn() }));
jest.setTimeout(15000);

const firstBox = { uid: 'box-1', box_number: 1, tag: 'MARK-1', transfer_id: '', weight: 12, target_order_uid: null };
const secondBox = { uid: 'box-2', box_number: 2, tag: 'MARK-2', transfer_id: 'XD123L', weight: 8, target_order_uid: 'order-2' };
const lists = [
    { uid: 'list-1', list_number: 'PL-1001', customer_name: '客户甲', boxes: [firstBox] },
    { uid: 'list-2', list_number: 'PL-1002', customer_name: '客户乙', boxes: [secondBox] },
];
const entries = lists.map(list => ({ ...list.boxes[0], cargo_uid: list.boxes[0].uid, packing_list_uid: list.uid,
    list_number: list.list_number, customer_name: list.customer_name, agent_name: list.uid === 'list-2' ? 'TC' : '', remarks: '', available: true }));
let catalogLists;
let hydratedEntries;
let saved;
let preview;
let originalOpen;
let originalCreateObjectURL;
let originalRevokeObjectURL;

function defaultRequest(path, options = {}) {
    if (path === '/shipping-confirmation-drafts' && !options.method) return Promise.resolve({ items: saved ? [{ ...saved, box_count: saved.entries.length }] : [] });
    if (path.startsWith('/packing-lists?')) {
        const params = new URLSearchParams(path.split('?')[1]);
        return Promise.resolve({ items: [Number(params.get('p')) === 2 || params.get('q') === '客户乙' ? catalogLists[1] : catalogLists[0]], total: 12 });
    }
    if (path === '/packing-lists/shipping-confirmation/boxes') return Promise.resolve({ items: hydratedEntries.filter(entry => options.body.cargo_uids.includes(entry.cargo_uid)) });
    if (path === '/shipping-confirmation-drafts' && options.method === 'POST') {
        saved = { uid: 'draft-1', version: 1, ...options.body,
            entries: options.body.entries.map(entry => ({ ...hydratedEntries.find(item => item.cargo_uid === entry.cargo_uid), ...entry })) };
        return Promise.resolve(saved);
    }
    if (path === '/shipping-confirmation-drafts/draft-1' && options.method === 'PUT') {
        saved = { ...saved, ...options.body, version: saved.version + 1,
            entries: options.body.entries.map(entry => ({ ...hydratedEntries.find(item => item.cargo_uid === entry.cargo_uid), ...entry })) };
        return Promise.resolve(saved);
    }
    if (path === '/shipping-confirmation-drafts/draft-1' && options.method === 'DELETE') {
        saved = null;
        return Promise.resolve(null);
    }
    if (path === '/shipping-confirmation-drafts/draft-1') return Promise.resolve(saved);
    return Promise.reject(new Error(`Unexpected request: ${path}`));
}

function renderPage(initialPath = '/shipping-confirmation-drafts') {
    const router = createMemoryRouter([
        { path: '/shipping-confirmation-drafts', element: <ShippingConfirmationDrafts /> },
        { path: '/shipping-confirmation-drafts/:uid', element: <ShippingConfirmationDrafts /> },
        { path: '/packing-lists', element: <div>装箱单列表页面</div> },
    ], { initialEntries: [initialPath] });
    render(<RouterProvider router={router} />);
    return router;
}

async function ready() {
    await waitUntilIdle();
    await within(screen.getByLabelText('可添加的装箱单箱子')).findByText('PL-1001');
}
async function waitUntilIdle() {
    await waitFor(() => expect(screen.getByLabelText('出货单草稿名称')).toBeEnabled());
    await waitFor(() => expect(screen.getByRole('button', { name: /保存草稿/ })).not.toHaveClass('ant-btn-loading'));
}
function selectCatalogBox(number) {
    const catalog = screen.getByLabelText('可添加的装箱单箱子');
    fireEvent.click(packingListCheckbox(catalog, number));
}
function packingListCheckbox(table, number) {
    return within(within(table).getByText(number).closest('tr')).getByRole('checkbox');
}
async function expandDraftList(number) {
    await waitUntilIdle();
    const table = screen.getByLabelText('出货单草稿箱子');
    await within(table).findByRole('button', { name: new RegExp(`^(展开|收起)装箱单 ${number}$`) });
    const expand = within(table).queryByRole('button', { name: `展开装箱单 ${number}` });
    if (expand) fireEvent.click(expand);
}
async function confirmAddBoxes() {
    const dialog = await screen.findByRole('dialog', { name: '添加所选箱子' });
    fireEvent.click(within(dialog).getByRole('button', { name: '确认添加' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '添加所选箱子' })).not.toBeInTheDocument());
    await waitUntilIdle();
}
async function addFirstBox() {
    await ready();
    selectCatalogBox('PL-1001');
    fireEvent.click(screen.getByRole('button', { name: /添加所选箱子（1）/ }));
    await confirmAddBoxes();
    await expandDraftList('PL-1001');
    await waitFor(() => expect(screen.getByLabelText('箱子 box-1 渠道代理')).toBeEnabled());
    await waitUntilIdle();
}
function useGroupedBoxes() {
    const thirdBox = { ...firstBox, uid: 'box-3', box_number: 3, tag: 'MARK-3', weight: 5 };
    catalogLists = [{ ...lists[0], boxes: [firstBox, thirdBox] }, lists[1]];
    hydratedEntries = [entries[0], { ...entries[0], ...thirdBox, cargo_uid: thirdBox.uid }, entries[1]];
}

beforeEach(() => {
    jest.clearAllMocks();
    saved = null;
    catalogLists = lists;
    hydratedEntries = entries;
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({ matches: false, media: query, onchange: null,
        addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }) });
    shippingConfirmationRequest.mockImplementation(defaultRequest);
    fetchShippingConfirmationPdf.mockResolvedValue(new Blob(['%PDF-1.4'], { type: 'application/pdf' }));
    preview = { document: { write: jest.fn() }, location: { href: '' }, close: jest.fn() };
    originalOpen = window.open;
    originalCreateObjectURL = URL.createObjectURL;
    originalRevokeObjectURL = URL.revokeObjectURL;
    window.open = jest.fn().mockReturnValue(preview);
    URL.createObjectURL = jest.fn().mockReturnValue('blob:shipping-pdf');
    URL.revokeObjectURL = jest.fn();
});

afterEach(() => {
    window.open = originalOpen;
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
});

test('collects boxes across packing list pages and saves independent agents and address remarks', async () => {
    const view = renderPage();
    await ready();
    selectCatalogBox('PL-1001');
    fireEvent.click(screen.getByRole('button', { name: '下一页装箱单' }));
    await screen.findByText('PL-1002');
    selectCatalogBox('PL-1002');
    fireEvent.click(screen.getByRole('button', { name: /添加所选箱子（2）/ }));
    await confirmAddBoxes();
    await expandDraftList('PL-1001');
    await expandDraftList('PL-1002');
    await waitFor(() => expect(screen.getByLabelText('箱子 box-1 渠道代理')).toBeEnabled());
    await waitUntilIdle();
    expect(screen.getByLabelText('箱子 box-2 渠道代理')).toHaveValue('TC');
    fireEvent.change(screen.getByLabelText('出货单草稿名称'), { target: { value: '下午出货' } });
    fireEvent.change(screen.getByLabelText('箱子 box-1 渠道代理'), { target: { value: 'JF' } });
    fireEvent.change(screen.getByLabelText('箱子 box-1 出货备注'), { target: { value: '地址 A，邮编 10000' } });
    fireEvent.change(screen.getByLabelText('箱子 box-2 出货备注'), { target: { value: '地址 B，邮编 20000' } });
    fireEvent.click(screen.getByRole('button', { name: /保存草稿/ }));
    await waitUntilIdle();
    expect(saved).toMatchObject({ title: '下午出货', version: 1 });
    expect(view.state.location.pathname).toBe('/shipping-confirmation-drafts/draft-1');
    expect(shippingConfirmationRequest).toHaveBeenCalledWith('/packing-lists/shipping-confirmation/boxes', {
        method: 'POST', body: { cargo_uids: ['box-1', 'box-2'] },
    });
    expect(shippingConfirmationRequest).toHaveBeenCalledWith('/shipping-confirmation-drafts', { method: 'POST', body: { title: '下午出货', entries: [
        { cargo_uid: 'box-1', agent_name: 'JF', remarks: '地址 A，邮编 10000' },
        { cargo_uid: 'box-2', agent_name: 'TC', remarks: '地址 B，邮编 20000' },
    ] } });
    expect(screen.getByText(/出货单草稿：2 箱，共 20.00 kg/)).toBeInTheDocument();
    expect(packingListCheckbox(screen.getByLabelText('可添加的装箱单箱子'), 'PL-1002')).toBeDisabled();
});

test('groups boxes by packing list and applies add metadata and draft bulk edits to selected children', async () => {
    useGroupedBoxes();
    renderPage();
    await ready();
    const catalog = screen.getByLabelText('可添加的装箱单箱子');
    expect(within(catalog).getAllByText('PL-1001')).toHaveLength(1);
    expect(within(catalog).queryByText('MARK-1')).not.toBeInTheDocument();
    expect(within(catalog).queryByText('MARK-3')).not.toBeInTheDocument();
    selectCatalogBox('PL-1001');
    expect(screen.getByRole('button', { name: /添加所选箱子（2）/ })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: '下一页装箱单' }));
    await within(catalog).findByText('PL-1002');
    selectCatalogBox('PL-1002');
    fireEvent.click(screen.getByRole('button', { name: '上一页装箱单' }));
    await within(catalog).findByText('PL-1001');
    expect(packingListCheckbox(catalog, 'PL-1001')).toBeChecked();
    fireEvent.click(within(catalog).getByRole('button', { name: '展开装箱单 PL-1001' }));
    expect(within(within(catalog).getByRole('row', { name: /MARK-1/ })).getByRole('checkbox')).toBeChecked();
    const thirdCheckbox = within(within(catalog).getByRole('row', { name: /MARK-3/ })).getByRole('checkbox');
    expect(thirdCheckbox).toBeChecked();
    fireEvent.click(thirdCheckbox);
    expect(screen.getByRole('button', { name: /添加所选箱子（2）/ })).toBeEnabled();
    fireEvent.click(thirdCheckbox);
    fireEvent.click(screen.getByRole('button', { name: /添加所选箱子（3）/ }));
    const dialog = await screen.findByRole('dialog', { name: '添加所选箱子' });
    fireEvent.change(within(dialog).getByLabelText('添加箱子渠道代理'), { target: { value: 'JF' } });
    fireEvent.change(within(dialog).getByLabelText('添加箱子出货备注'), { target: { value: '统一地址，邮编 10000' } });
    await confirmAddBoxes();
    expect(shippingConfirmationRequest).toHaveBeenCalledWith('/packing-lists/shipping-confirmation/boxes', {
        method: 'POST', body: { cargo_uids: ['box-1', 'box-2', 'box-3'] },
    });
    const draftTable = screen.getByLabelText('出货单草稿箱子');
    expect(within(draftTable).getAllByText('PL-1001')).toHaveLength(1);
    expect(within(draftTable).getAllByText('PL-1002')).toHaveLength(1);
    expect(screen.queryByLabelText('箱子 box-1 渠道代理')).not.toBeInTheDocument();
    fireEvent.click(packingListCheckbox(draftTable, 'PL-1001'));
    expect(screen.getByText('应用至所选 2 箱')).toBeInTheDocument();
    await expandDraftList('PL-1001');
    await expandDraftList('PL-1002');
    for (const cargoUid of ['box-1', 'box-2', 'box-3']) {
        expect(screen.getByLabelText(`箱子 ${cargoUid} 渠道代理`)).toHaveValue('JF');
        expect(screen.getByLabelText(`箱子 ${cargoUid} 出货备注`)).toHaveValue('统一地址，邮编 10000');
    }
    fireEvent.change(screen.getByLabelText('批量出货备注'), { target: { value: '客户甲的新地址' } });
    fireEvent.click(screen.getByRole('button', { name: '批量填写备注' }));
    expect(screen.getByLabelText('箱子 box-1 出货备注')).toHaveValue('客户甲的新地址');
    expect(screen.getByLabelText('箱子 box-3 出货备注')).toHaveValue('客户甲的新地址');
    expect(screen.getByLabelText('箱子 box-2 出货备注')).toHaveValue('统一地址，邮编 10000');
    fireEvent.click(screen.getByRole('button', { name: /保存草稿/ }));
    await waitUntilIdle();
    expect(saved.entries.map(entry => entry.cargo_uid)).toEqual(['box-1', 'box-3', 'box-2']);
    const saveBody = shippingConfirmationRequest.mock.calls.find(([path, options]) => path === '/shipping-confirmation-drafts' && options?.method === 'POST')[1].body;
    expect(saveBody.entries).toEqual([
        { cargo_uid: 'box-1', agent_name: 'JF', remarks: '客户甲的新地址' },
        { cargo_uid: 'box-3', agent_name: 'JF', remarks: '客户甲的新地址' },
        { cargo_uid: 'box-2', agent_name: 'JF', remarks: '统一地址，邮编 10000' },
    ]);
});

test('selects only eligible boxes from a packing list with boxes already in the draft', async () => {
    useGroupedBoxes();
    saved = { uid: 'draft-1', title: '部分已添加', version: 2, entries: [{ ...entries[0], remarks: '原有备注' }] };
    renderPage('/shipping-confirmation-drafts/draft-1');
    await ready();
    const catalog = screen.getByLabelText('可添加的装箱单箱子');
    const parentCheckbox = packingListCheckbox(catalog, 'PL-1001');
    expect(parentCheckbox).toBeEnabled();
    fireEvent.click(parentCheckbox);
    expect(screen.getByRole('button', { name: /添加所选箱子（1）/ })).toBeEnabled();
    fireEvent.click(within(catalog).getByRole('button', { name: '展开装箱单 PL-1001' }));
    expect(within(within(catalog).getByRole('row', { name: /MARK-1/ })).getByRole('checkbox')).toBeDisabled();
    expect(within(within(catalog).getByRole('row', { name: /MARK-3/ })).getByRole('checkbox')).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: /添加所选箱子（1）/ }));
    const dialog = await screen.findByRole('dialog', { name: '添加所选箱子' });
    fireEvent.change(within(dialog).getByLabelText('添加箱子出货备注'), { target: { value: '新箱备注' } });
    await confirmAddBoxes();
    expect(shippingConfirmationRequest).toHaveBeenCalledWith('/packing-lists/shipping-confirmation/boxes', {
        method: 'POST', body: { cargo_uids: ['box-3'] },
    });
    await expandDraftList('PL-1001');
    expect(screen.getByLabelText('箱子 box-1 出货备注')).toHaveValue('原有备注');
    expect(screen.getByLabelText('箱子 box-3 出货备注')).toHaveValue('新箱备注');
    expect(parentCheckbox).toBeDisabled();
});

test('allows empty add metadata and keeps each box agent and remarks returned by the server', async () => {
    useGroupedBoxes();
    hydratedEntries = hydratedEntries.map(entry => ({ ...entry,
        agent_name: entry.cargo_uid === 'box-1' ? 'JF' : 'TC', remarks: `默认备注 ${entry.cargo_uid}` }));
    renderPage();
    await ready();
    selectCatalogBox('PL-1001');
    fireEvent.click(screen.getByRole('button', { name: /添加所选箱子（2）/ }));
    const dialog = await screen.findByRole('dialog', { name: '添加所选箱子' });
    expect(within(dialog).getByLabelText('添加箱子渠道代理')).not.toBeRequired();
    expect(within(dialog).getByLabelText('添加箱子出货备注')).not.toBeRequired();
    expect(within(dialog).getByRole('button', { name: '确认添加' })).toBeEnabled();
    await confirmAddBoxes();
    await expandDraftList('PL-1001');
    expect(screen.getByLabelText('箱子 box-1 渠道代理')).toHaveValue('JF');
    expect(screen.getByLabelText('箱子 box-3 渠道代理')).toHaveValue('TC');
    expect(screen.getByLabelText('箱子 box-1 出货备注')).toHaveValue('默认备注 box-1');
    expect(screen.getByLabelText('箱子 box-3 出货备注')).toHaveValue('默认备注 box-3');
});

test('retains a selected packing list when another draft table page is selected and deselected', async () => {
    hydratedEntries = Array.from({ length: 21 }, (_, index) => ({ ...entries[0],
        cargo_uid: `paged-box-${index + 1}`, packing_list_uid: `paged-list-${index + 1}`,
        list_number: `PL-PAGE-${index + 1}`, remarks: '原地址' }));
    saved = { uid: 'draft-1', title: '多装箱单草稿', version: 2, entries: hydratedEntries };
    renderPage('/shipping-confirmation-drafts/draft-1');
    await waitUntilIdle();
    const table = screen.getByLabelText('出货单草稿箱子');
    await within(table).findByText('PL-PAGE-1');
    fireEvent.click(packingListCheckbox(table, 'PL-PAGE-1'));
    fireEvent.click(screen.getByTitle('Next Page'));
    await within(table).findByText('PL-PAGE-21');
    const lastGroupCheckbox = packingListCheckbox(table, 'PL-PAGE-21');
    fireEvent.click(lastGroupCheckbox);
    expect(screen.getByText('应用至所选 2 箱')).toBeInTheDocument();
    fireEvent.click(lastGroupCheckbox);
    expect(screen.getByText('应用至所选 1 箱')).toBeInTheDocument();
    fireEvent.click(screen.getByTitle('Previous Page'));
    await within(table).findByText('PL-PAGE-1');
    expect(packingListCheckbox(table, 'PL-PAGE-1')).toBeChecked();
    fireEvent.change(screen.getByLabelText('批量出货备注'), { target: { value: '仅第一箱地址' } });
    fireEvent.click(screen.getByRole('button', { name: '批量填写备注' }));
    fireEvent.click(screen.getByRole('button', { name: /保存草稿/ }));
    await waitUntilIdle();
    expect(saved.entries[0].remarks).toBe('仅第一箱地址');
    expect(saved.entries.slice(1).every(entry => entry.remarks === '原地址')).toBe(true);
}, 30000);

test('keeps pending boxes after cancellation and preserves add metadata when hydration fails', async () => {
    useGroupedBoxes();
    renderPage();
    await ready();
    selectCatalogBox('PL-1001');
    fireEvent.click(screen.getByRole('button', { name: /添加所选箱子（2）/ }));
    let dialog = await screen.findByRole('dialog', { name: '添加所选箱子' });
    fireEvent.click(within(dialog).getByRole('button', { name: /取\s*消/ }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '添加所选箱子' })).not.toBeInTheDocument());
    expect(shippingConfirmationRequest.mock.calls.some(([path]) => path === '/packing-lists/shipping-confirmation/boxes')).toBe(false);
    expect(screen.getByRole('button', { name: /添加所选箱子（2）/ })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: /添加所选箱子（2）/ }));
    dialog = await screen.findByRole('dialog', { name: '添加所选箱子' });
    fireEvent.change(within(dialog).getByLabelText('添加箱子渠道代理'), { target: { value: 'YX' } });
    fireEvent.change(within(dialog).getByLabelText('添加箱子出货备注'), { target: { value: '重试时保留的地址' } });
    shippingConfirmationRequest.mockImplementation((path, options) => path === '/packing-lists/shipping-confirmation/boxes'
        ? Promise.reject(new Error('箱子详情暂时无法加载')) : defaultRequest(path, options));
    fireEvent.click(within(dialog).getByRole('button', { name: '确认添加' }));
    await within(dialog).findByText('箱子详情暂时无法加载');
    await waitUntilIdle();
    expect(within(dialog).getByLabelText('添加箱子渠道代理')).toHaveValue('YX');
    expect(within(dialog).getByLabelText('添加箱子出货备注')).toHaveValue('重试时保留的地址');
    expect(screen.getByRole('button', { name: /添加所选箱子（2）/ })).toBeEnabled();
    expect(screen.getByText(/出货单草稿：0 箱/)).toBeInTheDocument();
    shippingConfirmationRequest.mockImplementation(defaultRequest);
    await confirmAddBoxes();
    await expandDraftList('PL-1001');
    expect(screen.getByLabelText('箱子 box-1 渠道代理')).toHaveValue('YX');
    expect(screen.getByLabelText('箱子 box-3 出货备注')).toHaveValue('重试时保留的地址');
    expect(screen.getByRole('button', { name: /添加所选箱子（0）/ })).toBeDisabled();
});

test('reopens a saved draft and adds boxes from a different packing list without overwriting its remarks', async () => {
    saved = { uid: 'draft-1', title: '已保存单', version: 4, entries: [{ ...entries[0], agent_name: 'JF', remarks: '先寄地址' }] };
    renderPage();
    await ready();
    fireEvent.click(await screen.findByRole('button', { name: '已保存单 1 箱' }));
    await expandDraftList('PL-1001');
    await waitFor(() => expect(screen.getByLabelText('箱子 box-1 渠道代理')).toBeEnabled());
    await waitUntilIdle();
    expect(screen.getByLabelText('箱子 box-1 出货备注')).toHaveValue('先寄地址');
    const search = screen.getByRole('searchbox', { name: '搜索出货装箱单' });
    fireEvent.change(search, { target: { value: '客户乙' } });
    fireEvent.keyDown(search, { key: 'Enter', code: 'Enter', keyCode: 13 });
    await waitFor(() => expect(within(screen.getByLabelText('可添加的装箱单箱子')).getByText('PL-1002')).toBeInTheDocument());
    selectCatalogBox('PL-1002');
    fireEvent.click(screen.getByRole('button', { name: /添加所选箱子（1）/ }));
    await confirmAddBoxes();
    await expandDraftList('PL-1002');
    await waitFor(() => expect(screen.getByLabelText('箱子 box-2 渠道代理')).toBeEnabled());
    await waitUntilIdle();
    fireEvent.click(screen.getByRole('button', { name: /保存草稿/ }));
    await waitUntilIdle();
    expect(saved.version).toBe(5);
    expect(saved.entries.map(entry => entry.cargo_uid)).toEqual(['box-1', 'box-2']);
    expect(saved.entries[0].remarks).toBe('先寄地址');
    expect(shippingConfirmationRequest).toHaveBeenCalledWith('/shipping-confirmation-drafts/draft-1', expect.objectContaining({
        method: 'PUT', body: expect.objectContaining({ expected_version: 4 }),
    }));
});

test('applies bulk remarks only to selected draft boxes, then saves before opening the PDF', async () => {
    renderPage();
    await addFirstBox();
    fireEvent.click(screen.getByRole('button', { name: '下一页装箱单' }));
    await waitFor(() => expect(within(screen.getByLabelText('可添加的装箱单箱子')).getByText('PL-1002')).toBeInTheDocument());
    selectCatalogBox('PL-1002');
    fireEvent.click(screen.getByRole('button', { name: /添加所选箱子（1）/ }));
    await confirmAddBoxes();
    await expandDraftList('PL-1002');
    await waitFor(() => expect(screen.getByLabelText('箱子 box-2 渠道代理')).toBeEnabled());
    await waitUntilIdle();
    const draftTable = screen.getByLabelText('出货单草稿箱子');
    fireEvent.click(packingListCheckbox(draftTable, 'PL-1001'));
    fireEvent.change(screen.getByLabelText('批量出货备注'), { target: { value: '批量地址 10000' } });
    fireEvent.click(screen.getByRole('button', { name: '批量填写备注' }));
    expect(screen.getByLabelText('箱子 box-1 出货备注')).toHaveValue('批量地址 10000');
    expect(screen.getByLabelText('箱子 box-2 出货备注')).toHaveValue('');
    fireEvent.click(screen.getByRole('button', { name: /保存并打印 PDF/ }));
    await waitFor(() => expect(preview.location.href).toBe('blob:shipping-pdf'));
    await waitUntilIdle();
    expect(saved).toBeTruthy();
    expect(fetchShippingConfirmationPdf).toHaveBeenCalledWith('draft-1', 1, ['box-1']);
    expect(saved.entries.map(entry => entry.cargo_uid)).toEqual(['box-1', 'box-2']);
    expect(window.open).toHaveBeenCalledWith('', '_blank');
    expect(preview.close).not.toHaveBeenCalled();
});

test('blocks leaving the page and preserves an unsaved draft when saving fails', async () => {
    const view = renderPage();
    await addFirstBox();
    fireEvent.change(screen.getByLabelText('箱子 box-1 出货备注'), { target: { value: '保留这条地址' } });
    shippingConfirmationRequest.mockImplementation((path, options) => path === '/shipping-confirmation-drafts' && options?.method === 'POST'
        ? Promise.reject(new Error('暂时无法保存')) : defaultRequest(path, options));
    fireEvent.click(screen.getByRole('button', { name: '返回装箱单列表' }));
    // rc-util uses the same title ID for both modals under NODE_ENV=test.
    const leaveDialog = await screen.findByRole('dialog');
    expect(within(leaveDialog).getByText('有未保存的出货单内容')).toBeInTheDocument();
    fireEvent.click(within(leaveDialog).getByRole('button', { name: '保存并离开' }));
    await within(leaveDialog).findByText('暂时无法保存');
    expect(view.state.location.pathname).toBe('/shipping-confirmation-drafts');
    expect(screen.getByLabelText('箱子 box-1 出货备注')).toHaveValue('保留这条地址');
    fireEvent.click(within(leaveDialog).getByRole('button', { name: '继续编辑' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByLabelText('箱子 box-1 出货备注')).toHaveValue('保留这条地址');
    await act(async () => { await view.navigate('/packing-lists'); });
    const retryDialog = await screen.findByRole('dialog');
    expect(within(retryDialog).getByText('有未保存的出货单内容')).toBeInTheDocument();
    fireEvent.click(within(retryDialog).getByRole('button', { name: '放弃修改并离开' }));
    await screen.findByText('装箱单列表页面');
    expect(saved).toBeNull();
});

test('loads a draft directly by URL and saves edits before starting a new draft, then deletes it', async () => {
    saved = { uid: 'draft-1', title: '已保存单', version: 4, entries: [{ ...entries[0], agent_name: 'JF', remarks: '原地址' }] };
    const view = renderPage('/shipping-confirmation-drafts/draft-1');
    await expandDraftList('PL-1001');
    await screen.findByLabelText('箱子 box-1 出货备注');
    await waitUntilIdle();
    expect(screen.getByRole('heading', { name: '出货确认单草稿' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByLabelText('箱子 box-1 出货备注')).toHaveValue('原地址');
    fireEvent.change(screen.getByLabelText('箱子 box-1 出货备注'), { target: { value: '新地址' } });
    const beforeUnload = new Event('beforeunload', { cancelable: true });
    fireEvent(window, beforeUnload);
    expect(beforeUnload.defaultPrevented).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: /新建出货单/ }));
    await waitUntilIdle();
    expect(view.state.location.pathname).toBe('/shipping-confirmation-drafts');
    expect(saved.entries[0].remarks).toBe('新地址');
    expect(saved.version).toBe(5);
    expect(screen.getByLabelText('出货单草稿名称')).toHaveValue('');
    fireEvent.click(screen.getByRole('button', { name: '已保存单 1 箱' }));
    await expandDraftList('PL-1001');
    await screen.findByLabelText('箱子 box-1 出货备注');
    await waitUntilIdle();
    expect(view.state.location.pathname).toBe('/shipping-confirmation-drafts/draft-1');
    expect(screen.getByLabelText('箱子 box-1 出货备注')).toHaveValue('新地址');
    fireEvent.click(screen.getByRole('button', { name: /删除草稿/ }));
    fireEvent.click(await screen.findByRole('button', { name: '删 除' }));
    await waitUntilIdle();
    expect(saved).toBeNull();
    expect(view.state.location.pathname).toBe('/shipping-confirmation-drafts');
    expect(shippingConfirmationRequest).toHaveBeenCalledWith('/shipping-confirmation-drafts/draft-1', {
        method: 'DELETE', body: { expected_version: 5 },
    });
});

test('saves dirty edits before leaving through other page navigation', async () => {
    saved = { uid: 'draft-1', title: '今日出货', version: 3, entries: [{ ...entries[0], remarks: '旧地址' }] };
    const view = renderPage('/shipping-confirmation-drafts/draft-1');
    await expandDraftList('PL-1001');
    await screen.findByLabelText('箱子 box-1 出货备注');
    await waitUntilIdle();
    fireEvent.change(screen.getByLabelText('箱子 box-1 出货备注'), { target: { value: '准备出货的新地址' } });
    await act(async () => { await view.navigate('/packing-lists'); });
    const leaveDialog = await screen.findByRole('dialog', { name: '有未保存的出货单内容' });
    fireEvent.click(within(leaveDialog).getByRole('button', { name: '保存并离开' }));
    await screen.findByText('装箱单列表页面');
    expect(saved.version).toBe(4);
    expect(saved.entries[0].remarks).toBe('准备出货的新地址');
    expect(view.state.location.pathname).toBe('/packing-lists');
});

test.each(['browser back', 'draft sidebar'])('recovers the previous draft after another draft fails to load using %s', async recovery => {
    saved = { uid: 'draft-1', title: '已保存单', version: 4, entries: [{ ...entries[0], remarks: '之前保存的地址' }] };
    const failingDraft = { uid: 'draft-2', title: '另一份草稿', box_count: 1 };
    shippingConfirmationRequest.mockImplementation((requestPath, options = {}) => {
        if (requestPath === '/shipping-confirmation-drafts' && !options.method) return Promise.resolve({ items: [{ ...saved, box_count: 1 }, failingDraft] });
        if (requestPath === '/shipping-confirmation-drafts/draft-2') return Promise.reject(new Error('另一份草稿暂时无法加载'));
        return defaultRequest(requestPath, options);
    });
    const view = renderPage('/shipping-confirmation-drafts/draft-1');
    await expandDraftList('PL-1001');
    await screen.findByLabelText('箱子 box-1 出货备注');
    await waitUntilIdle();
    fireEvent.click(packingListCheckbox(screen.getByLabelText('出货单草稿箱子'), 'PL-1001'));
    expect(screen.getByLabelText('当前打印范围')).toHaveTextContent('所选 1 箱');
    fireEvent.click(screen.getByRole('button', { name: '另一份草稿 1 箱' }));
    await screen.findByText('另一份草稿暂时无法加载');
    expect(view.state.location.pathname).toBe('/shipping-confirmation-drafts/draft-2');
    expect(screen.queryByLabelText('出货单草稿名称')).not.toBeInTheDocument();
    if (recovery === 'browser back') await act(async () => { await view.navigate(-1); });
    else fireEvent.click(screen.getByRole('button', { name: '已保存单 1 箱' }));
    await expandDraftList('PL-1001');
    await screen.findByLabelText('箱子 box-1 出货备注');
    await waitUntilIdle();
    expect(view.state.location.pathname).toBe('/shipping-confirmation-drafts/draft-1');
    expect(screen.queryByText('另一份草稿暂时无法加载')).not.toBeInTheDocument();
    expect(screen.getByLabelText('箱子 box-1 出货备注')).toHaveValue('之前保存的地址');
    expect(screen.getByRole('button', { name: /保存并打印 PDF/ })).toBeEnabled();
    expect(screen.getByLabelText('当前打印范围')).toHaveTextContent('草稿全部 1 箱（未勾选）');
    expect(shippingConfirmationRequest.mock.calls.filter(([path]) => path === '/shipping-confirmation-drafts/draft-1')).toHaveLength(2);
});

test('preserves conflicting edits and lets them be saved as a new draft', async () => {
    const maxLengthTitle = '出'.repeat(128);
    renderPage();
    await addFirstBox();
    fireEvent.change(screen.getByLabelText('出货单草稿名称'), { target: { value: maxLengthTitle } });
    fireEvent.click(screen.getByRole('button', { name: /保存草稿/ }));
    await waitUntilIdle();
    expect(saved).toBeTruthy();
    fireEvent.change(screen.getByLabelText('箱子 box-1 出货备注'), { target: { value: '本地最新地址' } });
    shippingConfirmationRequest.mockImplementation((path, options) => options?.method === 'PUT'
        ? Promise.reject(Object.assign(new Error('草稿已被他人更新'), { status: 409 })) : defaultRequest(path, options));
    fireEvent.click(screen.getByRole('button', { name: /保存草稿/ }));
    await screen.findByText(/草稿已被他人更新/);
    expect(screen.getByLabelText('箱子 box-1 出货备注')).toHaveValue('本地最新地址');
    fireEvent.click(screen.getByRole('button', { name: '另存为新草稿' }));
    await waitUntilIdle();
    expect(saved.entries[0].remarks).toBe('本地最新地址');
    expect(saved.title).toBe(`${maxLengthTitle.slice(0, 125)} 副本`);
    const cloneBody = shippingConfirmationRequest.mock.calls.filter(([path, options]) => path === '/shipping-confirmation-drafts' && options?.method === 'POST').pop()[1].body;
    expect(cloneBody.title).toHaveLength(128);
    expect(screen.queryByText(/草稿已被他人更新/)).not.toBeInTheDocument();
});

function useSavedPrintDraft() {
    useGroupedBoxes();
    saved = { uid: 'draft-1', title: '打印范围测试', version: 4, entries: hydratedEntries.map(entry => ({ ...entry })) };
}
async function openSavedPrintDraft() {
    const view = renderPage('/shipping-confirmation-drafts/draft-1');
    await expandDraftList('PL-1001');
    await expandDraftList('PL-1002');
    return view;
}
function selectDraftBox(cargoUid) {
    const row = within(screen.getByLabelText('出货单草稿箱子')).getAllByRole('row')
        .find(candidate => within(candidate).queryByLabelText(`箱子 ${cargoUid} 渠道代理`));
    fireEvent.click(within(row).getByRole('checkbox'));
}

test.each(['none', 'group', 'all', 'single'])('prints the %s checkbox range without editing or shipping any boxes', async selection => {
    useSavedPrintDraft();
    await openSavedPrintDraft();
    const table = screen.getByLabelText('出货单草稿箱子');
    if (selection === 'group') fireEvent.click(packingListCheckbox(table, 'PL-1001'));
    if (selection === 'all') fireEvent.click(within(table).getAllByRole('checkbox')[0]);
    if (selection === 'single') selectDraftBox('box-3');
    const selected = selection === 'group' ? ['box-1', 'box-3'] : selection === 'all' ? ['box-1', 'box-3', 'box-2'] : ['box-3'];
    expect(screen.getByLabelText('当前打印范围')).toHaveTextContent(selection === 'none' ? '打印范围：草稿全部 3 箱（未勾选）' : `打印范围：所选 ${selected.length} 箱`);
    fireEvent.click(screen.getByRole('button', { name: /保存并打印 PDF/ }));
    await waitFor(() => expect(preview.location.href).toBe('blob:shipping-pdf'));
    expect(fetchShippingConfirmationPdf.mock.calls).toEqual([selection === 'none' ? ['draft-1', 4] : ['draft-1', 4, selected]]);
    expect(shippingConfirmationRequest.mock.calls.filter(([, options]) => options?.method)).toEqual([]);
    expect(saved.entries.map(entry => entry.cargo_uid)).toEqual(['box-1', 'box-3', 'box-2']);
});

test('captures selected boxes before delayed complete save and prints once using the new version', async () => {
    useSavedPrintDraft();
    await openSavedPrintDraft();
    selectDraftBox('box-3');
    fireEvent.change(screen.getByLabelText('箱子 box-1 出货备注'), { target: { value: '保留未选备注' } });
    let resolveSave;
    shippingConfirmationRequest.mockImplementation((path, options) => options?.method === 'PUT'
        ? new Promise(resolve => { resolveSave = () => resolve(defaultRequest(path, options)); }) : defaultRequest(path, options));
    const button = screen.getByRole('button', { name: /保存并打印 PDF/ });
    fireEvent.click(button); fireEvent.click(button);
    expect(window.open).toHaveBeenCalledTimes(1);
    expect(fetchShippingConfirmationPdf).not.toHaveBeenCalled();
    const updates = shippingConfirmationRequest.mock.calls.filter(([, options]) => options?.method === 'PUT');
    expect(updates).toHaveLength(1);
    expect(updates[0][1].body.entries.map(entry => entry.cargo_uid)).toEqual(['box-1', 'box-3', 'box-2']);
    expect(updates[0][1].body.entries[0].remarks).toBe('保留未选备注');
    await act(async () => { resolveSave(); });
    await waitFor(() => expect(preview.location.href).toBe('blob:shipping-pdf'));
    expect(fetchShippingConfirmationPdf.mock.calls).toEqual([['draft-1', 5, ['box-3']]]);
    expect(saved.entries).toHaveLength(3);
});

test.each(['missing', 'unavailable'])('a selected box becoming %s in the saved response blocks PDF without falling back to all', async invalidation => {
    useSavedPrintDraft();
    await openSavedPrintDraft();
    selectDraftBox('box-3');
    fireEvent.change(screen.getByLabelText('出货单草稿名称'), { target: { value: '保存后的范围' } });
    shippingConfirmationRequest.mockImplementation(async (path, options) => {
        const result = await defaultRequest(path, options);
        if (options?.method === 'PUT') {
            saved = { ...result, entries: invalidation === 'missing' ? result.entries.filter(entry => entry.cargo_uid !== 'box-3')
                : result.entries.map(entry => entry.cargo_uid === 'box-3' ? { ...entry, available: false } : entry) };
            return saved;
        }
        return result;
    });
    fireEvent.click(screen.getByRole('button', { name: /保存并打印 PDF/ }));
    await screen.findByText('打印范围包含已删除、归档或不再可访问的箱子，请核对草稿后重试');
    expect(fetchShippingConfirmationPdf).not.toHaveBeenCalled();
    expect(preview.close).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText('出货单草稿名称')).toHaveValue('保存后的范围');
});

test('a clean saved draft can print valid selected boxes while unselected invalid boxes block printing all', async () => {
    useSavedPrintDraft();
    saved.entries[2].available = false;
    await openSavedPrintDraft();
    const print = screen.getByRole('button', { name: /保存并打印 PDF/ });
    expect(print).toBeDisabled();
    selectDraftBox('box-2');
    expect(print).toBeDisabled();
    selectDraftBox('box-2');
    selectDraftBox('box-1');
    expect(print).toBeEnabled();
    fireEvent.click(print);
    await waitFor(() => expect(preview.location.href).toBe('blob:shipping-pdf'));
    expect(fetchShippingConfirmationPdf).toHaveBeenCalledWith('draft-1', 4, ['box-1']);
    expect(shippingConfirmationRequest.mock.calls.filter(([, options]) => options?.method)).toEqual([]);
    expect(saved.entries).toHaveLength(3);
});

test('a dirty draft still saves all boxes and preserves unsaved content when strict save rejects an unselected invalid box', async () => {
    useSavedPrintDraft();
    saved.entries[2].available = false;
    await openSavedPrintDraft();
    selectDraftBox('box-1');
    fireEvent.change(screen.getByLabelText('箱子 box-1 出货备注'), { target: { value: '需要保留的地址' } });
    shippingConfirmationRequest.mockImplementation((path, options) => options?.method === 'PUT'
        ? Promise.reject(Object.assign(new Error('草稿包含失效箱子'), { status: 404 })) : defaultRequest(path, options));
    fireEvent.click(screen.getByRole('button', { name: /保存并打印 PDF/ }));
    await screen.findByText('草稿包含失效箱子');
    expect(fetchShippingConfirmationPdf).not.toHaveBeenCalled();
    expect(preview.close).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText('箱子 box-1 出货备注')).toHaveValue('需要保留的地址');
    const body = shippingConfirmationRequest.mock.calls.find(([, options]) => options?.method === 'PUT')[1].body;
    expect(body.entries.map(entry => entry.cargo_uid)).toEqual(['box-1', 'box-3', 'box-2']);
    expect(screen.getByLabelText('当前打印范围')).toHaveTextContent('所选 1 箱');
});

test.each([400, 403, 404, 409, 500])('PDF failure %s keeps the selected range and saved draft without retrying the entire draft', async status => {
    useSavedPrintDraft();
    await openSavedPrintDraft();
    selectDraftBox('box-3');
    fetchShippingConfirmationPdf.mockRejectedValue(Object.assign(new Error('所选箱子无法打印'), { status }));
    fireEvent.click(screen.getByRole('button', { name: /保存并打印 PDF/ }));
    await screen.findByText(/所选箱子无法打印/);
    expect(fetchShippingConfirmationPdf.mock.calls).toEqual([['draft-1', 4, ['box-3']]]);
    expect(preview.close).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText('当前打印范围')).toHaveTextContent('所选 1 箱');
    expect(saved.entries).toHaveLength(3);
});

test('a new draft saves every box and keeps its selected subset after PDF failure and explicit retry', async () => {
    const view = renderPage();
    await addFirstBox();
    fireEvent.click(screen.getByRole('button', { name: '下一页装箱单' }));
    await waitFor(() => expect(within(screen.getByLabelText('可添加的装箱单箱子')).getByText('PL-1002')).toBeInTheDocument());
    selectCatalogBox('PL-1002');
    fireEvent.click(screen.getByRole('button', { name: /添加所选箱子（1）/ }));
    await confirmAddBoxes();
    fireEvent.click(packingListCheckbox(screen.getByLabelText('出货单草稿箱子'), 'PL-1001'));
    fetchShippingConfirmationPdf.mockRejectedValueOnce(new Error('本次 PDF 生成失败'));
    fireEvent.click(screen.getByRole('button', { name: /保存并打印 PDF/ }));
    await screen.findByText('本次 PDF 生成失败');
    await waitUntilIdle();
    expect(view.state.location.pathname).toBe('/shipping-confirmation-drafts/draft-1');
    expect(screen.getByLabelText('当前打印范围')).toHaveTextContent('所选 1 箱');
    expect(saved.entries.map(entry => entry.cargo_uid)).toEqual(['box-1', 'box-2']);
    expect(preview.close).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: /保存并打印 PDF/ }));
    await waitFor(() => expect(preview.location.href).toBe('blob:shipping-pdf'));
    expect(fetchShippingConfirmationPdf.mock.calls).toEqual([['draft-1', 1, ['box-1']], ['draft-1', 1, ['box-1']]]);
    expect(shippingConfirmationRequest.mock.calls.filter(([path, options]) => path === '/shipping-confirmation-drafts' && options?.method === 'POST')).toHaveLength(1);
    expect(shippingConfirmationRequest.mock.calls.filter(([, options]) => options?.method === 'PUT')).toHaveLength(0);
});

test('switching to another saved draft resets printing selection and returning does not reuse the old subset', async () => {
    useSavedPrintDraft();
    const other = { uid: 'draft-2', title: '另一份打印草稿', version: 2, entries: [{ ...entries[1] }] };
    shippingConfirmationRequest.mockImplementation((path, options = {}) => {
        if (path === '/shipping-confirmation-drafts' && !options.method) return Promise.resolve({ items: [{ ...saved, box_count: 3 }, { ...other, box_count: 1 }] });
        if (path === '/shipping-confirmation-drafts/draft-2') return Promise.resolve(other);
        return defaultRequest(path, options);
    });
    await openSavedPrintDraft();
    selectDraftBox('box-3');
    expect(screen.getByLabelText('当前打印范围')).toHaveTextContent('所选 1 箱');
    fireEvent.click(screen.getByRole('button', { name: '另一份打印草稿 1 箱' }));
    await waitFor(() => expect(screen.getByLabelText('出货单草稿名称')).toHaveValue('另一份打印草稿'));
    await waitUntilIdle();
    expect(screen.getByLabelText('当前打印范围')).toHaveTextContent('草稿全部 1 箱（未勾选）');
    fireEvent.click(screen.getByRole('button', { name: '打印范围测试 3 箱' }));
    await waitFor(() => expect(screen.getByLabelText('出货单草稿名称')).toHaveValue('打印范围测试'));
    await waitUntilIdle();
    expect(screen.getByLabelText('当前打印范围')).toHaveTextContent('草稿全部 3 箱（未勾选）');
    expect(fetchShippingConfirmationPdf).not.toHaveBeenCalled();
});
