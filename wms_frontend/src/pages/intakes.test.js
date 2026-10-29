import React from 'react';
import fs from 'fs';
import path from 'path';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { PaperIntakeUploadDetail, PaperIntakeUpload } from './intakes';
import { getIntakeRoles, normalizeIntakeDraft, validateIntakeDraft } from '../common/intakeApi';

jest.setTimeout(15000);

const initialRecord = {
    uid: 'intake-1', submitted_by_name: '回传人甲', created_at: '2026-10-01 10:00:00',
    display_name: 'MARK-1', mark_hint: '', note: '', status: 'pending', version: 1,
    photos: [{ uid: 'photo-1', filename: 'MARK-1-1.jpg', original_filename: 'paper.jpg' }],
    draft_is_manual: true,
    draft: { mark: 'MARK-1', operator_name: '张师傅', boxes: [{ box_number: '1', item_name: '鞋子', count: 2, weight: 3.5, worker_ids: [1] }] },
    recognition_status: 'succeeded', recognition_result: null,
};
const candidate = { mark: 'OCR-MARK', operator_name: '李师傅', worker_ids: [2], boxes: [{ box_number: '2', item_name: '帽子', count: 4, weight: 1.2 }], warnings: ['请核对重量'] };
let record;
let failConfirm;
let failSave;
const response = data => ({ ok: true, json: async () => ({ code: 200, data }) });
const mutationCalls = action => global.fetch.mock.calls.filter(([url, options]) => String(url).endsWith(`/${action}`) && options.method !== 'GET');

function renderPage(initialPath = '/packing-list/upload/intake-1', onSubmitted) {
    const router = createMemoryRouter([
        { path: '/packing-list/upload/:uid', element: <PaperIntakeUploadDetail /> },
        { path: '/upload', element: <PaperIntakeUpload onSubmitted={onSubmitted} /> },
        { path: '/packing-lists', element: <div>装箱单列表</div> },
        { path: '/packing-lists/:uid', element: <div>装箱单详情</div> },
    ], { initialEntries: [initialPath] });
    render(<RouterProvider router={router} />);
    return router;
}

beforeEach(() => {
    record = JSON.parse(JSON.stringify(initialRecord)); failConfirm = false; failSave = false;
    localStorage.setItem('jwt', `header.${btoa(JSON.stringify({ roles: ['admin'] }))}.signature`);
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({ matches: false, media: query, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {} }) });
    URL.createObjectURL = jest.fn(() => 'blob:paper'); URL.revokeObjectURL = jest.fn();
    global.fetch = jest.fn(async (rawUrl, options = {}) => {
        const url = String(rawUrl);
        if (url.endsWith('/workers')) return response([{ id: 1, name: '张师傅' }, { id: 2, name: '李师傅' }, { id: 3, name: '王师傅' }]);
        if (url.includes('/goods-names?lang=cn')) return response([{ name: '运动鞋', category: '鞋包类' }, { name: '帽子', category: '服装类' }]);
        if (url.includes('/photos/')) return { ok: true, blob: async () => new Blob(['paper']) };
        if (url.includes('/my-packing-lists?')) return response({ items: [], total: 0, page_size: 20 });
        if (url.endsWith('/draft')) {
            if (failSave) return { ok: false, json: async () => ({ code: 409, msg: '草稿保存失败' }) };
            const body = JSON.parse(options.body);
            record = { ...record, draft: body.draft, draft_is_manual: true, version: record.version + 1 };
            return response(record);
        }
        if (url.endsWith('/recognize')) {
            record = { ...record, recognition_status: 'running', version: record.version + 1 };
            return response(record);
        }
        if (url.endsWith('/confirm')) {
            if (failConfirm) return { ok: false, json: async () => ({ code: 409, msg: '纸单已被更新，请重新加载' }) };
            record = { ...record, status: 'confirmed', packing_list_uid: 'packing-1', version: record.version + 1 };
            return response(record);
        }
        return response(record);
    });
});

afterEach(() => { localStorage.clear(); jest.restoreAllMocks(); jest.useRealTimers(); });

test('workers check recognition before upload completion and finish only after acknowledging the paper', async () => {
    jest.useFakeTimers();
    localStorage.setItem('jwt', `header.${btoa(JSON.stringify({ roles: ['worker'] }))}.signature`);
    record = { ...record, recognition_status: 'running', draft_is_manual: false, draft: { mark: '', boxes: [] } };
    const onSubmitted = jest.fn();
    const view = renderPage('/upload', onSubmitted);
    expect(screen.getByLabelText('唛头提示')).not.toBeVisible();
    const photo = new File(['image'], 'paper.jpg', { type: 'image/jpeg' });
    fireEvent.change(screen.getByLabelText('纸单照片'), { target: { files: [photo] } });
    fireEvent.click(screen.getByRole('button', { name: /识别照片并检查/ }));
    await screen.findByText('正在识别');
    const call = global.fetch.mock.calls.find(([, options]) => options.method === 'POST');
    expect(call[1].body.getAll('photos')).toEqual([photo]);
    expect(call[1].body.has('mark_hint')).toBe(false);
    expect(call[1].headers['x-token']).toEqual(localStorage.getItem('jwt'));
    expect(call[1].headers).not.toHaveProperty('Content-Type');
    expect(onSubmitted).not.toHaveBeenCalled();
    expect(screen.queryByText('照片已提交')).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /我已对照纸质单/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /核对完成并上传/ })).toBeDisabled();
    record = { ...record, version: 2, recognition_status: 'succeeded', recognition_result: candidate };
    await act(async () => { jest.advanceTimersByTime(3000); });
    await screen.findByDisplayValue('OCR-MARK');
    expect(screen.getByRole('button', { name: /核对完成并上传/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('第1箱重量'), { target: { value: '2.5' } });
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    fireEvent.click(screen.getByRole('button', { name: /核对完成并上传/ }));
    await screen.findByRole('link', { name: '查看装箱单' });
    expect(JSON.parse(mutationCalls('draft')[0][1].body)).toMatchObject({ draft: { mark: 'OCR-MARK', boxes: [{ weight: 2.5 }] } });
    expect(JSON.parse(mutationCalls('confirm')[0][1].body)).toEqual({ version: 3, reviewed: true });
    expect(onSubmitted).toHaveBeenCalledTimes(1);
    expect(onSubmitted).toHaveBeenCalledWith(expect.objectContaining({ status: 'confirmed', packing_list_uid: 'packing-1' }));
    expect(view.state.location.pathname).toBe('/upload');
    expect(screen.getByText('已核对')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /上传下一份/ }));
    expect(screen.getByRole('button', { name: /识别照片并检查/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /核对完成并上传/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/已选择/)).not.toBeInTheDocument();
});

test('workers download a real PDF template using authenticated API access from the upload page', async () => {
    localStorage.setItem('jwt', `header.${btoa(JSON.stringify({ roles: ['worker'] }))}.signature`);
    const pdf = new Blob(['%PDF-1.4\nA4 paper template'], { type: 'application/pdf' });
    const fetchImpl = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => String(url).endsWith('/template') ? Promise.resolve({ ok: true, headers: { get: () => 'application/pdf' }, blob: async () => pdf }) : fetchImpl(url, options));
    const downloadClick = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const view = renderPage('/upload');
    fireEvent.click(screen.getByRole('button', { name: '下载空白装箱单模板' }));
    await waitFor(() => expect(downloadClick).toHaveBeenCalledTimes(1));
    expect(global.fetch).toHaveBeenCalledWith(expect.stringMatching(/\/intakes\/template$/), {
        headers: expect.objectContaining({ 'x-token': localStorage.getItem('jwt'), 'x-time': expect.anything() }),
    });
    expect(URL.createObjectURL).toHaveBeenCalledWith(pdf);
    expect(downloadClick.mock.instances[0].download).toBe('paper-packing-list-a4.pdf');
    expect(downloadClick.mock.instances[0].href).toBe('blob:paper');
    expect(view.state.location.pathname).toBe('/upload');
});

test.each([
    ['HTTP error', { ok: false, json: async () => ({ msg: '模板下载失败，请重试' }) }, '模板下载失败，请重试'],
    ['empty PDF', { ok: true, headers: { get: () => 'application/pdf' }, blob: async () => new Blob([], { type: 'application/pdf' }) }, '模板文件为空，请重试'],
    ['HTML login response', { ok: true, headers: { get: () => 'text/html' }, blob: async () => new Blob(['<html>Login</html>'], { type: 'text/html' }) }, '模板文件不可用，请重试'],
])('template download rejects %s without producing an empty or invalid download', async (_, templateResponse, errorText) => {
    const fetchImpl = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => String(url).endsWith('/template') ? Promise.resolve(templateResponse) : fetchImpl(url, options));
    const downloadClick = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    renderPage('/upload');
    fireEvent.click(screen.getByRole('button', { name: '下载空白装箱单模板' }));
    expect(await screen.findByText(errorText)).toBeInTheDocument();
    expect(downloadClick).not.toHaveBeenCalled();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole('button', { name: '下载空白装箱单模板' })).not.toBeDisabled());
});

test('camera and picker append photos, preview them and submit only retained photos', async () => {
    renderPage('/upload');
    const camera = screen.getByLabelText('拍照照片');
    const picker = screen.getByLabelText('纸单照片');
    expect(camera).toHaveAttribute('capture', 'environment');
    expect(camera).not.toHaveAttribute('multiple');
    expect(picker).toHaveAttribute('multiple');
    const first = new File(['first'], 'first.jpg', { type: 'image/jpeg' });
    const second = new File(['second'], 'second.jpg', { type: 'image/jpeg' });
    const third = new File(['third'], 'third.jpg', { type: 'image/jpeg' });
    fireEvent.change(camera, { target: { files: [first] } });
    fireEvent.change(picker, { target: { files: [second, third] } });
    expect(screen.getByText('已选择 3 / 8 张，合计 0.0 MB')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '预览第1张照片' }));
    const dialog = await screen.findByRole('dialog', { name: 'first.jpg' });
    expect(within(dialog).getByRole('img', { name: 'first.jpg预览' })).toHaveAttribute('src', 'blob:paper');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }));
    fireEvent.click(screen.getByRole('button', { name: '移除第2张照片' }));
    fireEvent.click(screen.getByRole('button', { name: /识别照片并检查/ }));
    await screen.findByRole('heading', { name: /检查纸质装箱单/ });
    const call = global.fetch.mock.calls.find(([, options]) => options.method === 'POST');
    expect(call[1].body.getAll('photos')).toEqual([first, third]);
});

test('photo staging failure preserves selected files and can be retried before checking', async () => {
    let failUpload = true;
    const fetchImpl = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options = {}) => String(url).endsWith('/intakes') && options.method === 'POST' && failUpload
        ? Promise.resolve({ ok: false, json: async () => ({ code: 503, msg: '照片上传失败，请重试' }) }) : fetchImpl(url, options));
    const onSubmitted = jest.fn();
    renderPage('/upload', onSubmitted);
    const photo = new File(['image'], 'retain.jpg', { type: 'image/jpeg' });
    fireEvent.change(screen.getByLabelText('纸单照片'), { target: { files: [photo] } });
    fireEvent.click(screen.getByRole('button', { name: /识别照片并检查/ }));
    await screen.findByText('照片上传失败，请重试');
    expect(screen.getByText('已选择 1 / 8 张，合计 0.0 MB')).toBeInTheDocument();
    expect(onSubmitted).not.toHaveBeenCalled();
    failUpload = false;
    await waitFor(() => expect(screen.getByRole('button', { name: /识别照片并检查/ })).not.toHaveClass('ant-btn-loading'));
    fireEvent.click(screen.getByRole('button', { name: /识别照片并检查/ }));
    await screen.findByDisplayValue('MARK-1');
    const uploads = global.fetch.mock.calls.filter(([url, options]) => String(url).endsWith('/intakes') && options.method === 'POST');
    expect(uploads).toHaveLength(2);
    expect(uploads[1][1].body.getAll('photos')).toEqual([photo]);
    expect(onSubmitted).not.toHaveBeenCalled();
});

test('photo count and size limits reject additions without removing the current selection', () => {
    renderPage('/upload');
    const picker = screen.getByLabelText('纸单照片');
    const photos = Array.from({ length: 9 }, (_, i) => new File(['image'], `photo-${i}.jpg`, { type: 'image/jpeg' }));
    fireEvent.change(picker, { target: { files: photos.slice(0, 7) } });
    fireEvent.change(picker, { target: { files: photos.slice(7) } });
    expect(screen.getByText('每份纸单最多选择 8 张照片，请移除部分照片后再添加')).toBeInTheDocument();
    const large = new File(['image'], 'large.jpg', { type: 'image/jpeg' });
    Object.defineProperty(large, 'size', { value: 10 * 1024 * 1024 + 1 });
    fireEvent.change(picker, { target: { files: [large] } });
    expect(screen.getByText('每张照片不能超过 10MB，请选择较小的图片')).toBeInTheDocument();
    expect(screen.getByText('已选择 7 / 8 张，合计 0.0 MB')).toBeInTheDocument();
});

test('total upload size stays below twenty-four MB', () => {
    renderPage('/upload');
    const files = [10, 10, 5].map((size, i) => {
        const file = new File(['image'], `${i}.jpg`, { type: 'image/jpeg' });
        Object.defineProperty(file, 'size', { value: size * 1024 * 1024 });
        return file;
    });
    fireEvent.change(screen.getByLabelText('纸单照片'), { target: { files: files.slice(0, 2) } });
    fireEvent.change(screen.getByLabelText('纸单照片'), { target: { files: files.slice(2) } });
    expect(screen.getByText('照片合计不能超过 24MB，请移除部分照片或选择较小的图片')).toBeInTheDocument();
    expect(screen.getByText('已选择 2 / 8 张，合计 20.0 MB')).toBeInTheDocument();
});

test('all uploader roles can resume their own unfinished paper through the creation page', async () => {
    localStorage.setItem('jwt', `header.${btoa(JSON.stringify({ roles: ['salesperson'] }))}.signature`);
    const fetchImpl = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => String(url).includes('/my-packing-lists?') ? Promise.resolve(response({ items: [{ uid: 'intake-1', mark: 'MY-UPLOAD', box_count: 2, created_at: '2026-10-01 10:00:00' }], total: 21 })) : fetchImpl(url, options));
    const view = renderPage('/upload');
    const section = await screen.findByRole('region', { name: '我的未完成上传' });
    expect(await within(section).findByRole('link', { name: '继续检查并上传' })).toHaveAttribute('href', '/packing-list/upload/intake-1');
    fireEvent.click(within(section).getByTitle('2'));
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => String(url).includes('status=uploading&page=2&page_size=20'))).toBe(true));
    fireEvent.click(await within(section).findByRole('link', { name: '继续检查并上传' }));
    await screen.findByDisplayValue('MARK-1');
    expect(view.state.location.pathname).toBe('/packing-list/upload/intake-1');
    expect(screen.queryByText('待核对纸质单')).not.toBeInTheDocument();
});

test('owner access denied by the server cannot expose another uploader paper or complete it', async () => {
    const fetchImpl = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => String(url).endsWith('/intakes/intake-1') ? Promise.resolve({ ok: false, json: async () => ({ code: 403, msg: '仅上传者可继续检查此纸单' }) }) : fetchImpl(url, options));
    renderPage();
    await screen.findByText('仅上传者可继续检查此纸单');
    expect(screen.queryByLabelText('第1箱品名与件数')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /核对完成并上传/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '批量修改品名' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '批量修改操作人员' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '批量修改备注' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('第1箱备注')).not.toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/photos/'))).toBe(false);
    expect(mutationCalls('confirm')).toHaveLength(0);
});

test('untouched first review puts recognition straight into the editable table with matched workers', async () => {
    record = { ...record, draft_is_manual: false, draft: { mark: '', boxes: [] }, recognition_result: { ...candidate, boxes: [{ ...candidate.boxes[0], remark: '纸单写明易碎' }] }, recognition_status: 'needs_review' };
    renderPage();
    await screen.findByDisplayValue('OCR-MARK');
    expect(screen.getByLabelText('第1箱品名与件数')).toHaveValue('帽子 x 4');
    expect(screen.getByLabelText('第1箱备注')).toHaveValue('纸单写明易碎');
    expect(screen.getByText('李师傅')).toBeInTheDocument();
    expect(screen.queryByText('识别候选内容')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /填入核对表/ })).not.toBeInTheDocument();
    expect(mutationCalls('draft')).toHaveLength(0);
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: /核对完成并上传/ })).not.toBeDisabled());
});

test('an existing saved manual draft stays authoritative over recognition', async () => {
    record.draft.boxes[0].remark = '历史草稿备注';
    record.recognition_result = { ...candidate, boxes: [{ ...candidate.boxes[0], remark: '识别备注' }] };
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    expect(screen.getByLabelText('第1箱品名与件数')).toHaveValue('鞋子 x 2');
    expect(screen.getByLabelText('第1箱备注')).toHaveValue('历史草稿备注');
    expect(screen.getByText('张师傅')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('OCR-MARK')).not.toBeInTheDocument();
});

test('a duplicate recognized mark shows the date suffix and accepts the final mark returned at confirmation', async () => {
    record = { ...record, draft_is_manual: false, draft: { mark: '', boxes: [] }, recognition_result: { ...candidate, mark: 'OCR-MARK-20261007', original_mark: 'OCR-MARK' } };
    const fetchImpl = global.fetch.getMockImplementation();
    global.fetch.mockImplementation(async (url, options) => {
        if (String(url).endsWith('/confirm')) {
            record = { ...record, status: 'confirmed', packing_list_uid: 'packing-1', version: record.version + 1, display_name: 'OCR-MARK-20261007-2', draft: { ...record.draft, mark: 'OCR-MARK-20261007-2' } };
            return response(record);
        }
        return fetchImpl(url, options);
    });
    renderPage();
    await screen.findByDisplayValue('OCR-MARK-20261007');
    expect(screen.getByText('原唛头 OCR-MARK 已存在，已自动添加日期尾数。')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: /核对完成并上传/ })).not.toBeDisabled());
    fireEvent.click(screen.getByRole('button', { name: /核对完成并上传/ }));
    await screen.findByRole('link', { name: '查看装箱单' });
    expect(JSON.parse(mutationCalls('draft')[0][1].body).draft.mark).toBe('OCR-MARK-20261007');
    expect(screen.getByLabelText('唛头')).toHaveValue('OCR-MARK-20261007-2');
    expect(screen.getByLabelText('唛头')).toBeDisabled();
});

test('an explicitly saved empty draft stays empty despite recognition', async () => {
    record = { ...record, draft_is_manual: true, draft: { mark: '', operator_name: '', worker_ids: [], boxes: [] }, recognition_result: candidate };
    renderPage();
    await screen.findByLabelText('唛头');
    expect(screen.getByLabelText('唛头')).toHaveValue('');
    expect(screen.queryByLabelText('第1箱品名与件数')).not.toBeInTheDocument();
    expect(screen.queryByText('李师傅')).not.toBeInTheDocument();
});

test('recognition finishing while the reviewer has not edited auto-fills the table', async () => {
    jest.useFakeTimers();
    record = { ...record, draft_is_manual: false, draft: { mark: '', boxes: [] }, recognition_status: 'running' };
    renderPage();
    await screen.findByText('正在识别');
    record = { ...record, version: 2, recognition_status: 'succeeded', recognition_result: candidate };
    await act(async () => { jest.advanceTimersByTime(3000); });
    expect(await screen.findByDisplayValue('OCR-MARK')).toBeInTheDocument();
    expect(screen.getByLabelText('第1箱品名与件数')).toHaveValue('帽子 x 4');
});

test('recognition finishing never replaces unsaved local edits', async () => {
    jest.useFakeTimers();
    record = { ...record, draft_is_manual: false, draft: { mark: '', boxes: [] }, recognition_status: 'running' };
    renderPage();
    await screen.findByText('正在识别');
    fireEvent.change(screen.getByLabelText('唛头'), { target: { value: 'HUMAN-EDIT' } });
    record = { ...record, version: 2, recognition_status: 'succeeded', recognition_result: candidate };
    await act(async () => { jest.advanceTimersByTime(3000); });
    await screen.findByText('可以核对');
    expect(screen.getByLabelText('唛头')).toHaveValue('HUMAN-EDIT');
    expect(screen.queryByLabelText('第1箱品名与件数')).not.toBeInTheDocument();
});

test('doubt messages use one bounded scroll region and concise list items', async () => {
    record.recognition_result = { ...candidate, warnings: Array.from({ length: 15 }, (_, i) => `疑点 ${i + 1}`) };
    renderPage();
    const region = await screen.findByRole('region', { name: '识别疑点列表' });
    expect(screen.getByText('15 项')).toBeInTheDocument();
    expect(within(region).getAllByRole('listitem')).toHaveLength(15);
    expect(within(region).queryAllByRole('alert')).toHaveLength(0);
    expect(region).toHaveClass('warningScroll');
    const css = fs.readFileSync(path.join(__dirname, 'intakes.module.css'), 'utf8');
    expect(css).toMatch(/\.warningScroll\s*\{[^}]*height:\s*132px;[^}]*overflow-y:\s*auto;/);
});

test('the primary completion action requires a fresh acknowledgement and uses the saved version', async () => {
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    const mainAction = screen.getByRole('button', { name: /核对完成并上传/ });
    const acknowledgement = screen.getByRole('checkbox', { name: /我已对照纸质单/ });
    expect(mainAction).toHaveClass('ant-btn-primary');
    expect(mainAction).toBeDisabled();
    fireEvent.click(acknowledgement);
    expect(mainAction).not.toBeDisabled();
    fireEvent.change(screen.getByLabelText('唛头'), { target: { value: 'EDITED-MARK' } });
    expect(acknowledgement).not.toBeChecked();
    expect(mainAction).toBeDisabled();
    fireEvent.click(acknowledgement);
    fireEvent.click(mainAction);
    await screen.findByRole('link', { name: '查看装箱单' });
    expect(JSON.parse(mutationCalls('draft')[0][1].body)).toMatchObject({ version: 1, draft: { mark: 'EDITED-MARK', boxes: [{ worker_ids: [1] }] } });
    expect(JSON.parse(mutationCalls('confirm')[0][1].body)).toEqual({ version: 2, reviewed: true });
    expect(screen.getByLabelText('唛头')).toBeDisabled();
});

test('save failure keeps edits and does not finish upload', async () => {
    failSave = true;
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    fireEvent.change(screen.getByLabelText('唛头'), { target: { value: 'UNSAVED' } });
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    fireEvent.click(screen.getByRole('button', { name: /核对完成并上传/ }));
    await screen.findByText('草稿保存失败');
    expect(mutationCalls('confirm')).toHaveLength(0);
    expect(screen.getByLabelText('唛头')).toHaveValue('UNSAVED');
    expect(screen.queryByRole('link', { name: '查看装箱单' })).not.toBeInTheDocument();
});

test('confirmation failure permits retry with the latest saved version', async () => {
    failConfirm = true;
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    fireEvent.change(screen.getByLabelText('唛头'), { target: { value: 'SAVED-EDIT' } });
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    fireEvent.click(screen.getByRole('button', { name: /核对完成并上传/ }));
    await screen.findByText('纸单已被更新，请重新加载');
    expect(screen.queryByRole('link', { name: '查看装箱单' })).not.toBeInTheDocument();
    failConfirm = false;
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    fireEvent.click(screen.getByRole('button', { name: /核对完成并上传/ }));
    await screen.findByRole('link', { name: '查看装箱单' });
    expect(mutationCalls('draft')).toHaveLength(1);
    expect(mutationCalls('confirm')).toHaveLength(2);
    expect(JSON.parse(mutationCalls('confirm')[1][1].body)).toEqual({ version: 2, reviewed: true });
});

test('unknown handwritten names require choosing real approved workers before confirmation', async () => {
    record = { ...record, draft_is_manual: false, draft: { mark: '', boxes: [] }, recognition_result: { ...candidate, operator_name: '纸上未知姓名', worker_ids: [] } };
    renderPage();
    await screen.findByDisplayValue('OCR-MARK');
    expect(screen.getByText(/纸面署名：纸上未知姓名/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /核对完成并上传/ })).toBeDisabled();
    await waitFor(() => expect(screen.getByRole('combobox', { name: '第1箱实际操作人员' })).not.toBeDisabled());
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '第1箱实际操作人员' }));
    fireEvent.click(await screen.findByText('王师傅'));
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    expect(screen.getByRole('button', { name: /核对完成并上传/ })).not.toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: /保存检查进度/ }));
    await waitFor(() => expect(mutationCalls('draft')).toHaveLength(1));
    expect(JSON.parse(mutationCalls('draft')[0][1].body).draft).toMatchObject({ operator_name: '纸上未知姓名', boxes: [{ worker_ids: [3] }] });
});

test('missing or inactive worker IDs block confirmation', async () => {
    record.draft.boxes[0].worker_ids = [99];
    renderPage();
    await screen.findByText('人员 99（请重新选择）');
    expect(screen.getByRole('button', { name: /核对完成并上传/ })).toBeDisabled();
    expect(await screen.findByText(/存在已停用或未审核的人员/)).toBeInTheDocument();
});

test('approved workers with the same name are distinguished by their real IDs', async () => {
    const fetchImpl = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => String(url).endsWith('/workers') ? Promise.resolve(response([{ id: 1, name: '张师傅' }, { id: 2, name: '张师傅' }])) : fetchImpl(url, options));
    renderPage();
    await screen.findByText('张师傅 · ID 1');
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '第1箱实际操作人员' }));
    fireEvent.click(await screen.findByText('张师傅 · ID 2'));
    fireEvent.click(screen.getByRole('button', { name: /保存检查进度/ }));
    await waitFor(() => expect(mutationCalls('draft')).toHaveLength(1));
    expect(JSON.parse(mutationCalls('draft')[0][1].body).draft.boxes[0].worker_ids).toEqual([1, 2]);
});

test('partial drafts save without a worker binding or complete box fields', async () => {
    record.draft.boxes[0].worker_ids = [];
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    fireEvent.change(screen.getByLabelText('唛头'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: /保存检查进度/ }));
    await waitFor(() => expect(mutationCalls('draft')).toHaveLength(1));
    expect(JSON.parse(mutationCalls('draft')[0][1].body).draft).toMatchObject({ mark: '', boxes: [{ worker_ids: [] }] });
    expect(screen.getByRole('button', { name: /核对完成并上传/ })).toBeDisabled();
});

test.each([
    ['品名', '批量品名', 'LOCAL-NAME', '第1箱品名与件数', '鞋子 x 2'],
    ['备注', '批量备注', 'LOCAL-REMARK', '第1箱备注', ''],
])('polling detects concurrent saved edits while preserving local content and locking bulk %s', async (field, bulkLabel, proposedValue, boxLabel, unchangedValue) => {
    jest.useFakeTimers();
    record.recognition_status = 'running';
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    fireEvent.change(screen.getByLabelText('唛头'), { target: { value: 'LOCAL' } });
    fireEvent.click(screen.getByRole('checkbox', { name: '选择第1箱' }));
    fireEvent.click(screen.getByRole('button', { name: `批量修改${field}` }));
    fireEvent.change(screen.getByLabelText(bulkLabel), { target: { value: proposedValue } });
    record = { ...record, version: 2, draft: { ...record.draft, mark: 'OTHER' } };
    await act(async () => { jest.advanceTimersByTime(3000); });
    await screen.findByText('纸单已在其他页面更新，请重新加载后继续。当前检查内容已保留。');
    expect(screen.getByLabelText('唛头')).toHaveValue('LOCAL');
    expect(screen.getByRole('button', { name: /保存检查进度/ })).toBeDisabled();
    expect(screen.getByLabelText(bulkLabel)).toBeDisabled();
    expect(screen.getByRole('button', { name: '应用到所选箱子' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '批量修改操作人员' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '批量修改备注' })).toBeDisabled();
    expect(screen.getByLabelText('第1箱备注')).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '应用到所选箱子' }));
    expect(screen.getByLabelText(boxLabel)).toHaveValue(unchangedValue);
});

test('a poll started before saving cannot overwrite the saved review', async () => {
    jest.useFakeTimers();
    record.recognition_status = 'running';
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    const fetchImpl = global.fetch.getMockImplementation();
    const stale = { ...record, recognition_status: 'failed', recognition_error: '旧请求' };
    let resolvePoll;
    global.fetch.mockImplementation((url, options = {}) => String(url).endsWith('/intakes/intake-1') && !options.method ? new Promise(resolve => { resolvePoll = resolve; }) : fetchImpl(url, options));
    await act(async () => { jest.advanceTimersByTime(3000); });
    fireEvent.change(screen.getByLabelText('唛头'), { target: { value: 'SAVED-MARK' } });
    fireEvent.click(screen.getByRole('button', { name: /保存检查进度/ }));
    await waitFor(() => expect(mutationCalls('draft')).toHaveLength(1));
    await act(async () => { resolvePoll(response(stale)); });
    expect(screen.getByLabelText('唛头')).toHaveValue('SAVED-MARK');
    expect(screen.queryByText('旧请求')).not.toBeInTheDocument();
});

test('failed recognition offers reviewer retry and photos download under their paper name', async () => {
    record.recognition_status = 'failed';
    renderPage();
    await screen.findByRole('img', { name: 'MARK-1-1.jpg' });
    expect(screen.getByRole('link', { name: '下载照片' })).toHaveAttribute('download', 'MARK-1-1.jpg');
    fireEvent.click(screen.getByRole('button', { name: /重试识别/ }));
    await screen.findByText('正在识别');
    expect(mutationCalls('recognize')).toHaveLength(1);
});

test('reloading locks review fields and ignores edits and confirmation until its delayed response arrives', async () => {
    failSave = true;
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    fireEvent.change(screen.getByLabelText('唛头'), { target: { value: 'DISCARD-ME' } });
    fireEvent.click(screen.getByRole('button', { name: /保存检查进度/ }));
    await screen.findByText('草稿保存失败');
    const fetchImpl = global.fetch.getMockImplementation();
    let resolveReload;
    global.fetch.mockImplementation((url, options = {}) => String(url).endsWith('/intakes/intake-1') && !options.method
        ? new Promise(resolve => { resolveReload = resolve; }) : fetchImpl(url, options));
    fireEvent.click(screen.getByRole('button', { name: /重新加载/ }));
    const dialog = await screen.findByRole('dialog', { name: '重新加载纸单' });
    fireEvent.click(within(dialog).getByRole('button', { name: /放弃修改并重新加载/ }));
    expect(screen.getByLabelText('唛头')).toBeDisabled();
    expect(screen.getByLabelText('第1箱品名与件数')).toBeDisabled();
    expect(screen.getByLabelText('第1箱备注')).toBeDisabled();
    expect(screen.getByRole('combobox', { name: '第1箱实际操作人员' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: /我已对照纸质单/ })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: '全选箱子' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: '选择第1箱' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '批量修改品名' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '批量修改操作人员' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '批量修改备注' })).toBeDisabled();
    expect(screen.getByRole('button', { name: /核对完成并上传/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('唛头'), { target: { value: 'EDIT-DURING-RELOAD' } });
    fireEvent.change(screen.getByLabelText('第1箱备注'), { target: { value: 'EDIT-DURING-RELOAD' } });
    fireEvent.click(screen.getByLabelText('第1箱品名与件数'));
    expect(screen.queryByRole('dialog', { name: '第1箱商品明细' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /核对完成并上传/ }));
    expect(screen.getByLabelText('唛头')).toHaveValue('DISCARD-ME');
    expect(screen.getByLabelText('第1箱品名与件数')).toHaveValue('鞋子 x 2');
    expect(screen.getByLabelText('第1箱备注')).toHaveValue('');
    expect(mutationCalls('confirm')).toHaveLength(0);
    await act(async () => { resolveReload(response({ ...record, draft: { ...record.draft, mark: 'SERVER-MARK' } })); });
    expect(await screen.findByDisplayValue('SERVER-MARK')).not.toBeDisabled();
    expect(screen.getByRole('checkbox', { name: /我已对照纸质单/ })).not.toBeChecked();
    fireEvent.change(screen.getByLabelText('唛头'), { target: { value: 'AFTER-RELOAD' } });
    expect(screen.getByLabelText('唛头')).toHaveValue('AFTER-RELOAD');
});

test('unsaved human edits block navigation and browser unload', async () => {
    const view = renderPage();
    await screen.findByDisplayValue('MARK-1');
    fireEvent.change(screen.getByLabelText('唛头'), { target: { value: 'UNSAVED' } });
    const event = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    fireEvent.click(screen.getByRole('link', { name: '返回装箱单列表' }));
    const dialog = await screen.findByRole('dialog', { name: '有未保存的内容' });
    expect(view.state.location.pathname).toBe('/packing-list/upload/intake-1');
    fireEvent.click(within(dialog).getByRole('button', { name: /继续编辑/ }));
    expect(screen.getByLabelText('唛头')).toHaveValue('UNSAVED');
});

test('role compatibility, box limits and real worker bindings normalize and validate', () => {
    localStorage.setItem('jwt', `header.${btoa(JSON.stringify({ roles: 'worker', role: 'clerk' }))}.signature`);
    expect(getIntakeRoles()).toEqual(['worker', 'clerk']);
    expect(normalizeIntakeDraft({ worker_ids: ['1', 1, 0, null, 'x', 2], boxes: [{}] }).boxes[0].worker_ids).toEqual([1, 2]);
    expect(validateIntakeDraft(initialRecord.draft)).toBe('');
    expect(validateIntakeDraft({ ...initialRecord.draft, boxes: [{ ...initialRecord.draft.boxes[0], worker_ids: [] }] })).toContain('至少一名');
    expect(validateIntakeDraft({ ...initialRecord.draft, boxes: [{ ...initialRecord.draft.boxes[0], worker_ids: [1, 2, 3, 4, 5] }] })).toContain('最多选择 4');
    expect(validateIntakeDraft({ ...initialRecord.draft, boxes: [{ ...initialRecord.draft.boxes[0], box_number: '2147483648' }] })).toContain('不能超过 2147483647');
});

const threeBoxes = [
    { box_number: '1', item_name: '鞋子', count: 2, weight: 3.5, worker_ids: [1] },
    { box_number: '2', item_name: '帽子', count: 4, weight: 1.2, worker_ids: [2] },
    { box_number: '3', item_name: '围巾', count: 6, weight: 2.3, worker_ids: [1] },
];

test('editing one box remark resets acknowledgement, saves and reopens without changing another box', async () => {
    const boxes = threeBoxes.slice(0, 2).map((box, index) => ({ ...box, remark: index ? '保留第二箱备注' : '' }));
    record.draft.boxes = boxes;
    const view = renderPage();
    await screen.findByDisplayValue('MARK-1');
    const acknowledgement = screen.getByRole('checkbox', { name: /我已对照纸质单/ });
    fireEvent.click(acknowledgement);
    fireEvent.change(screen.getByLabelText('第1箱备注'), { target: { value: '易碎，请轻放\n到货前联系' } });
    expect(acknowledgement).not.toBeChecked();
    expect(screen.getByRole('button', { name: /核对完成并上传/ })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '保存检查进度' }));
    await screen.findByText('检查进度已保存');
    const updatedBoxes = [{ ...boxes[0], remark: '易碎，请轻放\n到货前联系' }, boxes[1]];
    expect(JSON.parse(mutationCalls('draft')[0][1].body)).toEqual({ version: 1, draft: normalizeIntakeDraft({ ...initialRecord.draft, boxes: updatedBoxes }) });
    await act(async () => { await view.navigate('/packing-lists'); });
    await act(async () => { await view.navigate('/packing-list/upload/intake-1'); });
    await screen.findByDisplayValue('MARK-1');
    expect(screen.getByLabelText('第1箱备注')).toHaveValue('易碎，请轻放\n到货前联系');
    expect(screen.getByLabelText('第2箱备注')).toHaveValue('保留第二箱备注');
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    fireEvent.click(screen.getByRole('button', { name: /核对完成并上传/ }));
    await screen.findByRole('link', { name: '查看装箱单' });
    expect(mutationCalls('draft')).toHaveLength(1);
    expect(JSON.parse(mutationCalls('confirm')[0][1].body)).toEqual({ version: 2, reviewed: true });
    expect(screen.getByLabelText('第1箱备注')).toBeDisabled();
    fireEvent.change(screen.getByLabelText('第1箱备注'), { target: { value: '已确认后不可更改' } });
    expect(screen.getByLabelText('第1箱备注')).toHaveValue('易碎，请轻放\n到货前联系');
    expect(screen.queryByRole('button', { name: '批量修改备注' })).not.toBeInTheDocument();
});

test('bulk remarks replace only selected boxes, reset acknowledgement and preserve mixed goods, workers and other fields', async () => {
    const boxes = threeBoxes.map((box, index) => ({ ...box, remark: `原备注 ${index + 1}`, ...(index === 1 ? { item_details: [{ item_name: '运动鞋', piece_count: 2, customs_code: '640411' }, { item_name: '帽子', piece_count: 3, customs_code: '650500' }] } : {}) }));
    record.draft.boxes = boxes;
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    const action = screen.getByRole('button', { name: '批量修改备注' });
    expect(action).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: '选择第2箱' }));
    fireEvent.click(screen.getByRole('checkbox', { name: '选择第3箱' }));
    const acknowledgement = screen.getByRole('checkbox', { name: /我已对照纸质单/ });
    fireEvent.click(acknowledgement);
    fireEvent.click(action);
    const dialog = await screen.findByRole('dialog', { name: '批量修改备注' });
    fireEvent.change(within(dialog).getByLabelText('批量备注'), { target: { value: ' 统一轻放\n联系收件人 ' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '应用到所选箱子' }));
    expect(acknowledgement).not.toBeChecked();
    expect(screen.getByLabelText('第1箱备注')).toHaveValue('原备注 1');
    expect(screen.getByLabelText('第2箱备注')).toHaveValue('统一轻放\n联系收件人');
    expect(screen.getByLabelText('第3箱备注')).toHaveValue('统一轻放\n联系收件人');
    expect(screen.getByRole('checkbox', { name: '选择第2箱' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: '选择第3箱' })).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: '保存检查进度' }));
    await screen.findByText('检查进度已保存');
    const updatedBoxes = boxes.map((box, index) => index ? { ...box, remark: '统一轻放\n联系收件人' } : box);
    expect(JSON.parse(mutationCalls('draft')[0][1].body).draft).toEqual(normalizeIntakeDraft({ ...initialRecord.draft, boxes: updatedBoxes }));
});

test('cancelling bulk remarks preserves draft and acknowledgement while select all can clear every remark with whitespace', async () => {
    const boxes = threeBoxes.map((box, index) => ({ ...box, remark: `原备注 ${index + 1}` }));
    record.draft.boxes = boxes;
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    fireEvent.click(screen.getByRole('checkbox', { name: '全选箱子' }));
    const acknowledgement = screen.getByRole('checkbox', { name: /我已对照纸质单/ });
    fireEvent.click(acknowledgement);
    fireEvent.click(screen.getByRole('button', { name: '批量修改备注' }));
    const dialog = await screen.findByRole('dialog', { name: '批量修改备注' });
    fireEvent.change(within(dialog).getByLabelText('批量备注'), { target: { value: '取消后不应用' } });
    fireEvent.click(within(dialog).getByRole('button', { name: /取\s*消/ }));
    expect(acknowledgement).toBeChecked();
    for (let i = 1; i <= 3; i += 1) expect(screen.getByLabelText(`第${i}箱备注`)).toHaveValue(`原备注 ${i}`);
    expect(mutationCalls('draft')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: '批量修改备注' }));
    expect(screen.getByLabelText('批量备注')).toHaveValue('');
    const apply = screen.getByRole('button', { name: '应用到所选箱子' });
    expect(apply).not.toBeDisabled();
    fireEvent.change(screen.getByLabelText('批量备注'), { target: { value: ' \n ' } });
    expect(apply).not.toBeDisabled();
    fireEvent.click(apply);
    expect(acknowledgement).not.toBeChecked();
    for (let i = 1; i <= 3; i += 1) expect(screen.getByLabelText(`第${i}箱备注`)).toHaveValue('');
    fireEvent.click(screen.getByRole('button', { name: '保存检查进度' }));
    await screen.findByText('检查进度已保存');
    expect(JSON.parse(mutationCalls('draft')[0][1].body).draft).toEqual(normalizeIntakeDraft({ ...initialRecord.draft, boxes: boxes.map(box => ({ ...box, remark: '' })) }));
});

test('box and bulk remark inputs retain up to 512 Unicode characters without splitting emoji', async () => {
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    const maximumRemark = '📦'.repeat(512);
    fireEvent.change(screen.getByLabelText('第1箱备注'), { target: { value: `${maximumRemark}多` } });
    expect(screen.getByLabelText('第1箱备注')).toHaveValue(maximumRemark);
    expect(screen.queryByText(/备注不能超过/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: '选择第1箱' }));
    fireEvent.click(screen.getByRole('button', { name: '批量修改备注' }));
    const dialog = await screen.findByRole('dialog', { name: '批量修改备注' });
    fireEvent.change(within(dialog).getByLabelText('批量备注'), { target: { value: `多${maximumRemark}` } });
    expect(within(dialog).getByLabelText('批量备注')).toHaveValue(`多${'📦'.repeat(511)}`);
    fireEvent.click(within(dialog).getByRole('button', { name: '应用到所选箱子' }));
    expect(screen.getByLabelText('第1箱备注')).toHaveValue(`多${'📦'.repeat(511)}`);
});

test('bulk names target only selected boxes, require text and reset review acknowledgement without touching other values', async () => {
    record.draft.boxes = threeBoxes;
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    const action = screen.getByRole('button', { name: '批量修改品名' });
    expect(action).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: '选择第2箱' }));
    fireEvent.click(screen.getByRole('checkbox', { name: '选择第3箱' }));
    const acknowledgement = screen.getByRole('checkbox', { name: /我已对照纸质单/ });
    fireEvent.click(acknowledgement);
    expect(acknowledgement).toBeChecked();
    fireEvent.click(action);
    const dialog = await screen.findByRole('dialog', { name: '批量修改品名' });
    const apply = within(dialog).getByRole('button', { name: '应用到所选箱子' });
    expect(apply).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText('批量品名'), { target: { value: '   ' } });
    expect(apply).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText('批量品名'), { target: { value: ' 衣服 ' } });
    fireEvent.click(apply);
    expect(acknowledgement).not.toBeChecked();
    expect(screen.getByLabelText('第1箱品名与件数')).toHaveValue('鞋子 x 2');
    expect(screen.getByLabelText('第2箱品名与件数')).toHaveValue('衣服 x 4');
    expect(screen.getByLabelText('第3箱品名与件数')).toHaveValue('衣服 x 6');
    expect(screen.getByRole('checkbox', { name: '选择第2箱' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: '选择第3箱' })).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: '保存检查进度' }));
    await screen.findByText('检查进度已保存');
    const payload = JSON.parse(mutationCalls('draft')[0][1].body).draft;
    expect(payload).toEqual(normalizeIntakeDraft({ ...initialRecord.draft, boxes: threeBoxes.map((box, index) => index ? { ...box, item_name: '衣服' } : box) }));
    expect(screen.getByText('已选择 0 箱')).toBeInTheDocument();
});

test('select all changes every item name and cancelling a proposed bulk change keeps the draft and acknowledgement intact', async () => {
    record.draft.boxes = threeBoxes;
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    fireEvent.click(screen.getByRole('checkbox', { name: '全选箱子' }));
    expect(screen.getByText('已选择 3 箱')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    fireEvent.click(screen.getByRole('button', { name: '批量修改品名' }));
    const dialog = await screen.findByRole('dialog', { name: '批量修改品名' });
    fireEvent.change(within(dialog).getByLabelText('批量品名'), { target: { value: '不应用的品名' } });
    fireEvent.click(within(dialog).getByRole('button', { name: /取\s*消/ }));
    expect(screen.getByRole('checkbox', { name: /我已对照纸质单/ })).toBeChecked();
    expect(screen.getByLabelText('第2箱品名与件数')).toHaveValue('帽子 x 4');
    fireEvent.click(screen.getByRole('button', { name: '批量修改品名' }));
    expect(screen.getByLabelText('批量品名')).toHaveValue('');
    fireEvent.change(screen.getByLabelText('批量品名'), { target: { value: '服装' } });
    fireEvent.click(screen.getByRole('button', { name: '应用到所选箱子' }));
    for (let i = 1; i <= 3; i += 1) expect(screen.getByLabelText(`第${i}箱品名与件数`)).toHaveValue(`服装 x ${threeBoxes[i - 1].count}`);
    fireEvent.click(screen.getByRole('button', { name: '取消选择' }));
    expect(screen.getByRole('checkbox', { name: '全选箱子' })).not.toBeChecked();
    expect(screen.getByText('已选择 0 箱')).toBeInTheDocument();
});

test('selection follows the original box when earlier rows are removed and does not select a newly added box', async () => {
    record.draft.boxes = threeBoxes;
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    fireEvent.click(screen.getByRole('checkbox', { name: '选择第2箱' }));
    fireEvent.change(screen.getByLabelText('第2箱箱号'), { target: { value: '20' } });
    fireEvent.click(screen.getByRole('button', { name: '删除第1箱' }));
    expect(screen.getByRole('checkbox', { name: '选择第1箱' })).toBeChecked();
    expect(screen.getByLabelText('第1箱箱号')).toHaveValue('20');
    fireEvent.click(screen.getByRole('button', { name: /添加一箱/ }));
    expect(screen.getByRole('checkbox', { name: '选择第3箱' })).not.toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: '批量修改品名' }));
    fireEvent.change(screen.getByLabelText('批量品名'), { target: { value: '已选择箱品名' } });
    fireEvent.click(screen.getByRole('button', { name: '应用到所选箱子' }));
    expect(screen.getByLabelText('第1箱品名与件数')).toHaveValue('已选择箱品名 x 4');
    expect(screen.getByLabelText('第2箱品名与件数')).toHaveValue('围巾 x 6');
    expect(screen.getByLabelText('第3箱品名与件数')).toHaveValue('');
    fireEvent.click(screen.getByRole('button', { name: '删除第1箱' }));
    expect(screen.getByText('已选择 0 箱')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '批量修改品名' })).toBeDisabled();
});

test('bulk workers replace only the selected box workers, save and reopen correctly and upload with the saved version', async () => {
    record.draft.boxes = threeBoxes;
    const view = renderPage();
    await screen.findByDisplayValue('MARK-1');
    fireEvent.click(screen.getByRole('checkbox', { name: '选择第2箱' }));
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    fireEvent.click(screen.getByRole('button', { name: '批量修改操作人员' }));
    const dialog = await screen.findByRole('dialog', { name: '批量修改操作人员' });
    expect(within(dialog).getByText('将以下实际操作人员应用到已选择的 1 个箱子，每箱最多 4 人。')).toBeInTheDocument();
    const removeIcons = within(dialog).getAllByRole('img', { name: 'close', hidden: true });
    fireEvent.click(removeIcons[removeIcons.length - 1]);
    fireEvent.mouseDown(within(dialog).getByRole('combobox', { name: '批量实际操作人员' }));
    fireEvent.click(await screen.findByText('王师傅'));
    fireEvent.click(within(dialog).getByRole('button', { name: '应用到所选箱子' }));
    expect(screen.getByRole('checkbox', { name: /我已对照纸质单/ })).not.toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: '保存检查进度' }));
    await screen.findByText('检查进度已保存');
    const updatedBoxes = threeBoxes.map((box, index) => index === 1 ? { ...box, worker_ids: [3] } : box);
    expect(JSON.parse(mutationCalls('draft')[0][1].body)).toEqual({ version: 1, draft: normalizeIntakeDraft({ ...initialRecord.draft, boxes: updatedBoxes }) });
    await act(async () => { await view.navigate('/packing-lists'); });
    await act(async () => { await view.navigate('/packing-list/upload/intake-1'); });
    await screen.findByDisplayValue('MARK-1');
    const secondBox = screen.getByRole('row', { name: /选择第2箱/ });
    expect(within(secondBox).getByText('王师傅')).toBeInTheDocument();
    expect(within(secondBox).queryByText('李师傅')).not.toBeInTheDocument();
    expect(within(screen.getByRole('row', { name: /选择第1箱/ })).getByText('张师傅')).toBeInTheDocument();
    for (let i = 1; i <= 3; i += 1) expect(screen.getByLabelText(`第${i}箱品名与件数`)).toHaveValue(`${threeBoxes[i - 1].item_name} x ${threeBoxes[i - 1].count}`);
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    fireEvent.click(screen.getByRole('button', { name: /核对完成并上传/ }));
    await screen.findByRole('link', { name: '查看装箱单' });
    expect(mutationCalls('draft')).toHaveLength(1);
    expect(JSON.parse(mutationCalls('confirm')[0][1].body)).toEqual({ version: 2, reviewed: true });
    expect(record.draft.boxes.map(box => box.worker_ids)).toEqual([[1], [3], [1]]);
    expect(screen.queryByRole('button', { name: '批量修改品名' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '批量修改操作人员' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '批量修改备注' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('第1箱备注')).toBeDisabled();
    expect(screen.queryByRole('checkbox', { name: '选择第1箱' })).not.toBeInTheDocument();
});

test('cancelling the bulk worker dialog keeps real worker bindings and all item names unchanged', async () => {
    record.draft.boxes = threeBoxes;
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    fireEvent.click(screen.getByRole('checkbox', { name: '选择第1箱' }));
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    fireEvent.click(screen.getByRole('button', { name: '批量修改操作人员' }));
    const dialog = await screen.findByRole('dialog', { name: '批量修改操作人员' });
    fireEvent.mouseDown(within(dialog).getByRole('combobox', { name: '批量实际操作人员' }));
    fireEvent.click(await screen.findByText('王师傅'));
    fireEvent.click(within(dialog).getByRole('button', { name: /取\s*消/ }));
    expect(screen.getByRole('checkbox', { name: /我已对照纸质单/ })).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: '保存检查进度' }));
    await screen.findByText('检查进度已保存');
    expect(JSON.parse(mutationCalls('draft')[0][1].body).draft).toEqual(normalizeIntakeDraft({ ...initialRecord.draft, boxes: threeBoxes }));
});

test('each box edits its own workers and new boxes start without inherited workers', async () => {
    record.draft.boxes = threeBoxes;
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '第2箱实际操作人员' }));
    fireEvent.click(await screen.findByText('王师傅'));
    expect(screen.getByRole('checkbox', { name: /我已对照纸质单/ })).not.toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: /添加一箱/ }));
    expect(screen.getByRole('combobox', { name: '第4箱实际操作人员' })).toBeInTheDocument();
    expect(screen.getByText(/第 4 箱请选择至少一名实际操作人员/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '保存检查进度' }));
    await screen.findByText('检查进度已保存');
    expect(JSON.parse(mutationCalls('draft')[0][1].body).draft.boxes.map(box => box.worker_ids)).toEqual([[1], [2, 3], [1], []]);
});

test('select all can bulk replace workers on every box while empty selections block the batch action', async () => {
    record.draft.boxes = threeBoxes;
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    expect(screen.getByRole('button', { name: '批量修改操作人员' })).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: '全选箱子' }));
    fireEvent.click(screen.getByRole('button', { name: '批量修改操作人员' }));
    const dialog = await screen.findByRole('dialog', { name: '批量修改操作人员' });
    fireEvent.mouseDown(within(dialog).getByRole('combobox', { name: '批量实际操作人员' }));
    fireEvent.click(await screen.findByText('王师傅'));
    fireEvent.click(within(dialog).getByRole('button', { name: '应用到所选箱子' }));
    fireEvent.click(screen.getByRole('button', { name: '保存检查进度' }));
    await screen.findByText('检查进度已保存');
    expect(JSON.parse(mutationCalls('draft')[0][1].body).draft.boxes.map(box => box.worker_ids)).toEqual([[3], [3], [3]]);
});

test('recognized mixed goods edit independently, sum quantities, and upload the persisted item details', async () => {
    record = { ...record, draft_is_manual: false, draft: { mark: '', boxes: [] }, recognition_result: {
        ...candidate, boxes: [{ ...candidate.boxes[0], item_name: '旧摘要', count: 99, item_details: [{ item_name: '运动鞋', piece_count: 2 }, { item_name: '帽子', piece_count: 3 }] }],
    } };
    renderPage();
    await screen.findByDisplayValue('OCR-MARK');
    expect(screen.getByLabelText('第1箱品名与件数')).toHaveValue('运动鞋 x 2、帽子 x 3');
    expect(screen.queryByLabelText('第1箱第1项品名')).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('第1箱品名与件数'));
    await screen.findByRole('dialog', { name: '第1箱商品明细' });
    expect(screen.getByLabelText('第1箱第1项品名')).toHaveValue('运动鞋');
    expect(screen.getByLabelText('第1箱第2项品名')).toHaveValue('帽子');
    fireEvent.change(screen.getByLabelText('第1箱第2项件数'), { target: { value: '4' } });
    fireEvent.change(screen.getByLabelText('第1箱第2项品名'), { target: { value: '拖鞋' } });
    expect(screen.getByLabelText('第1箱品名与件数')).toHaveValue('运动鞋 x 2、拖鞋 x 4');
    fireEvent.click(screen.getByRole('button', { name: /^完\s*成$/ }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '第1箱商品明细' })).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    fireEvent.click(screen.getByRole('button', { name: /核对完成并上传/ }));
    await screen.findByRole('link', { name: '查看装箱单' });
    const savedBox = JSON.parse(mutationCalls('draft')[0][1].body).draft.boxes[0];
    expect(savedBox).toMatchObject({ item_name: '运动鞋、拖鞋', count: 6, weight: 1.2, worker_ids: [2], item_details: [{ item_name: '运动鞋', piece_count: 2, customs_code: '' }, { item_name: '拖鞋', piece_count: 4, customs_code: '' }] });
    expect(mutationCalls('confirm')).toHaveLength(1);
    expect(screen.getByLabelText('第1箱品名与件数')).toHaveValue('运动鞋 x 2、拖鞋 x 4');
    expect(screen.getByLabelText('第1箱品名与件数')).toBeDisabled();
    fireEvent.click(screen.getByLabelText('第1箱品名与件数'));
    expect(screen.queryByRole('dialog', { name: '第1箱商品明细' })).not.toBeInTheDocument();
});

test('goods summary opens with the keyboard, closes on Escape or completion, and reflects incomplete details', async () => {
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    const summary = screen.getByLabelText('第1箱品名与件数');
    expect(summary).toHaveAttribute('readonly');
    expect(summary).toHaveAttribute('aria-expanded', 'false');
    fireEvent.keyDown(summary, { key: 'Enter' });
    const dialog = await screen.findByRole('dialog', { name: '第1箱商品明细' });
    expect(summary).toHaveAttribute('aria-expanded', 'true');
    await waitFor(() => expect(within(dialog).getByLabelText('第1箱品名')).toHaveFocus());
    fireEvent.change(within(dialog).getByLabelText('第1箱品名'), { target: { value: '围巾' } });
    fireEvent.change(within(dialog).getByLabelText('第1箱件数'), { target: { value: '7' } });
    expect(summary).toHaveValue('围巾 x 7');
    fireEvent.keyDown(within(dialog).getByLabelText('第1箱件数'), { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '第1箱商品明细' })).not.toBeInTheDocument());
    expect(summary).toHaveAttribute('aria-expanded', 'false');
    expect(summary).toHaveFocus();
    fireEvent.keyDown(summary, { key: ' ' });
    const reopened = await screen.findByRole('dialog', { name: '第1箱商品明细' });
    expect(within(reopened).getByLabelText('第1箱品名')).toHaveValue('围巾');
    expect(within(reopened).getByLabelText('第1箱件数')).toHaveValue('7');
    fireEvent.click(within(reopened).getByRole('button', { name: '第1箱添加品名' }));
    expect(summary).toHaveValue('围巾 x 7、品名待填写 x 待填写');
    fireEvent.click(within(reopened).getByRole('button', { name: /^完\s*成$/ }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '第1箱商品明细' })).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /添加一箱/ }));
    const newSummary = screen.getByLabelText('第2箱品名与件数');
    expect(newSummary).toHaveValue('');
    expect(newSummary).toHaveAttribute('placeholder', '点击填写品名和数量');
    fireEvent.click(newSummary);
    const newDetails = await screen.findByRole('dialog', { name: '第2箱商品明细' });
    fireEvent.change(within(newDetails).getByLabelText('第2箱件数'), { target: { value: '3' } });
    expect(newSummary).toHaveValue('品名待填写 x 3');
    expect(summary).toHaveValue('围巾 x 7、品名待填写 x 待填写');
    fireEvent.mouseDown(screen.getByLabelText('唛头'));
    fireEvent.click(screen.getByLabelText('唛头'));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '第2箱商品明细' })).not.toBeInTheDocument());
    expect(newSummary).toHaveValue('品名待填写 x 3');
});

test('saving from an open goods dropdown closes and disables it until the saved response arrives', async () => {
    const fetchImpl = global.fetch.getMockImplementation();
    let resolveSave;
    global.fetch.mockImplementation((url, options) => String(url).endsWith('/draft')
        ? new Promise(resolve => { resolveSave = async () => resolve(await fetchImpl(url, options)); }) : fetchImpl(url, options));
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    const summary = screen.getByLabelText('第1箱品名与件数');
    fireEvent.click(summary);
    const dialog = await screen.findByRole('dialog', { name: '第1箱商品明细' });
    fireEvent.change(within(dialog).getByLabelText('第1箱件数'), { target: { value: '5' } });
    fireEvent.click(screen.getByRole('button', { name: '保存检查进度' }));
    expect(summary).toBeDisabled();
    expect(screen.getByLabelText('第1箱备注')).toBeDisabled();
    expect(screen.getByRole('button', { name: '批量修改备注' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('第1箱备注'), { target: { value: 'SAVE-IN-FLIGHT' } });
    expect(screen.getByLabelText('第1箱备注')).toHaveValue('');
    expect(summary).toHaveAttribute('aria-expanded', 'false');
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '第1箱商品明细' })).not.toBeInTheDocument());
    fireEvent.click(summary);
    expect(screen.queryByRole('dialog', { name: '第1箱商品明细' })).not.toBeInTheDocument();
    await act(async () => { await resolveSave(); });
    await screen.findAllByText('检查进度已保存');
    const savedSummary = screen.getByLabelText('第1箱品名与件数');
    expect(savedSummary).not.toBeDisabled();
    expect(savedSummary).toHaveValue('鞋子 x 5');
    expect(record.draft.boxes[0]).toMatchObject({ count: 5, item_details: [{ item_name: '鞋子', piece_count: 5 }] });
    expect(record.draft.boxes[0].remark).toBe('');
    fireEvent.click(savedSummary);
    const reopened = await screen.findByRole('dialog', { name: '第1箱商品明细' });
    expect(within(reopened).getByLabelText('第1箱件数')).toHaveValue('5');
});

test('mixed legacy names keep the paper total for reference, preserve incomplete saved progress, and require every item quantity', async () => {
    record.draft.boxes[0] = { ...record.draft.boxes[0], item_name: '运动鞋、帽子', count: 12 };
    const view = renderPage();
    await screen.findByDisplayValue('MARK-1');
    expect(screen.getByLabelText('第1箱品名与件数')).toHaveValue('运动鞋 x 待填写、帽子 x 待填写');
    fireEvent.click(screen.getByLabelText('第1箱品名与件数'));
    await screen.findByRole('dialog', { name: '第1箱商品明细' });
    expect(screen.getByLabelText('第1箱第1项件数')).toHaveValue('');
    expect(screen.getByLabelText('第1箱第2项件数')).toHaveValue('');
    expect(screen.getByText('纸单合计，明细待补全')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    expect(screen.getByRole('button', { name: /核对完成并上传/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('第1箱第1项件数'), { target: { value: '3' } });
    expect(screen.getByLabelText('第1箱品名与件数')).toHaveValue('运动鞋 x 3、帽子 x 待填写');
    fireEvent.click(screen.getByRole('button', { name: /^完\s*成$/ }));
    fireEvent.click(screen.getByRole('button', { name: /保存检查进度/ }));
    await screen.findByText('检查进度已保存');
    expect(record.draft.boxes[0]).toMatchObject({ count: 12, item_details: [{ item_name: '运动鞋', piece_count: 3 }, { item_name: '帽子', piece_count: null }] });
    await act(async () => { await view.navigate('/packing-lists'); });
    await act(async () => { await view.navigate('/packing-list/upload/intake-1'); });
    await screen.findByDisplayValue('MARK-1');
    expect(screen.getByLabelText('第1箱品名与件数')).toHaveValue('运动鞋 x 3、帽子 x 待填写');
    fireEvent.click(screen.getByLabelText('第1箱品名与件数'));
    await screen.findByRole('dialog', { name: '第1箱商品明细' });
    expect(screen.getByLabelText('第1箱第1项件数')).toHaveValue('3');
    expect(screen.getByLabelText('第1箱第2项件数')).toHaveValue('');
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    expect(screen.getByRole('button', { name: /核对完成并上传/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('第1箱第2项件数'), { target: { value: '2' } });
    expect(screen.queryByText('纸单合计，明细待补全')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /^完\s*成$/ }));
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    fireEvent.click(screen.getByRole('button', { name: /核对完成并上传/ }));
    await screen.findByRole('link', { name: '查看装箱单' });
    expect(record.draft.boxes[0].count).toBe(5);
});

test('adding and removing goods preserves the box fields and offers the connected Chinese goods catalogue', async () => {
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    expect(screen.getByLabelText('第1箱品名与件数')).toHaveValue('鞋子 x 2');
    fireEvent.click(screen.getByLabelText('第1箱品名与件数'));
    const detail = await screen.findByRole('dialog', { name: '第1箱商品明细' });
    fireEvent.click(screen.getByRole('button', { name: '第1箱添加品名' }));
    expect(screen.getByLabelText('第1箱第1项品名')).toHaveValue('鞋子');
    const secondName = screen.getByLabelText('第1箱第2项品名');
    fireEvent.mouseDown(secondName);
    const goodsOption = await screen.findByText('运动鞋');
    fireEvent.mouseDown(goodsOption);
    fireEvent.click(goodsOption);
    expect(secondName).toHaveValue('运动鞋');
    expect(screen.getByLabelText('第1箱品名与件数')).toHaveAttribute('aria-expanded', 'true');
    await waitFor(() => expect(detail).toBeVisible());
    fireEvent.change(screen.getByLabelText('第1箱第2项件数'), { target: { value: '4' } });
    expect(screen.getByLabelText('第1箱品名与件数')).toHaveValue('鞋子 x 2、运动鞋 x 4');
    fireEvent.click(screen.getByRole('button', { name: /^完\s*成$/ }));
    fireEvent.click(screen.getByRole('button', { name: '保存检查进度' }));
    await screen.findByText('检查进度已保存');
    expect(record.draft.boxes[0]).toMatchObject({ box_number: '1', weight: 3.5, worker_ids: [1], item_name: '鞋子、运动鞋', count: 6 });
    fireEvent.click(screen.getByLabelText('第1箱品名与件数'));
    await screen.findByRole('dialog', { name: '第1箱商品明细' });
    fireEvent.click(screen.getByRole('button', { name: '删除第1箱第1项品名' }));
    expect(screen.getByLabelText('第1箱品名')).toHaveValue('运动鞋');
    expect(screen.getByLabelText('第1箱件数')).toHaveValue('4');
    expect(screen.getByRole('button', { name: '删除第1箱第1项品名' })).toBeDisabled();
    expect(screen.getByLabelText('第1箱品名与件数')).toHaveValue('运动鞋 x 4');
    fireEvent.click(screen.getByRole('button', { name: /^完\s*成$/ }));
    fireEvent.click(screen.getByRole('button', { name: '保存检查进度' }));
    await screen.findByText('检查进度已保存');
    expect(record.draft.boxes[0]).toMatchObject({ box_number: '1', weight: 3.5, worker_ids: [1], item_name: '运动鞋', count: 4 });
});

test('bulk names change only the chosen item row and preserve mixed goods and per-item quantities', async () => {
    record.draft.boxes = [{ ...threeBoxes[0], item_details: [{ item_name: '运动鞋', piece_count: 2 }, { item_name: '帽子', piece_count: 3 }] }, threeBoxes[1]];
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    fireEvent.click(screen.getByRole('checkbox', { name: '全选箱子' }));
    fireEvent.click(screen.getByRole('button', { name: '批量修改品名' }));
    const dialog = await screen.findByRole('dialog', { name: '批量修改品名' });
    expect(within(dialog).getByText(/保留箱内其他品名和各项件数/)).toBeInTheDocument();
    fireEvent.mouseDown(within(dialog).getByRole('combobox', { name: '批量品名行' }));
    fireEvent.click(await screen.findByText('第 2 项品名'));
    fireEvent.change(within(dialog).getByLabelText('批量品名'), { target: { value: '围巾' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '应用到所选箱子' }));
    expect(screen.getByLabelText('第1箱品名与件数')).toHaveValue('运动鞋 x 2、围巾 x 3');
    expect(screen.getByLabelText('第2箱品名与件数')).toHaveValue('帽子 x 4');
    fireEvent.click(screen.getByRole('button', { name: '保存检查进度' }));
    await screen.findByText('检查进度已保存');
    expect(record.draft.boxes[0]).toMatchObject({ item_name: '运动鞋、围巾', count: 5, item_details: [{ item_name: '运动鞋', piece_count: 2 }, { item_name: '围巾', piece_count: 3 }] });
    expect(record.draft.boxes[1]).toMatchObject(threeBoxes[1]);
});

test('unfinished-upload page restores from URL and pagination keeps unsaved photo metadata', async () => {
    const implementation = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, options) => String(url).includes('/my-packing-lists?')
        ? Promise.resolve(response({ items: [{ uid: 'intake-1', mark: 'MY-UPLOAD', box_count: 2 }], total: 21 }))
        : implementation(url, options));
    const router = renderPage('/upload?intake_page=2&keep=1#uploads');
    const section = await screen.findByRole('region', { name: '我的未完成上传' });
    await within(section).findByText('MY-UPLOAD');
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('status=uploading&page=2&page_size=20'))).toBe(true);
    fireEvent.change(screen.getByLabelText('唛头提示'), { target: { value: '尚未上传的唛头' } });
    fireEvent.click(within(section).getByTitle('1'));
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => String(url).includes('status=uploading&page=1&page_size=20'))).toBe(true));
    expect(screen.getByLabelText('唛头提示')).toHaveValue('尚未上传的唛头');
    expect(screen.queryByRole('dialog', { name: '有未保存的内容' })).not.toBeInTheDocument();
    await waitFor(() => expect(new URLSearchParams(router.state.location.search).get('intake_page') || '1').toBe('1'));
    expect(new URLSearchParams(router.state.location.search).get('keep')).toBe('1');
    expect(router.state.location.hash).toBe('#uploads');
});
