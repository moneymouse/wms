import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import AuditLogs from './auditLogs';

beforeEach(() => {
    window.localStorage.clear();
    const payload = window.btoa(JSON.stringify({ user_id: 7, roles: ['admin'] }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
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
    global.fetch = jest.fn(() => Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
            code: 200,
            data: [
                {
                    id: 1,
                    create_date: '2026-09-04 10:30:00',
                    event_type: 'order_receipt_revision',
                    action: 'order_unlock',
                    target_type: 'order',
                    target_id: 'order-uid',
                    operator_name: '管理员甲',
                    operator_role: 'admin',
                    remark: '客户要求更正重量',
                },
                {
                    id: 2,
                    create_date: '2026-09-04 10:45:00',
                    event_type: 'order_receipt_revision',
                    action: 'order_relock',
                    target_type: 'order',
                    target_id: 'order-uid',
                    operator_name: '管理员甲',
                    operator_role: 'admin',
                    remark: '管理员手动完成修订',
                },
            ],
            page: 1,
            page_size: 10,
            total: 2,
        }),
    }));
});

afterEach(() => {
    jest.restoreAllMocks();
});

test('receipt revision audit events and actions use Chinese labels', async () => {
    render(
        <MemoryRouter>
            <AuditLogs />
        </MemoryRouter>
    );

    expect(await screen.findAllByText('订单收据修订')).toHaveLength(2);
    expect(screen.getByText('解锁订单')).toBeInTheDocument();
    expect(screen.getByText('重新锁定订单')).toBeInTheDocument();
    expect(screen.queryByText('order_unlock')).not.toBeInTheDocument();
    expect(screen.queryByText('order_relock')).not.toBeInTheDocument();
});
