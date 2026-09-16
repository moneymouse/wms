import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import OrderDetail from './orderDetail';

jest.mock('antd/es/input/Input', () => ({
    __esModule: true,
    default: jest.requireActual('antd').Input,
}));
jest.mock('../components/ExportButton', () => function MockExportButton() {
    return null;
});
jest.mock('../components/BoxAssignmentModal', () => function MockBoxAssignmentModal() {
    return null;
});
jest.mock('../components/transportation', () => function MockTransportation() {
    return null;
});
jest.mock('../components/FeatureTour', () => function MockFeatureTour() {
    return null;
});

const lockedReceipt = {
    status: 'locked',
    has_history: true,
    unlock_eligible: true,
    blockers: [],
    revision: null,
};

const revisionOpenReceipt = {
    status: 'revision_open',
    has_history: true,
    unlock_eligible: false,
    blockers: [],
    revision: {
        id: 12,
        reason: '客户要求更正重量',
        opened_by_id: 7,
        opened_by_name: '管理员甲',
        opened_at: '2026-09-04 10:30:00',
    },
};

const buildOrder = (receiptLock = lockedReceipt) => ({
    uid: 'order-uid',
    order_id: 'ORDER-1',
    transportation: '',
    salesman: { id: 7, name: '管理员甲' },
    customer_ids: null,
    receipt_locked: receiptLock?.status === 'locked',
    ...(receiptLock === undefined ? {} : { receipt_lock: receiptLock }),
});

function setJwt(roles = ['admin', 'salesperson']) {
    const payload = window.btoa(JSON.stringify({ user_id: 7, name: 'Admin', roles }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
}

function createFetch({
    order = buildOrder(),
    unlockResult = { code: 200, msg: '解锁成功', data: revisionOpenReceipt },
    relockResult = { code: 200, msg: '锁定成功', data: lockedReceipt },
} = {}) {
    return jest.fn((rawUrl) => {
        const url = String(rawUrl);
        if (url.includes('/receipt-unlock')) {
            return Promise.resolve({ ok: true, json: () => Promise.resolve(unlockResult) });
        }
        if (url.includes('/receipt-relock')) {
            return Promise.resolve({ ok: true, json: () => Promise.resolve(relockResult) });
        }
        if (url.includes('/salesman')) {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({ code: 200, data: order.salesman }),
            });
        }
        if (url.includes('/users/salespersons') || url.includes('/customs-codes')) {
            return Promise.resolve({ ok: true, json: () => Promise.resolve({ code: 200, data: [] }) });
        }
        if (url.includes('/cargo?')) {
            return Promise.resolve({ ok: true, json: () => Promise.resolve({ code: 200, data: [] }) });
        }
        if (url.includes('/customer_detail/')) {
            return Promise.resolve({ ok: true, json: () => Promise.resolve({ code: 200, data: {} }) });
        }
        if (url.endsWith('/orders/order-uid')) {
            return Promise.resolve({ ok: true, json: () => Promise.resolve({ code: 200, data: order }) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ code: 200, data: [] }) });
    });
}

function renderOrderDetail() {
    return render(
        <MemoryRouter initialEntries={['/orders/order-uid']}>
            <Routes>
                <Route path="/orders/:order_id" element={<OrderDetail />} />
            </Routes>
        </MemoryRouter>
    );
}

beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    setJwt();
    Object.defineProperty(window, 'matchMedia', {
        writable: true,
        value: query => ({
            matches: false,
            media: query,
            onchange: null,
            addListener: () => {},
            removeListener: () => {},
            addEventListener: () => {},
            removeEventListener: () => {},
            dispatchEvent: () => false,
        }),
    });
});

afterEach(() => {
    jest.restoreAllMocks();
});

test('an admin unlocks a locked order with a required reason and can relock it', async () => {
    global.fetch = createFetch();
    renderOrderDetail();

    expect(await screen.findByText('收据生成，订单锁定')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /添\s*加/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /报\s*价/ })).not.toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: '解锁订单' }));
    expect(await screen.findByRole('dialog', { name: '解锁订单并开始修订' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /确\s*认\s*解\s*锁/ }));
    expect(await screen.findByText('请填写解锁原因')).toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/receipt-unlock'))).toBe(false);

    fireEvent.change(screen.getByPlaceholderText('请说明填写错误或业务变更内容'), {
        target: { value: '  客户要求更正重量  ' },
    });
    fireEvent.click(screen.getByRole('button', { name: /确\s*认\s*解\s*锁/ }));

    expect(await screen.findByText('订单修订中')).toBeInTheDocument();
    expect(screen.getByText('原因：客户要求更正重量')).toBeInTheDocument();
    expect(screen.getByText(/开启人：管理员甲/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /添\s*加/ })).not.toBeDisabled();
    expect(screen.getByRole('button', { name: /报\s*价/ })).not.toBeDisabled();

    const unlockCall = global.fetch.mock.calls.find(([url]) => String(url).includes('/receipt-unlock'));
    expect(unlockCall?.[1]).toMatchObject({ method: 'POST' });
    expect(JSON.parse(unlockCall[1].body)).toEqual({ reason: '客户要求更正重量' });

    fireEvent.click(screen.getByRole('button', { name: '完成修订并锁定' }));
    fireEvent.click(await screen.findByRole('button', { name: /完\s*成\s*并\s*锁\s*定/ }));

    await waitFor(() => expect(screen.getByText('收据生成，订单锁定')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /添\s*加/ })).toBeDisabled();
    const relockCall = global.fetch.mock.calls.find(([url]) => String(url).includes('/receipt-relock'));
    expect(relockCall?.[1]).toMatchObject({ method: 'POST' });
});

test('an unlock API error keeps both the modal and locked state visible', async () => {
    global.fetch = createFetch({
        unlockResult: { code: 409, msg: '存在待审核收款单，无法解锁' },
    });
    renderOrderDetail();

    fireEvent.click(await screen.findByRole('button', { name: '解锁订单' }));
    fireEvent.change(screen.getByPlaceholderText('请说明填写错误或业务变更内容'), {
        target: { value: '更正信息' },
    });
    fireEvent.click(screen.getByRole('button', { name: /确\s*认\s*解\s*锁/ }));

    expect(await screen.findByText('存在待审核收款单，无法解锁')).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: '解锁订单并开始修订' })).toBeInTheDocument();
    expect(screen.getByText('收据生成，订单锁定')).toBeInTheDocument();
});

test('a relock API error leaves the order in revision mode', async () => {
    global.fetch = createFetch({
        order: buildOrder(revisionOpenReceipt),
        relockResult: { code: 409, msg: '订单当前不在修订中' },
    });
    renderOrderDetail();

    expect(await screen.findByText('订单修订中')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '完成修订并锁定' }));
    fireEvent.click(await screen.findByRole('button', { name: /完\s*成\s*并\s*锁\s*定/ }));

    expect(await screen.findByText('订单当前不在修订中')).toBeInTheDocument();
    expect(screen.getByText('订单修订中')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /添\s*加/ })).not.toBeDisabled();
});

test('unlock blockers are shown in friendly language and prevent opening the modal', async () => {
    const blockedReceipt = {
        ...lockedReceipt,
        unlock_eligible: false,
        blockers: ['pending_receipt', 'approved_receipt', 'bonus_assigned'],
    };
    global.fetch = createFetch({ order: buildOrder(blockedReceipt) });
    renderOrderDetail();

    const unlockButton = await screen.findByRole('button', { name: '解锁订单' });
    expect(unlockButton).toBeDisabled();
    expect(screen.getByText('暂不能解锁：存在待审核收款单、存在已审核收款单、存在已分配奖金的包裹'))
        .toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: '解锁订单并开始修订' })).not.toBeInTheDocument();
});

test('non-admin users never receive receipt unlock or relock controls', async () => {
    window.localStorage.clear();
    setJwt(['salesperson']);
    global.fetch = createFetch({ order: buildOrder() });
    renderOrderDetail();

    expect(await screen.findByText('收据生成，订单锁定')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '解锁订单' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '完成修订并锁定' })).not.toBeInTheDocument();
});

test('a legacy locked response stays locked without exposing an unsupported unlock action', async () => {
    const legacyOrder = buildOrder();
    delete legacyOrder.receipt_lock;
    legacyOrder.receipt_locked = true;
    global.fetch = createFetch({ order: legacyOrder });
    renderOrderDetail();

    expect(await screen.findByText('收据生成，订单锁定')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /添\s*加/ })).toBeDisabled();
    expect(screen.queryByRole('button', { name: '解锁订单' })).not.toBeInTheDocument();
});
