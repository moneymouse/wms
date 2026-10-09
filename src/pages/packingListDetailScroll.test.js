import React from 'react';
import { act, fireEvent, queryByAttribute, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import PackingListDetail from './packingListDetail';
import { ORDER_EDIT_POLICY_KEYS } from '../common/orderEditPolicy';

// These exercise real Antd forms and modal transitions, including repeated desktop mounts.
jest.setTimeout(15000);

const editPolicy = Object.fromEntries(ORDER_EDIT_POLICY_KEYS.map(key => [key, true]));
const workers = [{ id: 1, name: '操作员甲' }, { id: 2, name: '操作员乙' }];
const makeBox = (uid, boxNumber, name, workerId = 1) => ({
    uid, box_number: boxNumber, item_name: name, piece_count: 2, weight: 3,
    item_details: [{ item_name: name, customs_code: '', piece_count: 2 }],
    status: 'pending_assign', identity_editable: true, original_number_editable: true,
    edit_policy: editPolicy,
    workers: [{ worker_id: workerId, worker_name: workers[workerId - 1].name }],
});
const response = (data, code = 200, msg = '') => {
    const body = JSON.parse(JSON.stringify({ code, data, msg }));
    return { ok: code === 200, json: () => Promise.resolve(body) };
};
const deferred = () => {
    let resolve;
    let reject;
    const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
    return { promise, resolve, reject };
};

let details;
let detailReads;
let onDetail;
let onSave;
let onWorkers;

function Navigation() {
    const navigate = useNavigate();
    return <>
        <button onClick={() => navigate('/packing-lists/pl-2')}>切换装箱单</button>
        <button onClick={() => navigate('/packing-lists/create-new')}>新开装箱单</button>
    </>;
}

function renderDetail() {
    const view = render(<MemoryRouter initialEntries={['/packing-lists/pl-1']}>
        <Navigation />
        <div data-testid="layout-scroll" style={{ overflowY: 'auto' }}>
            <div data-testid="content-scroll" style={{ overflowY: 'auto' }}>
                <Routes>
                    <Route path="/packing-lists/create-new" element={<input aria-label="新单唛头" />} />
                    <Route path="/packing-lists/:uid" element={<PackingListDetail />} />
                </Routes>
            </div>
        </div>
    </MemoryRouter>);
    const outer = screen.getByTestId('layout-scroll');
    const inner = screen.getByTestId('content-scroll');
    [outer, inner].forEach(element => {
        Object.defineProperties(element, {
            clientHeight: { configurable: true, value: 640 },
            scrollHeight: { configurable: true, value: 6400 },
            clientWidth: { configurable: true, value: 1200 },
            scrollWidth: { configurable: true, value: 1400 },
        });
    });
    outer.scrollTop = 80;
    outer.scrollLeft = 12;
    inner.scrollTop = 1370;
    inner.scrollLeft = 7;
    return { ...view, outer, inner };
}

function editButton(uid) {
    const button = queryByAttribute('data-box-edit-uid', screen.getByTestId('content-scroll'), uid);
    expect(button).toBeDefined();
    return button;
}

function installButtonGeometry(button, view) {
    button.getBoundingClientRect = jest.fn(() => {
        // Geometry must follow DOM order even while refreshed rows are hidden by a modal.
        // eslint-disable-next-line testing-library/no-node-access, testing-library/no-container
        const buttons = Array.from(view.container.querySelectorAll('[data-box-edit-uid]'));
        const top = 1700 + buttons.indexOf(button) * 320 - view.outer.scrollTop - view.inner.scrollTop;
        return { x: 0, y: top, top, bottom: top + 32, left: 0, right: 80, width: 80, height: 32, toJSON: () => ({}) };
    });
}

async function openEditor(uid, view) {
    const button = editButton(uid);
    installButtonGeometry(button, view);
    button.focus();
    fireEvent.click(button);
    const dialog = await screen.findByRole('dialog', { name: /编辑箱子/ });
    return { button, dialog, input: within(dialog).getByPlaceholderText('品名') };
}

function saveEditor(editor, name) {
    fireEvent.change(editor.input, { target: { value: name } });
    const save = within(editor.dialog).getByRole('button', { name: /保\s*存/ });
    save.focus();
    fireEvent.click(save);
    return save;
}

function saveCalls() {
    return global.fetch.mock.calls.filter(([url, options]) => /\/box\/[^/]+$/.test(String(url)) && options?.method === 'PUT');
}

function updateBox(uid, values) {
    Object.values(details).forEach(detail => {
        detail.boxes = detail.boxes.map(box => box.uid === uid ? { ...box, ...values } : box);
    });
}

async function expectRestored(editor, view, top = 1370, outerTop = 80) {
    await waitFor(() => expect(editor.button).toHaveFocus());
    expect(screen.queryByRole('dialog', { name: /编辑箱子/ })).not.toBeInTheDocument();
    expect(view.inner.scrollTop).toBe(top);
    expect(view.outer.scrollTop).toBe(outerTop);
    expect(view.inner.scrollLeft).toBe(7);
    expect(view.outer.scrollLeft).toBe(12);
}

beforeEach(() => {
    const payload = window.btoa(JSON.stringify({ user_id: 1, roles: ['clerk'] }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
    document.documentElement.scrollTop = 0;
    details = {
        'pl-1': { uid: 'pl-1', list_number: 'SCROLL-1', status: 'draft', boxes: [
            makeBox('box-1', 1, '鞋子'), makeBox('box-2', 2, '帽子', 2),
        ] },
        'pl-2': { uid: 'pl-2', list_number: 'SCROLL-2', status: 'draft', boxes: [makeBox('box-new', 1, '新单围巾', 2)] },
    };
    detailReads = {};
    onDetail = null;
    onSave = null;
    onWorkers = null;
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => {
        const minimumWidth = query.match(/min-width:\s*(\d+)px/);
        return {
            matches: Boolean(minimumWidth && Number(minimumWidth[1]) <= 1280), media: query, onchange: null,
            addListener: () => {}, removeListener: () => {}, addEventListener: () => {},
            removeEventListener: () => {}, dispatchEvent: () => false,
        };
    } });
    global.fetch = jest.fn((rawUrl, options = {}) => {
        const url = String(rawUrl);
        const detailMatch = url.match(/\/packing-list\/(pl-[12])$/);
        if (detailMatch && !options.method) {
            const uid = detailMatch[1];
            const count = detailReads[uid] = (detailReads[uid] || 0) + 1;
            return onDetail ? onDetail(uid, count) : Promise.resolve(response(details[uid]));
        }
        const workerMatch = url.match(/\/box\/([^/]+)\/workers$/);
        if (workerMatch) {
            const uid = workerMatch[1];
            if (onWorkers) return onWorkers(uid);
            const box = Object.values(details).flatMap(detail => detail.boxes).find(item => item.uid === uid);
            return Promise.resolve(response(box?.workers || []));
        }
        const boxMatch = url.match(/\/box\/([^/]+)$/);
        if (boxMatch && options.method === 'PUT') {
            const uid = boxMatch[1];
            const values = JSON.parse(options.body);
            if (onSave) return onSave(uid, values);
            updateBox(uid, values);
            return Promise.resolve(response(null));
        }
        return Promise.resolve(response(url.endsWith('/users/list') ? workers : []));
    });
});

afterEach(() => {
    window.localStorage.clear();
    jest.restoreAllMocks();
});

test('delayed detail refresh keeps the list and editor mounted, then restores both scroll ancestors and focus', async () => {
    const refresh = deferred();
    onDetail = (uid, count) => count > 1 ? refresh.promise : Promise.resolve(response(details[uid]));
    const view = renderDetail();
    await screen.findByText('SCROLL-1');
    const editor = await openEditor('box-1', view);
    const focus = jest.spyOn(editor.button, 'focus');
    const save = saveEditor(editor, '更正鞋子');
    await waitFor(() => expect(detailReads['pl-1']).toBe(2));
    expect(editor.button.isConnected).toBe(true);
    expect(editButton('box-1')).toBe(editor.button);
    expect(editor.input.isConnected).toBe(true);
    expect(within(editor.dialog).getByDisplayValue('更正鞋子')).toBe(editor.input);
    expect(screen.getByText('鞋子')).toBeInTheDocument();
    expect(screen.queryByText('更正鞋子')).not.toBeInTheDocument();
    await waitFor(() => expect(save).toHaveClass('ant-btn-loading'));
    expect(view.inner.scrollTop).toBe(1370);
    expect(view.outer.scrollTop).toBe(80);
    // Model a browser focus/closing side effect while the list still exists.
    view.inner.scrollTop = 0;
    view.outer.scrollTop = 0;
    await act(async () => refresh.resolve(response(details['pl-1'])));
    await expectRestored(editor, view);
    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
    expect(screen.getByText('更正鞋子')).toBeInTheDocument();
});

test('two save clicks before asynchronous validation completes send only one update', async () => {
    const pending = deferred();
    onSave = (uid, values) => { updateBox(uid, values); return pending.promise; };
    const view = renderDetail();
    await screen.findByText('SCROLL-1');
    const editor = await openEditor('box-1', view);
    fireEvent.change(editor.input, { target: { value: '快速双击更正' } });
    const save = within(editor.dialog).getByRole('button', { name: /保\s*存/ });
    fireEvent.click(save);
    fireEvent.click(save);
    await waitFor(() => expect(saveCalls()).toHaveLength(1));
    await act(async () => pending.resolve(response(null)));
    await expectRestored(editor, view);
    expect(saveCalls()).toHaveLength(1);
    expect(screen.getByText('快速双击更正')).toBeInTheDocument();
});

test.each(['rejected', 'network failure'])('%s save keeps edited input, dialog focus and nearby scroll position for retry', async failure => {
    const pending = deferred();
    onSave = () => pending.promise;
    const view = renderDetail();
    await screen.findByText('SCROLL-1');
    const editor = await openEditor('box-1', view);
    const save = saveEditor(editor, '失败后保留品名');
    await waitFor(() => expect(saveCalls()).toHaveLength(1));
    const errorLog = jest.spyOn(console, 'error').mockImplementation(() => {});
    await act(async () => {
        if (failure === 'rejected') pending.resolve(response(null, 409, '箱子版本已改变'));
        else pending.reject(new Error('fixture network failure'));
    });
    expect(await screen.findByText(failure === 'rejected' ? '箱子版本已改变' : '更新箱子失败')).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: /编辑箱子/ })).toBe(editor.dialog);
    expect(within(editor.dialog).getByDisplayValue('失败后保留品名')).toBe(editor.input);
    expect(save).toHaveFocus();
    expect(view.inner.scrollTop).toBe(1370);
    expect(view.outer.scrollTop).toBe(80);
    expect(detailReads['pl-1']).toBe(1);
    expect(editor.button.isConnected).toBe(true);
    errorLog.mockRestore();
    onSave = (uid, values) => { updateBox(uid, values); return Promise.resolve(response(null)); };
    saveEditor(editor, '重试更正品名');
    await expectRestored(editor, view);
    expect(saveCalls()).toHaveLength(2);
    expect(screen.getByText('重试更正品名')).toBeInTheDocument();
});

test('consecutive edits restore the most recently edited box at its own scroll position', async () => {
    const view = renderDetail();
    await screen.findByText('SCROLL-1');
    const first = await openEditor('box-1', view);
    saveEditor(first, '第一箱更正');
    await expectRestored(first, view);
    view.inner.scrollTop = 1650;
    view.outer.scrollTop = 92;
    const second = await openEditor('box-2', view);
    saveEditor(second, '第二箱更正');
    await expectRestored(second, view, 1650, 92);
    expect(screen.getByText('第一箱更正')).toBeInTheDocument();
    expect(screen.getByText('第二箱更正')).toBeInTheDocument();
    expect(saveCalls()).toHaveLength(2);
    expect(detailReads['pl-1']).toBe(3);
});

test('a refreshed list that inserts a box preserves the edited button identity and viewport offset', async () => {
    onDetail = (uid, count) => {
        if (count > 1) details[uid].boxes = [makeBox('box-added', 0, '新增箱'), ...details[uid].boxes];
        return Promise.resolve(response(details[uid]));
    };
    const view = renderDetail();
    await screen.findByText('SCROLL-1');
    const editor = await openEditor('box-1', view);
    const originalTop = editor.button.getBoundingClientRect().top;
    saveEditor(editor, '插入后仍可连续核对');
    await expectRestored(editor, view, 1690);
    expect(editButton('box-1')).toBe(editor.button);
    expect(editor.button.getBoundingClientRect().top).toBe(originalTop);
});

test('a failed refresh keeps existing detail visible and closes the successful editor with restored focus', async () => {
    onDetail = (uid, count) => Promise.resolve(count > 1 ? response(null, 500) : response(details[uid]));
    const view = renderDetail();
    await screen.findByText('SCROLL-1');
    const editor = await openEditor('box-1', view);
    saveEditor(editor, '服务端已保存');
    expect(await screen.findByText('获取详情失败')).toBeInTheDocument();
    await expectRestored(editor, view);
    expect(screen.getByText('SCROLL-1')).toBeInTheDocument();
    expect(editButton('box-1')).toBe(editor.button);
    expect(saveCalls()).toHaveLength(1);
});

test('navigation and a late save cannot close or focus the next packing list editor', async () => {
    const pending = deferred();
    onSave = () => pending.promise;
    const view = renderDetail();
    await screen.findByText('SCROLL-1');
    const oldEditor = await openEditor('box-1', view);
    const oldFocus = jest.spyOn(oldEditor.button, 'focus');
    saveEditor(oldEditor, '旧单修改');
    await waitFor(() => expect(saveCalls()).toHaveLength(1));
    fireEvent.click(screen.getByRole('button', { name: '切换装箱单' }));
    await screen.findByText('SCROLL-2');
    expect(screen.queryByRole('dialog', { name: /编辑箱子/ })).not.toBeInTheDocument();
    view.inner.scrollTop = 420;
    view.outer.scrollTop = 14;
    const newEditor = await openEditor('box-new', view);
    newEditor.input.focus();
    fireEvent.change(newEditor.input, { target: { value: '新单继续核对' } });
    await act(async () => pending.resolve(response(null)));
    expect(screen.getByRole('dialog', { name: /编辑箱子/ })).toBe(newEditor.dialog);
    expect(within(newEditor.dialog).getByDisplayValue('新单继续核对')).toBe(newEditor.input);
    expect(newEditor.input).toHaveFocus();
    expect(view.inner.scrollTop).toBe(420);
    expect(view.outer.scrollTop).toBe(14);
    expect(oldFocus).not.toHaveBeenCalled();
    expect(detailReads['pl-1']).toBe(1);
    expect(detailReads['pl-2']).toBe(1);
});

test('a late worker response cannot overwrite the next box editor after cancelling the previous one', async () => {
    const oldWorkers = deferred();
    onWorkers = uid => uid === 'box-1' ? oldWorkers.promise : Promise.resolve(response([{ worker_id: 2 }]));
    const view = renderDetail();
    await screen.findByText('SCROLL-1');
    const first = await openEditor('box-1', view);
    fireEvent.click(within(first.dialog).getByRole('button', { name: /取\s*消/ }));
    await expectRestored(first, view);
    const second = await openEditor('box-2', view);
    expect(within(second.dialog).getByText('操作员乙')).toBeInTheDocument();
    second.input.focus();
    await act(async () => oldWorkers.resolve(response([{ worker_id: 1 }])));
    expect(within(second.dialog).getByText('操作员乙')).toBeInTheDocument();
    expect(within(second.dialog).queryByText('操作员甲')).not.toBeInTheDocument();
    expect(second.input).toHaveFocus();
    saveEditor(second, '第二箱保持操作员');
    await expectRestored(second, view);
    expect(JSON.parse(saveCalls()[0][1].body).worker_ids).toEqual([2]);
});

test('opening a new packing list does not restore the previous editor position after a late refresh', async () => {
    const refresh = deferred();
    onDetail = (uid, count) => count > 1 ? refresh.promise : Promise.resolve(response(details[uid]));
    const view = renderDetail();
    await screen.findByText('SCROLL-1');
    const editor = await openEditor('box-1', view);
    const oldFocus = jest.spyOn(editor.button, 'focus');
    saveEditor(editor, '离开前保存');
    await waitFor(() => expect(detailReads['pl-1']).toBe(2));
    fireEvent.click(screen.getByRole('button', { name: '新开装箱单' }));
    const newMark = await screen.findByRole('textbox', { name: '新单唛头' });
    newMark.focus();
    view.inner.scrollTop = 35;
    view.outer.scrollTop = 0;
    await act(async () => refresh.resolve(response(details['pl-1'])));
    expect(newMark).toHaveFocus();
    expect(view.inner.scrollTop).toBe(35);
    expect(view.outer.scrollTop).toBe(0);
    expect(oldFocus).not.toHaveBeenCalled();
    expect(screen.queryByText('SCROLL-1')).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: /编辑箱子/ })).not.toBeInTheDocument();
});
