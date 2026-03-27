import React, { useState } from 'react';
import { Form, Input, Button, Checkbox, Card, Tabs, message, Typography } from 'antd';
import { User, Lock, Mail, Building2, KeyRound, Phone } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { endpoint } from '../config.js';
import getSafeHeader from '../common/safeHeader.js';

const { Title, Text } = Typography;

// --- 注入原生 CSS 样式，替代 Tailwind ---
const customStyles = `
  .erp-layout { min-height: 100vh; background-color: #f8fafc; display: flex; flex-direction: column; justify-content: center; align-items: center; padding: 16px; position: relative; overflow: hidden; font-family: sans-serif; }
  .blur-bg { position: absolute; border-radius: 50%; mix-blend-mode: multiply; filter: blur(48px); opacity: 0.1; pointer-events: none; }
  .bg-blue { top: -10%; left: -10%; width: 30rem; height: 30rem; background-color: #3b82f6; }
  .bg-indigo { top: 20%; right: -10%; width: 30rem; height: 30rem; background-color: #6366f1; }
  .bg-sky { bottom: -10%; left: 20%; width: 30rem; height: 30rem; background-color: #38bdf8; }
  .content-box { width: 100%; max-width: 440px; z-index: 10; display: flex; flex-direction: column; align-items: center; }
  .header-box { margin-bottom: 32px; text-align: center; width: 100%; }
  .logo-row { display: flex; align-items: center; justify-content: center; gap: 12px; margin-bottom: 12px; }
  .logo-icon-box { width: 48px; height: 48px; background: linear-gradient(to bottom right, #2563eb, #4f46e5); border-radius: 12px; display: flex; align-items: center; justify-content: center; box-shadow: 0 10px 15px -3px rgba(59, 130, 246, 0.3); }
  .custom-card { width: 100%; box-shadow: 0 25px 50px -12px rgba(226, 232, 240, 0.8) !important; border-radius: 16px !important; border: 0 !important; }
  .submit-btn { width: 100%; height: 44px !important; font-size: 16px !important; font-weight: 500 !important; }
  .form-icon { color: #9ca3af; margin-right: 8px; }
  .action-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
  .forgot-link { color: #2563eb; font-size: 14px; font-weight: 500; text-decoration: none; transition: color 0.3s; }
  .forgot-link:hover { color: #1d4ed8; }
  .form-spacing { margin-top: 16px; }
`;

// --- 提取：登录表单组件 ---
const LoginForm = ({ messageApi }) => {
    const navigate = useNavigate();

    const onLogin = async (values) => {
        messageApi.loading({ content: '系统登录中，请稍候...', key: 'login' });

        try {
            const response = await fetch(`${endpoint}/auth/login`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...getSafeHeader()
                },
                body: JSON.stringify({
                    phone: values.username,  // 将username映射为phone字段
                    password: values.password
                })
            });

            const result = await response.json();

            if (response.ok && result.code === 200) {
                // 登录成功，存储JWT token
                if (result.token) {
                    localStorage.setItem('jwt', result.token);
                }

                messageApi.success({
                    content: '登录成功！欢迎回到 ERP 系统。',
                    key: 'login',
                    duration: 2
                });

                // 延迟跳转到主页
                setTimeout(() => {
                    navigate('/');
                }, 1000);
            } else {
                // 登录失败
                messageApi.error({
                    content: result.msg || '登录失败，请检查手机号和密码。',
                    key: 'login',
                    duration: 3
                });
            }
        } catch (error) {
            console.error('登录请求失败:', error);
            messageApi.error({
                content: '网络连接失败，请检查网络后重试。',
                key: 'login',
                duration: 3
            });
        }
    };

    return (
        <Form
            name="login_form"
            layout="vertical"
            initialValues={{ remember: true }}
            onFinish={onLogin}
            size="large"
            className="form-spacing"
        >
            <Form.Item
                name="username"
                rules={[
                    { required: true, message: '请输入您的手机号！' },
                ]}
            >
                <Input
                    prefix={<User className="form-icon" size={18} />}
                    placeholder="手机号"
                />
            </Form.Item>

            <Form.Item
                name="password"
                rules={[{ required: true, message: '请输入您的密码！' }]}
            >
                <Input.Password
                    prefix={<Lock className="form-icon" size={18} />}
                    placeholder="登录密码"
                />
            </Form.Item>

            <div className="action-row">
                <Form.Item name="remember" valuePropName="checked" noStyle>
                    <Checkbox>7天内自动登录</Checkbox>
                </Form.Item>
                <a className="forgot-link" href="/forget_password">
                    忘记密码？
                </a>
            </div>

            <Form.Item style={{ marginBottom: '8px' }}>
                <Button type="primary" htmlType="submit" className="submit-btn">
                    登 录
                </Button>
            </Form.Item>
        </Form>
    );
};

// --- 提取：注册表单组件 ---
const RegisterForm = ({ messageApi, onSuccess }) => {
    const onRegister = async (values) => {
        messageApi.loading({ content: '正在为您开通企业账户...', key: 'register' });

        try {
            const response = await fetch(`${endpoint}/auth/register`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...getSafeHeader()
                },
                body: JSON.stringify({
                    phone: values.phone,
                    name: values.name,
                    password: values.password
                })
            });

            const result = await response.json();

            if (response.ok && result.code === 200) {
                // 注册成功
                messageApi.success({
                    content: '注册成功，请等待管理员审核！',
                    key: 'register',
                    duration: 3
                });

                // 注册成功后切换到登录标签页
                if (onSuccess) onSuccess();
            } else {
                // 注册失败
                messageApi.error({
                    content: result.msg || '注册失败，请检查信息后重试。',
                    key: 'register',
                    duration: 3
                });
            }
        } catch (error) {
            console.error('注册请求失败:', error);
            messageApi.error({
                content: '网络连接失败，请检查网络后重试。',
                key: 'register',
                duration: 3
            });
        }
    };

    return (
        <Form
            name="register_form"
            layout="vertical"
            onFinish={onRegister}
            size="large"
            className="form-spacing"
        >
            <Form.Item
                name="phone"
                rules={[
                    { required: true, message: '请输入您的用户名或手机号！' },
                ]}
            >
                <Input
                    prefix={<Phone className="form-icon" size={18} />}
                    placeholder="手机号"
                />
            </Form.Item>

            <Form.Item
                name="name"
                rules={[
                    { required: true, message: '请输入您的真实姓名！' },
                    { min: 2, message: '姓名至少2个字符！' },
                    { max: 20, message: '姓名不能超过20个字符！' }
                ]}
            >
                <Input
                    prefix={<User className="form-icon" size={18} />}
                    placeholder="真实姓名"
                />
            </Form.Item>

            <Form.Item
                name="password"
                rules={[
                    { required: true, message: '请设置您的密码！' },
                    { min: 6, message: '密码长度不能少于6位！' }
                ]}
                hasFeedback
            >
                <Input.Password
                    prefix={<Lock className="form-icon" size={18} />}
                    placeholder="设置密码"
                />
            </Form.Item>

            <Form.Item
                name="confirm"
                dependencies={['password']}
                hasFeedback
                rules={[
                    { required: true, message: '请再次确认您的密码！' },
                    ({ getFieldValue }) => ({
                        validator(_, value) {
                            if (!value || getFieldValue('password') === value) {
                                return Promise.resolve();
                            }
                            return Promise.reject(new Error('两次输入的密码不一致！'));
                        },
                    }),
                ]}
            >
                <Input.Password
                    prefix={<Lock className="form-icon" size={18} />}
                    placeholder="确认密码"
                />
            </Form.Item>

            <Form.Item style={{ marginBottom: '8px', marginTop: '24px' }}>
                <Button type="primary" htmlType="submit" className="submit-btn">
                    注册账户
                </Button>
            </Form.Item>
        </Form>
    );
};

export default function Login() {
    const [activeKey, setActiveKey] = useState('login');
    const [messageApi, contextHolder] = message.useMessage();

    // 定义 Tabs 的内容面板
    const tabItems = [
        {
            key: 'login',
            label: '账户登录',
            children: <LoginForm messageApi={messageApi} />
        },
        {
            key: 'register',
            label: '注册新账户',
            children: <RegisterForm messageApi={messageApi} onSuccess={() => setActiveKey('login')} />
        }
    ];

    return (
        <div className="erp-layout">
            {/* 注入纯 CSS 样式 */}
            <style>{customStyles}</style>

            {/* 注入全局提示组件 */}
            {contextHolder}

            {/* 现代化背景装饰元素 (毛玻璃渐变效果) */}
            <div className="blur-bg bg-blue"></div>
            <div className="blur-bg bg-indigo"></div>
            <div className="blur-bg bg-sky"></div>

            <div className="content-box">

                {/* Logo与标题区 */}
                <div className="header-box">
                    <div className="logo-row">
                        <div className="logo-icon-box">
                            <Building2 color="#ffffff" size={26} strokeWidth={2.5} />
                        </div>
                        <Title level={2} style={{ margin: 0, color: '#1e293b', fontWeight: 600, letterSpacing: '0.05em' }}>
                            Nexus ERP
                        </Title>
                    </div>
                    <Text style={{ color: '#64748b', fontSize: '16px' }}>新一代企业级智能资源规划平台</Text>
                </div>

                {/* 核心登录/注册卡片 */}
                <Card
                    className="custom-card"
                    styles={{
                        body: { padding: '36px 40px' }
                    }}
                >
                    <Tabs
                        activeKey={activeKey}
                        onChange={setActiveKey}
                        centered
                        items={tabItems}
                        size="large"
                        tabBarStyle={{ marginBottom: 12 }}
                    />
                </Card>

            </div>
        </div>
    );
}