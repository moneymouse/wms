import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import Receipts from './receipts';

jest.mock('../components/FeatureTour', () => function MockFeatureTour({
    autoEnabled,
    forceAutoStart,
    onStepChange,
    onTourEnd,
    steps,
}) {
    return (
        <>
            <button
                aria-label="测试收款引导"
                data-auto-enabled={String(autoEnabled)}
                data-force-auto-start={String(forceAutoStart)}
                onClick={() => onStepChange(steps.length - 1)}
            >
                测试收款引导
            </button>
            {forceAutoStart && (
                <button aria-label="完成自动收款引导" onClick={() => onTourEnd('completed', 'auto')}>
                    完成自动收款引导
                </button>
            )}
        </>
    );
});

beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    const payload = window.btoa(JSON.stringify({ user_id: 7, roles: ['salesperson'] }));
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
    global.fetch = jest.fn((url) => Promise.resolve({
        ok: true,
        json: () => Promise.resolve(url.includes('/receipts?')
            ? { code: 200, data: [], page: 1, page_size: 20, total: 0 }
            : { code: 200, data: [] }),
    }));
});

afterEach(() => {
    jest.restoreAllMocks();
});

test('the receipt tour changes to the records tab without submitting data', async () => {
    const { container } = render(<MemoryRouter><Receipts /></MemoryRouter>);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());

    const trigger = screen.getByRole('button', { name: '测试收款引导' });
    expect(trigger).toHaveAttribute('data-auto-enabled', 'false');
    fireEvent.click(trigger);

    await waitFor(() => {
        const records = container.querySelector('[data-tour="receipt-records"]');
        expect(records).toBeInTheDocument();
        expect(records.closest('.ant-tabs-tabpane')).toHaveClass('ant-tabs-tabpane-active');
    });
    expect(global.fetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
});

test('the receipt page does not start the full onboarding workflow by itself', async () => {
    render(<MemoryRouter><Receipts /></MemoryRouter>);

    expect(await screen.findByRole('button', { name: '测试收款引导' }))
        .toHaveAttribute('data-auto-enabled', 'false');
    expect(window.sessionStorage.getItem('wms:tour-flow:7')).toBeNull();
});

test('admin continues from receipt entry to finance audit', async () => {
    const payload = window.btoa(JSON.stringify({ user_id: 8, roles: ['admin'] }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
    window.sessionStorage.setItem('wms:tour-flow:8', JSON.stringify({
        campaignId: 'cost-quote-receipt',
        stage: 'receipt-entry',
    }));

    render(
        <MemoryRouter initialEntries={['/receipts']}>
            <Routes>
                <Route path="/receipts" element={<Receipts />} />
                <Route path="/finance" element={<div>财务中心页</div>} />
            </Routes>
        </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: '完成自动收款引导' }));

    expect(await screen.findByText('财务中心页')).toBeInTheDocument();
    expect(JSON.parse(window.sessionStorage.getItem('wms:tour-flow:8'))).toMatchObject({
        stage: 'receipt-audit',
    });
});
