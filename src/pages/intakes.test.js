import React from 'react';
import fs from 'fs';
import path from 'path';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { PaperIntakeUploadDetail, PaperIntakeUpload } from './intakes';
import { getIntakeRoles, normalizeIntakeDraft, validateIntakeDraft } from '../common/intakeApi';

const initialRecord = {
    uid: 'intake-1', submitted_by_name: '回传人甲', created_at: '2026-10-01 10:00:00',
    display_name: 'MARK-1', mark_hint: '', note: '', status: 'pending', version: 1,
    photos: [{ uid: 'photo-1', filename: 'MARK-1-1.jpg', original_filename: 'paper.jpg' }],
    draft_is_manual: true,
    draft: { mark: 'MARK-1', operator_name: '张师傅', worker_ids: [1], boxes: [{ box_number: '1', item_name: '鞋子', count: 2, weight: 3.5 }] },
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
    expect(screen.queryByLabelText('第1箱品名')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /核对完成并上传/ })).not.toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/photos/'))).toBe(false);
    expect(mutationCalls('confirm')).toHaveLength(0);
});

test('untouched first review puts recognition straight into the editable table with matched workers', async () => {
    record = { ...record, draft_is_manual: false, draft: { mark: '', boxes: [] }, recognition_result: candidate, recognition_status: 'needs_review' };
    renderPage();
    await screen.findByDisplayValue('OCR-MARK');
    expect(screen.getByLabelText('第1箱品名')).toHaveValue('帽子');
    expect(screen.getByText('李师傅')).toBeInTheDocument();
    expect(screen.queryByText('识别候选内容')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /填入核对表/ })).not.toBeInTheDocument();
    expect(mutationCalls('draft')).toHaveLength(0);
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: /核对完成并上传/ })).not.toBeDisabled());
});

test('an existing saved manual draft stays authoritative over recognition', async () => {
    record.recognition_result = candidate;
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    expect(screen.getByLabelText('第1箱品名')).toHaveValue('鞋子');
    expect(screen.getByText('张师傅')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('OCR-MARK')).not.toBeInTheDocument();
});

test('an explicitly saved empty draft stays empty despite recognition', async () => {
    record = { ...record, draft_is_manual: true, draft: { mark: '', operator_name: '', worker_ids: [], boxes: [] }, recognition_result: candidate };
    renderPage();
    await screen.findByLabelText('唛头');
    expect(screen.getByLabelText('唛头')).toHaveValue('');
    expect(screen.queryByLabelText('第1箱品名')).not.toBeInTheDocument();
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
    expect(screen.getByLabelText('第1箱品名')).toHaveValue('帽子');
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
    expect(screen.queryByLabelText('第1箱品名')).not.toBeInTheDocument();
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
    expect(JSON.parse(mutationCalls('draft')[0][1].body)).toMatchObject({ version: 1, draft: { mark: 'EDITED-MARK', worker_ids: [1] } });
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
    await waitFor(() => expect(screen.getByRole('combobox', { name: '实际操作人员' })).not.toBeDisabled());
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '实际操作人员' }));
    fireEvent.click(await screen.findByText('王师傅'));
    fireEvent.click(screen.getByRole('checkbox', { name: /我已对照纸质单/ }));
    expect(screen.getByRole('button', { name: /核对完成并上传/ })).not.toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: /保存检查进度/ }));
    await waitFor(() => expect(mutationCalls('draft')).toHaveLength(1));
    expect(JSON.parse(mutationCalls('draft')[0][1].body).draft).toMatchObject({ operator_name: '纸上未知姓名', worker_ids: [3] });
});

test('missing or inactive worker IDs block confirmation', async () => {
    record.draft.worker_ids = [99];
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
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '实际操作人员' }));
    fireEvent.click(await screen.findByText('张师傅 · ID 2'));
    fireEvent.click(screen.getByRole('button', { name: /保存检查进度/ }));
    await waitFor(() => expect(mutationCalls('draft')).toHaveLength(1));
    expect(JSON.parse(mutationCalls('draft')[0][1].body).draft.worker_ids).toEqual([1, 2]);
});

test('partial drafts save without a worker binding or complete box fields', async () => {
    record.draft.worker_ids = [];
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    fireEvent.change(screen.getByLabelText('唛头'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: /保存检查进度/ }));
    await waitFor(() => expect(mutationCalls('draft')).toHaveLength(1));
    expect(JSON.parse(mutationCalls('draft')[0][1].body).draft).toMatchObject({ mark: '', worker_ids: [] });
    expect(screen.getByRole('button', { name: /核对完成并上传/ })).toBeDisabled();
});

test('polling detects concurrent saved edits while preserving local content', async () => {
    jest.useFakeTimers();
    record.recognition_status = 'running';
    renderPage();
    await screen.findByDisplayValue('MARK-1');
    fireEvent.change(screen.getByLabelText('唛头'), { target: { value: 'LOCAL' } });
    record = { ...record, version: 2, draft: { ...record.draft, mark: 'OTHER' } };
    await act(async () => { jest.advanceTimersByTime(3000); });
    await screen.findByText('纸单已在其他页面更新，请重新加载后继续。当前检查内容已保留。');
    expect(screen.getByLabelText('唛头')).toHaveValue('LOCAL');
    expect(screen.getByRole('button', { name: /保存检查进度/ })).toBeDisabled();
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
    expect(screen.getByLabelText('第1箱品名')).toBeDisabled();
    expect(screen.getByRole('combobox', { name: '实际操作人员' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: /我已对照纸质单/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /核对完成并上传/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('唛头'), { target: { value: 'EDIT-DURING-RELOAD' } });
    fireEvent.change(screen.getByLabelText('第1箱品名'), { target: { value: 'EDIT-DURING-RELOAD' } });
    fireEvent.click(screen.getByRole('button', { name: /核对完成并上传/ }));
    expect(screen.getByLabelText('唛头')).toHaveValue('DISCARD-ME');
    expect(screen.getByLabelText('第1箱品名')).toHaveValue('鞋子');
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
    expect(normalizeIntakeDraft({ worker_ids: ['1', 1, 0, null, 'x', 2] }).worker_ids).toEqual([1, 2]);
    expect(validateIntakeDraft(initialRecord.draft)).toBe('');
    expect(validateIntakeDraft({ ...initialRecord.draft, worker_ids: [] })).toContain('至少一名');
    expect(validateIntakeDraft({ ...initialRecord.draft, worker_ids: [1, 2, 3, 4, 5] })).toContain('最多选择 4');
    expect(validateIntakeDraft({ ...initialRecord.draft, boxes: [{ ...initialRecord.draft.boxes[0], box_number: '2147483648' }] })).toContain('不能超过 2147483647');
});
