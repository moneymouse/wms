// 角色定义
export const ROLES = {
    ADMIN: 'admin',
    STORE_MANAGER: 'store_manager',
    SALESPERSON: 'salesperson',
    CLERK: 'clerk',
    FINANCE: 'finance',
    WORKER: 'worker'
};

export const ROLE_LABEL_MAP = {
    admin: '管理员',
    store_manager: '店长',
    salesperson: '业务员',
    clerk: '文员',
    finance: '财务',
    worker: '操作人员'
};

// 菜单配置：key -> 可见角色列表
export const menuPermissions = {
    '': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.SALESPERSON, ROLES.CLERK], // 创建订单
    'orders': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.SALESPERSON, ROLES.CLERK, ROLES.FINANCE], // 订单列表
    'upload': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.CLERK], // 上传明细
    'customers': [ROLES.ADMIN, ROLES.STORE_MANAGER], // 客户管理
    'packing-list/new': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.SALESPERSON, ROLES.WORKER], // 创建装箱单
    'packing-lists': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.SALESPERSON, ROLES.CLERK, ROLES.FINANCE], // 装箱单列表
    'work-details': [ROLES.ADMIN, ROLES.FINANCE, ROLES.WORKER], // 工作详情
    'bonus': [ROLES.ADMIN, ROLES.FINANCE, ROLES.WORKER], // 奖金
    'finance': [ROLES.ADMIN, ROLES.FINANCE], // 财务配置与汇总
    'cost-management': [ROLES.ADMIN, ROLES.STORE_MANAGER], // 渠道成本管理
    'logs': [ROLES.ADMIN], // 操作日志
    'audit-logs': [ROLES.ADMIN], // 审计日志
    'admin': [ROLES.ADMIN], // 用户申请
    'settings': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.SALESPERSON, ROLES.CLERK, ROLES.FINANCE, ROLES.WORKER], // 设置（所有角色）
};

// 路由权限配置
export const routePermissions = {
    '/': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.SALESPERSON, ROLES.CLERK],
    '/orders': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.SALESPERSON, ROLES.CLERK, ROLES.FINANCE],
    '/orders/:order_id': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.SALESPERSON, ROLES.CLERK, ROLES.FINANCE],
    '/upload': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.CLERK],
    '/customers': [ROLES.ADMIN, ROLES.STORE_MANAGER],
    '/packing-list/new': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.SALESPERSON, ROLES.WORKER],
    '/packing-lists': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.SALESPERSON, ROLES.WORKER, ROLES.CLERK, ROLES.FINANCE],
    '/work-details': [ROLES.ADMIN, ROLES.FINANCE, ROLES.WORKER],
    '/bonus': [ROLES.ADMIN, ROLES.FINANCE, ROLES.WORKER],
    '/bonus-estimate': [ROLES.ADMIN, ROLES.FINANCE, ROLES.WORKER],
    '/finance': [ROLES.ADMIN, ROLES.FINANCE],
    '/cost-management': [ROLES.ADMIN, ROLES.STORE_MANAGER],
    '/logs': [ROLES.ADMIN],
    '/audit-logs': [ROLES.ADMIN],
    '/admin': [ROLES.ADMIN],
    '/settings': [ROLES.ADMIN, ROLES.STORE_MANAGER, ROLES.SALESPERSON, ROLES.CLERK, ROLES.FINANCE, ROLES.WORKER], // 设置
};

// 权限检查函数：用户角色集合与允许角色集合交集非空时通过
export const hasPermission = (userRoles, allowedRoles) => {
    const userRoleSet = new Set(Array.isArray(userRoles) ? userRoles : [userRoles]);
    const allowedRoleSet = new Set(allowedRoles);
    for (const role of userRoleSet) {
        if (allowedRoleSet.has(role)) return true;
    }
    return false;
};

// 着陆页配置：角色 -> 默认着陆页
export const landingPages = {
    [ROLES.ADMIN]: '/',
    [ROLES.STORE_MANAGER]: '/',
    [ROLES.SALESPERSON]: '/',
    [ROLES.CLERK]: '/orders',
    [ROLES.FINANCE]: '/finance',
    [ROLES.WORKER]: '/work-details',
};

// 获取角色着陆页：传入角色数组时，返回第一个匹配角色的着陆页
export const getLandingPage = (userRoles) => {
    const roles = Array.isArray(userRoles) ? userRoles : [userRoles];
    for (const role of roles) {
        if (landingPages[role]) {
            return landingPages[role];
        }
    }
    return '/orders';
};
