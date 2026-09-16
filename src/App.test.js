import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import App from './App';
import {readFeatureTourState, shouldAutoShowFeatureTour} from './common/featureTourState';

jest.mock('./common/featureTourState', () => ({
    ...jest.requireActual('./common/featureTourState'),
    shouldAutoShowFeatureTour: jest.fn(() => true),
}));

function setJwt(userId, roles, name = 'Test User') {
    const payload = window.btoa(JSON.stringify({ user_id: userId, name, roles }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
}

beforeEach(() => {
    shouldAutoShowFeatureTour.mockReturnValue(true);
    window.localStorage.clear();
    window.sessionStorage.clear();
    Object.defineProperty(window, 'matchMedia', {
        writable: true,
        value: query => ({
            matches: true,
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

test('renders the authenticated application menu', async () => {
    setJwt(1, ['admin'], 'Admin Test');

    render(<MemoryRouter initialEntries={['/receipts']}><App/></MemoryRouter>);

    expect(await screen.findByText('收款管理')).toBeInTheDocument();
});

test('multi-role labels use spacing without punctuation separators', async () => {
    setJwt(11, ['admin', 'salesperson'], 'Multi Role Test');

    render(<MemoryRouter><App /></MemoryRouter>);
    fireEvent.click((await screen.findByRole('img', { name: 'menu-unfold' })).closest('button'));

    expect(await screen.findByText('管理员')).toHaveStyle({ whiteSpace: 'nowrap' });
    expect(screen.getByText('业务员')).toHaveStyle({ whiteSpace: 'nowrap' });
    expect(screen.queryByText('，')).not.toBeInTheDocument();
});

test('clicking receipt management advances an active onboarding flow', async () => {
    setJwt(2, ['salesperson'], 'Sales Test');
    window.sessionStorage.setItem('wms:tour-flow:2', JSON.stringify({
        campaignId: 'cost-quote-receipt',
        stage: 'receipt-navigation',
    }));

    render(<MemoryRouter initialEntries={['/orders/example']}><App/></MemoryRouter>);
    fireEvent.click(await screen.findByText('收款管理'));

    expect(JSON.parse(window.sessionStorage.getItem('wms:tour-flow:2'))).toMatchObject({
        stage: 'receipt-entry',
    });
});

test('first login offers to start the new feature onboarding', async () => {
    setJwt(3, ['salesperson']);

    render(<MemoryRouter><App /></MemoryRouter>);

    await waitFor(() => expect(shouldAutoShowFeatureTour).toHaveBeenCalled());
    expect(await screen.findByText('发现新功能：成本报价与收款管理')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '立即了解' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '稍后了解' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '打开新功能引导中心' })).toBeInTheDocument();
});

test('starting immediately enters order selection and records the prompt decision', async () => {
    setJwt(4, ['salesperson']);
    render(<MemoryRouter><App /></MemoryRouter>);

    fireEvent.click(await screen.findByRole('button', { name: '立即了解' }));

    expect(JSON.parse(window.sessionStorage.getItem('wms:tour-flow:4'))).toMatchObject({
        campaignId: 'cost-quote-receipt',
        stage: 'select-quote-order',
    });
    expect(readFeatureTourState('4').campaigns['cost-quote-receipt'].chapters['workflow-start'])
        .toMatchObject({ status: 'completed', version: 1 });
});

test('finance starts with receipt audit and can open the global feature center', async () => {
    setJwt(6, ['finance']);
    render(<MemoryRouter initialEntries={['/finance']}><App /></MemoryRouter>);

    expect(await screen.findByText('依次了解收款审核和应收账款台账。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '打开新功能引导中心' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '立即了解' }));

    expect(JSON.parse(window.sessionStorage.getItem('wms:tour-flow:6'))).toMatchObject({
        stage: 'receipt-audit',
    });
});

test('admin follows the salesperson onboarding path instead of the finance path', async () => {
    setJwt(7, ['admin']);
    render(<MemoryRouter><App /></MemoryRouter>);

    expect(await screen.findByText('选择一笔由你负责的订单，依次了解订单报价和收款登记。')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '立即了解' }));

    expect(JSON.parse(window.sessionStorage.getItem('wms:tour-flow:7'))).toMatchObject({
        stage: 'select-quote-order',
    });
});

test('postponing points to the menu help and the menu can start the full onboarding later', async () => {
    setJwt(5, ['salesperson']);
    render(<MemoryRouter><App /></MemoryRouter>);

    fireEvent.click(await screen.findByRole('button', { name: '稍后了解' }));

    expect(await screen.findByText('稍后从这里开始')).toBeInTheDocument();
    expect(readFeatureTourState('5').campaigns['cost-quote-receipt'].chapters['workflow-start'])
        .toMatchObject({ status: 'dismissed', version: 1 });

    fireEvent.click(screen.getByRole('button', { name: '打开新功能引导中心' }));
    const startLater = await screen.findByRole('button', { name: '开始“成本报价与收款管理”引导' });
    fireEvent.click(startLater);

    await waitFor(() => expect(JSON.parse(window.sessionStorage.getItem('wms:tour-flow:5'))).toMatchObject({
        stage: 'select-quote-order',
    }));
});
