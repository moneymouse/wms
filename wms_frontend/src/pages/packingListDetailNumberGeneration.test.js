import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import PackingListDetail from './packingListDetail';
import { ORDER_EDIT_POLICY_KEYS } from '../common/orderEditPolicy';

jest.mock('../components/PackingListReceiptButton', () => () => null);

const policy = Object.fromEntries(ORDER_EDIT_POLICY_KEYS.map(key => [key, true]));
const boxes = [
    { uid: 'box-1', box_number: 1, transfer_id: null, target_order_uid: null, status: 'pending_assign' },
    { uid: 'box-2', box_number: 2, transfer_id: 'OLD-2', target_order_uid: 'order-2', status: 'pending_outbound' },
    { uid: 'box-3', box_number: 3, transfer_id: 'OUTBOUND-3', target_order_uid: 'order-3', status: 'outbound' },
].map(box => ({ ...box, weight: 2, item_name: '鞋子', piece_count: 1, edit_policy: policy }));

const response = (data, code = 200, msg = '') => Promise.resolve({
    ok: code === 200, json: () => Promise.resolve({ code, data, msg }),
});
const generationCalls = () => global.fetch.mock.calls.filter(([url]) => String(url).includes('/generate-original-numbers'));

function setup({ roles = ['clerk'], onGenerate, overrides = {} } = {}) {
    const token = window.btoa(JSON.stringify({ user_id: 1, roles }));
    window.localStorage.setItem('jwt', `header.${token}.signature`);
    const detail = { uid: 'pl-1', list_number: 'MARK-1', status: 'completed', boxes, ...overrides };
    global.fetch = jest.fn((rawUrl, options = {}) => {
        const url = String(rawUrl);
        if (url.includes('/generate-original-numbers')) {
            if (onGenerate) return onGenerate(url, options);
            const body = JSON.parse(options.body);
            return response({ generated_count: body.box_uids.length, boxes: body.box_uids.map((uid, index) => ({
                uid, transfer_id: `D80000000${index + 1}L`,
            })) });
        }
        if (url.endsWith('/packing-list/pl-1')) return response(detail);
        if (url.endsWith('/packing-list/pl-2')) return response({ ...detail, uid: 'pl-2', list_number: 'MARK-2' });
        return response([]);
    });
}

function Navigation() {
    const navigate = useNavigate();
    return <button onClick={() => navigate('/packing-lists/pl-2')}>切换装箱单</button>;
}
function renderDetail() {
    return render(<MemoryRouter initialEntries={['/packing-lists/pl-1']}>
        <Navigation />
        <Routes><Route path="/packing-lists/:uid" element={<PackingListDetail />} /></Routes>
    </MemoryRouter>);
}

beforeEach(() => {
    window.localStorage.clear();
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({
        matches: false, media: query, onchange: null,
        addListener: () => {}, removeListener: () => {}, addEventListener: () => {},
        removeEventListener: () => {}, dispatchEvent: () => false,
    }) });
});
afterEach(() => jest.restoreAllMocks());

test('only an explicit click generates selected unassigned boxes and preserves other originals', async () => {
    setup();
    renderDetail();
    await screen.findByText('MARK-1');
    const button = screen.getByRole('button', { name: '生成原单号' });
    expect(button).toBeDisabled();
    expect(generationCalls()).toHaveLength(0);
    fireEvent.click(screen.getByRole('checkbox', { name: '箱子 1' }));
    fireEvent.click(button);
    expect(await screen.findByRole('checkbox', { name: '一票多件' })).not.toBeChecked();
    expect(generationCalls()).toHaveLength(0);
    fireEvent.click(await screen.findByRole('button', { name: '确认生成' }));
    expect(await screen.findByText('D800000001L')).toBeInTheDocument();
    expect(screen.getByText('OLD-2')).toBeInTheDocument();
    expect(screen.getByText('OUTBOUND-3')).toBeInTheDocument();
    expect(generationCalls()).toHaveLength(1);
    expect(generationCalls()[0][0]).toMatch(/\/packing-lists\/pl-1\/boxes\/generate-original-numbers$/);
    expect(generationCalls()[0][1].method).toBe('POST');
    expect(JSON.parse(generationCalls()[0][1].body)).toEqual({ box_uids: ['box-1'], expected_values: { 'box-1': null } });
});

test('existing original numbers require replacement confirmation and include all selected expected values', async () => {
    setup();
    renderDetail();
    await screen.findByText('MARK-1');
    fireEvent.click(screen.getByRole('checkbox', { name: '箱子 1' }));
    fireEvent.click(screen.getByRole('checkbox', { name: '箱子 2' }));
    fireEvent.click(screen.getByRole('button', { name: '生成原单号' }));
    expect(await screen.findByText(/其中 1 箱已有的原单号将被替换/)).toBeInTheDocument();
    expect(generationCalls()).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: '生成并替换' }));
    await screen.findByText('D800000002L');
    expect(JSON.parse(generationCalls()[0][1].body)).toEqual({
        box_uids: ['box-1', 'box-2'], expected_values: { 'box-1': null, 'box-2': 'OLD-2' },
    });
    expect(screen.getByText('OUTBOUND-3')).toBeInTheDocument();
});

test('one-ticket checkbox creates a shared master for empty selected boxes', async () => {
    setup({ overrides: { boxes: boxes.slice(0, 2).map(box => ({ ...box, transfer_id: null })) },
        onGenerate: () => response({ generated_count: 2, boxes: [
            { uid: 'box-1', transfer_id: 'D800000001L-1' },
            { uid: 'box-2', transfer_id: 'D800000001L-2' },
        ] }) });
    renderDetail();
    await screen.findByText('MARK-1');
    fireEvent.click(screen.getByRole('checkbox', { name: '箱子 1' }));
    fireEvent.click(screen.getByRole('checkbox', { name: '箱子 2' }));
    fireEvent.click(screen.getByRole('button', { name: '生成原单号' }));
    fireEvent.click(await screen.findByRole('checkbox', { name: '一票多件' }));
    fireEvent.click(await screen.findByRole('button', { name: '确认生成' }));
    expect(await screen.findByText('D800000001L-2')).toBeInTheDocument();
    expect(JSON.parse(generationCalls()[0][1].body)).toMatchObject({
        multi_piece: true, box_uids: ['box-1', 'box-2'],
    });
});

test('one-ticket append preserves existing originals and displays server conflicts without replacing boxes', async () => {
    setup({ overrides: { boxes: boxes.slice(0, 2).map(box => ({ ...box,
        transfer_id: box.uid === 'box-1' ? 'D800000001L-1' : null })) },
        onGenerate: () => response(null, 409, '所选箱子属于不同主单号，请选择同一票的箱子') });
    renderDetail();
    await screen.findByText('MARK-1');
    fireEvent.click(screen.getByRole('checkbox', { name: '箱子 1' }));
    fireEvent.click(screen.getByRole('checkbox', { name: '箱子 2' }));
    fireEvent.click(screen.getByRole('button', { name: '生成原单号' }));
    fireEvent.click(await screen.findByRole('checkbox', { name: '一票多件' }));
    await waitFor(() => expect(screen.queryByText(/其中 1 箱已有的原单号将被替换/)).not.toBeInTheDocument());
    fireEvent.click(await screen.findByRole('button', { name: '确认生成' }));
    expect(await screen.findByText('所选箱子属于不同主单号，请选择同一票的箱子')).toBeInTheDocument();
    expect(screen.getByText('D800000001L-1')).toBeInTheDocument();
    expect(JSON.parse(generationCalls()[0][1].body)).toEqual({
        box_uids: ['box-1', 'box-2'], expected_values: { 'box-1': 'D800000001L-1', 'box-2': null }, multi_piece: true,
    });
});

test('selecting an outbound or restricted box disables batch generation for the complete selection', async () => {
    setup({ overrides: { boxes: boxes.map(box => box.uid === 'box-2'
        ? { ...box, edit_policy: { ...policy, tracking_numbers: false } } : box) } });
    renderDetail();
    await screen.findByText('MARK-1');
    fireEvent.click(screen.getByRole('checkbox', { name: '箱子 1' }));
    expect(screen.getByRole('button', { name: '生成原单号' })).not.toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: '箱子 3' }));
    expect(screen.getByRole('button', { name: '生成原单号' })).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: '箱子 3' }));
    fireEvent.click(screen.getByRole('checkbox', { name: '箱子 2' }));
    expect(screen.getByRole('button', { name: '生成原单号' })).toBeDisabled();
    expect(generationCalls()).toHaveLength(0);
});

test('pending requests block repeat generation and conflicts preserve saved originals', async () => {
    let resolve;
    setup({ onGenerate: () => new Promise(done => { resolve = done; }) });
    renderDetail();
    await screen.findByText('MARK-1');
    fireEvent.click(screen.getByRole('checkbox', { name: '箱子 1' }));
    const button = screen.getByRole('button', { name: '生成原单号' });
    fireEvent.click(button);
    fireEvent.click(await screen.findByRole('button', { name: '确认生成' }));
    fireEvent.click(button);
    expect(button).toBeDisabled();
    expect(generationCalls()).toHaveLength(1);
    await act(async () => { resolve(await response(null, 409, '号码已被修改，请刷新后重试')); });
    expect(await screen.findByText('号码已被修改，请刷新后重试')).toBeInTheDocument();
    expect(screen.getByText('OLD-2')).toBeInTheDocument();
    expect(screen.queryByText('D800000001L')).not.toBeInTheDocument();
    expect(button).not.toBeDisabled();
});

test.each(['worker', 'finance', 'customer'])('%s has no generation action even with permissive field policies', async role => {
    setup({ roles: [role] });
    renderDetail();
    await screen.findByText('MARK-1');
    expect(screen.queryByRole('button', { name: '生成原单号' })).not.toBeInTheDocument();
    expect(generationCalls()).toHaveLength(0);
});

test('a late batch response cannot write originals into the next packing list', async () => {
    let resolve;
    setup({ onGenerate: () => new Promise(done => { resolve = done; }) });
    renderDetail();
    await screen.findByText('MARK-1');
    fireEvent.click(screen.getByRole('checkbox', { name: '箱子 1' }));
    fireEvent.click(screen.getByRole('button', { name: '生成原单号' }));
    fireEvent.click(await screen.findByRole('button', { name: '确认生成' }));
    fireEvent.click(screen.getByRole('button', { name: '切换装箱单' }));
    await screen.findByText('MARK-2');
    await act(async () => { resolve(await response({ boxes: [{ uid: 'box-1', transfer_id: 'D800000001L' }] })); });
    expect(screen.getByText('MARK-2')).toBeInTheDocument();
    expect(screen.queryByText('D800000001L')).not.toBeInTheDocument();
});
