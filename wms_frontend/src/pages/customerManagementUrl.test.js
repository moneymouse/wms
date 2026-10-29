import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import CustomerManagement from './customerManagement';

jest.mock('../config', () => ({ endpoint: '/api' }));

function Page() {
    const location = useLocation();
    return <><CustomerManagement /><output data-testid="url">{location.search}{location.hash}</output></>;
}

beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({ matches: false, media: query,
        addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }) });
    global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ code: 200,
        data: Array.from({ length: 35 }, (_, index) => ({ id: index + 1, name: `保存客户${String(index + 1).padStart(2, '0')}` })),
    }) }));
});
afterEach(() => jest.restoreAllMocks());

test('customer search and table page restore from URL and a new search resets the page', async () => {
    const params = new URLSearchParams({ customer_search: '保存客户', customer_page: JSON.stringify({ current: 2, pageSize: 10 }), keep: '1' });
    render(<MemoryRouter initialEntries={[`/customers?${params}#table`]}><Page /></MemoryRouter>);
    expect(screen.getByPlaceholderText('搜索客户姓名/手机号/微信')).toHaveValue('保存客户');
    await screen.findByText('保存客户11');
    expect(screen.queryByText('保存客户01')).not.toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText('搜索客户姓名/手机号/微信'), { target: { value: '保存客户03' } });
    await screen.findByText('保存客户03');
    await waitFor(() => expect(screen.queryByText('保存客户11')).not.toBeInTheDocument());
    await waitFor(() => expect(new URL(screen.getByTestId('url').textContent, 'http://localhost').searchParams.get('customer_search')).toBe('保存客户03'));
    const url = new URL(screen.getByTestId('url').textContent, 'http://localhost');
    expect(url.searchParams.get('customer_search')).toBe('保存客户03');
    expect(JSON.parse(url.searchParams.get('customer_page'))).toEqual({ current: 1, pageSize: 10 });
    expect(url.searchParams.get('keep')).toBe('1');
    expect(url.hash).toBe('#table');
});
