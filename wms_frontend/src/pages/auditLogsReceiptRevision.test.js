import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';

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

    expect(await screen.findAllByText('订单业务修订')).toHaveLength(2);
    expect(screen.getByText('解锁订单')).toBeInTheDocument();
    expect(screen.getByText('重新锁定订单')).toBeInTheDocument();
    expect(screen.queryByText('order_unlock')).not.toBeInTheDocument();
    expect(screen.queryByText('order_relock')).not.toBeInTheDocument();
});

function AuditNavigation() {
    const location = useLocation();
    const navigate = useNavigate();
    return <><AuditLogs /><output aria-label="当前地址">{location.search}</output>
        <button onClick={() => navigate('/audit-logs')}>打开默认审计页</button>
        <button onClick={() => navigate(-1)}>返回上一筛选</button></>;
}

test('audit filters restore the form and request from the URL, including browser back', async () => {
    const query = { p: 2, s: 10, sf: 'create_date', so: 0, q: '订单甲', event_type: 'order_receipt_revision', date_from: '2026-09-01', date_to: '2026-09-20' };
    render(<MemoryRouter initialEntries={[`/audit-logs?auditFilters=${encodeURIComponent(JSON.stringify(query))}&payment_id=8`]}><AuditNavigation /></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole('textbox', { name: '搜索审计记录' })).toHaveValue('订单甲'));
    expect(screen.getByDisplayValue('2026-09-01')).toBeInTheDocument();
    expect(screen.getByDisplayValue('2026-09-20')).toBeInTheDocument();
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => {
        const params = new URL(url, 'http://localhost').searchParams;
        return params.get('q') === '订单甲' && params.get('p') === '2' && params.get('date_to') === '2026-09-20';
    })).toBe(true));
    fireEvent.click(screen.getByRole('button', { name: '打开默认审计页' }));
    await waitFor(() => expect(screen.getByRole('textbox', { name: '搜索审计记录' })).toHaveValue(''));
    fireEvent.click(screen.getByRole('button', { name: '返回上一筛选' }));
    await waitFor(() => expect(screen.getByRole('textbox', { name: '搜索审计记录' })).toHaveValue('订单甲'));
    fireEvent.change(screen.getByRole('textbox', { name: '搜索审计记录' }), { target: { value: '客户乙' } });
    fireEvent.click(screen.getByText('筛选', { exact: true }));
    await waitFor(() => {
        const params = new URLSearchParams(screen.getByLabelText('当前地址').textContent);
        expect(JSON.parse(params.get('auditFilters'))).toMatchObject({ q: '客户乙', p: 1 });
        expect(params.get('payment_id')).toBe('8');
    });
});
