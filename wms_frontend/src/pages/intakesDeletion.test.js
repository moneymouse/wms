import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { PaperIntakeUpload } from './intakes';
import { intakeRequest } from '../common/intakeApi';

jest.mock('../common/intakeApi', () => ({
    ...jest.requireActual('../common/intakeApi'), intakeRequest: jest.fn(),
}));

jest.setTimeout(15000);

const upload = {
    uid: 'intake-1', mark: 'MY-UPLOAD', box_count: 2, created_at: '2026-10-08 10:00:00',
    source: 'paper', status: 'uploading', packing_list_uid: null,
    version: 7, can_delete: true, photo_cleanup_pending: false,
};
let items;
const deletionCalls = () => intakeRequest.mock.calls.filter(([, options]) => options?.method === 'DELETE');
const listCalls = () => intakeRequest.mock.calls.filter(([path]) => path.startsWith('/my-packing-lists?'));
const requestError = (status, message, data) => Object.assign(new Error(message), { status, data });
const showPage = () => {
    const router = createMemoryRouter([
        { path: '/upload', element: <PaperIntakeUpload /> },
        { path: '/packing-list/upload/:uid', element: <div>检查纸单详情</div> },
    ], { initialEntries: ['/upload'] });
    return render(<RouterProvider router={router} />);
};
const entryButton = mark => screen.findByRole('button', { name: `删除未完成上传 ${mark || upload.mark}` });
const openDeletion = async mark => {
    fireEvent.click(await entryButton(mark));
    return screen.findByRole('dialog', { name: '删除这份未完成上传？' });
};

beforeEach(() => {
    items = [{ ...upload }];
    localStorage.setItem('jwt', `header.${btoa(JSON.stringify({ user_id: 1, roles: ['salesperson'] }))}.signature`);
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({ matches: false, media: query,
        addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {} }) });
    intakeRequest.mockReset();
    intakeRequest.mockImplementation(async (path, options) => {
        if (path.startsWith('/my-packing-lists?')) {
            const page = Number(new URLSearchParams(path.split('?')[1]).get('page'));
            return { items: items.slice((page - 1) * 20, page * 20), total: items.length, page, page_size: 20 };
        }
        if (options?.method === 'DELETE') {
            const uid = decodeURIComponent(path.slice(1));
            items = items.filter(item => (item.intake_uid || item.uid) !== uid);
            return { deleted: true, photo_cleanup_pending: false };
        }
        throw new Error(`unexpected request ${path}`);
    });
});

afterEach(() => {
    cleanup();
    localStorage.clear();
    jest.restoreAllMocks();
});

test('cancel keeps the unfinished upload and makes no deletion request', async () => {
    showPage();
    const dialog = await openDeletion();
    expect(within(dialog).getByText(/未完成上传记录、已保存的检查内容和关联纸单原图/)).toBeInTheDocument();
    expect(within(dialog).getByText(/删除后不可恢复/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: /取\s*消/ }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(deletionCalls()).toHaveLength(0);
    expect(screen.getByRole('link', { name: '继续检查并上传' })).toHaveAttribute('href', '/packing-list/upload/intake-1');
    expect(await entryButton()).toBeEnabled();
});

test('confirmation deletes the selected intake version then refreshes the list', async () => {
    items = [{ ...upload, intake_uid: 'intake/encoded' }];
    showPage();
    const dialog = await openDeletion();
    fireEvent.click(within(dialog).getByRole('button', { name: '确认删除' }));
    await screen.findByText('未完成上传及关联原图已删除');
    expect(deletionCalls()).toEqual([['/intake%2Fencoded', { method: 'DELETE', body: { version: 7 } }]]);
    await waitFor(() => expect(listCalls()).toHaveLength(2));
    await waitFor(() => expect(screen.queryByRole('link', { name: '继续检查并上传' })).not.toBeInTheDocument());
    expect(screen.queryByText(upload.mark)).not.toBeInTheDocument();
});

test('repeated entry and confirmation clicks send one request and cannot close a pending deletion', async () => {
    let resolveDelete;
    const implementation = intakeRequest.getMockImplementation();
    intakeRequest.mockImplementation((path, options) => options?.method === 'DELETE'
        ? new Promise(resolve => { resolveDelete = resolve; }) : implementation(path, options));
    showPage();
    const entry = await entryButton();
    fireEvent.click(entry); fireEvent.click(entry);
    const dialog = await screen.findByRole('dialog', { name: '删除这份未完成上传？' });
    expect(screen.getAllByRole('dialog')).toHaveLength(1);
    const confirm = within(dialog).getByRole('button', { name: '确认删除' });
    fireEvent.click(confirm); fireEvent.click(confirm);
    expect(deletionCalls()).toHaveLength(1);
    expect(within(dialog).getByRole('button', { name: /取\s*消/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: '刷新未完成上传' })).toBeDisabled();
    expect(entry).toBeDisabled();
    expect(within(dialog).queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    items = [];
    await act(async () => { resolveDelete({ deleted: true, photo_cleanup_pending: false }); });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(deletionCalls()).toHaveLength(1);
});

test('deleting the final item on the final page loads the preceding page', async () => {
    items = Array.from({ length: 21 }, (_, index) => ({ ...upload, uid: `intake-${index}`, mark: `UPLOAD-${index}` }));
    showPage();
    await entryButton('UPLOAD-0');
    fireEvent.click(screen.getByTitle('2'));
    const dialog = await openDeletion('UPLOAD-20');
    fireEvent.click(within(dialog).getByRole('button', { name: '确认删除' }));
    expect(await entryButton('UPLOAD-0')).toBeEnabled();
    expect(listCalls().map(([path]) => Number(new URLSearchParams(path.split('?')[1]).get('page')))).toEqual([1, 2, 2, 1]);
    expect(screen.queryByText('UPLOAD-20')).not.toBeInTheDocument();
});

test.each([
    ['completed', { status: 'completed' }],
    ['confirmed', { status: 'confirmed' }],
    ['draft', { status: 'draft' }],
    ['formal packing list', { packing_list_uid: 'packing-1' }],
    ['permission denied', { can_delete: false }],
    ['permission absent', { can_delete: undefined }],
])('a %s entry cannot expose the unfinished deletion action', async (_, changes) => {
    items = [{ ...upload, ...changes }];
    showPage();
    await screen.findByText(upload.mark);
    expect(screen.queryByRole('button', { name: /删除未完成上传/ })).not.toBeInTheDocument();
    expect(deletionCalls()).toHaveLength(0);
});

test('a version conflict closes confirmation, refreshes capability and never retries automatically', async () => {
    const implementation = intakeRequest.getMockImplementation();
    intakeRequest.mockImplementation((path, options) => {
        if (options?.method === 'DELETE') {
            items = [{ ...upload, version: 8, status: 'completed', packing_list_uid: 'packing-1', can_delete: false }];
            return Promise.reject(requestError(409, '纸单已经核对完成'));
        }
        return implementation(path, options);
    });
    showPage();
    const dialog = await openDeletion();
    fireEvent.click(within(dialog).getByRole('button', { name: '确认删除' }));
    await screen.findByText('纸单已经核对完成。请核对刷新后的列表，再决定是否删除。');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() => expect(listCalls()).toHaveLength(2));
    expect(screen.queryByRole('button', { name: /删除未完成上传/ })).not.toBeInTheDocument();
    expect(deletionCalls()).toHaveLength(1);
});

test('503 cleanup failure keeps confirmation for retry and hides continuing a deleted upload', async () => {
    let firstDelete = true;
    const implementation = intakeRequest.getMockImplementation();
    intakeRequest.mockImplementation((path, options) => {
        if (options?.method === 'DELETE' && firstDelete) {
            firstDelete = false;
            items = [{ ...upload, version: 8, photo_cleanup_pending: true }];
            return Promise.reject(requestError(503, '关联原图清理失败，请重试', { deleted: true, photo_cleanup_pending: true }));
        }
        return implementation(path, options);
    });
    showPage();
    const dialog = await openDeletion();
    fireEvent.click(within(dialog).getByRole('button', { name: '确认删除' }));
    await within(dialog).findByText('关联原图清理失败，请重试');
    expect(within(dialog).getByText('记录已停用，关联原图尚未清理完成，请重试删除。')).toBeInTheDocument();
    await screen.findByText('删除尚未完成，关联原图待清理');
    expect(screen.queryByRole('link', { name: '继续检查并上传' })).not.toBeInTheDocument();
    expect(screen.queryByText('未完成上传及关联原图已删除')).not.toBeInTheDocument();
    await waitFor(() => expect(within(dialog).getByRole('button', { name: '重试删除' })).toBeEnabled());
    fireEvent.click(within(dialog).getByRole('button', { name: '重试删除' }));
    await screen.findByText('未完成上传及关联原图已删除');
    expect(deletionCalls().map(([, options]) => options.body)).toEqual([{ version: 7 }, { version: 7 }]);
    await waitFor(() => expect(screen.queryByText(upload.mark)).not.toBeInTheDocument());
});

test('a pending cleanup entry can be retried after reopening the upload page', async () => {
    items = [{ ...upload, photo_cleanup_pending: true }];
    showPage();
    const retry = await screen.findByRole('button', { name: `重试删除 ${upload.mark}` });
    expect(screen.queryByRole('link', { name: '继续检查并上传' })).not.toBeInTheDocument();
    fireEvent.click(retry);
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: '重试删除' }));
    await screen.findByText('未完成上传及关联原图已删除');
    expect(deletionCalls()).toHaveLength(1);
});

test.each([403, 500, 503, undefined])('failure status %s retains the record and confirmation until explicit retry', async status => {
    let firstDelete = true;
    const implementation = intakeRequest.getMockImplementation();
    intakeRequest.mockImplementation((path, options) => {
        if (options?.method === 'DELETE' && firstDelete) {
            firstDelete = false;
            return Promise.reject(requestError(status, '本次删除失败，请重试'));
        }
        return implementation(path, options);
    });
    showPage();
    const dialog = await openDeletion();
    fireEvent.click(within(dialog).getByRole('button', { name: '确认删除' }));
    await within(dialog).findByText('本次删除失败，请重试');
    expect(screen.getByRole('link', { name: '继续检查并上传' })).toBeInTheDocument();
    expect(listCalls()).toHaveLength(1);
    expect(deletionCalls()).toHaveLength(1);
    await waitFor(() => expect(within(dialog).getByRole('button', { name: '确认删除' })).toBeEnabled());
    fireEvent.click(within(dialog).getByRole('button', { name: '确认删除' }));
    await screen.findByText('未完成上传及关联原图已删除');
    expect(deletionCalls()).toHaveLength(2);
});

test('a list refresh failure following deletion is visible and retry reloads without deleting again', async () => {
    let listFailures = 0;
    const implementation = intakeRequest.getMockImplementation();
    intakeRequest.mockImplementation((path, options) => {
        if (options?.method === 'DELETE') listFailures = 1;
        if (path.startsWith('/my-packing-lists?') && listFailures > 0) {
            listFailures -= 1;
            return Promise.reject(new Error('未完成上传列表加载失败'));
        }
        return implementation(path, options);
    });
    showPage();
    const dialog = await openDeletion();
    fireEvent.click(within(dialog).getByRole('button', { name: '确认删除' }));
    await screen.findByText('未完成上传列表加载失败');
    fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }));
    await waitFor(() => expect(screen.queryByText('未完成上传列表加载失败')).not.toBeInTheDocument());
    expect(deletionCalls()).toHaveLength(1);
    expect(listCalls()).toHaveLength(3);
});
