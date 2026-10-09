import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import PackingListList from './packingListList';
import PackingListCreate from './packingListCreate';
import { getLandingPage, hasPermission, menuPermissions, routePermissions } from '../common/roleConfig';

jest.mock('../components/MyPackingLists', () => () => <div>个人装箱单清单</div>);
jest.mock('./intakes', () => ({ PaperIntakeUpload: () => <div>纸质装箱单上传区</div> }));

beforeEach(() => {
    localStorage.clear();
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({
        matches: false, media: query, onchange: null,
        addListener: () => {}, removeListener: () => {},
        addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
    }) });
    global.fetch = jest.fn(async rawUrl => ({ ok: true, json: async () => ({ code: 200,
        data: String(rawUrl).includes('/packing-lists') ? { items: [], total: 0 } : [],
    }) }));
});

afterEach(() => { localStorage.clear(); jest.restoreAllMocks(); });

function setRole(role) {
    localStorage.setItem('jwt', `header.${btoa(JSON.stringify({ user_id: 1, roles: [role] }))}.signature`);
}

test('worker packing-list entry renders the personal unified list without a paper review entry', async () => {
    setRole('worker');
    render(<MemoryRouter><PackingListList /></MemoryRouter>);
    expect(screen.getByText('个人装箱单清单')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /待核对纸质单/ })).not.toBeInTheDocument();
});

test('clerk opens the shipping draft page from the link beside the packing-list heading', async () => {
    setRole('clerk');
    render(<MemoryRouter initialEntries={['/packing-lists']}><Routes>
        <Route path="/packing-lists" element={<PackingListList />} />
        <Route path="/shipping-confirmation-drafts" element={<div>出货确认单草稿页面</div>} />
    </Routes></MemoryRouter>);
    expect(screen.queryByRole('button', { name: /待核对纸质单/ })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: /出货确认单草稿/ }));
    expect(await screen.findByText('出货确认单草稿页面')).toBeInTheDocument();
});

test('PDF entry opens the shipping draft page without an editor modal', async () => {
    setRole('salesperson');
    render(<MemoryRouter initialEntries={['/packing-lists']}><Routes>
        <Route path="/packing-lists" element={<PackingListList />} />
        <Route path="/shipping-confirmation-drafts" element={<div>出货确认单草稿页面</div>} />
    </Routes></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: /出货确认单（PDF）/ }));
    expect(await screen.findByText('出货确认单草稿页面')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

test('creation page keeps manual entry and offers paper upload without a separate parser page', async () => {
    setRole('worker');
    render(<MemoryRouter><PackingListCreate /></MemoryRouter>);
    expect(await screen.findByRole('button', { name: /手动录入/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('纸质装箱单上传区')).not.toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: /拍照上传纸质单/ }));
    expect(screen.getByText('纸质装箱单上传区')).toBeVisible();
    expect(screen.getByRole('button', { name: /我的装箱单/ })).toBeInTheDocument();
    expect(screen.queryByText('识别候选内容')).not.toBeInTheDocument();
});

test('route permissions allow uploaders to finish their uploads and reserve shipping drafts for shipping staff', () => {
    expect(getLandingPage(['worker'])).toBe('/packing-lists');
    expect(getLandingPage(['employee'])).toBe('/packing-lists');
    for (const role of ['worker', 'employee']) {
        expect(hasPermission([role], menuPermissions['packing-list/new'])).toBe(true);
        expect(hasPermission([role], routePermissions['/packing-list/new'])).toBe(true);
        expect(hasPermission([role], routePermissions['/packing-lists'])).toBe(true);
        expect(hasPermission([role], routePermissions['/packing-list/upload/:uid'])).toBe(true);
        expect(hasPermission([role], routePermissions['/shipping-confirmation-drafts'])).toBe(false);
        expect(hasPermission([role], routePermissions['/shipping-confirmation-drafts/:uid'])).toBe(false);
    }
    for (const role of ['admin', 'store_manager', 'salesperson', 'clerk']) {
        expect(hasPermission([role], routePermissions['/packing-list/upload/:uid'])).toBe(true);
        expect(hasPermission([role], routePermissions['/shipping-confirmation-drafts'])).toBe(true);
        expect(hasPermission([role], routePermissions['/shipping-confirmation-drafts/:uid'])).toBe(true);
    }
    expect(menuPermissions).not.toHaveProperty('intakes');
    expect(routePermissions).not.toHaveProperty('/intakes');
    expect(routePermissions).not.toHaveProperty('/intakes/:uid');
});
