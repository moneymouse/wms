import React, { useState, useEffect } from 'react';
import {
    MenuFoldOutlined,
    MenuUnfoldOutlined,
    PlusSquareOutlined,
    UnorderedListOutlined,
    UploadOutlined,
    TeamOutlined,
    InboxOutlined,
    ContainerOutlined,
    UserOutlined,
    LogoutOutlined,
    SettingOutlined,
    MenuOutlined,
    SolutionOutlined,
    GiftOutlined,
    AccountBookOutlined,
    ToolOutlined,
    DollarOutlined,
    AuditOutlined
} from '@ant-design/icons';
import { Avatar, Button, Layout, Menu, theme, Tooltip, Drawer, Grid } from 'antd';
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { LogIcon } from "./pages/logs";
import { menuPermissions, routePermissions, hasPermission, getLandingPage, ROLE_LABEL_MAP } from "./common/roleConfig";

const { Header, Sider, Content } = Layout;
const { useBreakpoint } = Grid;

function App() {
    const screens = useBreakpoint();
    const isMobile = screens.md === false;
    const [drawerVisible, setDrawerVisible] = useState(false);

    const [collapsed, setCollapsed] = useState(true);
    const [userRoles, setUserRoles] = useState([]);
    const [username, setUsername] = useState('');
    const {
        token: { colorBgContainer },
    } = theme.useToken();

    const { pathname } = useLocation();
    const navigate = useNavigate();

    const getSelectedMenuKey = () => {
        const currentPath = pathname.replace(/^\//, '');
        if (currentPath === '') return '';
        if (currentPath.startsWith('orders/')) return 'orders';
        if (currentPath.startsWith('packing-list/')) return 'packing-list/new';
        if (currentPath.startsWith('bonus-estimate')) return 'bonus';
        if (currentPath.startsWith('bonus')) return 'bonus';
        return currentPath;
    };

    useEffect(() => {
        // 从 localStorage 获取 JWT 并检查用户角色
        const jwt = localStorage.getItem('jwt');
        if (!jwt) navigate("/login");
        try {
            // 分割 JWT 并获取负载部分（第二部分）
            const parts = jwt.split('.');
            if (parts.length === 3) {
                // 解码 base64 编码的负载
                const payload = JSON.parse(atob(parts[1]));
                const roles = payload.roles || (payload.role ? [payload.role] : []);
                // 设置用户角色
                setUserRoles(roles);
                setUsername(payload.name || payload.username || payload.phone || '');

                // 检查当前路由权限，无权限则重定向到着陆页
                const currentPath = pathname === '' ? '/' : pathname;
                const routeKey = Object.keys(routePermissions).find(key => {
                    if (key.includes(':')) {
                        // 处理动态路由如 /orders/:order_id
                        const pattern = key.replace(/:[^/]+/g, '[^/]+');
                        return new RegExp(`^${pattern}$`).test(currentPath);
                    }
                    return key === currentPath;
                });

                if (routeKey && !hasPermission(roles, routePermissions[routeKey])) {
                    navigate(getLandingPage(roles));
                }
            }
        } catch (e) {
            console.error('解析 JWT 时出错:', e);
            setUserRoles([]);
            setUsername('');
            navigate("/login")
        }
    }, [pathname, navigate]);

    const handleLogout = () => {
        localStorage.removeItem('jwt');
        setUserRoles([]);
        setUsername('');
        navigate('/login');
    };

    // 根据用户角色构建菜单项
    const allMenuItems = [
        {
            key: '',
            icon: <PlusSquareOutlined />,
            label: '创建新订单',
        },
        {
            key: 'orders',
            icon: <UnorderedListOutlined />,
            label: '订单列表',
        },
        {
            key: 'upload',
            icon: <UploadOutlined />,
            label: '上传明细'
        },
        {
            key: 'customers',
            icon: <TeamOutlined />,
            label: '客户管理',
        },
        {
            key: 'packing-list/new',
            icon: <InboxOutlined />,
            label: '创建装箱单',
        },
        {
            key: 'packing-lists',
            icon: <ContainerOutlined />,
            label: '装箱单列表',
        },
        {
            key: 'work-details',
            icon: <SolutionOutlined />,
            label: '工作详情',
        },
        {
            key: 'bonus',
            icon: <GiftOutlined />,
            label: '奖金',
        },
        {
            key: 'finance',
            icon: <AccountBookOutlined />,
            label: '财务',
        },
        {
            key: 'cost-management',
            icon: <DollarOutlined />,
            label: '成本管理',
        },
        {
            key: 'logs',
            label: '操作日志',
            icon: <LogIcon />,
        },
        {
            key: 'audit-logs',
            label: '审计日志',
            icon: <AuditOutlined />,
        },
        {
            key: 'admin',
            label: '管理',
            icon: <ToolOutlined />,
        },
        {
            key: 'settings',
            label: '设置',
            icon: <SettingOutlined />,
        }
    ];

    // 根据用户角色过滤菜单项
    const menuItems = allMenuItems.filter(item =>
        menuPermissions[item.key] && hasPermission(userRoles, menuPermissions[item.key])
    );

    const siderContent = (
        <>
            {!isMobile && (
                <Header style={{ padding: 0 }}>
                    <Button
                        type="link"
                        icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
                        onClick={() => setCollapsed(!collapsed)}
                        style={{
                            fontSize: '12px',
                            width: !collapsed ? 191 : 72,
                            height: 40,
                            margin: '0 4px',
                            paddingRight: !collapsed ? 127 : 0
                        }}
                    />
                </Header>
            )}
            <Menu
                theme="dark"
                mode="inline"
                selectedKeys={[getSelectedMenuKey()]}
                onClick={({ key }) => {
                    navigate(key);
                    if (isMobile) setDrawerVisible(false);
                }}
                style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}
                items={menuItems}
            />
            <div
                style={{
                    padding: (!isMobile && collapsed) ? '16px 8px' : '16px',
                    borderTop: '1px solid rgba(255,255,255,0.08)',
                    display: 'flex',
                    flexDirection: (!isMobile && collapsed) ? 'column' : 'row',
                    alignItems: 'center',
                    justifyContent: (!isMobile && collapsed) ? 'center' : 'space-between',
                    gap: (!isMobile && collapsed) ? '16px' : '12px',
                    color: 'rgba(255,255,255,0.85)',
                    transition: 'all 0.3s',
                    background: '#001529'
                }}
            >
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', overflow: 'hidden' }}>
                    <Avatar size={32} icon={<UserOutlined />} style={{ flexShrink: 0, backgroundColor: 'rgba(255,255,255,0.15)' }} />
                    {(isMobile || !collapsed) && (
                        <div style={{ lineHeight: 1.4, overflow: 'hidden', whiteSpace: 'nowrap' }}>
                            <div style={{ fontSize: 14, fontWeight: 500, textOverflow: 'ellipsis', overflow: 'hidden' }}>{username || '未知用户'}</div>
                            <div style={{ fontSize: 12, opacity: 0.65, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                                {userRoles.length > 0
                                    ? userRoles.map(role => <span key={role}>{ROLE_LABEL_MAP[role] || role}</span>).reduce((prev, curr) => [prev, '，', curr])
                                    : '未登录'
                                }
                            </div>
                        </div>
                    )}
                </div>
                <Tooltip title="退出登录" placement={(!isMobile && collapsed) ? "right" : "top"}>
                    <Button
                        type="text"
                        icon={<LogoutOutlined />}
                        onClick={handleLogout}
                        style={{
                            color: 'rgba(255,255,255,0.65)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            width: 32,
                            height: 32,
                            padding: 0,
                            flexShrink: 0,
                            borderRadius: '6px'
                        }}
                        onMouseEnter={(e) => {
                            e.currentTarget.style.color = '#ff4d4f';
                            e.currentTarget.style.backgroundColor = 'rgba(255,77,79,0.15)';
                        }}
                        onMouseLeave={(e) => {
                            e.currentTarget.style.color = 'rgba(255,255,255,0.65)';
                            e.currentTarget.style.backgroundColor = 'transparent';
                        }}
                    />
                </Tooltip>
            </div>
        </>
    );

    return (
        <Layout>
            {!isMobile ? (
                <Sider
                    trigger={null}
                    collapsible
                    collapsed={collapsed}
                    breakpoint="lg"
                    onBreakpoint={(broken) => {
                        setCollapsed(broken);
                    }}
                    collapsedWidth={80}
                    style={{
                        height: '100vh',
                        position: 'sticky',
                        top: 0,
                        left: 0,
                        zIndex: 100,
                        display: 'flex',
                        flexDirection: 'column'
                    }}
                >
                    {siderContent}
                </Sider>
            ) : (
                <Drawer
                    styles={{ body: { padding: 0, display: 'flex', flexDirection: 'column', backgroundColor: '#001529' } }}
                    placement="left"
                    closable={false}
                    onClose={() => setDrawerVisible(false)}
                    open={drawerVisible}
                    width={250}
                >
                    {siderContent}
                </Drawer>
            )}
            <Layout style={{
                overflowY: 'auto',
                maxHeight: '100vh'
            }}>
                {isMobile && (
                    <Header style={{
                        padding: '0 16px',
                        display: 'flex',
                        alignItems: 'center',
                        background: '#001529',
                        position: 'sticky',
                        top: 0,
                        zIndex: 100
                    }}>
                        <Button
                            type="text"
                            icon={<MenuOutlined style={{ color: 'white', fontSize: '18px' }} />}
                            onClick={() => setDrawerVisible(true)}
                            style={{ padding: 0, width: 40, height: 40, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                        />
                        <div style={{ color: 'white', marginLeft: 16, fontSize: '18px', fontWeight: 500 }}>
                            WMS 管理系统
                        </div>
                    </Header>
                )}
                <Content
                    style={{
                        margin: isMobile ? '16px' : '24px 16px',
                        padding: isMobile ? '16px' : '0 24px',
                        minHeight: '100vh',
                        background: colorBgContainer,
                        overflowX: 'hidden',
                        overflowY: 'auto'
                    }}
                >
                    <Outlet />
                </Content>
            </Layout>
        </Layout>
    );
}

export default App;
