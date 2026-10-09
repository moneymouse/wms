import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import PackingListCreate from './packingListCreate';

jest.setTimeout(20000);

jest.mock('./intakes', () => ({ PaperIntakeUpload: () => <div>纸单上传入口</div> }));

const workers = [{ id: 1, name: '工人甲' }, { id: 2, name: '工人乙' }, { id: 3, name: '工人丙' }];
const result = data => ({ ok: true, status: 200, json: async () => ({ code: 200, data }) });
let nextBoxNumber;

beforeEach(() => {
    nextBoxNumber = 0;
    localStorage.clear();
    localStorage.setItem('jwt', `header.${btoa(JSON.stringify({ user_id: 1, roles: ['admin'] }))}.signature`);
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({ matches: false, media: query, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {} }) });
    global.fetch = jest.fn(async (rawUrl, options = {}) => {
        const url = String(rawUrl);
        if (url.includes('/work/workers')) return result(workers);
        if (url.includes('/packing-lists?')) return result({ items: [] });
        if (url.endsWith('/customer_list')) return result([]);
        if (url.endsWith('/packing-list') && options.method === 'POST') return result({ uid: 'pl-1', list_number: 'MARK-1' });
        if (url.endsWith('/packing-list/pl-1/box') && options.method === 'POST') {
            nextBoxNumber += 1;
            return result({ ...JSON.parse(options.body), uid: `box-${nextBoxNumber}`, box_number: nextBoxNumber, workers: [] });
        }
        return result({});
    });
});
afterEach(() => { localStorage.clear(); jest.restoreAllMocks(); });

async function renderCreatedPage() {
    render(<MemoryRouter><PackingListCreate /></MemoryRouter>);
    fireEvent.change(await screen.findByPlaceholderText('请输入唛头（自动大写）'), { target: { value: 'MARK-1' } });
    fireEvent.click(screen.getByRole('button', { name: /创建装箱单/ }));
    await screen.findByRole('combobox', { name: '新箱操作人员' });
    await waitFor(() => expect(screen.getByRole('combobox', { name: '新箱操作人员' })).not.toBeDisabled());
}

async function addBox(workerNames, { enterItemName = true } = {}) {
    const expectedBoxNumber = nextBoxNumber + 1;
    if (enterItemName) fireEvent.change(screen.getByRole('combobox', { name: '新箱第1项品名' }), { target: { value: '鞋子' } });
    fireEvent.change(screen.getByPlaceholderText('件数或算式'), { target: { value: '2' } });
    fireEvent.change(screen.getByPlaceholderText('请输入重量'), { target: { value: '3.5' } });
    if (workerNames) {
        const workerSelect = screen.getByRole('combobox', { name: '新箱操作人员' }).closest('.ant-select');
        workerSelect.querySelectorAll('.ant-select-selection-item-remove').forEach(icon => fireEvent.click(icon));
        fireEvent.mouseDown(screen.getByRole('combobox', { name: '新箱操作人员' }));
        for (const workerName of (Array.isArray(workerNames) ? workerNames : [workerNames])) {
            fireEvent.click(await screen.findByText(workerName, { selector: '.ant-select-item-option-content' }));
        }
        fireEvent.keyDown(screen.getByRole('combobox', { name: '新箱操作人员' }), { key: 'Escape', keyCode: 27 });
    }
    fireEvent.click(screen.getByRole('button', { name: /添加箱子/ }));
    await waitFor(() => expect(global.fetch.mock.calls.filter(([url]) => String(url).endsWith('/workers/add'))).toHaveLength(expectedBoxNumber));
    await waitFor(() => expect(screen.getByRole('button', { name: /添加箱子/ })).not.toHaveClass('ant-btn-loading'));
}

test('consecutive manual boxes retain item names and all selected workers while clearing count, weight and remark', async () => {
    await renderCreatedPage();
    fireEvent.change(screen.getByPlaceholderText('可填写额外说明信息'), { target: { value: '第一箱备注' } });
    await addBox(['工人甲', '工人乙']);
    expect(screen.getByRole('combobox', { name: '新箱第1项品名' })).toHaveValue('鞋子');
    const workerSelect = screen.getByRole('combobox', { name: '新箱操作人员' }).closest('.ant-select');
    expect(within(workerSelect).getByText('工人甲')).toBeInTheDocument();
    expect(within(workerSelect).getByText('工人乙')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('件数或算式')).toHaveValue('');
    await waitFor(() => expect(screen.getByPlaceholderText('请输入重量')).toHaveValue(''));
    expect(screen.getByPlaceholderText('可填写额外说明信息')).toHaveValue('');
    await addBox(undefined, { enterItemName: false });
    const assignments = global.fetch.mock.calls.filter(([url]) => String(url).endsWith('/workers/add'));
    expect(assignments.map(([url, options]) => [String(url).split('/box/')[1], JSON.parse(options.body).worker_ids])).toEqual([
        ['box-1/workers/add', [1, 2]], ['box-2/workers/add', [1, 2]],
    ]);
    const boxes = global.fetch.mock.calls.filter(([url, options]) => String(url).endsWith('/packing-list/pl-1/box') && options.method === 'POST');
    expect(JSON.parse(boxes[1][1].body)).toEqual(expect.objectContaining({ item_name: '鞋子', piece_count: 2, weight: 3.5, remark: null }));
    expect(screen.getByRole('button', { name: '修改第1箱操作人员' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '修改第2箱操作人员' })).toBeInTheDocument();
});

test('editing one existing manual box uses its worker endpoint and does not change the other box', async () => {
    await renderCreatedPage();
    await addBox('工人甲');
    await addBox('工人乙');
    fireEvent.click(screen.getByRole('button', { name: '修改第1箱操作人员' }));
    const dialog = await screen.findByRole('dialog', { name: '修改本箱操作人员' });
    const removeIcons = within(dialog).getAllByRole('img', { name: 'close', hidden: true });
    fireEvent.click(removeIcons[removeIcons.length - 1]);
    fireEvent.mouseDown(within(dialog).getByRole('combobox', { name: '本箱实际操作人员' }));
    fireEvent.click(await screen.findByText('工人丙', { selector: '.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option-content' }));
    fireEvent.click(within(dialog).getByRole('button', { name: '保存本箱操作人员' }));
    await screen.findByText('本箱操作人员已保存');
    const updates = global.fetch.mock.calls.filter(([url, options]) => String(url).endsWith('/workers') && options.method === 'PUT');
    expect(updates).toHaveLength(1);
    expect(updates[0]).toEqual([expect.stringMatching(/\/box\/box-1\/workers$/), expect.objectContaining({ method: 'PUT', body: JSON.stringify({ worker_ids: [3] }) })]);
    expect(screen.getByText('工人乙', { selector: '.ant-typography' })).toBeInTheDocument();
});

test('worker role can assign each new box and does not receive existing-worker replacement controls', async () => {
    localStorage.setItem('jwt', `header.${btoa(JSON.stringify({ user_id: 1, roles: ['worker'] }))}.signature`);
    await renderCreatedPage();
    await addBox('工人甲');
    expect(screen.queryByRole('button', { name: '修改第1箱操作人员' })).not.toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([url, options]) => String(url).endsWith('/workers') && options.method === 'PUT')).toBe(false);
});
