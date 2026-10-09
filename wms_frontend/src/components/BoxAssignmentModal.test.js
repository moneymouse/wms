import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

import BoxAssignmentModal from './BoxAssignmentModal';


beforeEach(() => {
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
    global.fetch = jest.fn((url) => {
        const params = new URLSearchParams(String(url).split('?')[1] || '');
        const page = Number(params.get('p') || 1);
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
                code: 200,
                data: {
                    items: [{
                        packing_list_uid: `page-${page}`,
                        list_number: `PAGE-${page}`,
                        boxes: [{ uid: `box-${page}`, box_number: 1, weight: 1.5 }],
                    }],
                    total: 25,
                    total_boxes: 30,
                    page,
                    page_size: 10,
                },
            }),
        });
    });
});

afterEach(() => {
    jest.restoreAllMocks();
});

test('box assignment loads packing lists one server page at a time', async () => {
    render(
        <BoxAssignmentModal
            visible
            onClose={jest.fn()}
            customerName="测试客户"
            orderUid="order-1"
            onSuccess={jest.fn()}
        />
    );

    expect(await screen.findByText('PAGE-1')).toBeInTheDocument();
    expect(global.fetch.mock.calls[0][0]).toContain('p=1');
    expect(global.fetch.mock.calls[0][0]).toContain('s=10');

    fireEvent.click(screen.getByTitle('2'));

    expect(await screen.findByText('PAGE-2')).toBeInTheDocument();
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => (
        String(url).includes('p=2')
    ))).toBe(true));
});

test('keeps the mark search focused while filtered boxes are loading', async () => {
    render(
        <BoxAssignmentModal
            visible
            onClose={jest.fn()}
            customerName="测试客户"
            orderUid="order-1"
            onSuccess={jest.fn()}
        />
    );

    expect(await screen.findByText('PAGE-1')).toBeInTheDocument();

    let resolveSearch;
    global.fetch.mockImplementationOnce(() => new Promise(resolve => {
        resolveSearch = resolve;
    }));

    const searchInput = screen.getByPlaceholderText('搜索唛头');
    act(() => searchInput.focus());
    fireEvent.change(searchInput, { target: { value: 'PAGE-2' } });

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    expect(screen.getByPlaceholderText('搜索唛头')).toBe(searchInput);
    expect(searchInput).toHaveFocus();

    await act(async () => {
        resolveSearch({
            ok: true,
            json: () => Promise.resolve({
                code: 200,
                data: {
                    items: [],
                    total: 0,
                    total_boxes: 0,
                    page: 1,
                    page_size: 10,
                },
            }),
        });
    });

    expect(await screen.findByText('未找到匹配的唛头')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('搜索唛头')).toBe(searchInput);
    expect(searchInput).toHaveFocus();
});
