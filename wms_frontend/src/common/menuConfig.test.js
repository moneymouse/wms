import { buildMenuItems, getSelectedMenuGroup, getSelectedMenuKey } from './menuConfig';
import { menuPermissions } from './roleConfig';

const pages = Object.keys(menuPermissions).map(key => ({ key, label: key || '创建新订单' }));
const leafKeys = items => items.flatMap(item => item.children ? item.children.map(child => child.key) : [item.key]);

test('admin sees seven centers in order and a final standalone settings item', () => {
    const items = buildMenuItems(pages, ['admin']);
    expect(items.map(item => item.label)).toEqual([
        '订单管理', '仓储管理', '客户管理', '财务中心', '日志中心', '管理中心', '个人中心', 'settings',
    ]);
    expect(items[2].children.map(item => item.key)).toEqual(['customers']);
    expect(items[3].children.map(item => item.key)).toEqual(['receipts', 'finance', 'cost-management']);
    expect(items[4].children.map(item => item.key)).toEqual(['logs', 'audit-logs']);
    expect(items[5].children.map(item => item.key)).toEqual(['admin', 'storage-management']);
    expect(items[7].children).toBeUndefined();
    expect(new Set(leafKeys(items))).toEqual(new Set(Object.keys(menuPermissions)));
    expect(leafKeys(items)).toHaveLength(Object.keys(menuPermissions).length);
});

test.each([
    ['clerk', ['order-management', 'warehouse-management', 'settings'], ['', 'orders', 'order-exceptions', 'upload', 'packing-lists', 'settings']],
    ['worker', ['warehouse-management', 'personal-center', 'settings'], ['packing-list/new', 'packing-lists', 'work-details', 'bonus', 'settings']],
    ['employee', ['warehouse-management'], ['packing-list/new', 'packing-lists']],
    ['finance', ['order-management', 'warehouse-management', 'finance-center', 'personal-center', 'settings'], ['orders', 'packing-lists', 'receipts', 'finance', 'work-details', 'bonus', 'settings']],
])('%s keeps its existing allowed pages and sees no empty group', (role, groupKeys, expectedPages) => {
    const items = buildMenuItems(pages, [role]);
    expect(items.map(item => item.key)).toEqual(groupKeys);
    expect(leafKeys(items)).toEqual(expectedPages);
});

test('combined roles retain allowed pages without duplicating entries', () => {
    const items = buildMenuItems(pages, ['salesperson', 'finance']);
    expect(items.map(item => item.key)).toEqual(['order-management', 'warehouse-management', 'customer-management', 'finance-center', 'personal-center', 'settings']);
    expect(leafKeys(items)).toContain('customers');
    expect(leafKeys(items)).toContain('finance');
    expect(leafKeys(items)).not.toContain('cost-management');
    expect(leafKeys(items)).not.toContain('logs');
    expect(leafKeys(items)).toHaveLength(new Set(leafKeys(items)).size);
});

test('unauthorized or unknown pages and their empty groups are removed', () => {
    expect(buildMenuItems([...pages, { key: 'unknown', label: 'Unknown' }], [])).toEqual([]);
});

test.each([
    ['/', '', 'order-management'],
    ['/orders/example', 'orders', 'order-management'],
    ['/order-exceptions', 'order-exceptions', 'order-management'],
    ['/packing-list/upload/example', 'packing-list/new', 'warehouse-management'],
    ['/packing-lists/example', 'packing-lists', 'warehouse-management'],
    ['/shipping-confirmation-drafts', 'packing-lists', 'warehouse-management'],
    ['/shipping-confirmation-drafts/example', 'packing-lists', 'warehouse-management'],
    ['/bonus-estimate', 'bonus', 'personal-center'],
    ['/receipts', 'receipts', 'finance-center'],
    ['/settings', 'settings', undefined],
])('%s highlights its existing leaf and enclosing group', (path, leaf, group) => {
    const selectedKey = getSelectedMenuKey(path);
    expect(selectedKey).toBe(leaf);
    expect(getSelectedMenuGroup(buildMenuItems(pages, ['admin']), selectedKey)).toBe(group);
});
