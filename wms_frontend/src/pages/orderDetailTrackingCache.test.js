import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import OrderDetail from './orderDetail';

jest.mock('../config', () => ({ endpoint: '/api' }));
jest.mock('antd/es/input/Input', () => ({ __esModule: true, default: jest.requireActual('antd').Input }));
jest.mock('../components/ExportButton', () => () => null);
jest.mock('../components/BoxAssignmentModal', () => () => null);
jest.mock('../components/FeatureTour', () => () => null);
jest.mock('../components/transportation', () => () => null);

const response = (data, status = 200, msg) => ({ ok: status < 400, status, json: async () => ({ code: status, data, msg }) });
const cargo = (overrides = {}) => ({ uid: 'cargo-a', transfer_id: 'ORIGINAL-A', waybill_id: 'WAYBILL-A', status: 1,
    count: 1, weight: 1.5, removal_allowed: false, track_status: 'InTransit_Other',
    tracking_received_at: '2026-10-11T15:30:00Z', events: [{ time_utc: '2026-10-11T15:20:00Z', location: '广州', description: '包裹已离开分拨中心' }], ...overrides });

function Harness() {
    const navigate = useNavigate();
    return <><OrderDetail /><button onClick={() => navigate('/orders/order-b')}>切换到订单 B</button></>;
}
function showOrder(cargos, options = {}) {
    global.fetch = jest.fn(async rawUrl => {
        const path = new URL(rawUrl, 'http://localhost').pathname;
        if (/\/orders\/order-[ab]\/cargo$/.test(path)) return options.cargoResponse ? options.cargoResponse(path) : response(cargos);
        if (/\/orders\/order-[ab]$/.test(path)) return response({ uid: path.split('/').pop(), order_id: path.endsWith('order-a') ? 'ORDER-A' : 'ORDER-B', transportation: 'DHL' });
        if (path.endsWith('/salesman')) return response(null);
        return response([]);
    });
    return render(<MemoryRouter initialEntries={['/orders/order-a']}><Routes>
        <Route path="/orders/:order_id" element={<Harness />} />
    </Routes></MemoryRouter>);
}
async function parcelRow(label = 'ORIGINAL-A') {
    await screen.findByText(label);
    return screen.getAllByRole('row').find(row => within(row).queryByText(label));
}
beforeEach(() => {
    localStorage.clear(); sessionStorage.clear();
    localStorage.setItem('jwt', `h.${btoa(JSON.stringify({ user_id: 7, roles: ['admin'] }))}.s`);
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({ matches: false, media: query,
        onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }) });
});
afterEach(() => jest.restoreAllMocks());

test('ordinary parcel displays cached logistics and events while warehouse outbound permissions remain intact', async () => {
    const record = cargo(); showOrder([record]);
    const row = await parcelRow();
    expect(within(row).getByText('运输途中')).toBeInTheDocument();
    expect(within(row).queryByText('出库')).not.toBeInTheDocument();
    expect(within(row).getByRole('button', { name: /移\s*除/ })).toBeDisabled();
    expect(within(row).getByRole('button', { name: '撤销出库' })).toBeEnabled();
    expect(within(row).getByText('1.5KG')).toHaveAttribute('title', '货物已出库，重量不可修改');
    fireEvent.mouseEnter(within(row).getByRole('button', { name: '运输途中' }));
    await screen.findByText('广州, 包裹已离开分拨中心');
    expect(screen.getByText(/^2026-10-11 \d{2}:20$/)).toBeInTheDocument();
    expect(screen.getByText(/^最近物流推送：2026-10-11 \d{2}:30$/)).toBeInTheDocument();
    expect(record.status).toBe(1);
    expect(global.fetch.mock.calls.every(([url, options]) => String(url).startsWith('/api/') && !options?.method)).toBe(true);
});

test.each([['normal', undefined, 1], ['shipped packing', 'packing-a', 1]])('%s parcel with no cache shows pending push without inventing a logistics result', async (_, packingUid, status) => {
    showOrder([cargo({ packing_list_uid: packingUid, status, track_status: undefined, events: [], tracking_received_at: null, tracking_pending: true })]);
    const row = await parcelRow();
    expect(within(row).getByText('等待物流推送')).toBeInTheDocument();
    expect(within(row).queryByText(/NotFound|找不到|运输途中/)).not.toBeInTheDocument();
    expect(within(row).getByRole('button', { name: /移\s*除/ })).toBeDisabled();
});

test('pending packing parcel keeps its warehouse display even when an old cache exists', async () => {
    showOrder([cargo({ packing_list_uid: 'packing-a', status: 0, track_status: 'Delivered_Other', removal_allowed: true, date: null })]);
    const row = await parcelRow();
    expect(within(row).getByText('待出库')).toBeInTheDocument();
    expect(within(row).queryByText('成功签收')).not.toBeInTheDocument();
    expect(within(row).getByRole('button', { name: /移\s*除/ })).toBeEnabled();
    expect(within(row).queryByRole('button', { name: '撤销出库' })).not.toBeInTheDocument();
});

test('shipped packing parcel displays its cached logistics state', async () => {
    showOrder([cargo({ packing_list_uid: 'packing-a', track_status: 'Delivered_Other' })]);
    const row = await parcelRow();
    expect(within(row).getByText('成功签收')).toBeInTheDocument();
    expect(within(row).queryByText('待出库')).not.toBeInTheDocument();
});

test.each([[403, '无权查看包裹'], [500, undefined]])('parcel HTTP %s errors show the actual server message or a general load failure', async (status, msg) => {
    showOrder([], { cargoResponse: () => response([cargo()], status, msg) });
    await screen.findByText(msg || '获取包裹详情失败');
    expect(screen.queryByText('ORIGINAL-A')).not.toBeInTheDocument();
    expect(screen.queryByText('17Track 获取订单跟踪信息失败')).not.toBeInTheDocument();
});

test('a business error inside HTTP 200 is shown without displaying its parcel data', async () => {
    showOrder([], { cargoResponse: () => ({ ok: true, status: 200, json: async () => ({ code: 500, data: [cargo()], msg: '本地物流缓存暂时不可用' }) }) });
    await screen.findByText('本地物流缓存暂时不可用');
    expect(screen.queryByText('ORIGINAL-A')).not.toBeInTheDocument();
});

test('switching orders ignores a late cache response from the old order', async () => {
    let resolveOld;
    showOrder([], { cargoResponse: path => path.includes('order-a') ? new Promise(resolve => { resolveOld = resolve; }) : response([cargo({ uid: 'cargo-b', transfer_id: 'ORIGINAL-B', track_status: 'Delivered_Other' })]) });
    await waitFor(() => expect(resolveOld).toBeDefined());
    fireEvent.click(screen.getByRole('button', { name: '切换到订单 B' }));
    await screen.findByText('ORIGINAL-B');
    await act(async () => resolveOld(response([cargo()])));
    expect(screen.queryByText('ORIGINAL-A')).not.toBeInTheDocument();
    expect(screen.getByText('成功签收')).toBeInTheDocument();
});
