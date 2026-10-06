import React, { useState, useEffect, useRef } from 'react';
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
    AuditOutlined,
    TransactionOutlined,
    QuestionCircleOutlined
} from '@ant-design/icons';
import { Avatar, Button, Layout, Menu, theme, Tooltip, Drawer, Grid, Modal, Popover, Space, Tour } from 'antd';
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { LogIcon } from "./pages/logs";
import { menuPermissions, routePermissions, hasPermission, getUserRoles, getLandingPage, ROLE_LABEL_MAP } from "./common/roleConfig";
import {
    COST_QUOTE_RECEIPT_TOUR,
    getCostQuoteReceiptChapter,
    getCostQuoteReceiptOnboardingFlow,
} from "./common/featureTourConfig";
import {
    FEATURE_TOUR_FLOW_EVENT,
    clearFeatureTourFlow,
    getCurrentTourUser,
    readFeatureTourFlow,
    readFeatureTourState,
    saveFeatureTourChapterState,
    saveFeatureTourFlow,
    shouldAutoShowFeatureTour,
} from "./common/featureTourState";

const { Header, Sider, Content } = Layout;
const { useBreakpoint } = Grid;
const workflowStartTourChapter = getCostQuoteReceiptChapter('workflowStart');

function App() {
    const screens = useBreakpoint();
    const isMobile = screens.md === false;
    const [drawerVisible, setDrawerVisible] = useState(false);

    const [collapsed, setCollapsed] = useState(true);
    const [userRoles, setUserRoles] = useState([]);
    const [username, setUsername] = useState('');
    const [featurePromptOpen, setFeaturePromptOpen] = useState(false);
    const [featureHelpHintOpen, setFeatureHelpHintOpen] = useState(false);
    const [featureCenterOpen, setFeatureCenterOpen] = useState(false);
    const checkedFeaturePromptUser = useRef(null);
    const {
        token: { colorBgContainer },
    } = theme.useToken();

    const { pathname } = useLocation();
    const isFinancePage = pathname === '/finance' || pathname === '/receipts';
    const navigate = useNavigate();
    const { userId: tourUserId } = getCurrentTourUser();
    const onboardingFlow = COST_QUOTE_RECEIPT_TOUR.enabled ? getCostQuoteReceiptOnboardingFlow(userRoles) : null;

    useEffect(() => {
        const handleTourFlowChange = (event) => {
            if (isMobile && event.detail?.stage === 'receipt-navigation') {
                setDrawerVisible(true);
            }
        };
        window.addEventListener(FEATURE_TOUR_FLOW_EVENT, handleTourFlowChange);
        return () => window.removeEventListener(FEATURE_TOUR_FLOW_EVENT, handleTourFlowChange);
    }, [isMobile]);

    const getSelectedMenuKey = () => {
        const currentPath = pathname.replace(/^\//, '');
        if (currentPath === '') return '';
        if (currentPath.startsWith('orders/')) return 'orders';
        if (currentPath.startsWith('packing-list/')) return 'packing-list/new';
        if (currentPath.startsWith('packing-lists/')) return 'packing-lists';
        if (currentPath === 'shipping-confirmation-drafts' || currentPath.startsWith('shipping-confirmation-drafts/')) return 'packing-lists';
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
                const roles = getUserRoles(payload);
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

    useEffect(() => {
        if (!tourUserId || !onboardingFlow) return;
        if (checkedFeaturePromptUser.current === tourUserId) return;
        checkedFeaturePromptUser.current = tourUserId;

        const activeFlow = readFeatureTourFlow(tourUserId);
        if (activeFlow?.campaignId === COST_QUOTE_RECEIPT_TOUR.id) return;

        const state = readFeatureTourState(tourUserId);
        if (shouldAutoShowFeatureTour({
            campaign: COST_QUOTE_RECEIPT_TOUR,
            chapter: workflowStartTourChapter,
            state,
            userRoles,
        })) {
            setFeaturePromptOpen(true);
        }
    }, [onboardingFlow, tourUserId, userRoles]);

    const saveFeaturePromptDecision = (status) => {
        saveFeatureTourChapterState({
            userId: tourUserId,
            campaignId: COST_QUOTE_RECEIPT_TOUR.id,
            chapterId: workflowStartTourChapter.id,
            version: workflowStartTourChapter.version,
            status,
        });
    };

    const startCostQuoteReceiptTour = () => {
        if (!onboardingFlow) return;
        saveFeaturePromptDecision('completed');
        setFeaturePromptOpen(false);
        setFeatureHelpHintOpen(false);
        setFeatureCenterOpen(false);
        saveFeatureTourFlow({
            userId: tourUserId,
            campaignId: COST_QUOTE_RECEIPT_TOUR.id,
            stage: onboardingFlow.startStage,
        });
        navigate(onboardingFlow.startPath, {
            state: { featureTourCampaign: COST_QUOTE_RECEIPT_TOUR.id },
        });
        if (isMobile) setDrawerVisible(false);
    };

    const postponeCostQuoteReceiptTour = () => {
        saveFeaturePromptDecision('dismissed');
        setFeaturePromptOpen(false);
        if (isMobile) setDrawerVisible(true);
        window.setTimeout(() => setFeatureHelpHintOpen(true), isMobile ? 350 : 0);
    };

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
            label: userRoles.some(role => ['worker', 'employee'].includes(role)) && !userRoles.some(role => ['admin', 'store_manager', 'salesperson', 'clerk', 'finance'].includes(role)) ? '我的装箱单' : '装箱单列表',
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
            key: 'receipts',
            icon: <TransactionOutlined />,
            label: '收付款',
            className: 'tour-receipts-menu',
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
                    if (key === 'receipts') {
                        const { userId } = getCurrentTourUser();
                        const flow = readFeatureTourFlow(userId);
                        if (flow?.campaignId === COST_QUOTE_RECEIPT_TOUR.id) clearFeatureTourFlow(userId);
                    }
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
                                    ? userRoles.map(role => (
                                        <span key={role} style={{ whiteSpace: 'nowrap' }}>
                                            {ROLE_LABEL_MAP[role] || role}
                                        </span>
                                    ))
                                    : '未登录'
                                }
                            </div>
                        </div>
                    )}
                </div>
                <Space direction={(!isMobile && collapsed) ? 'vertical' : 'horizontal'} size={8}>
                    {onboardingFlow && (
                        <Popover
                            open={featureCenterOpen}
                            onOpenChange={setFeatureCenterOpen}
                            trigger="click"
                            placement={(!isMobile && collapsed) ? 'rightBottom' : 'topRight'}
                            title="新功能引导"
                            content={(
                                <div style={{ width: 240 }}>
                                    <div style={{ marginBottom: 10, color: 'rgba(0,0,0,0.65)' }}>
                                        {onboardingFlow.description}
                                    </div>
                                    <Button type="primary" block onClick={startCostQuoteReceiptTour}>
                                        开始“{COST_QUOTE_RECEIPT_TOUR.name}”引导
                                    </Button>
                                </div>
                            )}
                        >
                            <Tooltip title="新功能引导" placement={(!isMobile && collapsed) ? "right" : "top"}>
                                <Button
                                    className="tour-new-feature-help"
                                    aria-label="打开新功能引导中心"
                                    type="text"
                                    icon={<QuestionCircleOutlined />}
                                    onClick={() => setFeatureHelpHintOpen(false)}
                                    style={{ color: 'rgba(255,255,255,0.72)', width: 32, height: 32, padding: 0 }}
                                />
                            </Tooltip>
                        </Popover>
                    )}
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
                </Space>
            </div>
        </>
    );

    return (
        <Layout>
            <Modal
                open={featurePromptOpen}
                title={`发现新功能：${COST_QUOTE_RECEIPT_TOUR.name}`}
                onCancel={postponeCostQuoteReceiptTour}
                maskClosable={false}
                footer={[
                    <Button key="later" onClick={postponeCostQuoteReceiptTour}>稍后了解</Button>,
                    <Button key="start" type="primary" onClick={startCostQuoteReceiptTour}>立即了解</Button>,
                ]}
            >
                <p>{COST_QUOTE_RECEIPT_TOUR.summary}</p>
                <p>{onboardingFlow?.description}</p>
            </Modal>
            <Tour
                open={featureHelpHintOpen}
                disabledInteraction={false}
                onClose={() => setFeatureHelpHintOpen(false)}
                onFinish={() => setFeatureHelpHintOpen(false)}
                steps={[
                    {
                        target: () => document.querySelector('.tour-new-feature-help'),
                        title: '稍后从这里开始',
                        description: '点击菜单栏问号，可以随时打开新功能引导中心并启动完整流程。',
                        nextButtonProps: { children: '知道了' },
                    },
                ]}
            />
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
                maxHeight: '100vh',
                minWidth: 0,
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
                        margin: isFinancePage ? 0 : isMobile ? '16px' : '24px 16px',
                        padding: isFinancePage ? (isMobile ? '0 16px' : '0 24px') : isMobile ? '16px' : '0 24px',
                        minHeight: isFinancePage ? '100%' : '100vh',
                        background: colorBgContainer,
                        overflowX: 'hidden',
                        overflowY: isFinancePage ? 'visible' : 'auto'
                    }}
                >
                    <Outlet />
                </Content>
            </Layout>
        </Layout>
    );
}

export default App;
