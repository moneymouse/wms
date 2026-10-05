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

test('reviewer opens the paper review queue from the link beside the packing-list heading', async () => {
    setRole('clerk');
    render(<MemoryRouter initialEntries={['/packing-lists']}><Routes>
        <Route path="/packing-lists" element={<PackingListList />} />
        <Route path="/intakes" element={<div>待核对队列页面</div>} />
    </Routes></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: /待核对纸质单\?/ }));
    expect(await screen.findByText('待核对队列页面')).toBeInTheDocument();
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

test('formal route permissions keep worker upload and personal records accessible while reserving paper review for reviewers', () => {
    expect(getLandingPage(['worker'])).toBe('/packing-lists');
    expect(getLandingPage(['employee'])).toBe('/packing-lists');
    for (const role of ['worker', 'employee']) {
        expect(hasPermission([role], menuPermissions['packing-list/new'])).toBe(true);
        expect(hasPermission([role], routePermissions['/packing-list/new'])).toBe(true);
        expect(hasPermission([role], routePermissions['/packing-lists'])).toBe(true);
        expect(hasPermission([role], routePermissions['/intakes'])).toBe(false);
        expect(hasPermission([role], routePermissions['/intakes/:uid'])).toBe(false);
    }
    for (const role of ['admin', 'store_manager', 'salesperson', 'clerk']) {
        expect(hasPermission([role], routePermissions['/intakes'])).toBe(true);
        expect(hasPermission([role], routePermissions['/intakes/:uid'])).toBe(true);
    }
    expect(menuPermissions).not.toHaveProperty('intakes');
});
