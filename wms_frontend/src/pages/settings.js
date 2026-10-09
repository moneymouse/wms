import React, { useState } from 'react';
import { Card, Form, Input, Button, message, Typography, Divider } from 'antd';
import { Lock, KeyRound } from 'lucide-react';
import { endpoint } from '../config.js';
import getSafeHeader from '../common/safeHeader.js';

const { Title, Text } = Typography;

const Settings = () => {
    const [form] = Form.useForm();
    const [loading, setLoading] = useState(false);
    const [messageApi, contextHolder] = message.useMessage();

    const handleChangePassword = async (values) => {
        setLoading(true);
        messageApi.loading({ content: '正在修改密码...', key: 'password' });

        try {
            const response = await fetch(`${endpoint}/auth/password/change`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...getSafeHeader()
                },
                body: JSON.stringify({
                    old_password: values.oldPassword,
                    new_password: values.newPassword
                })
            });

            const result = await response.json();

            if (response.ok && result.code === 200) {
                messageApi.success({
                    content: '密码修改成功！',
                    key: 'password',
                    duration: 2
                });
                form.resetFields();
            } else {
                messageApi.error({
                    content: result.msg || '修改失败，请重试。',
                    key: 'password',
                    duration: 3
                });
            }
        } catch (error) {
            console.error('修改密码失败:', error);
            messageApi.error({
                content: '网络连接失败，请检查网络后重试。',
                key: 'password',
                duration: 3
            });
        } finally {
            setLoading(false);
        }
    };

    return (
        <div style={{ padding: 24, maxWidth: 600 }}>
            {contextHolder}

            <Title level={3} style={{ marginBottom: 24 }}>
                <KeyRound size={24} style={{ marginRight: 8, verticalAlign: 'middle' }} />
                设置
            </Title>

            <Card title="修改密码">
                <Text type="secondary" style={{ display: 'block', marginBottom: 24 }}>
                    请输入当前密码和新密码来更新您的登录密码。
                </Text>

                <Form
                    form={form}
                    layout="vertical"
                    onFinish={handleChangePassword}
                    autoComplete="off"
                >
                    <Form.Item
                        name="oldPassword"
                        label="当前密码"
                        rules={[
                            { required: true, message: '请输入当前密码！' }
                        ]}
                    >
                        <Input.Password
                            prefix={<Lock size={16} style={{ color: '#9ca3af' }} />}
                            placeholder="请输入当前密码"
                            size="large"
                        />
                    </Form.Item>

                    <Divider />

                    <Form.Item
                        name="newPassword"
                        label="新密码"
                        rules={[
                            { required: true, message: '请输入新密码！' },
                            { min: 6, message: '密码长度不能少于6位！' }
                        ]}
                        hasFeedback
                    >
                        <Input.Password
                            prefix={<Lock size={16} style={{ color: '#9ca3af' }} />}
                            placeholder="请输入新密码（至少6位）"
                            size="large"
                        />
                    </Form.Item>

                    <Form.Item
                        name="confirmPassword"
                        label="确认新密码"
                        dependencies={['newPassword']}
                        hasFeedback
                        rules={[
                            { required: true, message: '请确认新密码！' },
                            ({ getFieldValue }) => ({
                                validator(_, value) {
                                    if (!value || getFieldValue('newPassword') === value) {
                                        return Promise.resolve();
                                    }
                                    return Promise.reject(new Error('两次输入的密码不一致！'));
                                },
                            }),
                        ]}
                    >
                        <Input.Password
                            prefix={<Lock size={16} style={{ color: '#9ca3af' }} />}
                            placeholder="请再次输入新密码"
                            size="large"
                        />
                    </Form.Item>

                    <Form.Item style={{ marginTop: 32 }}>
                        <Button
                            type="primary"
                            htmlType="submit"
                            loading={loading}
                            size="large"
                            style={{ width: '100%' }}
                        >
                            确认修改
                        </Button>
                    </Form.Item>
                </Form>
            </Card>
        </div>
    );
};

export default Settings;
