import React, { useState } from 'react';
import { Form, Input, Button, Card, message, Typography, Result } from 'antd';
import { Phone, Lock, Building2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { endpoint } from '../config.js';
import getSafeHeader from '../common/safeHeader.js';

const { Title, Text } = Typography;

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
  .form-spacing { margin-top: 16px; }
  .back-link { color: #2563eb; font-size: 14px; font-weight: 500; text-decoration: none; transition: color 0.3s; margin-top: 16px; display: block; text-align: center; }
  .back-link:hover { color: #1d4ed8; }
`;

export default function ForgetPassword() {
    const [messageApi, contextHolder] = message.useMessage();
    const [submitted, setSubmitted] = useState(false);
    const [loading, setLoading] = useState(false);
    const navigate = useNavigate();

    const onSubmit = async (values) => {
        setLoading(true);
        messageApi.loading({ content: '正在提交申请...', key: 'forgot' });

        try {
            const response = await fetch(`${endpoint}/auth/password/forgot`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...getSafeHeader()
                },
                body: JSON.stringify({
                    phone: values.phone,
                    new_password: values.password
                })
            });

            const result = await response.json();

            if (response.ok && result.code === 200) {
                messageApi.success({
                    content: '申请已提交！',
                    key: 'forgot',
                    duration: 2
                });
                setSubmitted(true);
            } else {
                messageApi.error({
                    content: result.msg || '提交失败，请重试。',
                    key: 'forgot',
                    duration: 3
                });
            }
        } catch (error) {
            console.error('请求失败:', error);
            messageApi.error({
                content: '网络连接失败，请检查网络后重试。',
                key: 'forgot',
                duration: 3
            });
        } finally {
            setLoading(false);
        }
    };

    if (submitted) {
        return (
            <div className="erp-layout">
                <style>{customStyles}</style>
                {contextHolder}
                <div className="blur-bg bg-blue"></div>
                <div className="blur-bg bg-indigo"></div>
                <div className="blur-bg bg-sky"></div>
                <div className="content-box">
                    <Card className="custom-card" styles={{ body: { padding: '48px 40px' } }}>
                        <Result
                            status="success"
                            title="申请已提交"
                            subTitle="您的密码重置申请已提交，请等待管理员审核。审核通过后，您就可以使用新密码登录了。"
                            extra={[
                                <Button type="primary" key="login" onClick={() => navigate('/login')}>
                                    返回登录
                                </Button>
                            ]}
                        />
                    </Card>
                </div>
            </div>
        );
    }

    return (
        <div className="erp-layout">
            <style>{customStyles}</style>
            {contextHolder}
            <div className="blur-bg bg-blue"></div>
            <div className="blur-bg bg-indigo"></div>
            <div className="blur-bg bg-sky"></div>

            <div className="content-box">
                <div className="header-box">
                    <div className="logo-row">
                        <div className="logo-icon-box">
                            <Building2 color="#ffffff" size={26} strokeWidth={2.5} />
                        </div>
                        <Title level={2} style={{ margin: 0, color: '#1e293b', fontWeight: 600, letterSpacing: '0.05em' }}>
                            Nexus ERP
                        </Title>
                    </div>
                    <Text style={{ color: '#64748b', fontSize: '16px' }}>忘记密码</Text>
                </div>

                <Card
                    className="custom-card"
                    styles={{ body: { padding: '36px 40px' } }}
                >
                    <Text style={{ display: 'block', marginBottom: 24, color: '#64748b' }}>
                        请输入您的手机号和新密码，提交后等待管理员审核。
                    </Text>

                    <Form
                        name="forgot_password_form"
                        layout="vertical"
                        onFinish={onSubmit}
                        size="large"
                        className="form-spacing"
                    >
                        <Form.Item
                            name="phone"
                            rules={[
                                { required: true, message: '请输入您的手机号！' },
                            ]}
                        >
                            <Input
                                prefix={<Phone className="form-icon" size={18} />}
                                placeholder="手机号"
                            />
                        </Form.Item>

                        <Form.Item
                            name="password"
                            rules={[
                                { required: true, message: '请设置新密码！' },
                                { min: 6, message: '密码长度不能少于6位！' }
                            ]}
                            hasFeedback
                        >
                            <Input.Password
                                prefix={<Lock className="form-icon" size={18} />}
                                placeholder="新密码"
                            />
                        </Form.Item>

                        <Form.Item
                            name="confirm"
                            dependencies={['password']}
                            hasFeedback
                            rules={[
                                { required: true, message: '请确认新密码！' },
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
                                placeholder="确认新密码"
                            />
                        </Form.Item>

                        <Form.Item style={{ marginBottom: '8px', marginTop: '24px' }}>
                            <Button
                                type="primary"
                                htmlType="submit"
                                className="submit-btn"
                                loading={loading}
                            >
                                提交申请
                            </Button>
                        </Form.Item>
                    </Form>

                    <a className="back-link" href="/login">
                        返回登录
                    </a>
                </Card>
            </div>
        </div>
    );
}
