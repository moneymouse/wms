import React, { useState, useEffect } from 'react';
import { Table, Button, Space, message, Card, Tag, Modal, Select, Input, Typography, Tabs, Switch, Upload, Tooltip } from 'antd';
import { CheckOutlined, CloseOutlined, UserOutlined, KeyOutlined, UploadOutlined, PlusOutlined, DeleteOutlined } from '@ant-design/icons';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import EXPORT_FIELDS from '../common/exportFields';
import * as XLSX from 'xlsx';
import { useNavigate } from 'react-router-dom';

const ROLE_OPTIONS = [
    { value: 'admin', label: '管理员' },
    { value: 'store_manager', label: '店长' },
    { value: 'salesperson', label: '业务员' },
    { value: 'clerk', label: '文员' },
    { value: 'finance', label: '财务' },
    { value: 'worker', label: '操作人员' }
];

const ROLE_LABEL_MAP = Object.fromEntries(ROLE_OPTIONS.map(r => [r.value, r.label]));

const AdminPage = () => {
    const [loading, setLoading] = useState(false);
    const [data, setData] = useState([]);
    const [approveModalVisible, setApproveModalVisible] = useState(false);
    const [rejectModalVisible, setRejectModalVisible] = useState(false);
    const [currentRecord, setCurrentRecord] = useState(null);
    const [selectedRoles, setSelectedRoles] = useState(['salesperson']);
    const [rejectRemark, setRejectRemark] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [usersLoading, setUsersLoading] = useState(false);
    const [users, setUsers] = useState([]);
    const [editingRoleUser, setEditingRoleUser] = useState({});
    // 密码重置相关状态
    const [passwordRequests, setPasswordRequests] = useState([]);
    const [passwordRequestsLoading, setPasswordRequestsLoading] = useState(false);
    const [rejectPasswordModalVisible, setRejectPasswordModalVisible] = useState(false);
    const [currentPasswordRequest, setCurrentPasswordRequest] = useState(null);
    const [passwordRejectRemark, setPasswordRejectRemark] = useState('');
    const [resetPasswordModalVisible, setResetPasswordModalVisible] = useState(false);
    const [resetPasswordUser, setResetPasswordUser] = useState(null);
    const [newPassword, setNewPassword] = useState('');
    const [deleteModalVisible, setDeleteModalVisible] = useState(false);
    const [userToDelete, setUserToDelete] = useState(null);
    // 品名管理相关状态
    const [goodsNames, setGoodsNames] = useState([]);
    const [goodsNameLoading, setGoodsNameLoading] = useState(false);
    const [newCnName, setNewCnName] = useState('');
    const [newEnName, setNewEnName] = useState('');
    const [editingGoodsName, setEditingGoodsName] = useState({ id: null, name: '' });

    // Excel 模板管理相关状态
    const [excelTemplates, setExcelTemplates] = useState([]);
    const [excelTemplateLoading, setExcelTemplateLoading] = useState(false);
    const [excelModalVisible, setExcelModalVisible] = useState(false);
    const [editingTemplate, setEditingTemplate] = useState(null);
    const [templateForm, setTemplateForm] = useState({
        mode_key: '',
        label: '',
        template_type: 'column',
        single_order_only: false,
        mappings: [],
    });
    const [templateFileList, setTemplateFileList] = useState([]);
    const [templateSubmitting, setTemplateSubmitting] = useState(false);
    // 可视化配置状态
    const [excelPreview, setExcelPreview] = useState(null);
    const [draggingField, setDraggingField] = useState(null);

    const navigate = useNavigate();

    // 获取待审核用户列表
    const fetchApplications = async () => {
        setLoading(true);
        try {
            const response = await fetch(`${endpoint}/auth/pending`, {
                headers: getSafeHeader()
            });

            if (response.status === 401 || response.status === 403) {
                message.error('权限不足或登录已过期');
                navigate('/login');
                return;
            }

            const result = await response.json();
            if (result.code === 200) {
                setData(result.data || []);
            } else {
                message.error(result.msg || '获取申请列表失败');
            }
        } catch (error) {
            console.error('Error fetching applications:', error);
            message.error('获取申请列表失败');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchApplications();
        fetchUsers();
        fetchPasswordRequests();
        fetchGoodsNames();
        fetchExcelTemplates();
    }, []);

    // 打开审核通过对话框
    const showApproveModal = (record) => {
        setCurrentRecord(record);
        setSelectedRoles(['salesperson']);
        setApproveModalVisible(true);
    };

    // 打开审核拒绝对话框
    const showRejectModal = (record) => {
        setCurrentRecord(record);
        setRejectRemark('');
        setRejectModalVisible(true);
    };

    // 审核通过
    const handleApprove = async () => {
        if (!currentRecord) return;
        if (!selectedRoles || selectedRoles.length === 0) {
            message.warning('请至少选择一个角色');
            return;
        }
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/auth/approve/${currentRecord.id}`, {
                method: 'POST',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ roles: selectedRoles })
            });

            const result = await response.json();
            if (result.code === 200) {
                message.success(`用户 ${currentRecord.name} 审核已通过`);
                setApproveModalVisible(false);
                fetchApplications();
            } else {
                message.error(result.msg || '操作失败');
            }
        } catch (error) {
            console.error('Approve error:', error);
            message.error('操作异常');
        } finally {
            setSubmitting(false);
        }
    };

    // 审核拒绝
    const handleReject = async () => {
        if (!currentRecord) return;
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/auth/reject/${currentRecord.id}`, {
                method: 'POST',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ remark: rejectRemark })
            });

            const result = await response.json();
            if (result.code === 200) {
                message.success(`用户 ${currentRecord.name} 申请已拒绝`);
                setRejectModalVisible(false);
                fetchApplications();
            } else {
                message.error(result.msg || '操作失败');
            }
        } catch (error) {
            console.error('Reject error:', error);
            message.error('操作异常');
        } finally {
            setSubmitting(false);
        }
    };

    const fetchUsers = async () => {
        setUsersLoading(true);
        try {
            const response = await fetch(`${endpoint}/users`, {
                headers: getSafeHeader()
            });
            const result = await response.json();
            if (result.code === 200) {
                setUsers((result.data || []).map((item) => ({ ...item, key: item.id })));
            } else {
                message.error(result.msg || '获取用户列表失败');
            }
        } catch (error) {
            console.error('Fetch users error:', error);
            message.error('获取用户列表失败');
        } finally {
            setUsersLoading(false);
        }
    };

    const handleUpdateRole = async (record) => {
        if (!Object.prototype.hasOwnProperty.call(editingRoleUser, record.id)) {
            message.warning('请先选择角色');
            return;
        }
        const roles = editingRoleUser[record.id];
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/users/${record.id}/role`, {
                method: 'PUT',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ roles: roles || [] })
            });
            const result = await response.json();
            if (result.code === 200) {
                message.success(result.msg || '角色更新成功');
                await fetchUsers();
                return;
            }
            message.error(result.msg || '角色更新失败');
        } catch (error) {
            console.error('Update role error:', error);
            message.error('角色更新失败');
        } finally {
            setSubmitting(false);
        }
    };

    // ==================== 密码重置相关函数 ====================

    const fetchPasswordRequests = async () => {
        setPasswordRequestsLoading(true);
        try {
            const response = await fetch(`${endpoint}/auth/password/requests`, {
                headers: getSafeHeader()
            });
            const result = await response.json();
            if (result.code === 200) {
                setPasswordRequests(result.data || []);
            }
        } catch (error) {
            console.error('Fetch password requests error:', error);
        } finally {
            setPasswordRequestsLoading(false);
        }
    };

    const handleApprovePasswordRequest = async (requestId) => {
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/auth/password/approve/${requestId}`, {
                method: 'POST',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                }
            });
            const result = await response.json();
            if (result.code === 200) {
                message.success('密码重置申请已通过');
                fetchPasswordRequests();
            } else {
                message.error(result.msg || '操作失败');
            }
        } catch (error) {
            console.error('Approve password request error:', error);
            message.error('操作异常');
        } finally {
            setSubmitting(false);
        }
    };

    const showRejectPasswordModal = (record) => {
        setCurrentPasswordRequest(record);
        setPasswordRejectRemark('');
        setRejectPasswordModalVisible(true);
    };

    const handleRejectPasswordRequest = async () => {
        if (!currentPasswordRequest) return;
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/auth/password/reject/${currentPasswordRequest.id}`, {
                method: 'POST',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ remark: passwordRejectRemark })
            });
            const result = await response.json();
            if (result.code === 200) {
                message.success('密码重置申请已拒绝');
                setRejectPasswordModalVisible(false);
                fetchPasswordRequests();
            } else {
                message.error(result.msg || '操作失败');
            }
        } catch (error) {
            console.error('Reject password request error:', error);
            message.error('操作异常');
        } finally {
            setSubmitting(false);
        }
    };

    const showResetPasswordModal = (record) => {
        setResetPasswordUser(record);
        setNewPassword('');
        setResetPasswordModalVisible(true);
    };

    const handleResetPassword = async () => {
        if (!resetPasswordUser) return;
        if (!newPassword || newPassword.length < 6) {
            message.warning('密码长度不能少于6位');
            return;
        }
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/users/${resetPasswordUser.id}/reset-password`, {
                method: 'POST',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ new_password: newPassword })
            });
            const result = await response.json();
            if (result.code === 200) {
                message.success(`用户 ${resetPasswordUser.name} 的密码已重置`);
                setResetPasswordModalVisible(false);
            } else {
                message.error(result.msg || '重置失败');
            }
        } catch (error) {
            console.error('Reset password error:', error);
            message.error('操作异常');
        } finally {
            setSubmitting(false);
        }
    };

    const showDeleteModal = (record) => {
        setUserToDelete(record);
        setDeleteModalVisible(true);
    };

    const handleDeleteUser = async () => {
        if (!userToDelete) return;
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/users/${userToDelete.id}`, {
                method: 'DELETE',
                headers: getSafeHeader()
            });
            const result = await response.json();
            if (result.code === 200) {
                message.success(result.msg || '用户已删除');
                setDeleteModalVisible(false);
                await fetchUsers();
            } else {
                message.error(result.msg || '删除失败');
            }
        } catch (error) {
            console.error('Delete user error:', error);
            message.error('删除失败');
        } finally {
            setSubmitting(false);
        }
    };

    // ==================== Excel 模板管理相关函数 ====================

    const fetchExcelTemplates = async () => {
        setExcelTemplateLoading(true);
        try {
            const response = await fetch(`${endpoint}/excel-templates`, {
                headers: getSafeHeader()
            });
            const result = await response.json();
            if (result.code === 200) {
                setExcelTemplates(result.data || []);
            } else {
                message.error(result.msg || '获取模板列表失败');
            }
        } catch (error) {
            console.error('Fetch excel templates error:', error);
            message.error('获取模板列表失败');
        } finally {
            setExcelTemplateLoading(false);
        }
    };

    const openTemplateModal = (record = null) => {
        if (record) {
            let config = {};
            try {
                config = JSON.parse(record.config || '{}');
            } catch {
                config = {};
            }
            setEditingTemplate(record);
            setTemplateForm({
                mode_key: record.mode_key,
                label: record.label,
                template_type: record.template_type,
                single_order_only: record.single_order_only,
                mappings: [],
            });
            setTemplateFileList([]);
            setExcelPreview(null);

            let mappings = [];
            // 新格式兼容
            if (config.column_mappings) {
                Object.entries(config.column_mappings).forEach(([target, field]) => {
                    if (field) mappings.push({ target, field, type: 'column' });
                });
            }
            if (config.cell_mappings) {
                config.cell_mappings.forEach(m => {
                    if (m.cell && m.field) mappings.push({ target: m.cell, field: m.field, type: 'cell' });
                });
            }
            // 旧格式兼容
            if (config.reference_table && config.columns) {
                mappings = config.columns
                    .filter(col => config.reference_table[col])
                    .map(col => ({
                        target: col,
                        field: config.reference_table[col],
                        type: 'column',
                    }));
            }
            setTemplateForm(prev => ({ ...prev, mappings }));
        } else {
            setEditingTemplate(null);
            setTemplateForm({
                mode_key: '',
                label: '',
                template_type: 'column',
                single_order_only: false,
                mappings: [],
            });
            setTemplateFileList([]);
            setExcelPreview(null);
        }
        setExcelModalVisible(true);
    };

    const closeTemplateModal = () => {
        setExcelModalVisible(false);
        setEditingTemplate(null);
        setTemplateForm({
            mode_key: '',
            label: '',
            template_type: 'column',
            single_order_only: false,
            mappings: [],
        });
        setTemplateFileList([]);
        setExcelPreview(null);
        setDraggingField(null);
    };

    const handleSaveTemplate = async () => {
        const { mode_key, label, single_order_only } = templateForm;
        if (!mode_key.trim()) {
            message.warning('请输入模板标识');
            return;
        }
        if (!label.trim()) {
            message.warning('请输入模板名称');
            return;
        }
        if (templateForm.mappings.length === 0) {
            message.warning('请至少添加一条字段映射');
            return;
        }

        const hasNewFile = templateFileList.length > 0;
        const hasExistingFile = !!editingTemplate?.template_file;

        let config = {};
        if (hasNewFile || hasExistingFile) {
            // 有文件 → 新格式
            const column_mappings = {};
            const cell_mappings = [];
            templateForm.mappings.forEach(m => {
                if (!m.target || !m.field) return;
                if (m.type === 'column') {
                    column_mappings[m.target] = m.field;
                } else if (m.type === 'cell') {
                    cell_mappings.push({ cell: m.target, field: m.field });
                }
            });
            config = { column_mappings, cell_mappings };
        } else {
            // 无文件 → 旧格式（仅保留列映射）
            const columns = [];
            const reference_table = {};
            templateForm.mappings.forEach(m => {
                if (m.type === 'column' && m.target) {
                    columns.push(m.target);
                    reference_table[m.target] = m.field || '';
                }
            });
            if (columns.length === 0) {
                message.warning('无文件模板至少需要一条列映射');
                return;
            }
            config = { columns, reference_table };
        }

        const payload = {
            mode_key: mode_key.trim(),
            label: label.trim(),
            template_type: templateForm.template_type,
            single_order_only: templateForm.template_type === 'cell' ? true : single_order_only,
            config,
        };

        setTemplateSubmitting(true);
        try {
            const url = editingTemplate
                ? `${endpoint}/excel-templates/${editingTemplate.id}`
                : `${endpoint}/excel-templates`;
            const method = editingTemplate ? 'PUT' : 'POST';
            const response = await fetch(url, {
                method,
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });
            const result = await response.json();
            if (result.code === 200) {
                message.success(editingTemplate ? '更新成功' : '创建成功');
                // 如有文件待上传，执行上传
                if (templateFileList.length > 0 && result.data?.id) {
                    const file = templateFileList[0].originFileObj || templateFileList[0];
                    const formData = new FormData();
                    formData.append('file', file);
                    const uploadRes = await fetch(`${endpoint}/excel-templates/${result.data.id}/upload`, {
                        method: 'POST',
                        headers: getSafeHeader(),
                        body: formData
                    });
                    const uploadResult = await uploadRes.json();
                    if (uploadResult.code !== 200) {
                        message.warning('模板保存成功，但文件上传失败');
                    }
                }
                closeTemplateModal();
                fetchExcelTemplates();
            } else {
                message.error(result.msg || '操作失败');
            }
        } catch (error) {
            console.error('Save template error:', error);
            message.error('操作异常');
        } finally {
            setTemplateSubmitting(false);
        }
    };

    const handleArchiveTemplate = async (id) => {
        try {
            const response = await fetch(`${endpoint}/excel-templates/${id}/archive`, {
                method: 'POST',
                headers: getSafeHeader()
            });
            const result = await response.json();
            if (result.code === 200) {
                message.success('归档成功');
                fetchExcelTemplates();
            } else {
                message.error(result.msg || '归档失败');
            }
        } catch (error) {
            console.error('Archive template error:', error);
            message.error('归档失败');
        }
    };

    const handleDeleteTemplate = async (id) => {
        try {
            const response = await fetch(`${endpoint}/excel-templates/${id}`, {
                method: 'DELETE',
                headers: getSafeHeader()
            });
            const result = await response.json();
            if (result.code === 200) {
                message.success('删除成功');
                fetchExcelTemplates();
            } else {
                message.error(result.msg || '删除失败');
            }
        } catch (error) {
            console.error('Delete template error:', error);
            message.error('删除失败');
        }
    };

    // ==================== 可视化配置相关函数 ====================

    const parseExcelForPreview = (file) => {
        const reader = new FileReader();
        reader.onload = (e) => {
            const data = new Uint8Array(e.target.result);
            const workbook = XLSX.read(data, { type: 'array' });
            const firstSheet = workbook.Sheets[workbook.SheetNames[0]];
            const jsonData = XLSX.utils.sheet_to_json(firstSheet, { header: 1, defval: '' });

            const previewRows = jsonData.slice(0, 5);
            if (previewRows.length === 0) {
                setExcelPreview({ columns: [], rows: [] });
                return;
            }

            const maxCols = Math.max(...previewRows.map(r => r.length), 0);
            const columns = Array.from({ length: maxCols }, (_, idx) => XLSX.utils.encode_col(idx));

            const rows = previewRows.map((row, rowIdx) =>
                Array.from({ length: maxCols }, (_, colIdx) => ({
                    value: String(row[colIdx] || ''),
                    cellRef: `${XLSX.utils.encode_col(colIdx)}${rowIdx + 1}`,
                }))
            );

            setExcelPreview({ columns, rows });
        };
        reader.readAsArrayBuffer(file);
    };

    const handleTemplateFileChange = ({ fileList }) => {
        setTemplateFileList(fileList);
        if (fileList.length > 0 && fileList[0].originFileObj) {
            parseExcelForPreview(fileList[0].originFileObj);
        } else {
            setExcelPreview(null);
        }
    };

    const handleFieldDragStart = (field) => {
        setDraggingField(field);
    };

    const handleColumnDrop = (col, field) => {
        if (!field) return;
        setTemplateForm(prev => {
            let newMappings = prev.mappings.filter(m => !(m.type === 'column' && m.target === col));
            newMappings.push({ target: col, field, type: 'column' });
            // 清除该列已有的单元格映射
            newMappings = newMappings.filter(m => {
                if (m.type !== 'cell') return true;
                return !new RegExp(`^${col}\\d+$`).test(m.target);
            });
            return { ...prev, mappings: newMappings };
        });
    };

    const handleCellDrop = (cellRef, field) => {
        if (!field) return;
        setTemplateForm(prev => {
            const newMappings = prev.mappings.filter(m => m.target !== cellRef);
            newMappings.push({ target: cellRef, field, type: 'cell' });
            return { ...prev, mappings: newMappings };
        });
    };

    const removeColumnMapping = (col) => {
        setTemplateForm(prev => ({
            ...prev,
            mappings: prev.mappings.filter(m => !(m.type === 'column' && m.target === col))
        }));
    };

    const removeCellMapping = (cellRef) => {
        setTemplateForm(prev => ({
            ...prev,
            mappings: prev.mappings.filter(m => m.target !== cellRef)
        }));
    };

    const addMappingRow = () => {
        setTemplateForm(prev => ({
            ...prev,
            mappings: [...prev.mappings, { target: '', field: '', type: prev.template_type === 'cell' ? 'cell' : 'column' }]
        }));
    };

    const removeMappingRow = (index) => {
        setTemplateForm(prev => ({
            ...prev,
            mappings: prev.mappings.filter((_, i) => i !== index)
        }));
    };

    const updateMappingRow = (index, key, value) => {
        setTemplateForm(prev => {
            const newMappings = [...prev.mappings];
            newMappings[index] = { ...newMappings[index], [key]: value };
            return { ...prev, mappings: newMappings };
        });
    };

    // ==================== 品名管理相关函数 ====================

    const fetchGoodsNames = async () => {
        setGoodsNameLoading(true);
        try {
            const response = await fetch(`${endpoint}/goods-names`, {
                headers: getSafeHeader()
            });
            const result = await response.json();
            if (result.code === 200) {
                setGoodsNames(result.data || []);
            } else {
                message.error(result.msg || '获取品名列表失败');
            }
        } catch (error) {
            console.error('Fetch goods names error:', error);
            message.error('获取品名列表失败');
        } finally {
            setGoodsNameLoading(false);
        }
    };

    const handleAddGoodsName = async (lang) => {
        const raw = lang === 'cn' ? newCnName : newEnName;
        const names = raw
            .split(/[、\n]+/)
            .map(s => s.trim())
            .filter(s => s.length > 0);
        if (names.length === 0) {
            message.warning('请输入品名');
            return;
        }
        setSubmitting(true);
        try {
            const results = await Promise.allSettled(
                names.map(name =>
                    fetch(`${endpoint}/goods-names`, {
                        method: 'POST',
                        headers: {
                            ...getSafeHeader(),
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ lang, name })
                    }).then(r => r.json())
                )
            );
            const successCount = results.filter(r => r.status === 'fulfilled' && r.value.code === 200).length;
            const failCount = names.length - successCount;
            if (successCount > 0) {
                message.success(`成功添加 ${successCount} 个品名`);
            }
            if (failCount > 0) {
                message.warning(`${failCount} 个品名添加失败（可能已存在）`);
            }
            if (lang === 'cn') setNewCnName('');
            else setNewEnName('');
            fetchGoodsNames();
        } catch (error) {
            console.error('Add goods name error:', error);
            message.error('添加失败');
        } finally {
            setSubmitting(false);
        }
    };

    const handleDeleteGoodsName = async (id) => {
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/goods-names/${id}`, {
                method: 'DELETE',
                headers: getSafeHeader()
            });
            const result = await response.json();
            if (result.code === 200) {
                message.success('删除成功');
                fetchGoodsNames();
            } else {
                message.error(result.msg || '删除失败');
            }
        } catch (error) {
            console.error('Delete goods name error:', error);
            message.error('删除失败');
        } finally {
            setSubmitting(false);
        }
    };

    const handleUpdateGoodsName = async (id, newName) => {
        const name = newName.trim();
        if (!name) {
            message.warning('品名不能为空');
            return;
        }
        setSubmitting(true);
        try {
            const response = await fetch(`${endpoint}/goods-names/${id}`, {
                method: 'PUT',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ name })
            });
            const result = await response.json();
            if (result.code === 200) {
                message.success('更新成功');
                setEditingGoodsName({ id: null, name: '' });
                fetchGoodsNames();
            } else {
                message.error(result.msg || '更新失败');
            }
        } catch (error) {
            console.error('Update goods name error:', error);
            message.error('更新失败');
        } finally {
            setSubmitting(false);
        }
    };

    const columns = [
        {
            title: '姓名',
            dataIndex: 'name',
            key: 'name',
            render: (text) => <Space><UserOutlined />{text}</Space>
        },
        {
            title: '手机号',
            dataIndex: 'phone',
            key: 'phone',
        },
        {
            title: '申请时间',
            dataIndex: 'create_date',
            key: 'create_date',
        },
        {
            title: '状态',
            dataIndex: 'status',
            key: 'status',
            render: (status) => {
                let color = 'default';
                let text = '未知';
                if (status === 'pending') {
                    color = 'processing';
                    text = '待审核';
                } else if (status === 'approved') {
                    color = 'success';
                    text = '已通过';
                } else if (status === 'rejected') {
                    color = 'error';
                    text = '已拒绝';
                }
                return <Tag color={color}>{text}</Tag>;
            }
        },
        {
            title: '操作',
            key: 'action',
            render: (_, record) => (
                <Space size="middle">
                    {record.status === 'pending' && (
                        <>
                            <Button
                                type="primary"
                                size="small"
                                icon={<CheckOutlined />}
                                onClick={() => showApproveModal(record)}
                            >
                                通过
                            </Button>
                            <Button
                                danger
                                size="small"
                                icon={<CloseOutlined />}
                                onClick={() => showRejectModal(record)}
                            >
                                拒绝
                            </Button>
                        </>
                    )}
                </Space>
            ),
        },
    ];

    const userColumns = [
        {
            title: '姓名',
            dataIndex: 'name',
            key: 'name',
            render: (text) => <Space><UserOutlined />{text}</Space>
        },
        {
            title: '手机号',
            dataIndex: 'phone',
            key: 'phone',
        },
        {
            title: '状态',
            dataIndex: 'status',
            key: 'status',
            render: (status) => <Tag color={status === 'approved' ? 'success' : 'processing'}>{status || '-'}</Tag>
        },
        {
            title: '当前角色',
            dataIndex: 'roles',
            key: 'roles',
            render: (roles) => (
                <Space size={4} wrap>
                    {Array.isArray(roles) && roles.length > 0
                        ? roles.map(r => <Tag key={r} color="blue">{ROLE_LABEL_MAP[r] || r}</Tag>)
                        : <Typography.Text type="secondary">未设置</Typography.Text>
                    }
                </Space>
            )
        },
        {
            title: '角色管理',
            key: 'roleAction',
            render: (_, record) => (
                <Space>
                    <Select
                        mode="multiple"
                        allowClear
                        placeholder="选择角色（清空=移除）"
                        style={{ width: 220 }}
                        value={Object.prototype.hasOwnProperty.call(editingRoleUser, record.id)
                            ? editingRoleUser[record.id] ?? []
                            : (record.roles || [])}
                        options={ROLE_OPTIONS}
                        onChange={(value) => {
                            setEditingRoleUser((prev) => ({ ...prev, [record.id]: value === undefined ? [] : value }));
                        }}
                    />
                    <Button type="primary" loading={submitting} onClick={() => handleUpdateRole(record)}>
                        保存
                    </Button>
                    <Button icon={<KeyOutlined />} onClick={() => showResetPasswordModal(record)}>
                        重置密码
                    </Button>
                    <Button danger onClick={() => showDeleteModal(record)}>
                        删除
                    </Button>
                </Space>
            )
        }
    ];

    const passwordRequestColumns = [
        {
            title: '用户姓名',
            dataIndex: 'user_name',
            key: 'user_name',
            render: (text) => <Space><UserOutlined />{text}</Space>
        },
        {
            title: '手机号',
            dataIndex: 'user_phone',
            key: 'user_phone',
        },
        {
            title: '申请时间',
            dataIndex: 'create_date',
            key: 'create_date',
        },
        {
            title: '操作',
            key: 'action',
            render: (_, record) => (
                <Space size="middle">
                    <Button
                        type="primary"
                        size="small"
                        icon={<CheckOutlined />}
                        onClick={() => handleApprovePasswordRequest(record.id)}
                        loading={submitting}
                    >
                        通过
                    </Button>
                    <Button
                        danger
                        size="small"
                        icon={<CloseOutlined />}
                        onClick={() => showRejectPasswordModal(record)}
                    >
                        拒绝
                    </Button>
                </Space>
            ),
        },
    ];

    return (
        <Space direction="vertical" size={16} style={{ margin: 20, width: 'calc(100% - 40px)' }}>
            <Card title="用户申请管理">
                <Table
                    columns={columns}
                    dataSource={data}
                    rowKey="id"
                    loading={loading}
                    pagination={{ pageSize: 10 }}
                />
            </Card>

            <Card title="用户角色管理">
                <Table
                    columns={userColumns}
                    dataSource={users}
                    rowKey="id"
                    loading={usersLoading}
                    pagination={{ pageSize: 10 }}
                />
            </Card>

            <Card title="密码重置申请">
                <Table
                    columns={passwordRequestColumns}
                    dataSource={passwordRequests}
                    rowKey="id"
                    loading={passwordRequestsLoading}
                    pagination={{ pageSize: 10 }}
                    locale={{ emptyText: '暂无密码重置申请' }}
                />
            </Card>

            {/* <Card title="品名管理">
                <Tabs
                    items={[
                        {
                            key: 'cn',
                            label: '中文品名',
                            children: (
                                <Space direction="vertical" style={{ width: '100%' }}>
                                    <Space align="start">
                                        <Input.TextArea
                                            placeholder="输入中文品名，支持顿号、换行分隔批量输入"
                                            value={newCnName}
                                            onChange={(e) => setNewCnName(e.target.value)}
                                            style={{ width: 240 }}
                                            rows={3}
                                        />
                                        <Button type="primary" onClick={() => handleAddGoodsName('cn')} loading={submitting}>
                                            添加
                                        </Button>
                                    </Space>
                                    <Table
                                        dataSource={goodsNames.filter(g => g.lang === 'cn')}
                                        rowKey="id"
                                        loading={goodsNameLoading}
                                        pagination={{ pageSize: 10 }}
                                        scroll={{ y: 400 }}
                                        columns={[
                                            {
                                                title: '品名',
                                                dataIndex: 'name',
                                                key: 'name',
                                                render: (text, record) => {
                                                    if (editingGoodsName.id === record.id) {
                                                        return (
                                                            <Space>
                                                                <Input
                                                                    value={editingGoodsName.name}
                                                                    onChange={(e) => setEditingGoodsName({ ...editingGoodsName, name: e.target.value })}
                                                                    onPressEnter={() => handleUpdateGoodsName(record.id, editingGoodsName.name)}
                                                                    style={{ width: 200 }}
                                                                />
                                                                <Button type="primary" size="small" onClick={() => handleUpdateGoodsName(record.id, editingGoodsName.name)}>保存</Button>
                                                                <Button size="small" onClick={() => setEditingGoodsName({ id: null, name: '' })}>取消</Button>
                                                            </Space>
                                                        );
                                                    }
                                                    return text;
                                                }
                                            },
                                            {
                                                title: '操作',
                                                key: 'action',
                                                width: 160,
                                                render: (_, record) => (
                                                    <Space>
                                                        <Button size="small" onClick={() => setEditingGoodsName({ id: record.id, name: record.name })}>编辑</Button>
                                                        <Button danger size="small" onClick={() => handleDeleteGoodsName(record.id)}>删除</Button>
                                                    </Space>
                                                )
                                            }
                                        ]}
                                    />
                                </Space>
                            )
                        },
                        {
                            key: 'en',
                            label: '英文品名',
                            children: (
                                <Space direction="vertical" style={{ width: '100%' }}>
                                    <Space align="start">
                                        <Input.TextArea
                                            placeholder="输入英文品名，支持顿号、换行分隔批量输入"
                                            value={newEnName}
                                            onChange={(e) => setNewEnName(e.target.value)}
                                            style={{ width: 240 }}
                                            rows={3}
                                        />
                                        <Button type="primary" onClick={() => handleAddGoodsName('en')} loading={submitting}>
                                            添加
                                        </Button>
                                    </Space>
                                    <Table
                                        dataSource={goodsNames.filter(g => g.lang === 'en')}
                                        rowKey="id"
                                        loading={goodsNameLoading}
                                        pagination={{ pageSize: 10 }}
                                        scroll={{ y: 400 }}
                                        columns={[
                                            {
                                                title: '品名',
                                                dataIndex: 'name',
                                                key: 'name',
                                                render: (text, record) => {
                                                    if (editingGoodsName.id === record.id) {
                                                        return (
                                                            <Space>
                                                                <Input
                                                                    value={editingGoodsName.name}
                                                                    onChange={(e) => setEditingGoodsName({ ...editingGoodsName, name: e.target.value })}
                                                                    onPressEnter={() => handleUpdateGoodsName(record.id, editingGoodsName.name)}
                                                                    style={{ width: 200 }}
                                                                />
                                                                <Button type="primary" size="small" onClick={() => handleUpdateGoodsName(record.id, editingGoodsName.name)}>保存</Button>
                                                                <Button size="small" onClick={() => setEditingGoodsName({ id: null, name: '' })}>取消</Button>
                                                            </Space>
                                                        );
                                                    }
                                                    return text;
                                                }
                                            },
                                            {
                                                title: '操作',
                                                key: 'action',
                                                width: 160,
                                                render: (_, record) => (
                                                    <Space>
                                                        <Button size="small" onClick={() => setEditingGoodsName({ id: record.id, name: record.name })}>编辑</Button>
                                                        <Button danger size="small" onClick={() => handleDeleteGoodsName(record.id)}>删除</Button>
                                                    </Space>
                                                )
                                            }
                                        ]}
                                    />
                                </Space>
                            )
                        }
                    ]}
                />
            </Card> */}

            <Card title="Excel模板管理">
                <Space direction="vertical" style={{ width: '100%' }}>
                    <Button type="primary" onClick={() => openTemplateModal(null)} icon={<PlusOutlined />}>
                        新增模板
                    </Button>
                    <Table
                        dataSource={excelTemplates}
                        rowKey="id"
                        loading={excelTemplateLoading}
                        pagination={{ pageSize: 10 }}
                        columns={[
                            { title: '标识', dataIndex: 'mode_key', key: 'mode_key' },
                            { title: '名称', dataIndex: 'label', key: 'label' },
                            {
                                title: '类型',
                                dataIndex: 'template_type',
                                key: 'template_type',
                                render: (type) => type === 'column' ? '列模式' : '单元格模式'
                            },
                            {
                                title: '单订单限制',
                                dataIndex: 'single_order_only',
                                key: 'single_order_only',
                                render: (v) => v ? <Tag color="orange">是</Tag> : <Tag>否</Tag>
                            },
                            {
                                title: '操作',
                                key: 'action',
                                render: (_, record) => (
                                    <Space>
                                        <Button size="small" onClick={() => openTemplateModal(record)}>编辑</Button>
                                        <Button size="small" onClick={() => handleArchiveTemplate(record.id)}>归档</Button>
                                        <Button danger size="small" onClick={() => handleDeleteTemplate(record.id)}>删除</Button>
                                    </Space>
                                )
                            }
                        ]}
                    />
                </Space>
            </Card>

            {/* Excel 模板编辑对话框 */}
            <Modal
                title={editingTemplate ? '编辑模板' : '新增模板'}
                open={excelModalVisible}
                onOk={handleSaveTemplate}
                onCancel={closeTemplateModal}
                confirmLoading={templateSubmitting}
                okText="保存"
                cancelText="取消"
                width={900}
            >
                <Space direction="vertical" style={{ width: '100%' }} size="middle">
                    <Space>
                        <span>模板标识：</span>
                        <Input
                            placeholder="如 jifei"
                            value={templateForm.mode_key}
                            onChange={(e) => setTemplateForm(prev => ({ ...prev, mode_key: e.target.value }))}
                            disabled={!!editingTemplate}
                            style={{ width: 200 }}
                        />
                    </Space>
                    <Space>
                        <span>模板名称：</span>
                        <Input
                            placeholder="如 极飞订单"
                            value={templateForm.label}
                            onChange={(e) => setTemplateForm(prev => ({ ...prev, label: e.target.value }))}
                            style={{ width: 200 }}
                        />
                    </Space>
                    <Space>
                        <span>导出类型：</span>
                        <Select
                            value={templateForm.template_type}
                            onChange={(value) => setTemplateForm(prev => ({
                                ...prev,
                                template_type: value,
                                single_order_only: value === 'cell' ? true : prev.single_order_only
                            }))}
                            style={{ width: 200 }}
                            options={[
                                { value: 'column', label: '列模式（批量）' },
                                { value: 'cell', label: '单元格模式（单订单）' },
                            ]}
                        />
                    </Space>
                    <Space>
                        <span>仅限单订单：</span>
                        <Switch
                            checked={templateForm.single_order_only}
                            onChange={(checked) => setTemplateForm(prev => ({ ...prev, single_order_only: checked }))}
                            disabled={templateForm.template_type === 'cell'}
                        />
                    </Space>

                    <Space direction="vertical" style={{ width: '100%' }}>
                        <span>上传模板文件（.xlsx/.xls）：</span>
                        <Upload
                            beforeUpload={() => false}
                            fileList={templateFileList}
                            onChange={handleTemplateFileChange}
                            accept=".xlsx,.xls"
                            maxCount={1}
                        >
                            <Button icon={<UploadOutlined />}>选择文件</Button>
                        </Upload>
                        {editingTemplate?.template_file && (
                            <Typography.Text type="secondary">
                                当前文件：{editingTemplate.template_file}
                            </Typography.Text>
                        )}
                    </Space>

                    {/* 可视化配置：有文件预览时显示 */}
                    {excelPreview && (
                        <div style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: 16 }}>
                            <div style={{ marginBottom: 12, fontWeight: 'bold' }}>
                                拖拽字段到表格中：列头 = 列映射（整列），单元格 = 单元格映射（单格）
                            </div>
                            {/* 字段标签池 */}
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16, padding: 12, background: '#fafafa', borderRadius: 4 }}>
                                {EXPORT_FIELDS.map(field => (
                                    <Tag
                                        key={field.value}
                                        draggable
                                        onDragStart={() => handleFieldDragStart(field.value)}
                                        style={{ cursor: 'move', userSelect: 'none' }}
                                        color="blue"
                                    >
                                        {field.label}
                                    </Tag>
                                ))}
                            </div>

                            {/* Excel 预览网格 */}
                            <div style={{ overflowX: 'auto' }}>
                                <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13, tableLayout: 'fixed' }}>
                                    <thead>
                                        <tr>
                                            {excelPreview.columns.map(col => {
                                                const colMapping = templateForm.mappings.find(m => m.type === 'column' && m.target === col);
                                                return (
                                                    <th
                                                        key={col}
                                                        onDragOver={(e) => e.preventDefault()}
                                                        onDrop={(e) => {
                                                            e.preventDefault();
                                                            handleColumnDrop(col, draggingField);
                                                        }}
                                                        style={{
                                                            border: '1px solid #d9d9d9',
                                                            padding: '6px 8px',
                                                            backgroundColor: colMapping ? '#e6f7ff' : '#f5f5f5',
                                                            width: 120,
                                                            maxWidth: 120,
                                                            overflow: 'hidden',
                                                            position: 'relative',
                                                        }}
                                                    >
                                                        <Tooltip title={col}>
                                                            <div style={{ fontWeight: 'bold', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{col}</div>
                                                        </Tooltip>
                                                        {colMapping && (
                                                            <div style={{ marginTop: 4 }}>
                                                                <Tag
                                                                    closable
                                                                    onClose={() => removeColumnMapping(col)}
                                                                    color="processing"
                                                                >
                                                                    {EXPORT_FIELDS.find(f => f.value === colMapping.field)?.label || colMapping.field}
                                                                </Tag>
                                                            </div>
                                                        )}
                                                    </th>
                                                );
                                            })}
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {excelPreview.rows.map((row, rowIdx) => (
                                            <tr key={rowIdx}>
                                                {row.map((cell, colIdx) => {
                                                    const cellMapping = templateForm.mappings.find(m => m.type === 'cell' && m.target === cell.cellRef);
                                                    const isMapped = !!cellMapping;
                                                    return (
                                                        <td
                                                            key={colIdx}
                                                            onDragOver={(e) => e.preventDefault()}
                                                            onDrop={(e) => {
                                                                e.preventDefault();
                                                                handleCellDrop(cell.cellRef, draggingField);
                                                            }}
                                                            style={{
                                                                border: '1px solid #d9d9d9',
                                                                padding: '6px 8px',
                                                                backgroundColor: isMapped ? '#fff7e6' : 'white',
                                                                width: 120,
                                                                maxWidth: 120,
                                                                height: 40,
                                                                overflow: 'hidden',
                                                                verticalAlign: 'top',
                                                            }}
                                                        >
                                                            <Tooltip title={cell.value}>
                                                                <div style={{ color: '#666', minHeight: 18, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{cell.value}</div>
                                                            </Tooltip>
                                                            {isMapped && (
                                                                <div style={{ marginTop: 4 }}>
                                                                    <Tag
                                                                        closable
                                                                        onClose={() => removeCellMapping(cell.cellRef)}
                                                                        color="warning"
                                                                        size="small"
                                                                    >
                                                                        {EXPORT_FIELDS.find(f => f.value === cellMapping.field)?.label || cellMapping.field}
                                                                    </Tag>
                                                                </div>
                                                            )}
                                                        </td>
                                                    );
                                                })}
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>

                            {/* 已放置映射汇总 */}
                            <div style={{ marginTop: 12 }}>
                                <Typography.Text type="secondary">
                                    列映射：{templateForm.mappings.filter(m => m.type === 'column').length} 个，单元格映射：{templateForm.mappings.filter(m => m.type === 'cell').length} 个
                                </Typography.Text>
                            </div>
                        </div>
                    )}

                    {/* 字段映射表格：始终显示 */}
                    <div>
                        <Space style={{ marginBottom: 8 }}>
                            <span>字段映射：</span>
                            <Button size="small" icon={<PlusOutlined />} onClick={addMappingRow}>添加行</Button>
                        </Space>
                        <Table
                            dataSource={templateForm.mappings.map((m, i) => ({ ...m, key: i }))}
                            pagination={false}
                            size="small"
                            columns={[
                                {
                                    title: '目标',
                                    dataIndex: 'target',
                                    key: 'target',
                                    render: (text, record, index) => (
                                        <Input
                                            value={text}
                                            placeholder={record.type === 'column' ? '如 A' : '如 B3'}
                                            onChange={(e) => updateMappingRow(index, 'target', e.target.value)}
                                            style={{ width: 120 }}
                                        />
                                    )
                                },
                                {
                                    title: '对应字段',
                                    dataIndex: 'field',
                                    key: 'field',
                                    render: (text, record, index) => (
                                        <Select
                                            value={text || undefined}
                                            placeholder="选择字段"
                                            onChange={(value) => updateMappingRow(index, 'field', value)}
                                            style={{ width: 160 }}
                                            options={EXPORT_FIELDS}
                                            allowClear
                                        />
                                    )
                                },
                                {
                                    title: '类型',
                                    dataIndex: 'type',
                                    key: 'type',
                                    render: (text, record, index) => (
                                        <Select
                                            value={text}
                                            onChange={(value) => updateMappingRow(index, 'type', value)}
                                            style={{ width: 120 }}
                                            options={[
                                                { value: 'column', label: '列映射' },
                                                { value: 'cell', label: '单元格映射' },
                                            ]}
                                        />
                                    )
                                },
                                {
                                    title: '操作',
                                    key: 'action',
                                    width: 80,
                                    render: (_, record) => (
                                        <Button
                                            danger
                                            size="small"
                                            icon={<DeleteOutlined />}
                                            onClick={() => removeMappingRow(record.key)}
                                        />
                                    )
                                }
                            ]}
                        />
                    </div>
                </Space>
            </Modal>

            {/* 审核通过对话框 */}
            <Modal
                title="审核通过"
                open={approveModalVisible}
                onOk={handleApprove}
                onCancel={() => setApproveModalVisible(false)}
                confirmLoading={submitting}
                okText="确认通过"
                cancelText="取消"
            >
                <p>确定通过用户 <strong>{currentRecord?.name}</strong> 的申请吗？</p>
                <div style={{ marginTop: 16 }}>
                    <span>分配角色：</span>
                    <Select
                        mode="multiple"
                        value={selectedRoles}
                        onChange={setSelectedRoles}
                        style={{ width: '100%', marginTop: 8 }}
                        options={ROLE_OPTIONS}
                        placeholder="请选择角色"
                    />
                </div>
            </Modal>

            {/* 审核拒绝对话框 */}
            <Modal
                title="审核拒绝"
                open={rejectModalVisible}
                onOk={handleReject}
                onCancel={() => setRejectModalVisible(false)}
                confirmLoading={submitting}
                okText="确认拒绝"
                cancelText="取消"
            >
                <p>确定拒绝用户 <strong>{currentRecord?.name}</strong> 的申请吗？</p>
                <div style={{ marginTop: 16 }}>
                    <span>拒绝原因（选填）：</span>
                    <Input.TextArea
                        value={rejectRemark}
                        onChange={(e) => setRejectRemark(e.target.value)}
                        placeholder="请输入拒绝原因"
                        rows={3}
                        style={{ marginTop: 8 }}
                    />
                </div>
            </Modal>

            {/* 拒绝密码重置申请对话框 */}
            <Modal
                title="拒绝密码重置申请"
                open={rejectPasswordModalVisible}
                onOk={handleRejectPasswordRequest}
                onCancel={() => setRejectPasswordModalVisible(false)}
                confirmLoading={submitting}
                okText="确认拒绝"
                cancelText="取消"
            >
                <p>确定拒绝用户 <strong>{currentPasswordRequest?.user_name}</strong> 的密码重置申请吗？</p>
                <div style={{ marginTop: 16 }}>
                    <span>拒绝原因（选填）：</span>
                    <Input.TextArea
                        value={passwordRejectRemark}
                        onChange={(e) => setPasswordRejectRemark(e.target.value)}
                        placeholder="请输入拒绝原因"
                        rows={3}
                        style={{ marginTop: 8 }}
                    />
                </div>
            </Modal>

            {/* 重置密码对话框 */}
            <Modal
                title="重置用户密码"
                open={resetPasswordModalVisible}
                onOk={handleResetPassword}
                onCancel={() => setResetPasswordModalVisible(false)}
                confirmLoading={submitting}
                okText="确认重置"
                cancelText="取消"
            >
                <p>为用户 <strong>{resetPasswordUser?.name}</strong>（{resetPasswordUser?.phone}）设置新密码：</p>
                <div style={{ marginTop: 16 }}>
                    <Input.Password
                        value={newPassword}
                        onChange={(e) => setNewPassword(e.target.value)}
                        placeholder="请输入新密码（至少6位）"
                        style={{ width: '100%' }}
                    />
                </div>
            </Modal>

            {/* 删除用户对话框 */}
            <Modal
                title="删除用户"
                open={deleteModalVisible}
                onOk={handleDeleteUser}
                onCancel={() => setDeleteModalVisible(false)}
                confirmLoading={submitting}
                okText="确认删除"
                cancelText="取消"
                okButtonProps={{ danger: true }}
            >
                <p>确定删除用户 <strong>{userToDelete?.name}</strong>（{userToDelete?.phone}）吗？此操作不可恢复。</p>
            </Modal>
        </Space>
    );
};

export default AdminPage;
