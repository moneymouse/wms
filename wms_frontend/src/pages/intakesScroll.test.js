/* eslint-disable testing-library/no-node-access -- Scroll ancestors and persistent row identity require native DOM inspection. */
import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { PaperIntakeUploadDetail } from './intakes';

const makeRecord = (uid = 'intake-1') => ({
    uid, display_name: uid, status: 'pending', version: 1, photos: [],
    recognition_status: 'succeeded', draft_is_manual: true,
    draft: { mark: uid, operator_name: '', boxes: Array.from({ length: 5 }, (_, index) => ({
        box_number: String(index + 1), item_name: '鞋子', count: 2, weight: 3,
        worker_ids: [1], remark: '',
    })) },
});
const response = data => ({ ok: true, json: async () => ({ code: 200, data }) });
const failure = msg => ({ ok: false, status: 500, json: async () => ({ code: 500, msg }) });
let records;
let pendingSave;
let pendingConfirm;

function scrollDimensions(element, { height = 1800, width = 500 } = {}) {
    Object.defineProperties(element, {
        clientHeight: { configurable: true, value: 300 },
        scrollHeight: { configurable: true, value: height },
        clientWidth: { configurable: true, value: 500 },
        scrollWidth: { configurable: true, value: width },
    });
}

async function renderPage() {
    const router = createMemoryRouter([
        { path: '/packing-list/upload/:uid', element: <PaperIntakeUploadDetail /> },
        { path: '/packing-lists', element: <button>装箱单列表</button> },
    ], { initialEntries: ['/packing-list/upload/intake-1'] });
    render(<div data-testid="layout-scroll" style={{ overflowY: 'auto' }}>
        <div data-testid="content-scroll" style={{ overflowY: 'auto' }}>
            <RouterProvider router={router} />
            <button data-testid="other-control">其他操作</button>
        </div>
    </div>);
    await waitFor(() => expect(screen.getByLabelText('第5箱备注')).not.toBeDisabled());
    const outer = screen.getByTestId('layout-scroll');
    const inner = screen.getByTestId('content-scroll');
    scrollDimensions(outer); scrollDimensions(inner);
    const table = screen.getByLabelText('第5箱备注').closest('.ant-table-content');
    scrollDimensions(table, { height: 300, width: 1200 });
    table.style.overflowX = 'auto';
    outer.scrollTop = 210; inner.scrollTop = 450; table.scrollLeft = 180;
    return { router, outer, inner, table };
}

function save(editor) {
    act(() => editor.focus());
    const button = screen.getByRole('button', { name: '保存检查进度' });
    act(() => button.focus());
    fireEvent.click(button);
    return button;
}

async function finishSave({ error } = {}) {
    const { resolve, body, uid } = pendingSave;
    if (!error) records[uid] = { ...records[uid], version: records[uid].version + 1, draft: body.draft };
    await act(async () => { resolve(error ? failure(error) : response(records[uid])); });
}

beforeEach(() => {
    records = { 'intake-1': makeRecord(), 'intake-2': makeRecord('intake-2') };
    pendingSave = null; pendingConfirm = null;
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({
        matches: false, media: query, addListener: () => {}, removeListener: () => {},
        addEventListener: () => {}, removeEventListener: () => {},
    }) });
    global.fetch = jest.fn(async (rawUrl, options = {}) => {
        const url = String(rawUrl);
        if (url.endsWith('/workers')) return response([{ id: 1, name: '测试工人' }]);
        if (url.includes('/goods-names?')) return response([]);
        const uid = url.match(/\/intakes\/(intake-[12])/)[1];
        if (url.endsWith('/draft')) return new Promise(resolve => { pendingSave = { resolve, uid, body: JSON.parse(options.body) }; });
        if (url.endsWith('/confirm')) return new Promise(resolve => { pendingConfirm = { resolve, uid }; });
        return response(records[uid]);
    });
});

afterEach(() => { jest.restoreAllMocks(); });

test('consecutive draft saves preserve row nodes, nested scrolling and the last edited field while clearing selection', async () => {
    const { outer, inner, table } = await renderPage();
    const fifth = screen.getByLabelText('第5箱备注');
    const fourth = screen.getByLabelText('第4箱备注');
    const rows = [fourth.closest('tr'), fifth.closest('tr')];
    fireEvent.click(screen.getByRole('checkbox', { name: '选择第5箱' }));
    fireEvent.change(fifth, { target: { value: '第一次纠错' } });
    const focus = jest.spyOn(fifth, 'focus');
    save(fifth);
    expect(fifth).toBeDisabled();
    outer.scrollTop = 0; inner.scrollTop = 0; table.scrollLeft = 0;
    await finishSave();
    expect(screen.getByLabelText('第5箱备注')).toBe(fifth);
    expect(fifth.closest('tr')).toBe(rows[1]);
    expect(fifth).toHaveFocus();
    expect(focus).toHaveBeenLastCalledWith({ preventScroll: true });
    expect(screen.getByRole('checkbox', { name: '选择第5箱' })).not.toBeChecked();
    expect([outer.scrollTop, inner.scrollTop, table.scrollLeft]).toEqual([210, 450, 180]);
    expect(pendingSave.body.version).toBe(1);

    inner.scrollTop = 640; table.scrollLeft = 220;
    fireEvent.change(fourth, { target: { value: '第二次纠错' } });
    save(fourth);
    inner.scrollTop = 0; table.scrollLeft = 0;
    await finishSave();
    expect(screen.getByLabelText('第4箱备注')).toBe(fourth);
    expect(fourth.closest('tr')).toBe(rows[0]);
    expect(fourth).toHaveFocus();
    expect(fifth).toHaveValue('第一次纠错');
    expect(fourth).toHaveValue('第二次纠错');
    expect(screen.getByRole('checkbox', { name: '选择第5箱' })).not.toBeChecked();
    expect([outer.scrollTop, inner.scrollTop, table.scrollLeft]).toEqual([210, 640, 220]);
    expect(pendingSave.body.version).toBe(2);
});

test('a failed draft preserves local content and the editor offset after an error banner is inserted', async () => {
    const { outer, inner, table } = await renderPage();
    const editor = screen.getByLabelText('第5箱备注');
    fireEvent.click(screen.getByRole('checkbox', { name: '选择第5箱' }));
    editor.getBoundingClientRect = () => ({ top: 900 - inner.scrollTop + (screen.queryByText('测试保存失败') ? 56 : 0) });
    fireEvent.change(editor, { target: { value: '仍待保存的纠错' } });
    save(editor);
    outer.scrollTop = 0; inner.scrollTop = 0; table.scrollLeft = 0;
    await finishSave({ error: '测试保存失败' });
    expect(await screen.findByText('测试保存失败')).toBeInTheDocument();
    expect(screen.getByLabelText('第5箱备注')).toBe(editor);
    expect(editor).toHaveValue('仍待保存的纠错');
    expect(editor).not.toBeDisabled();
    expect(editor).toHaveFocus();
    expect(screen.getByRole('checkbox', { name: '选择第5箱' })).toBeChecked();
    expect([outer.scrollTop, inner.scrollTop, table.scrollLeft]).toEqual([210, 506, 180]);
    expect(editor.getBoundingClientRect().top).toBe(450);
    expect(records['intake-1'].draft.boxes[4].remark).toBe('');
});

test('saving an open goods editor restores its surviving row summary after the popup closes', async () => {
    const { inner } = await renderPage();
    const summary = screen.getByLabelText('第5箱品名与件数');
    fireEvent.click(summary);
    const dialog = await screen.findByRole('dialog', { name: '第5箱商品明细' });
    const name = within(dialog).getByLabelText('第5箱品名');
    await waitFor(() => expect(name).toHaveFocus());
    fireEvent.change(name, { target: { value: '衣服' } });
    const button = screen.getByRole('button', { name: '保存检查进度' });
    act(() => button.focus());
    fireEvent.click(button);
    inner.scrollTop = 0;
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '第5箱商品明细' })).not.toBeInTheDocument());
    await finishSave();
    expect(screen.getByLabelText('第5箱品名与件数')).toBe(summary);
    expect(summary).toHaveValue('衣服 x 2');
    expect(summary).toHaveFocus();
    expect(inner.scrollTop).toBe(450);
});

test('a confirm pre-save preserves rows and clears selection when confirmation fails', async () => {
    const { inner } = await renderPage();
    const editor = screen.getByLabelText('第5箱备注');
    fireEvent.click(screen.getByRole('checkbox', { name: '选择第5箱' }));
    fireEvent.change(editor, { target: { value: '确认前纠错' } });
    act(() => editor.focus());
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    const button = screen.getByRole('button', { name: /核对完成并上传/ });
    act(() => button.focus()); fireEvent.click(button);
    await finishSave();
    await waitFor(() => expect(pendingConfirm).not.toBeNull());
    expect(screen.getByLabelText('第5箱备注')).toBe(editor);
    inner.scrollTop = 0;
    await act(async () => { pendingConfirm.resolve(failure('测试确认失败')); });
    expect(await screen.findByText('测试确认失败')).toBeInTheDocument();
    expect(editor).not.toBeDisabled();
    expect(editor).toHaveFocus();
    expect(screen.getByRole('checkbox', { name: '选择第5箱' })).not.toBeChecked();
    expect(inner.scrollTop).toBe(450);
});

test('confirmation success on the same page preserves scrolling and focuses the now read-only box row', async () => {
    const { outer, inner, table } = await renderPage();
    const editor = screen.getByLabelText('第5箱备注');
    const rowKey = editor.closest('tr').getAttribute('data-row-key');
    fireEvent.change(editor, { target: { value: '确认完成' } });
    act(() => editor.focus());
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    const button = screen.getByRole('button', { name: /核对完成并上传/ });
    act(() => button.focus()); fireEvent.click(button);
    await finishSave();
    await waitFor(() => expect(pendingConfirm).not.toBeNull());
    outer.scrollTop = 0; inner.scrollTop = 0; table.scrollLeft = 0;
    records['intake-1'] = { ...records['intake-1'], status: 'confirmed', packing_list_uid: 'packing-1', version: 3 };
    await act(async () => { pendingConfirm.resolve(response(records['intake-1'])); });
    const confirmedEditor = screen.getByLabelText('第5箱备注');
    expect(editor.isConnected).toBe(false);
    expect(confirmedEditor).toBeDisabled();
    const currentRow = confirmedEditor.closest('tr');
    expect(currentRow.getAttribute('data-row-key')).toBe(rowKey);
    expect(currentRow).toHaveFocus();
    expect([outer.scrollTop, inner.scrollTop, table.scrollLeft]).toEqual([210, 450, 180]);
    expect(screen.getByRole('link', { name: '查看装箱单' })).toHaveAttribute('href', '/packing-lists/packing-1');
});

test.each(['wheel', 'focus'])('a user %s interaction while saving cancels position and focus restoration', async interaction => {
    const { inner } = await renderPage();
    const editor = screen.getByLabelText('第5箱备注');
    fireEvent.change(editor, { target: { value: '纠错' } });
    save(editor);
    const other = screen.getByTestId('other-control');
    if (interaction === 'wheel') fireEvent.wheel(inner, { deltaY: 100 });
    else act(() => other.focus());
    inner.scrollTop = 900;
    await finishSave();
    expect(inner.scrollTop).toBe(900);
    expect(editor).not.toHaveFocus();
    expect(document.activeElement === other).toBe(interaction === 'focus');
});

test('a delayed save cannot restore the previous editor after navigating to another paper', async () => {
    const { router, inner } = await renderPage();
    const editor = screen.getByLabelText('第5箱备注');
    fireEvent.change(editor, { target: { value: '旧单纠错' } });
    save(editor);
    await act(async () => { await router.navigate('/packing-list/upload/intake-2'); });
    const dialog = await screen.findByRole('dialog', { name: '有未保存的内容' });
    fireEvent.click(within(dialog).getByRole('button', { name: '放弃修改并离开' }));
    const mark = await screen.findByDisplayValue('intake-2');
    act(() => mark.focus()); inner.scrollTop = 80;
    await finishSave();
    expect(editor).not.toBeInTheDocument();
    expect(mark).toHaveFocus();
    expect(inner.scrollTop).toBe(80);
    expect(screen.getByLabelText('第5箱备注')).toHaveValue('');
    expect(router.state.location.pathname).toBe('/packing-list/upload/intake-2');
});

test('an explicit reload resets rows and selection but keeps the matching box nearby even when server order changes', async () => {
    const { outer, inner, table } = await renderPage();
    const editor = screen.getByLabelText('第5箱备注');
    fireEvent.click(screen.getByRole('checkbox', { name: '选择第5箱' }));
    fireEvent.change(editor, { target: { value: '将被放弃' } });
    save(editor);
    await finishSave({ error: '测试保存失败' });
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }));
    const dialog = await screen.findByRole('dialog', { name: '重新加载纸单' });
    records['intake-1'] = { ...records['intake-1'], draft: { ...records['intake-1'].draft, boxes: [...records['intake-1'].draft.boxes].reverse() } };
    fireEvent.click(within(dialog).getByRole('button', { name: '放弃修改并重新加载' }));
    outer.scrollTop = 0; inner.scrollTop = 0; table.scrollLeft = 0;
    await waitFor(() => expect(screen.getByLabelText('第5箱备注')).not.toBe(editor));
    const reloadedEditor = screen.getByLabelText('第1箱备注');
    expect(reloadedEditor).toHaveValue('');
    expect(reloadedEditor).toHaveFocus();
    expect(screen.getByLabelText('第1箱箱号')).toHaveValue('5');
    expect([outer.scrollTop, inner.scrollTop, table.scrollLeft]).toEqual([210, 450, 180]);
    expect(screen.getByRole('checkbox', { name: '选择第5箱' })).not.toBeChecked();
});

test('reload follows the original box identity after an earlier unsaved row was deleted and the box number edited', async () => {
    const { inner } = await renderPage();
    fireEvent.click(screen.getByRole('button', { name: '删除第1箱' }));
    const editor = screen.getByLabelText('第4箱备注');
    expect(screen.getByLabelText('第4箱箱号')).toHaveValue('5');
    fireEvent.change(screen.getByLabelText('第4箱箱号'), { target: { value: '4' } });
    fireEvent.change(editor, { target: { value: '箱号与备注尚未保存' } });
    save(editor);
    await finishSave({ error: '测试保存失败' });
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }));
    const dialog = await screen.findByRole('dialog', { name: '重新加载纸单' });
    fireEvent.click(within(dialog).getByRole('button', { name: '放弃修改并重新加载' }));
    inner.scrollTop = 0;
    await waitFor(() => expect(screen.getByLabelText('第5箱备注')).not.toBeDisabled());
    expect(screen.getByLabelText('第5箱备注')).toHaveFocus();
    expect(screen.getByLabelText('第4箱备注')).not.toHaveFocus();
    expect(inner.scrollTop).toBe(450);
});
