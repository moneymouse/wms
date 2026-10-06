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
let saved;
let preview;
let originalOpen;
let originalCreateObjectURL;
let originalRevokeObjectURL;

function defaultRequest(path, options = {}) {
    if (path === '/shipping-confirmation-drafts' && !options.method) return Promise.resolve({ items: saved ? [{ ...saved, box_count: saved.entries.length }] : [] });
    if (path.startsWith('/packing-lists?')) {
        const params = new URLSearchParams(path.split('?')[1]);
        return Promise.resolve({ items: [Number(params.get('p')) === 2 || params.get('q') === '客户乙' ? lists[1] : lists[0]], total: 12 });
    }
    if (path === '/packing-lists/shipping-confirmation/boxes') return Promise.resolve({ items: entries.filter(entry => options.body.cargo_uids.includes(entry.cargo_uid)) });
    if (path === '/shipping-confirmation-drafts' && options.method === 'POST') {
        saved = { uid: 'draft-1', version: 1, ...options.body,
            entries: options.body.entries.map(entry => ({ ...entries.find(item => item.cargo_uid === entry.cargo_uid), ...entry })) };
        return Promise.resolve(saved);
    }
    if (path === '/shipping-confirmation-drafts/draft-1' && options.method === 'PUT') {
        saved = { ...saved, ...options.body, version: saved.version + 1,
            entries: options.body.entries.map(entry => ({ ...entries.find(item => item.cargo_uid === entry.cargo_uid), ...entry })) };
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
    await screen.findByText('PL-1001');
}
async function waitUntilIdle() {
    await waitFor(() => expect(screen.getByLabelText('出货单草稿名称')).toBeEnabled());
    await waitFor(() => expect(screen.getByRole('button', { name: /保存草稿/ })).not.toHaveClass('ant-btn-loading'));
}
function selectCatalogBox(number) {
    const catalog = screen.getByLabelText('可添加的装箱单箱子');
    fireEvent.click(within(within(catalog).getByRole('row', { name: new RegExp(number) })).getByRole('checkbox'));
}
async function addFirstBox() {
    await ready();
    selectCatalogBox('PL-1001');
    fireEvent.click(screen.getByRole('button', { name: /添加所选箱子（1）/ }));
    await waitFor(() => expect(screen.getByLabelText('箱子 box-1 渠道代理')).toBeEnabled());
    await waitUntilIdle();
}

beforeEach(() => {
    jest.clearAllMocks();
    saved = null;
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
    expect(within(within(screen.getByLabelText('可添加的装箱单箱子')).getByRole('row', { name: /PL-1002/ })).getByRole('checkbox')).toBeDisabled();
});

test('reopens a saved draft and adds boxes from a different packing list without overwriting its remarks', async () => {
    saved = { uid: 'draft-1', title: '已保存单', version: 4, entries: [{ ...entries[0], agent_name: 'JF', remarks: '先寄地址' }] };
    renderPage();
    await ready();
    fireEvent.click(await screen.findByRole('button', { name: '已保存单 1 箱' }));
    await waitFor(() => expect(screen.getByLabelText('箱子 box-1 渠道代理')).toBeEnabled());
    await waitUntilIdle();
    expect(screen.getByLabelText('箱子 box-1 出货备注')).toHaveValue('先寄地址');
    const search = screen.getByRole('searchbox', { name: '搜索出货装箱单' });
    fireEvent.change(search, { target: { value: '客户乙' } });
    fireEvent.keyDown(search, { key: 'Enter', code: 'Enter', keyCode: 13 });
    await waitFor(() => expect(within(screen.getByLabelText('可添加的装箱单箱子')).getByText('PL-1002')).toBeInTheDocument());
    selectCatalogBox('PL-1002');
    fireEvent.click(screen.getByRole('button', { name: /添加所选箱子（1）/ }));
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
    await waitFor(() => expect(screen.getByLabelText('箱子 box-2 渠道代理')).toBeEnabled());
    await waitUntilIdle();
    const draftTable = screen.getByLabelText('出货单草稿箱子');
    fireEvent.click(within(within(draftTable).getByRole('row', { name: /PL-1001/ })).getByRole('checkbox'));
    fireEvent.change(screen.getByLabelText('批量出货备注'), { target: { value: '批量地址 10000' } });
    fireEvent.click(screen.getByRole('button', { name: '批量填写备注' }));
    expect(screen.getByLabelText('箱子 box-1 出货备注')).toHaveValue('批量地址 10000');
    expect(screen.getByLabelText('箱子 box-2 出货备注')).toHaveValue('');
    fireEvent.click(screen.getByRole('button', { name: /保存并打印 PDF/ }));
    await waitFor(() => expect(preview.location.href).toBe('blob:shipping-pdf'));
    await waitUntilIdle();
    expect(saved).toBeTruthy();
    expect(fetchShippingConfirmationPdf).toHaveBeenCalledWith('draft-1', 1);
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
    const leaveDialog = await screen.findByRole('dialog', { name: '有未保存的出货单内容' });
    fireEvent.click(within(leaveDialog).getByRole('button', { name: '保存并离开' }));
    await within(leaveDialog).findByText('暂时无法保存');
    expect(view.state.location.pathname).toBe('/shipping-confirmation-drafts');
    expect(screen.getByLabelText('箱子 box-1 出货备注')).toHaveValue('保留这条地址');
    fireEvent.click(within(leaveDialog).getByRole('button', { name: '继续编辑' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByLabelText('箱子 box-1 出货备注')).toHaveValue('保留这条地址');
    await act(async () => { await view.navigate('/packing-lists'); });
    const retryDialog = await screen.findByRole('dialog', { name: '有未保存的出货单内容' });
    fireEvent.click(within(retryDialog).getByRole('button', { name: '放弃修改并离开' }));
    await screen.findByText('装箱单列表页面');
    expect(saved).toBeNull();
});

test('loads a draft directly by URL and saves edits before starting a new draft, then deletes it', async () => {
    saved = { uid: 'draft-1', title: '已保存单', version: 4, entries: [{ ...entries[0], agent_name: 'JF', remarks: '原地址' }] };
    const view = renderPage('/shipping-confirmation-drafts/draft-1');
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
    await screen.findByLabelText('箱子 box-1 出货备注');
    await waitUntilIdle();
    fireEvent.click(screen.getByRole('button', { name: '另一份草稿 1 箱' }));
    await screen.findByText('另一份草稿暂时无法加载');
    expect(view.state.location.pathname).toBe('/shipping-confirmation-drafts/draft-2');
    expect(screen.queryByLabelText('出货单草稿名称')).not.toBeInTheDocument();
    if (recovery === 'browser back') await act(async () => { await view.navigate(-1); });
    else fireEvent.click(screen.getByRole('button', { name: '已保存单 1 箱' }));
    await screen.findByLabelText('箱子 box-1 出货备注');
    await waitUntilIdle();
    expect(view.state.location.pathname).toBe('/shipping-confirmation-drafts/draft-1');
    expect(screen.queryByText('另一份草稿暂时无法加载')).not.toBeInTheDocument();
    expect(screen.getByLabelText('箱子 box-1 出货备注')).toHaveValue('之前保存的地址');
    expect(screen.getByRole('button', { name: /保存并打印 PDF/ })).toBeEnabled();
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
