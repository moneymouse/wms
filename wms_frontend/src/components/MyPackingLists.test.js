import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import MyPackingLists from './MyPackingLists';
import { intakeRequest } from '../common/intakeApi';

jest.mock('../common/intakeApi', () => ({ intakeRequest: jest.fn() }));

const pending = {
    uid: 'paper-1', mark: 'PAPER-1', source: 'paper', status: 'uploading',
    created_at: '2026-10-02 09:00:00', box_count: null,
};
const manual = {
    uid: 'manual-1', mark: 'MANUAL-1', source: 'manual', status: 'completed',
    created_at: '2026-10-02 08:00:00', box_count: 5, packing_list_uid: 'packing-manual-1',
};
const draft = {
    ...manual, uid: 'manual-draft', mark: 'DRAFT-1', status: 'draft', packing_list_uid: 'packing-draft-1',
};
const confirmed = {
    ...pending, uid: 'paper-confirmed', mark: 'CONFIRMED-1', status: 'completed',
    box_count: 3, packing_list_uid: 'packing-paper-1',
};
const result = (items, total = items.length) => ({ items, total, page: 1, page_size: 20 });
const deferred = () => {
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    return { promise, resolve };
};

function pageElement(refreshKey = 0) {
    return <MemoryRouter initialEntries={['/packing-lists']}>
        <Routes>
            <Route path="/packing-lists" element={<MyPackingLists refreshKey={refreshKey} />} />
            <Route path="/packing-list/new" element={<div>创建装箱单页面</div>} />
            <Route path="/packing-lists/:uid" element={<div>正式装箱单详情</div>} />
        </Routes>
    </MemoryRouter>;
}

beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
        writable: true,
        value: query => ({
            matches: false, media: query, onchange: null,
            addListener: () => {}, removeListener: () => {},
            addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
        }),
    });
    intakeRequest.mockReset();
    intakeRequest.mockResolvedValue(result([pending, manual, draft, confirmed]));
});

afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
});

test('loads the personal endpoint and shows only worker-facing packing-list information', async () => {
    intakeRequest.mockResolvedValue(result([
        { ...pending, photos: [{ filename: 'secret-photo.jpg' }], recognition_status: 'failed', warnings: ['内部识别警告'] },
        manual, draft, confirmed,
    ]));
    render(pageElement());
    expect(await screen.findByText('PAPER-1')).toBeInTheDocument();
    expect(intakeRequest).toHaveBeenCalledWith('/my-packing-lists?page=1&page_size=20&mark=', expect.objectContaining({ signal: expect.any(Object) }));
    expect(screen.getByRole('heading', { name: '我的装箱单' })).toBeInTheDocument();
    expect(screen.getByText('上传未完成')).toBeInTheDocument();
    expect(screen.getByText('草稿')).toBeInTheDocument();
    expect(screen.getAllByText('已创建')).toHaveLength(1);
    expect(screen.getByText('已核对')).toBeInTheDocument();
    const pendingRow = screen.getByRole('row', { name: /PAPER-1/ });
    expect(within(pendingRow).getByText('拍照上传')).toBeInTheDocument();
    expect(within(pendingRow).getByRole('link', { name: '继续检查并上传' })).toHaveAttribute('href', '/packing-list/upload/paper-1');
    expect(screen.queryByText(/内部识别警告|secret-photo|识别状态|查看纸单|解析/)).not.toBeInTheDocument();
    expect(screen.getAllByRole('link')).toHaveLength(4);
    expect(within(screen.getByRole('row', { name: /MANUAL-1/ })).getByRole('link')).toHaveAttribute('href', '/packing-lists/packing-manual-1');
    expect(within(screen.getByRole('row', { name: /DRAFT-1/ })).getByRole('link')).toHaveAttribute('href', '/packing-lists/packing-draft-1');
    expect(within(screen.getByRole('row', { name: /CONFIRMED-1/ })).getByRole('link')).toHaveAttribute('href', '/packing-lists/packing-paper-1');
});

test('opens the regular packing-list details and the unified creation page', async () => {
    const view = render(pageElement());
    await screen.findByText('CONFIRMED-1');
    fireEvent.click(within(screen.getByRole('row', { name: /CONFIRMED-1/ })).getByRole('link', { name: '查看装箱单' }));
    expect(await screen.findByText('正式装箱单详情')).toBeInTheDocument();
    view.unmount();
    render(pageElement());
    fireEvent.click(screen.getByRole('button', { name: /创建装箱单/ }));
    expect(await screen.findByText('创建装箱单页面')).toBeInTheDocument();
});

test('paginates and searches by mark on the server, resetting a search to page one', async () => {
    intakeRequest.mockImplementation(async path => {
        const params = new URLSearchParams(path.split('?')[1]);
        return result([{ ...manual, mark: params.get('mark') || `PAGE-${params.get('page')}` }], 41);
    });
    render(pageElement());
    await screen.findByText('PAGE-1');
    fireEvent.click(screen.getByTitle('2'));
    expect(await screen.findByText('PAGE-2')).toBeInTheDocument();
    expect(intakeRequest).toHaveBeenLastCalledWith('/my-packing-lists?page=2&page_size=20&mark=', expect.any(Object));
    const search = screen.getByLabelText('按唛头查找我的装箱单');
    fireEvent.change(search, { target: { value: '  客户 A/1  ' } });
    fireEvent.keyDown(search, { key: 'Enter', code: 'Enter' });
    expect(await screen.findByText('客户 A/1')).toBeInTheDocument();
    const params = new URLSearchParams(intakeRequest.mock.calls.at(-1)[0].split('?')[1]);
    expect(params.get('page')).toBe('1');
    expect(params.get('mark')).toBe('客户 A/1');
});

test('shows a safe load error and retries without exposing internal recognition messages', async () => {
    intakeRequest.mockRejectedValueOnce(new Error('recognition backend secret'));
    render(pageElement());
    expect(await screen.findByText('装箱单加载失败，请重试')).toBeInTheDocument();
    expect(screen.queryByText(/backend secret/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }));
    expect(await screen.findByText('MANUAL-1')).toBeInTheDocument();
    expect(screen.queryByText('装箱单加载失败，请重试')).not.toBeInTheDocument();
});

test('invalid list data produces a recoverable error instead of a broken table', async () => {
    intakeRequest.mockResolvedValueOnce({ items: null, total: 1 });
    render(pageElement());
    expect(await screen.findByText('装箱单加载失败，请重试')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }));
    expect(await screen.findByText('MANUAL-1')).toBeInTheDocument();
});

test('an older response cannot replace the latest mark search', async () => {
    const old = deferred();
    intakeRequest.mockReturnValueOnce(old.promise).mockResolvedValueOnce(result([{ ...manual, mark: 'LATEST' }]));
    render(pageElement());
    const oldSignal = intakeRequest.mock.calls[0][1].signal;
    const search = screen.getByLabelText('按唛头查找我的装箱单');
    fireEvent.change(search, { target: { value: 'LATEST' } });
    fireEvent.keyDown(search, { key: 'Enter', code: 'Enter' });
    expect(await screen.findByText('LATEST')).toBeInTheDocument();
    expect(oldSignal.aborted).toBe(true);
    await act(async () => { old.resolve(result([{ ...pending, mark: 'OLD' }])); });
    expect(screen.getByText('LATEST')).toBeInTheDocument();
    expect(screen.queryByText('OLD')).not.toBeInTheDocument();
});

test('unfinished uploads link to the uploader check page without reviewer polling', async () => {
    jest.useFakeTimers();
    render(pageElement());
    await screen.findByText('PAPER-1');
    expect(screen.getByRole('link', { name: '继续检查并上传' })).toHaveAttribute('href', '/packing-list/upload/paper-1');
    await act(async () => { jest.advanceTimersByTime(30000); });
    expect(intakeRequest).toHaveBeenCalledTimes(1);
});

test('refreshKey refreshes the list after a parent upload completes', async () => {
    intakeRequest.mockResolvedValueOnce(result([manual])).mockResolvedValueOnce(result([pending]));
    const view = render(pageElement());
    await screen.findByText('MANUAL-1');
    view.rerender(pageElement(1));
    expect(await screen.findByText('PAPER-1')).toBeInTheDocument();
    await waitFor(() => expect(intakeRequest).toHaveBeenCalledTimes(2));
});

test('the real xs breakpoint renders compact cards with no duplicate desktop table or paper parsing links', async () => {
    window.matchMedia = query => ({
        matches: query === '(max-width: 575px)', media: query, onchange: null,
        addListener: () => {}, removeListener: () => {},
        addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
    });
    render(pageElement());
    await screen.findByText('PAPER-1');
    const cards = screen.getAllByRole('article');
    expect(cards).toHaveLength(4);
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.getAllByText('PAPER-1')).toHaveLength(1);
    const paper = screen.getByRole('article', { name: '装箱单 PAPER-1' });
    expect(within(paper).getByText('上传未完成')).toBeInTheDocument();
    expect(within(paper).getByText('拍照上传')).toBeInTheDocument();
    expect(within(paper).getByText('箱数：-')).toBeInTheDocument();
    expect(within(paper).getByText('创建时间：2026-10-02 09:00:00')).toBeInTheDocument();
    expect(within(paper).getByRole('link', { name: '继续检查并上传' })).toHaveAttribute('href', '/packing-list/upload/paper-1');
    const formal = screen.getByRole('article', { name: '装箱单 CONFIRMED-1' });
    expect(within(formal).getByText('箱数：3')).toBeInTheDocument();
    expect(within(formal).getByRole('link', { name: '查看装箱单' })).toHaveAttribute('href', '/packing-lists/packing-paper-1');
});

test('restores personal packing-list search and pagination from a copied URL', async () => {
    render(<MemoryRouter initialEntries={['/packing-lists?my_packing_search=已保存唛头&my_packing_page=3']}><MyPackingLists /></MemoryRouter>);
    await screen.findByText('PAPER-1');
    expect(screen.getByLabelText('按唛头查找我的装箱单')).toHaveValue('已保存唛头');
    const params = new URLSearchParams(intakeRequest.mock.calls[0][0].split('?')[1]);
    expect(params.get('mark')).toBe('已保存唛头');
    expect(params.get('page')).toBe('3');
});
