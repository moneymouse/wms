import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import AdminPage from './admin';

jest.mock('../components/GoodsNameManagement', () => function MockGoodsNameManagement() {
    return <div>品名管理模块</div>;
});
jest.mock('../components/CustomsCodeManagement', () => function MockCustomsCodeManagement() {
    return <div>海关编码管理模块</div>;
});
beforeEach(() => {
    window.localStorage.clear();
    const payload = window.btoa(JSON.stringify({ user_id: 1, roles: ['admin'] }));
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
    // This test verifies layout only; keep requests pending so asynchronous data
    // updates do not add unrelated state-transition noise to the assertions.
    global.fetch = jest.fn(() => new Promise(() => {}));
});

afterEach(() => {
    jest.restoreAllMocks();
});

test('management functions are grouped with user sections last', async () => {
    render(
        <MemoryRouter initialEntries={['/admin']}>
            <Routes>
                <Route path="/admin" element={<AdminPage />} />
            </Routes>
        </MemoryRouter>
    );

    expect(await screen.findByRole('heading', { name: '管理中心' })).toBeInTheDocument();
    const sectionHeadings = screen.getAllByRole('heading', { level: 4 });
    expect(sectionHeadings.map(node => node.textContent)).toEqual([
        '审批处理',
        '渠道与导出配置',
        '商品与报关资料',
        '用户与权限',
    ]);

    expect(within(screen.getByRole('region', { name: '审批处理' })).getByText('低价报价审批')).toBeInTheDocument();

    const channelSection = screen.getByRole('region', { name: '渠道与导出配置' });
    expect(within(channelSection).getByText('运输方式管理')).toBeInTheDocument();
    expect(within(channelSection).getByText('Excel模板管理')).toBeInTheDocument();

    const referenceSection = screen.getByRole('region', { name: '商品与报关资料' });
    expect(within(referenceSection).getByText('品名管理模块')).toBeInTheDocument();
    expect(within(referenceSection).getByText('海关编码管理模块')).toBeInTheDocument();

    expect(screen.queryByRole('region', { name: '订单修订' })).not.toBeInTheDocument();

    const userSection = screen.getByRole('region', { name: '用户与权限' });
    expect(within(userSection).getByText('用户申请管理')).toBeInTheDocument();
    expect(within(userSection).getByText('用户角色管理')).toBeInTheDocument();
    expect(within(userSection).getByText('密码重置申请')).toBeInTheDocument();

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(6));
});
