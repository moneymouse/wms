import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { message, Modal } from 'antd';
import StorageManagement from './storageManagement';
import { storagePhotoRequest, storageRequest } from '../common/storageApi';
import { hasPermission, menuPermissions, routePermissions } from '../common/roleConfig';

jest.mock('../common/storageApi', () => ({
    ...jest.requireActual('../common/storageApi'), storageRequest: jest.fn(), storagePhotoRequest: jest.fn(),
}));

const initialSummary = {
    total_bytes: 1048576, total_files: 3, photo_groups: 1, pending_cleanup_files: 0, pending_cleanup_bytes: 0,
};
const packing = {
    uid: 'packing-1', intake_uid: 'intake-1', packing_list_uid: 'packing-1', detail_url: '/packing-lists/packing-1',
    list_number: 'MARK-2026-001', box_count: 4, archived: false, can_delete_photos: true, missing_photo_count: 0,
    last_shipped_at: '2026-01-01T10:00:00', days_since_shipped: 280, photo_count: 2, photo_bytes: 3072,
};
let summary;
let items;
const useRole = role => localStorage.setItem('jwt', `header.${btoa(JSON.stringify({ roles: [role] }))}.signature`);
const showPage = () => render(<MemoryRouter><StorageManagement /></MemoryRouter>);
const deleteCalls = () => storageRequest.mock.calls.filter(([, options]) => options?.method === 'DELETE');

beforeEach(() => {
    useRole('admin');
    summary = { ...initialSummary };
    items = [{ ...packing }];
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({ matches: false, media: query,
        addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {} }) });
    storageRequest.mockReset();
    storagePhotoRequest.mockReset();
    storagePhotoRequest.mockResolvedValue(new Blob(['photo'], { type: 'image/jpeg' }));
    URL.createObjectURL = jest.fn().mockImplementation(() => `blob:storage-photo-${URL.createObjectURL.mock.calls.length}`);
    URL.revokeObjectURL = jest.fn();
    storageRequest.mockImplementation(async (path, options) => {
        if (path === '/summary') return summary;
        if (path === '/packing-lists') return { items, total: items.length, page: 1, page_size: 20 };
        if (path.match(/^\/intakes\/[^/]+\/photos$/) && options?.method !== 'DELETE') return { photos: [
            { uid: 'photo-1', filename: 'paper-1.jpg', original_filename: '装箱单正面.jpg', mime_type: 'image/jpeg', missing: false },
            { uid: 'photo-2', filename: 'paper-2.jpg', original_filename: '装箱单背面.jpg', mime_type: 'image/jpeg', missing: false },
        ] };
        if (options?.method === 'DELETE') {
            items = [];
            summary = { ...summary, total_bytes: summary.total_bytes - 3072, total_files: summary.total_files - 2, photo_groups: 0 };
            return { deleted_files: 2, deleted_bytes: 3072 };
        }
        if (path === '/cleanup') return { deleted_files: 1, deleted_bytes: 1024, pending_files: 0 };
        throw new Error(`unexpected request ${path}`);
    });
});

afterEach(async () => {
    cleanup();
    await act(async () => {
        Modal.destroyAll();
        message.destroy();
        await new Promise(resolve => setTimeout(resolve, 100));
    });
    localStorage.clear();
    jest.restoreAllMocks();
});

test('the default photo list and summary request all photos without a retention filter', async () => {
    showPage();
    expect(await screen.findByRole('link', { name: packing.list_number })).toHaveAttribute('href', '/packing-lists/packing-1');
    expect(storageRequest.mock.calls.find(([path]) => path === '/summary')[1]).not.toHaveProperty('params');
    expect(storageRequest).toHaveBeenCalledWith('/packing-lists', expect.objectContaining({
        params: { page: 1, page_size: 20, q: '' },
    }));
    expect(screen.getByText('1.00 MB')).toBeInTheDocument();
    expect(screen.getByText('照片列表')).toBeInTheDocument();
    expect(screen.getByText('照片组数')).toBeInTheDocument();
    expect(screen.queryByText('符合清理条件的占用')).not.toBeInTheDocument();
    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '应用筛选' })).not.toBeInTheDocument();
});

test.each(['finance', 'salesperson', 'worker'])('role %s cannot read or clean storage', role => {
    useRole(role);
    showPage();
    expect(screen.getByText('无权访问存储管理')).toBeInTheDocument();
    expect(storageRequest).not.toHaveBeenCalled();
    expect(hasPermission([role], routePermissions['/storage-management'])).toBe(false);
    expect(hasPermission([role], menuPermissions['storage-management'])).toBe(false);
});

test('store managers can access the page and navigation entry', async () => {
    useRole('store_manager');
    showPage();
    expect(await screen.findByRole('link', { name: packing.list_number })).toBeInTheDocument();
    expect(hasPermission(['store_manager'], menuPermissions['storage-management'])).toBe(true);
});

test('pending, recent, partly shipped, confirmed and archived sources all remain visible', async () => {
    items = [
        { ...packing, uid: 'pending-intake', intake_uid: 'pending-intake', packing_list_uid: null, detail_url: null,
            list_number: 'PENDING-MARK', last_shipped_at: null, days_since_shipped: null, can_delete_photos: false,
            missing_photo_count: 1, cleanup_reason: '纸单尚未确认生成装箱单' },
        { ...packing, uid: 'recent', intake_uid: 'recent-intake', packing_list_uid: 'recent', detail_url: '/packing-lists/recent',
            list_number: 'RECENT-MARK', last_shipped_at: '2026-10-01T12:00:00', days_since_shipped: 6,
            can_delete_photos: false, cleanup_reason: '最后出货未满 90 天' },
        { ...packing, uid: 'partial', intake_uid: 'partial-intake', packing_list_uid: 'partial', detail_url: '/packing-lists/partial',
            list_number: 'PARTIAL-MARK', can_delete_photos: false, cleanup_reason: '尚未全部完成出货' },
        packing,
        { ...packing, uid: 'archived', intake_uid: 'archived-intake', packing_list_uid: 'archived', detail_url: '/packing-lists/archived',
            list_number: 'ARCHIVED-MARK', archived: true },
        { ...packing, uid: 'deleted-intake', intake_uid: 'deleted-intake', packing_list_uid: null, detail_url: null,
            list_number: 'DELETED-SOURCE-MARK', can_delete_photos: false, cleanup_reason: '来源装箱单已删除' },
    ];
    summary = { ...summary, photo_groups: 6 };
    showPage();
    await screen.findByText('PENDING-MARK');
    const pendingRow = screen.getByText('PENDING-MARK').closest('tr');
    expect(pendingRow).toHaveAttribute('data-row-key', 'pending-intake');
    expect(within(pendingRow).getByText('未生成装箱单')).toBeInTheDocument();
    expect(within(pendingRow).getByText('缺失文件 1 张')).toBeInTheDocument();
    expect(within(pendingRow).queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'RECENT-MARK' })).toHaveAttribute('href', '/packing-lists/recent');
    expect(screen.getByRole('link', { name: 'PARTIAL-MARK' })).toHaveAttribute('href', '/packing-lists/partial');
    expect(screen.getByRole('link', { name: packing.list_number })).toHaveAttribute('href', packing.detail_url);
    const archivedRow = screen.getByText('ARCHIVED-MARK').closest('tr');
    expect(within(archivedRow).getByText('已归档')).toBeInTheDocument();
    expect(within(archivedRow).queryByRole('link')).not.toBeInTheDocument();
    expect(within(archivedRow).getByRole('button', { name: '删除照片' })).toBeEnabled();
    expect(screen.getByText('DELETED-SOURCE-MARK')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: '删除照片' })).toHaveLength(6);
    for (const name of ['PENDING-MARK', 'RECENT-MARK', 'PARTIAL-MARK', 'DELETED-SOURCE-MARK']) {
        const row = screen.getByText(name).closest('tr');
        const button = within(row).getByRole('button', { name: '删除照片' });
        expect(button).toBeEnabled();
    }
    expect(deleteCalls()).toHaveLength(0);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: '查看照片' })).toHaveLength(6);
});

test.each([null, '2026-10-06T12:00:00'])('archived photos can be cleaned with shipment date %s without a detail link', async shippedAt => {
    const archived = { ...packing, uid: 'archived', intake_uid: 'archived-intake', packing_list_uid: 'archived',
        list_number: 'ARCHIVED-MARK', archived: true, box_count: 0, last_shipped_at: shippedAt,
        days_since_shipped: shippedAt ? 1 : null, can_delete_photos: true, cleanup_reason: '' };
    items = [archived];
    showPage();
    const row = (await screen.findByText('ARCHIVED-MARK')).closest('tr');
    expect(within(row).getByText('已归档')).toBeInTheDocument();
    expect(within(row).queryByRole('link')).not.toBeInTheDocument();
    fireEvent.click(within(row).getByRole('button', { name: '删除照片' }));
    const modal = await screen.findByRole('dialog');
    expect(within(modal).getByText('该装箱单已归档。')).toBeInTheDocument();
    expect(within(modal).queryByText(/最后出货时间/)).not.toBeInTheDocument();
    expect(within(modal).getByText('装箱单、箱子和财务记录会保留。')).toBeInTheDocument();
    fireEvent.click(within(modal).getByRole('button', { name: '确认删除照片' }));
    await waitFor(() => expect(storageRequest).toHaveBeenCalledWith('/intakes/archived-intake/photos', {
        method: 'DELETE', body: { days: 90 },
    }));
    await waitFor(() => expect(screen.queryByText('ARCHIVED-MARK')).not.toBeInTheDocument());
});

test('pagination preserves an unfiltered photo list query', async () => {
    const implementation = storageRequest.getMockImplementation();
    storageRequest.mockImplementation((path, options) => path === '/packing-lists'
        ? Promise.resolve({ items, total: 25, page: options.params.page, page_size: 20 }) : implementation(path, options));
    showPage();
    await screen.findByRole('link', { name: packing.list_number });
    fireEvent.click(screen.getByTitle('2'));
    await waitFor(() => expect(storageRequest).toHaveBeenCalledWith('/packing-lists', expect.objectContaining({
        params: { page: 2, page_size: 20, q: '' },
    })));
    expect(storageRequest.mock.calls.filter(([path]) => path === '/packing-lists').every(([, options]) => !('days' in options.params))).toBe(true);
});

test('search is initiated by the user and clearing it restores the entire photo list', async () => {
    showPage();
    await screen.findByRole('link', { name: packing.list_number });
    const search = screen.getByRole('searchbox', { name: '搜索装箱单唛头' });
    fireEvent.change(search, { target: { value: ' MARK / A ' } });
    expect(storageRequest.mock.calls.filter(([path]) => path === '/packing-lists')).toHaveLength(1);
    fireEvent.keyDown(search, { key: 'Enter', code: 'Enter', charCode: 13 });
    await waitFor(() => expect(storageRequest).toHaveBeenCalledWith('/packing-lists', expect.objectContaining({
        params: { page: 1, page_size: 20, q: 'MARK / A' },
    })));
    fireEvent.change(search, { target: { value: '' } });
    await waitFor(() => expect(storageRequest.mock.calls.filter(([path]) => path === '/packing-lists')).toHaveLength(3));
    expect(storageRequest.mock.calls.filter(([path]) => path === '/packing-lists').at(-1)[1].params)
        .toEqual({ page: 1, page_size: 20, q: '' });
    expect(storageRequest.mock.calls.filter(([path]) => path === '/summary').every(([, options]) => !options.params)).toBe(true);
});

test('photos are only deleted after an irreversible deletion confirmation and statistics refresh', async () => {
    showPage();
    await screen.findByRole('link', { name: packing.list_number });
    fireEvent.click(screen.getByRole('button', { name: '删除照片' }));
    const modal = await screen.findByRole('dialog');
    expect(within(modal).getByText(/删除后不可恢复/)).toBeInTheDocument();
    expect(within(modal).getByText(/最后出货时间：2026-01-01 10:00/)).toBeInTheDocument();
    expect(within(modal).getByText(/当前上传来源的全部纸单照片/)).toBeInTheDocument();
    expect(within(modal).getByText('装箱单、箱子和财务记录会保留。')).toBeInTheDocument();
    expect(deleteCalls()).toHaveLength(0);
    fireEvent.click(within(modal).getByRole('button', { name: '确认删除照片' }));
    await waitFor(() => expect(deleteCalls()).toHaveLength(1));
    expect(deleteCalls()[0]).toEqual(['/intakes/intake-1/photos', { method: 'DELETE', body: { days: 90 } }]);
    expect(await screen.findByText('暂无纸单照片')).toBeInTheDocument();
    expect(storageRequest.mock.calls.filter(([path]) => path === '/summary')).toHaveLength(2);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});

test('cancelling deletion keeps the photos', async () => {
    showPage();
    await screen.findByRole('link', { name: packing.list_number });
    fireEvent.click(screen.getByRole('button', { name: '删除照片' }));
    const modal = await screen.findByRole('dialog');
    fireEvent.click(within(modal).getByRole('button', { name: /取.*消/ }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(deleteCalls()).toHaveLength(0);
    expect(screen.getByRole('link', { name: packing.list_number })).toBeInTheDocument();
});

test.each([
    ['recent', '最后出货未满 90 天', 'packing-1', false],
    ['pending', '纸单尚未确认生成装箱单', null, false],
    ['archived-recent', '最后出货未满 90 天', 'packing-1', true],
])('source %s can be deleted after its early deletion warning', async (sourceUid, warning, packingUid, archived) => {
    items = [{ ...packing, intake_uid: sourceUid, packing_list_uid: packingUid, archived,
        can_delete_photos: true, last_shipped_at: '2026-10-06T12:00:00', days_since_shipped: 1,
        deletion_warning: warning }];
    showPage();
    await screen.findByText(packing.list_number);
    fireEvent.click(screen.getByRole('button', { name: '删除照片' }));
    const modal = await screen.findByRole('dialog');
    expect(within(modal).getByText('尚未满足照片保留期限或出货条件，仍可删除')).toBeInTheDocument();
    expect(within(modal).getByText(`${warning}。请确认现在删除。`)).toBeInTheDocument();
    expect(deleteCalls()).toHaveLength(0);
    fireEvent.click(within(modal).getByRole('button', { name: '确认删除照片' }));
    await waitFor(() => expect(deleteCalls()).toEqual([[`/intakes/${sourceUid}/photos`, { method: 'DELETE', body: { days: 90 } }]]));
    expect(await screen.findByText('暂无纸单照片')).toBeInTheDocument();
});

test('deleting one upload source preserves the other photos of the same packing list', async () => {
    items = [packing, { ...packing, intake_uid: 'intake-2' }];
    const implementation = storageRequest.getMockImplementation();
    storageRequest.mockImplementation((path, options) => {
        if (options?.method === 'DELETE') {
            items = items.filter(item => item.intake_uid !== 'intake-1');
            return Promise.resolve({ deleted_files: 2, deleted_bytes: 3072 });
        }
        return implementation(path, options);
    });
    showPage();
    await screen.findAllByRole('link', { name: packing.list_number });
    fireEvent.click(within(screen.getAllByRole('link', { name: packing.list_number })[0].closest('tr')).getByRole('button', { name: '删除照片' }));
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: '确认删除照片' }));
    await waitFor(() => expect(screen.getAllByRole('link', { name: packing.list_number })).toHaveLength(1));
    expect(deleteCalls()[0][0]).toBe('/intakes/intake-1/photos');
    expect(screen.getByRole('link', { name: packing.list_number }).closest('tr')).toHaveAttribute('data-row-key', 'intake-2');
});

test('photos can be viewed, switched and reopened by upload source with blob URLs released', async () => {
    items = [packing, { ...packing, intake_uid: 'intake-2', list_number: 'SECOND-SOURCE' }];
    showPage();
    const firstRow = (await screen.findByRole('link', { name: packing.list_number })).closest('tr');
    fireEvent.click(within(firstRow).getByRole('button', { name: '查看照片' }));
    let modal = await screen.findByRole('dialog');
    expect(await within(modal).findByRole('img', { name: '纸单照片：装箱单正面.jpg' })).toHaveAttribute('src', 'blob:storage-photo-1');
    expect(storageRequest).toHaveBeenCalledWith('/intakes/intake-1/photos', expect.objectContaining({ signal: expect.anything() }));
    expect(storagePhotoRequest).toHaveBeenCalledWith('intake-1', 'photo-1', expect.objectContaining({ signal: expect.anything() }));
    fireEvent.click(within(modal).getByRole('button', { name: '查看第2张照片' }));
    expect(await within(modal).findByRole('img', { name: '纸单照片：装箱单背面.jpg' })).toHaveAttribute('src', 'blob:storage-photo-2');
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:storage-photo-1');
    fireEvent.click(within(modal).getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:storage-photo-2');
    fireEvent.click(within(screen.getByRole('link', { name: 'SECOND-SOURCE' }).closest('tr')).getByRole('button', { name: '查看照片' }));
    modal = await screen.findByRole('dialog');
    await within(modal).findByRole('img', { name: '纸单照片：装箱单正面.jpg' });
    expect(storagePhotoRequest).toHaveBeenLastCalledWith('intake-2', 'photo-1', expect.objectContaining({ signal: expect.anything() }));
    expect(storagePhotoRequest).toHaveBeenCalledTimes(3);
});

test('photo requests that finish after switching images cannot replace the selected photo', async () => {
    let finishFirstPhoto;
    storagePhotoRequest.mockImplementationOnce(() => new Promise(resolve => { finishFirstPhoto = resolve; }));
    showPage();
    await screen.findByRole('link', { name: packing.list_number });
    fireEvent.click(screen.getByRole('button', { name: '查看照片' }));
    const modal = await screen.findByRole('dialog');
    await waitFor(() => expect(storagePhotoRequest).toHaveBeenCalledTimes(1));
    fireEvent.click(within(modal).getByRole('button', { name: '查看第2张照片' }));
    const image = await within(modal).findByRole('img', { name: '纸单照片：装箱单背面.jpg' });
    expect(storagePhotoRequest.mock.calls[0][2].signal.aborted).toBe(true);
    await act(async () => { finishFirstPhoto(new Blob(['old photo'], { type: 'image/jpeg' })); });
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(image).toHaveAttribute('src', 'blob:storage-photo-1');
});

test('a photo load failure stays visible and can be retried', async () => {
    storagePhotoRequest.mockRejectedValueOnce(new Error('照片文件不存在'));
    showPage();
    await screen.findByRole('link', { name: packing.list_number });
    fireEvent.click(screen.getByRole('button', { name: '查看照片' }));
    const modal = await screen.findByRole('dialog');
    expect(await within(modal).findByText('照片文件不存在')).toBeInTheDocument();
    fireEvent.click(within(modal).getByRole('button', { name: '重试加载照片' }));
    await within(modal).findByRole('img', { name: '纸单照片：装箱单正面.jpg' });
    expect(storagePhotoRequest).toHaveBeenCalledTimes(2);
    expect(within(modal).queryByText('照片文件不存在')).not.toBeInTheDocument();
});

test('photo list failures can be retried and missing files are explained without fetching them', async () => {
    const implementation = storageRequest.getMockImplementation();
    let photoListRequests = 0;
    storageRequest.mockImplementation((path, options) => {
        if (path === '/intakes/intake-1/photos') {
            photoListRequests += 1;
            if (photoListRequests === 1) return Promise.reject(new Error('照片目录暂时不可用'));
            return Promise.resolve({ photos: [{ uid: 'missing', filename: 'missing.jpg', missing: true }] });
        }
        return implementation(path, options);
    });
    showPage();
    await screen.findByRole('link', { name: packing.list_number });
    fireEvent.click(screen.getByRole('button', { name: '查看照片' }));
    const modal = await screen.findByRole('dialog');
    await within(modal).findByText('照片目录暂时不可用');
    fireEvent.click(within(modal).getByRole('button', { name: '重试加载照片' }));
    expect(await within(modal).findByText('照片文件已缺失，无法查看原图')).toBeInTheDocument();
    expect(storagePhotoRequest).not.toHaveBeenCalled();
});

test('backend rejection remains visible and does not remove the packing list', async () => {
    const implementation = storageRequest.getMockImplementation();
    storageRequest.mockImplementation((path, options) => options?.method === 'DELETE'
        ? Promise.reject(new Error('装箱单尚未全部完成出货')) : implementation(path, options));
    showPage();
    await screen.findByRole('link', { name: packing.list_number });
    fireEvent.click(screen.getByRole('button', { name: '删除照片' }));
    const modal = await screen.findByRole('dialog');
    fireEvent.click(within(modal).getByRole('button', { name: '确认删除照片' }));
    expect(await screen.findByText('装箱单尚未全部完成出货')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: packing.list_number })).toBeInTheDocument();
    expect(storageRequest.mock.calls.filter(([path]) => path === '/summary')).toHaveLength(1);
});

test('failed requests show real errors and can be retried without showing a false zero', async () => {
    const implementation = storageRequest.getMockImplementation();
    storageRequest.mockRejectedValue(new Error('磁盘统计服务不可用'));
    showPage();
    expect(await screen.findByText('存储数据加载失败')).toBeInTheDocument();
    expect(screen.getByText('统计：磁盘统计服务不可用')).toBeInTheDocument();
    expect(screen.getByText('列表加载失败，请点击重试加载')).toBeInTheDocument();
    expect(screen.queryByText('0 B')).not.toBeInTheDocument();
    storageRequest.mockImplementation(implementation);
    fireEvent.click(screen.getByRole('button', { name: '重试加载' }));
    expect(await screen.findByRole('link', { name: packing.list_number })).toBeInTheDocument();
    expect(screen.queryByText('存储数据加载失败')).not.toBeInTheDocument();
});

test('pending file cleanup reports remaining failures and refreshes usage', async () => {
    summary = { ...summary, pending_cleanup_files: 2, pending_cleanup_bytes: 2048 };
    const implementation = storageRequest.getMockImplementation();
    storageRequest.mockImplementation((path, options) => path === '/cleanup'
        ? Promise.resolve({ deleted_files: 0, deleted_bytes: 0, pending_files: 2 }) : implementation(path, options));
    showPage();
    fireEvent.click(await screen.findByRole('button', { name: '重试清理待清理文件' }));
    expect(await screen.findByText(/仍有 2 个文件未能清理/)).toBeInTheDocument();
    expect(storageRequest).toHaveBeenCalledWith('/cleanup', { method: 'POST' });
    await waitFor(() => expect(storageRequest.mock.calls.filter(([path]) => path === '/summary')).toHaveLength(2));
});

test('a partially failed deletion reports pending files and exposes cleanup retry', async () => {
    const implementation = storageRequest.getMockImplementation();
    storageRequest.mockImplementation((path, options) => {
        if (options?.method === 'DELETE') {
            items = [];
            summary = { ...summary, photo_groups: 0,
                pending_cleanup_files: 2, pending_cleanup_bytes: 3072 };
            return Promise.resolve({ deleted_files: 0, deleted_bytes: 0, pending_files: 2 });
        }
        return implementation(path, options);
    });
    showPage();
    await screen.findByRole('link', { name: packing.list_number });
    fireEvent.click(screen.getByRole('button', { name: '删除照片' }));
    const modal = await screen.findByRole('dialog');
    fireEvent.click(within(modal).getByRole('button', { name: '确认删除照片' }));
    expect(await screen.findByText(/仍有 2 个文件等待清理/)).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: '重试清理待清理文件' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: packing.list_number })).not.toBeInTheDocument();
});

test('restores submitted storage search and page directly from the URL', async () => {
    const filters = { page: 2, page_size: 20, q: '恢复唛头' };
    const implementation = storageRequest.getMockImplementation();
    storageRequest.mockImplementation((path, options) => path === '/packing-lists'
        ? Promise.resolve({ items, total: 41, page: options.params.page, page_size: 20 })
        : implementation(path, options));
    render(<MemoryRouter initialEntries={[`/storage-management?storage_filters=${encodeURIComponent(JSON.stringify(filters))}`]}><StorageManagement /></MemoryRouter>);
    await screen.findByRole('link', { name: packing.list_number });
    expect(screen.getByLabelText('搜索装箱单唛头')).toHaveValue('恢复唛头');
    expect(storageRequest).toHaveBeenCalledWith('/packing-lists', expect.objectContaining({ params: filters }));
});
