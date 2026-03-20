import React, {useState, useEffect} from 'react';
import {
    MenuFoldOutlined,
    MenuUnfoldOutlined,
    PlusSquareOutlined,
    UnorderedListOutlined,
    UploadOutlined,
} from '@ant-design/icons';
import {Button, Layout, Menu, theme} from 'antd';
import {Outlet, useLocation, useNavigate} from "react-router-dom";
import {LogIcon} from "./pages/logs";

const {Header, Sider, Content} = Layout;

function App() {
    const [collapsed, setCollapsed] = useState(true);
    const [isAdmin, setIsAdmin] = useState(false);
    const {
        token: {colorBgContainer},
    } = theme.useToken();

    const {pathname} = useLocation();
    const navigate = useNavigate();

    useEffect(() => {
        // 从 localStorage 获取 JWT 并检查用户角色
        const jwt = localStorage.getItem('jwt');
        try {
            // 分割 JWT 并获取负载部分（第二部分）
            const parts = jwt.split('.');
            if (parts.length === 3) {
                // 解码 base64 编码的负载
                const payload = JSON.parse(atob(parts[1]));
                // 检查用户角色是否为 admin
                setIsAdmin(payload.role === 'admin');
            }
        } catch (e) {
            console.error('解析 JWT 时出错:', e);
            setIsAdmin(false);
            navigate("/login")
        }
    }, []);

    // 根据用户角色构建菜单项
    const menuItems = [
        {
            key: '',
            icon: <PlusSquareOutlined/>,
            label: '创建新订单',
        },
        {
            key: 'orders',
            icon: <UnorderedListOutlined/>,
            label: '订单列表',
        },
        {
            key: 'upload',
            icon: <UploadOutlined />,
            label: '上传明细'
        }
    ];

    // 如果用户是管理员，添加操作日志菜单项
    if (isAdmin) {
        menuItems.push({
            key: 'logs',
            label: '操作日志',
            icon: <LogIcon />,
        });
    }

    return (
        <Layout>
            <Sider trigger={null} collapsible collapsed={collapsed} style={{
                height: '100vh'
            }}>
                <Header style={{padding: 0}}>
                    <Button
                        type="link"
                        icon={collapsed ? <MenuUnfoldOutlined/> : <MenuFoldOutlined/>}
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
                <Menu
                    theme="dark"
                    mode="inline"
                    selectedKeys={[pathname.split('/')[1]]}
                    onClick={({key}) => {
                        navigate(key);
                    }}
                    items={menuItems}
                />
            </Sider>
            <Layout style={{
                overflowY: 'auto',
                maxHeight: '100vh'
            }}>
                <Content
                    style={{
                        margin: '24px 16px',
                        padding: '0 24px',
                        minHeight: '100vh',
                        background: colorBgContainer,
                        overflowY: 'auto'
                    }}
                >
                    <Outlet/>
                </Content>
            </Layout>
        </Layout>
    );
}

export default App;
