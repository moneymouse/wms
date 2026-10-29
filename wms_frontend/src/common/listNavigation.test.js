import { getListNavigationUser, getRememberedListUrl, rememberListLocation } from './listNavigation';

const admin = { userId: '7', roles: ['admin'] };
const memoryStorage = () => {
    const values = new Map();
    return { getItem: jest.fn(key => values.get(key) || null), setItem: jest.fn((key, value) => values.set(key, value)) };
};

test('remembers filters and hash per user and list, without serializing editor state', () => {
    const storage = memoryStorage();
    rememberListLocation({ pathname: '/receipts', search: '?tab=receivable&q=XD-001', hash: '#results', state: { paymentContext: { customerId: 2 } } }, admin, storage);
    expect(getRememberedListUrl('/receipts', admin, storage)).toBe('/receipts?tab=receivable&q=XD-001#results');
    expect(getRememberedListUrl('/orders', admin, storage)).toBe('/orders');
    expect(getRememberedListUrl('/receipts', { ...admin, userId: '8' }, storage)).toBe('/receipts');
    expect(storage.setItem.mock.calls[0][1]).not.toContain('paymentContext');
    expect(storage.setItem.mock.calls[0][1]).not.toContain('customerId');
});

test('opening or clearing an explicit list URL replaces its remembered filters', () => {
    const storage = memoryStorage();
    rememberListLocation({ pathname: '/orders', search: '?q=old' }, admin, storage);
    rememberListLocation({ pathname: '/orders', search: '?q=new' }, admin, storage);
    expect(getRememberedListUrl('/orders', admin, storage)).toBe('/orders?q=new');
    rememberListLocation({ pathname: '/orders' }, admin, storage);
    expect(getRememberedListUrl('/orders', admin, storage)).toBe('/orders');
});

test('menu destinations retain filters while omitting transient detail links', () => {
    const storage = memoryStorage();
    rememberListLocation({ pathname: '/receipts', search: '?tab=receivable&payment_id=8&q=XD-001' }, admin, storage);
    expect(getRememberedListUrl('/receipts', admin, storage)).toBe('/receipts?tab=receivable&q=XD-001');
    rememberListLocation({ pathname: '/order-exceptions', search: '?exception_uid=example&status=open&custom=value' }, admin, storage);
    expect(getRememberedListUrl('/order-exceptions', admin, storage)).toBe('/order-exceptions?status=open&custom=value');
});

test('only approved list paths and authorized actors can save or restore URLs', () => {
    const storage = memoryStorage();
    for (const pathname of ['/', '/settings', '/login', '/orders/123', '/packing-list/new', '//evil.example/orders', 'https://evil.example/orders']) {
        expect(rememberListLocation({ pathname, search: '?q=x' }, admin, storage)).toBe(false);
        expect(getRememberedListUrl(pathname, admin, storage)).toBe(pathname);
    }
    expect(storage.setItem).not.toHaveBeenCalled();
    rememberListLocation({ pathname: '/finance', search: '?financeTab=payments' }, admin, storage);
    expect(getRememberedListUrl('/finance', { ...admin, roles: ['salesperson'] }, storage)).toBe('/finance');
    expect(rememberListLocation({ pathname: '/finance', search: '?q=x' }, { ...admin, roles: ['worker'] }, storage)).toBe(false);
    expect(rememberListLocation({ pathname: '/orders', search: '?q=x' }, { ...admin, userId: null }, storage)).toBe(false);
});

test('rejects corrupted and redirected stored targets', () => {
    const storage = memoryStorage();
    rememberListLocation({ pathname: '/orders', search: '?q=x' }, admin, storage);
    const key = storage.setItem.mock.calls[0][0];
    for (const value of ['not-json', JSON.stringify({ pathname: '/finance', search: '?q=x', hash: '' }), JSON.stringify({ pathname: '/orders', search: '//evil.example', hash: '' }), JSON.stringify({ pathname: '/orders', search: '?q=x', hash: '\n#x' })]) {
        storage.setItem(key, value);
        expect(getRememberedListUrl('/orders', admin, storage)).toBe('/orders');
    }
});

test('storage failures degrade to ordinary navigation', () => {
    const storage = { getItem: () => { throw new Error('Storage blocked'); }, setItem: () => { throw new Error('Quota exceeded'); } };
    expect(rememberListLocation({ pathname: '/orders', search: '?q=x' }, admin, storage)).toBe(false);
    expect(getRememberedListUrl('/orders', admin, storage)).toBe('/orders');
    expect(getListNavigationUser(storage)).toEqual({ userId: null, roles: [] });
});

test('reads the current account and merged role formats at menu navigation time', () => {
    const storage = memoryStorage();
    const jwt = payload => `header.${window.btoa(JSON.stringify(payload))}.signature`;
    storage.setItem('jwt', jwt({ user_id: 7, role: 'finance', roles: ['salesperson'] }));
    expect(getListNavigationUser(storage)).toEqual({ userId: 7, roles: ['salesperson', 'finance'] });
    storage.setItem('jwt', jwt({ user_id: 8, roles: ['worker'] }));
    expect(getListNavigationUser(storage)).toEqual({ userId: 8, roles: ['worker'] });
    storage.setItem('jwt', 'invalid');
    expect(getListNavigationUser(storage)).toEqual({ userId: undefined, roles: [] });
});

test('bonus aliases share a remembered list URL', () => {
    const storage = memoryStorage();
    rememberListLocation({ pathname: '/bonus-estimate', search: '?month=2026-09' }, admin, storage);
    expect(getRememberedListUrl('/bonus', admin, storage)).toBe('/bonus?month=2026-09');
});
