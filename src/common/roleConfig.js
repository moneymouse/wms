// 角色定义
export const ROLES = {
    ADMIN: 'admin',
    STORE_MANAGER: 'store_manager',
    SALESPERSON: 'salesperson',
    CLERK: 'clerk',
    FINANCE: 'finance'
};

// 菜单配置：key -> 可见角色列表
export const menuPermissions = {
    '': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.SALESPERSON], // 创建订单
    'orders': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.SALESPERSON, ROLES.CLERK, ROLES.FINANCE], // 订单列表
    'upload': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.CLERK], // 上传明细
    'customers': [ROLES.ADMIN, ROLES.STORE_MANAGER], // 客户管理
    'logs': [ROLES.ADMIN], // 操作日志
    'admin': [ROLES.ADMIN], // 用户申请
};

// 路由权限配置
export const routePermissions = {
    '/': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.SALESPERSON],
    '/orders': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.SALESPERSON, ROLES.CLERK, ROLES.FINANCE],
    '/orders/:order_id': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.SALESPERSON, ROLES.CLERK, ROLES.FINANCE],
    '/upload': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.CLERK],
    '/customers': [ROLES.ADMIN, ROLES.STORE_MANAGER],
    '/logs': [ROLES.ADMIN],
    '/admin': [ROLES.ADMIN],
};

// 权限检查函数
export const hasPermission = (userRole, allowedRoles) => {
    return allowedRoles.includes(userRole);
};

// 着陆页配置：角色 -> 默认着陆页
export const landingPages = {
    [ROLES.ADMIN]: '/',
    [ROLES.STORE_MANAGER]: '/',
    [ROLES.SALESPERSON]: '/',
    [ROLES.CLERK]: '/orders',
    [ROLES.FINANCE]: '/orders',
};

// 获取角色着陆页
export const getLandingPage = (userRole) => {
    return landingPages[userRole] || '/orders';
};
