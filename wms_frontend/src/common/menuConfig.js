import { hasPermission, menuPermissions } from './roleConfig';

export const MENU_GROUPS = [
    { key: 'order-management', label: '订单管理', pages: ['', 'orders', 'order-exceptions', 'upload'] },
    { key: 'warehouse-management', label: '仓储管理', pages: ['packing-list/new', 'packing-lists'] },
    { key: 'customer-management', label: '客户管理', pages: ['customers'] },
    { key: 'finance-center', label: '财务中心', pages: ['receipts', 'finance', 'cost-management'] },
    { key: 'log-center', label: '日志中心', pages: ['logs', 'audit-logs'] },
    { key: 'management-center', label: '管理中心', pages: ['admin', 'storage-management'] },
    { key: 'personal-center', label: '个人中心', pages: ['work-details', 'bonus'] },
];

export function buildMenuItems(pages, userRoles, groupIcons = {}) {
    const allowedPages = new Map(pages
        .filter(page => menuPermissions[page.key] && hasPermission(userRoles, menuPermissions[page.key]))
        .map(page => [page.key, page]));
    const groups = MENU_GROUPS.map(({ key, label, pages: pageKeys }) => ({
        key,
        label,
        icon: groupIcons[key],
        children: pageKeys.map(pageKey => allowedPages.get(pageKey)).filter(Boolean),
    })).filter(group => group.children.length > 0);
    const settings = allowedPages.get('settings');
    return settings ? [...groups, settings] : groups;
}

export function getSelectedMenuKey(pathname) {
    const currentPath = pathname.replace(/^\//, '');
    if (currentPath.startsWith('orders/')) return 'orders';
    if (currentPath.startsWith('packing-list/')) return 'packing-list/new';
    if (currentPath.startsWith('packing-lists/')) return 'packing-lists';
    if (currentPath === 'shipping-confirmation-drafts' || currentPath.startsWith('shipping-confirmation-drafts/')) return 'packing-lists';
    if (currentPath === 'bonus-estimate' || currentPath.startsWith('bonus-estimate/') || currentPath.startsWith('bonus/')) return 'bonus';
    return currentPath;
}

export function getSelectedMenuGroup(menuItems, selectedKey) {
    return menuItems.find(item => item.children?.some(child => child.key === selectedKey))?.key;
}
