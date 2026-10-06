import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import {
    Card,
    AutoComplete,
    Input,
    InputNumber,
    Select,
    Button,
    Space,
    Tag,
    Typography,
    message,
    Modal,
    Descriptions,
    Image,
    List,
    Form,
    Grid,
    Checkbox,
    Spin,
    Popconfirm,
    Dropdown
} from 'antd';
import {
    PrinterOutlined,
    PlusOutlined,
    CheckOutlined,
    DeleteOutlined,
    EditOutlined,
    ArrowLeftOutlined,
    CloseOutlined,
    ReloadOutlined
} from '@ant-design/icons';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import { hasPermission } from '../common/roleConfig';
import { getBoxEditPolicy, normalizeOrderEditPolicy } from '../common/orderEditPolicy';
import { isBoxIdentityEditable, isBoxOriginalNumberEditable, isCargoOutboundOrLater } from '../common/cargoStatus';
import { buildCustomsCodeOptions, findCustomsCodeForName } from '../common/customsCodeLookup';
import styles from './packingListDetail.module.css';

const { Title, Text } = Typography;
const { Option } = Select;

const BOX_STATUS = {
    PENDING_ASSIGN: 'pending_assign',
    PENDING_OUTBOUND: 'pending_outbound',
    OUTBOUND: 'outbound'
};

const BOX_STATUS_META = {
    [BOX_STATUS.PENDING_ASSIGN]: { text: '待分配', color: 'gold', level: 0 },
    [BOX_STATUS.PENDING_OUTBOUND]: { text: '待出库', color: 'blue', level: 1 },
    [BOX_STATUS.OUTBOUND]: { text: '已出库', color: 'green', level: 2 }
};

const PACKING_DRAFT_META = { text: '草稿', color: 'default', level: -1 };

const getMarkText = (record) => record?.list_number || record?.mark || '-';

const normalizeCustomerId = (value) => {
    if (value === undefined || value === null || value === '') return null;
    const n = Number(value);
    return Number.isNaN(n) ? null : n;
};

const normalizeMark = (value) => String(value || '').trim().toUpperCase();

const isSameStringArray = (a, b) => {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((item, idx) => String(item || '') === String(b[idx] || ''));
};

const getBoxItemDetails = (box) => {
    const details = Array.isArray(box?.item_details) ? box.item_details : [];
    if (details.length > 0) {
        return details
            .map((row) => {
                const name = (row?.item_name || '').trim();
                const piece = Number(row?.piece_count || 0);
                if (!name) return null;
                return {
                    item_name: name,
                    customs_code: String(row?.customs_code || '').trim(),
                    piece_count: piece > 0 ? piece : 0,
                };
            })
            .filter(Boolean);
    }

    const fallbackName = (box?.item_name || '').trim();
    const fallbackPiece = Number(box?.piece_count || 0);
    return fallbackName
        ? [{ item_name: fallbackName, customs_code: '', piece_count: fallbackPiece > 0 ? fallbackPiece : 0 }]
        : [];
};

const normalizeBoxStatus = (box) => {
    if (isCargoOutboundOrLater(box)) {
        return BOX_STATUS.OUTBOUND;
    }

    const hasOrder = !!box?.target_order_uid;
    if (!hasOrder) {
        return BOX_STATUS.PENDING_ASSIGN;
    }
    return BOX_STATUS.PENDING_OUTBOUND;
};

const getBoxStatusMeta = (box) => {
    const code = normalizeBoxStatus(box);
    return BOX_STATUS_META[code] || BOX_STATUS_META[BOX_STATUS.PENDING_ASSIGN];
};

const getPackingListStatusMeta = (record) => {
    if (record?.status === 'draft') {
        return PACKING_DRAFT_META;
    }

    const boxes = Array.isArray(record?.boxes) ? record.boxes : [];
    if (boxes.length === 0) return BOX_STATUS_META[BOX_STATUS.PENDING_ASSIGN];

    const minLevel = boxes.reduce((min, box) => {
        const meta = getBoxStatusMeta(box);
        return Math.min(min, meta.level);
    }, Number.MAX_SAFE_INTEGER);

    const matched = Object.values(BOX_STATUS_META).find((meta) => meta.level === minLevel);
    return matched || BOX_STATUS_META[BOX_STATUS.PENDING_ASSIGN];
};

const renderBoxStatusTag = (box) => (
    <Tag color={getBoxStatusMeta(box).color}>{getBoxStatusMeta(box).text}</Tag>
);

function getJwtPayload() {
    const token = localStorage.getItem('jwt');
    if (!token) return {};
    try {
        const parts = token.split('.');
        if (parts.length !== 3) return {};
        return JSON.parse(atob(parts[1]));
    } catch (_) {
        return {};
    }
}

export default function PackingListDetail() {
    const { uid } = useParams();
    const navigate = useNavigate();
    const [messageApi, contextHolder] = message.useMessage();
    const [payload, setPayload] = useState({});
    const screens = Grid.useBreakpoint();

    const [currentDetail, setCurrentDetail] = useState(null);
    const [loading, setLoading] = useState(true);
    const [workers, setWorkers] = useState([]);
    const [customers, setCustomers] = useState([]);
    const [customsCodes, setCustomsCodes] = useState([]);
    const [boxForm] = Form.useForm();
    const [addingBox, setAddingBox] = useState(false);
    const [addBoxVisible, setAddBoxVisible] = useState(false);
    const [completing, setCompleting] = useState(false);
    const [deleting, setDeleting] = useState(false);
    const [customerEditVisible, setCustomerEditVisible] = useState(false);
    const [editingMark, setEditingMark] = useState('');
    const [editingCustomerId, setEditingCustomerId] = useState(null);
    const [editingPackingStatus, setEditingPackingStatus] = useState('draft');
    const [editingPhotos, setEditingPhotos] = useState([]);
    const [savingCustomer, setSavingCustomer] = useState(false);
    const [batchDeleting, setBatchDeleting] = useState(false);
    const [generatingOriginalNumbers, setGeneratingOriginalNumbers] = useState(false);
    const originalGenerationPending = useRef(false);
    const activePackingUid = useRef(uid);
    activePackingUid.current = uid;
    const [selectedBatchAction, setSelectedBatchAction] = useState('archive');
    const [selectedShipBoxUids, setSelectedShipBoxUids] = useState([]);
    const [boxEditVisible, setBoxEditVisible] = useState(false);
    const [editingBox, setEditingBox] = useState(null);
    const [savingBox, setSavingBox] = useState(false);
    const [undoShippingBoxUid, setUndoShippingBoxUid] = useState(null);
    const [deletingBoxUid, setDeletingBoxUid] = useState(null);
    const [boxEditForm] = Form.useForm();
    const addBoxItemDetails = Form.useWatch('item_details', boxForm) || [];
    const editBoxItemDetails = Form.useWatch('item_details', boxEditForm) || [];

    const canDeletePackingList = hasPermission(payload?.roles, ['admin', 'store_manager']);
    const canEditPackingListDetail = hasPermission(payload?.roles, ['admin', 'store_manager', 'salesperson']);
    const canEditBoxes = hasPermission(payload?.roles, ['admin', 'store_manager', 'salesperson', 'clerk']);
    const canUndoShip = hasPermission(payload?.roles, ['admin', 'store_manager']);
    const boxPolicyDefaults = {
        box_content: canEditBoxes,
        box_weight: hasPermission(payload?.roles, ['admin', 'store_manager', 'salesperson', 'worker']),
        tracking_numbers: canEditBoxes,
        box_workers: canEditBoxes,
        archive_or_delete: canEditBoxes,
    };
    const resolveBoxPolicy = (box) => {
        const policy = getBoxEditPolicy(box, currentDetail, boxPolicyDefaults);
        return {
            ...policy,
            box_weight: policy.box_weight && normalizeBoxStatus(box) !== BOX_STATUS.OUTBOUND,
        };
    };
    const packingListPolicy = normalizeOrderEditPolicy(currentDetail?.edit_policy, {
        defaults: {
            order_fields: canEditPackingListDetail,
            archive_or_delete: canDeletePackingList,
        },
    });
    const canOpenBoxEditor = (box) => {
        const policy = resolveBoxPolicy(box);
        return policy.box_content || policy.box_weight || policy.tracking_numbers || policy.box_workers;
    };
    const assignedBoxes = (currentDetail?.boxes || []).filter(box => box.target_order_uid);
    const canEditPackingListByPolicy = packingListPolicy.order_fields
        && assignedBoxes.every(box => resolveBoxPolicy(box).box_content);
    const canArchivePackingListByPolicy = packingListPolicy.archive_or_delete
        && assignedBoxes.every(box => resolveBoxPolicy(box).archive_or_delete);

    useEffect(() => {
        setPayload(getJwtPayload());
    }, []);

    useEffect(() => {
        if (uid) {
            handleViewDetail(uid);
            fetchWorkers();
            fetchCustomers();
            fetchCustomsCodes();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [uid]);

    useEffect(() => {
        setSelectedShipBoxUids([]);
    }, [uid]);

    const fetchCustomers = async () => {
        try {
            const res = await fetch(`${endpoint}/customer_list`, {
                headers: getSafeHeader()
            });
            const data = await res.json();
            if (data.code === 200) {
                setCustomers(data.data || []);
            }
        } catch (error) {
            console.error('获取客户列表失败:', error);
        }
    };

    const fetchWorkers = async () => {
        try {
            const res = await fetch(`${endpoint}/users/list`, {
                headers: getSafeHeader()
            });
            const data = await res.json();
            if (data.code === 200) {
                setWorkers(data.data || []);
            }
        } catch (error) {
            console.error('获取操作员列表失败:', error);
        }
    };

    const fetchCustomsCodes = async () => {
        try {
            const res = await fetch(`${endpoint}/customs-codes`, {
                headers: getSafeHeader()
            });
            const data = await res.json();
            if (data.code === 200) setCustomsCodes(data.data || []);
        } catch (error) {
            console.error('获取海关编码失败:', error);
        }
    };

    const getCustomsCodeOptions = (itemName) => {
        return buildCustomsCodeOptions(customsCodes, itemName);
    };

    const handleItemNameChange = (form, index, value) => {
        form.setFieldValue(
            ['item_details', index, 'customs_code'],
            findCustomsCodeForName(customsCodes, value)
        );
    };

    const handleViewDetail = async (detailUid) => {
        setLoading(true);
        try {
            const res = await fetch(`${endpoint}/packing-list/${detailUid}`, {
                headers: getSafeHeader()
            });
            const data = await res.json();

            if (data.code === 200) {
                setCurrentDetail(data.data);
            } else {
                messageApi.error(data.msg || '获取详情失败');
            }
        } catch (error) {
            messageApi.error('获取详情失败');
            console.error(error);
        } finally {
            setLoading(false);
        }
    };

    const handlePrintPackingList = async (packingListUid, boxUids = []) => {
        if (!packingListUid) return;
        const selectedBoxUids = (Array.isArray(boxUids) ? boxUids : []).filter(Boolean);

        if (Array.isArray(boxUids) && selectedBoxUids.length === 0) {
            messageApi.warning('请先选择要打印的箱子');
            return;
        }

        const previewWindow = window.open('', '_blank');
        if (!previewWindow) {
            messageApi.warning('浏览器拦截了新窗口，请允许弹窗后重试');
            return;
        }
        previewWindow.document.write('正在生成装箱单 PDF...');

        try {
            const query = selectedBoxUids.length > 0
                ? `?box_uids=${encodeURIComponent(selectedBoxUids.join(','))}`
                : '';
            const res = await fetch(`${endpoint}/packing-list/${packingListUid}/pdf${query}`, {
                headers: getSafeHeader()
            });

            if (!res.ok) {
                let errMsg = '导出装箱单失败';
                const contentType = (res.headers.get('content-type') || '').toLowerCase();
                if (contentType.includes('application/json')) {
                    const errData = await res.json();
                    errMsg = errData?.msg || errMsg;
                }
                throw new Error(errMsg);
            }

            const blob = await res.blob();
            const blobUrl = window.URL.createObjectURL(blob);
            previewWindow.location.href = blobUrl;
            window.setTimeout(() => window.URL.revokeObjectURL(blobUrl), 60 * 1000);
        } catch (error) {
            previewWindow.close();
            messageApi.error(error?.message || '导出装箱单失败');
            console.error(error);
        }
    };

    const openAddBoxModal = () => {
        boxForm.setFieldsValue({
            item_details: [{ item_name: '', customs_code: '', piece_count: null }],
            weight: null,
            worker_ids: [],
            remark: ''
        });
        setAddBoxVisible(true);
    };

    const handleAddBox = async () => {
        if (!currentDetail) return;
        try {
            const values = await boxForm.validateFields();
            const itemDetails = (values.item_details || [])
                .map((row) => ({
                    item_name: String(row?.item_name || '').trim(),
                    customs_code: String(row?.customs_code || '').trim(),
                    piece_count: Number(row?.piece_count || 0)
                }))
                .filter((row) => row.item_name && row.piece_count > 0);

            if (itemDetails.length === 0) {
                messageApi.warning('请至少填写一条有效品名明细');
                return;
            }

            const mergedName = itemDetails.map((row) => row.item_name).join('、');
            const totalPiece = itemDetails.reduce((sum, row) => sum + row.piece_count, 0);

            setAddingBox(true);

            const res = await fetch(`${endpoint}/packing-list/${currentDetail.uid}/box`, {
                method: 'POST',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    item_name: mergedName,
                    piece_count: totalPiece,
                    item_details: itemDetails,
                    weight: values.weight || null,
                    remark: values.remark || ''
                })
            });
            const data = await res.json();

            if (data.code === 200) {
                if (values.worker_ids && values.worker_ids.length > 0) {
                    await fetch(`${endpoint}/box/${data.data.uid}/workers`, {
                        method: 'PUT',
                        headers: {
                            ...getSafeHeader(),
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ worker_ids: values.worker_ids })
                    });
                }
                messageApi.success('箱子添加成功');
                boxForm.resetFields();
                setAddBoxVisible(false);
                await handleViewDetail(currentDetail.uid);
            } else {
                messageApi.error(data.msg || '添加失败');
            }
        } catch (error) {
            if (error.errorFields) return;
            messageApi.error('添加请求失败');
            console.error(error);
        } finally {
            setAddingBox(false);
        }
    };

    const handleCompleteCurrent = async () => {
        if (!currentDetail) return;

        const boxes = currentDetail.boxes || [];
        if (boxes.length === 0) {
            messageApi.warning('请至少添加一个箱子');
            return;
        }

        const unweighedBoxes = boxes.filter(b => !b.weight || b.weight <= 0);
        if (unweighedBoxes.length > 0) {
            messageApi.warning(`还有 ${unweighedBoxes.length} 个箱子未称重`);
            return;
        }

        setCompleting(true);
        try {
            const res = await fetch(`${endpoint}/packing-list/${currentDetail.uid}/complete`, {
                method: 'POST',
                headers: getSafeHeader()
            });
            const data = await res.json();

            if (data.code === 200) {
                messageApi.success('装箱单已提交');
                await handleViewDetail(currentDetail.uid);
            } else {
                messageApi.error(data.msg || '提交失败');
            }
        } catch (error) {
            messageApi.error('提交失败');
            console.error(error);
        } finally {
            setCompleting(false);
        }
    };

    const handleArchiveCurrent = () => {
        if (!currentDetail) return;
        if (!canArchivePackingListByPolicy) {
            messageApi.warning('当前没有归档该装箱单的权限');
            return;
        }

        Modal.confirm({
            title: '确认归档该装箱单吗？',
            content: `唛头：${getMarkText(currentDetail)}。归档后装箱单将不再显示在列表中。`,
            okText: '确认归档',
            okType: 'danger',
            cancelText: '取消',
            onOk: async () => {
                setDeleting(true);
                try {
                    const res = await fetch(`${endpoint}/packing-list/${currentDetail.uid}/archive`, {
                        method: 'POST',
                        headers: getSafeHeader()
                    });
                    const data = await res.json();

                    if (data.code === 200) {
                        messageApi.success('装箱单已归档');
                        navigate('/packing-lists');
                    } else {
                        messageApi.error(data.msg || '归档失败');
                    }
                } catch (error) {
                    messageApi.error('归档失败');
                    console.error(error);
                } finally {
                    setDeleting(false);
                }
            }
        });
    };

    const handleDeleteCurrent = () => {
        if (!currentDetail) return;
        if (!canArchivePackingListByPolicy) {
            messageApi.warning('当前没有删除该装箱单的权限');
            return;
        }

        Modal.confirm({
            title: '确认彻底删除该装箱单吗？',
            content: `唛头：${getMarkText(currentDetail)}。此操作不可恢复，数据将从数据库中永久删除。`,
            okText: '删除',
            okType: 'danger',
            cancelText: '取消',
            onOk: async () => {
                setDeleting(true);
                try {
                    const res = await fetch(`${endpoint}/packing-list/${currentDetail.uid}`, {
                        method: 'DELETE',
                        headers: getSafeHeader()
                    });
                    const data = await res.json();

                    if (data.code === 200) {
                        messageApi.success('装箱单已删除');
                        navigate('/packing-lists');
                    } else {
                        messageApi.error(data.msg || '删除失败');
                    }
                } catch (error) {
                    messageApi.error('删除失败');
                    console.error(error);
                } finally {
                    setDeleting(false);
                }
            }
        });
    };

    const openCustomerEditModal = () => {
        if (!currentDetail) return;
        if (!canEditPackingListByPolicy) {
            messageApi.warning('当前没有修改该装箱单的权限');
            return;
        }
        setEditingMark(getMarkText(currentDetail));
        setEditingCustomerId(currentDetail.customer_id ?? null);
        setEditingPackingStatus(currentDetail.status || 'draft');
        setEditingPhotos(Array.isArray(currentDetail.photos) ? currentDetail.photos : []);
        setCustomerEditVisible(true);
    };

    const handleUpdateCustomer = async () => {
        if (!currentDetail) return;

        const currentMark = normalizeMark(getMarkText(currentDetail));
        const nextMark = normalizeMark(editingMark);
        const currentCustomerId = normalizeCustomerId(currentDetail.customer_id);
        const nextCustomerId = normalizeCustomerId(editingCustomerId);
        const currentStatus = currentDetail.status || 'draft';
        const nextStatus = editingPackingStatus || 'draft';
        const currentPhotos = Array.isArray(currentDetail.photos) ? currentDetail.photos : [];
        const nextPhotos = (editingPhotos || [])
            .map((item) => String(item || '').trim())
            .filter(Boolean);
        if (
            currentCustomerId === nextCustomerId &&
            currentMark === nextMark &&
            currentStatus === nextStatus &&
            isSameStringArray(currentPhotos, nextPhotos)
        ) {
            messageApi.info('装箱单信息未变化，无需保存');
            setCustomerEditVisible(false);
            return;
        }

        if (!nextMark) {
            messageApi.warning('唛头不能为空');
            return;
        }

        setSavingCustomer(true);
        try {
            const res = await fetch(`${endpoint}/packing-list/${currentDetail.uid}`, {
                method: 'PUT',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    list_number: nextMark,
                    customer_id: editingCustomerId,
                    status: nextStatus,
                    photos: nextPhotos
                })
            });
            const data = await res.json();

            if (data.code === 200) {
                messageApi.success('装箱单信息已更新');
                setCustomerEditVisible(false);
                await handleViewDetail(currentDetail.uid);
            } else {
                messageApi.error(data.msg || '更新装箱单失败');
            }
        } catch (error) {
            messageApi.error('更新装箱单失败');
            console.error(error);
        } finally {
            setSavingCustomer(false);
        }
    };

    const openBoxEditModal = async (box) => {
        if (!box || originalGenerationPending.current) return;
        if (!canOpenBoxEditor(box)) {
            messageApi.warning('当前没有修改该箱子的权限');
            return;
        }
        const itemDetails = getBoxItemDetails(box);
        setEditingBox(box);
        boxEditForm.setFieldsValue({
            box_number: box.box_number,
            item_details: itemDetails.length > 0 ? itemDetails : [{ item_name: '', customs_code: '', piece_count: 1 }],
            weight: box.weight ?? undefined,
            remark: box.remark || '',
            transfer_id: box.transfer_id || '',
            waybill_id: box.waybill_id || '',
            worker_ids: (Array.isArray(box.workers) ? box.workers : [])
                .map(worker => worker.worker_id ?? worker.id)
                .filter(id => id !== undefined && id !== null)
        });
        setBoxEditVisible(true);

        try {
            const res = await fetch(`${endpoint}/box/${box.uid}/workers`, {
                headers: getSafeHeader()
            });
            const data = await res.json();
            if (data.code === 200) {
                boxEditForm.setFieldValue(
                    'worker_ids',
                    (data.data || []).map((worker) => worker.worker_id)
                );
            }
        } catch (error) {
            console.error('获取箱子操作员失败:', error);
        }
    };

    const handleUpdateBox = async () => {
        if (!editingBox?.uid || !currentDetail?.uid) return;

        try {
            const values = await boxEditForm.validateFields();
            const policy = resolveBoxPolicy(editingBox);
            const details = (values.item_details || [])
                .map((row) => ({
                    item_name: String(row?.item_name || '').trim(),
                    customs_code: String(row?.customs_code || '').trim(),
                    piece_count: Number(row?.piece_count || 0)
                }))
                .filter((row) => row.item_name && row.piece_count > 0);

            if (policy.box_content && details.length === 0) {
                messageApi.warning('请至少填写一条有效品名明细');
                return;
            }

            const mergedName = details.map((row) => row.item_name).join('、');
            const totalPiece = details.reduce((sum, row) => sum + row.piece_count, 0);

            const payload = {};
            if (policy.box_content) {
                Object.assign(payload, {
                    item_name: mergedName,
                    piece_count: totalPiece,
                    item_details: details,
                    remark: values.remark ?? '',
                });
            }
            if (policy.box_content && isBoxIdentityEditable(editingBox)) {
                payload.box_number = values.box_number;
            }
            if (policy.box_weight) payload.weight = values.weight ?? null;
            if (policy.tracking_numbers) {
                if (isBoxOriginalNumberEditable(editingBox)) payload.transfer_id = values.transfer_id ?? '';
                payload.waybill_id = values.waybill_id ?? '';
            }
            if (policy.box_workers) payload.worker_ids = values.worker_ids || [];
            if (Object.keys(payload).length === 0) {
                messageApi.warning('该箱子当前没有可修改字段');
                return;
            }

            setSavingBox(true);
            const updateRes = await fetch(`${endpoint}/box/${editingBox.uid}`, {
                method: 'PUT',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });
            const updateData = await updateRes.json();
            if (updateData.code !== 200) {
                messageApi.error(updateData.msg || '更新箱子失败');
                return;
            }

            messageApi.success('箱子信息已更新');
            setBoxEditVisible(false);
            setEditingBox(null);
            await handleViewDetail(currentDetail.uid);
        } catch (error) {
            if (error?.errorFields) return;
            messageApi.error('更新箱子失败');
            console.error(error);
        } finally {
            setSavingBox(false);
        }
    };

    const handleArchiveBox = (box) => {
        if (!box?.uid || !currentDetail?.uid) return;
        if (!resolveBoxPolicy(box).archive_or_delete) {
            messageApi.warning('该箱子当前不能归档');
            return;
        }

        Modal.confirm({
            title: '确认归档该箱子吗？',
            content: `箱号：${box.box_number || '-'}。归档后箱子将不再显示。`,
            okText: '确认归档',
            okType: 'danger',
            cancelText: '取消',
            onOk: async () => {
                setDeletingBoxUid(box.uid);
                try {
                    const res = await fetch(`${endpoint}/box/${box.uid}/archive`, {
                        method: 'POST',
                        headers: getSafeHeader()
                    });
                    const data = await res.json();
                    if (data.code === 200) {
                        messageApi.success('箱子已归档');
                        await handleViewDetail(currentDetail.uid);
                    } else {
                        messageApi.error(data.msg || '归档箱子失败');
                    }
                } catch (error) {
                    messageApi.error('归档箱子失败');
                    console.error(error);
                } finally {
                    setDeletingBoxUid(null);
                }
            }
        });
    };

    const handleDeleteBox = (box) => {
        if (!box?.uid || !currentDetail?.uid) return;
        if (!resolveBoxPolicy(box).archive_or_delete) {
            messageApi.warning('该箱子当前不能删除');
            return;
        }

        Modal.confirm({
            title: '确认彻底删除该箱子吗？',
            content: `箱号：${box.box_number || '-'}。此操作不可恢复，数据将从数据库中永久删除。`,
            okText: '删除',
            okType: 'danger',
            cancelText: '取消',
            onOk: async () => {
                setDeletingBoxUid(box.uid);
                try {
                    const res = await fetch(`${endpoint}/box/${box.uid}`, {
                        method: 'DELETE',
                        headers: getSafeHeader()
                    });
                    const data = await res.json();
                    if (data.code === 200) {
                        messageApi.success('箱子已删除');
                        await handleViewDetail(currentDetail.uid);
                    } else {
                        messageApi.error(data.msg || '删除箱子失败');
                    }
                } catch (error) {
                    messageApi.error('删除箱子失败');
                    console.error(error);
                } finally {
                    setDeletingBoxUid(null);
                }
            }
        });
    };

    const handleArchiveSelectedBoxes = () => {
        if (!currentDetail?.uid) return;

        const boxUids = selectedShipBoxUids.filter((uid) => allBatchCandidateUids.includes(uid));
        if (boxUids.length === 0) {
            messageApi.warning('请先选择要归档的箱子');
            return;
        }

        Modal.confirm({
            title: '确认归档所选箱子吗？',
            content: `共选择 ${boxUids.length} 个箱子，归档后箱子将不再显示。`,
            okText: '确认归档',
            okType: 'danger',
            cancelText: '取消',
            onOk: async () => {
                setBatchDeleting(true);
                try {
                    const res = await fetch(`${endpoint}/cargo/archive`, {
                        method: 'POST',
                        headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
                        body: JSON.stringify({ cargo_id_list: boxUids })
                    });
                    const data = await res.json();
                    if (!res.ok || data.code !== 200) {
                        messageApi.error(data.msg || '批量归档箱子失败');
                        return;
                    }
                    messageApi.success(`已归档 ${boxUids.length} 箱`);

                    setSelectedShipBoxUids([]);
                    await handleViewDetail(currentDetail.uid);
                } finally {
                    setBatchDeleting(false);
                }
            }
        });
    };

    const handleGenerateSelectedOriginalNumbers = () => {
        if (!currentDetail?.uid || originalGenerationPending.current) return;
        const selectedBoxes = (currentDetail.boxes || []).filter(box => selectedShipBoxUids.includes(box.uid));
        if (!selectedBoxes.length) {
            messageApi.warning('请先选择要生成原单号的箱子');
            return;
        }
        if (selectedBoxes.some(box => !resolveBoxPolicy(box).tracking_numbers || !isBoxOriginalNumberEditable(box))) {
            messageApi.warning('所选箱子包含当前不能修改原单号的箱子');
            return;
        }
        const packingUid = currentDetail.uid;
        const requestBody = {
            box_uids: selectedBoxes.map(box => box.uid),
            expected_values: Object.fromEntries(selectedBoxes.map(box => [box.uid, box.transfer_id ?? null])),
        };
        const generate = async () => {
            if (originalGenerationPending.current || activePackingUid.current !== packingUid) return;
            originalGenerationPending.current = true;
            setGeneratingOriginalNumbers(true);
            try {
                const res = await fetch(`${endpoint}/packing-lists/${packingUid}/boxes/generate-original-numbers`, {
                    method: 'POST',
                    headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
                    body: JSON.stringify(requestBody),
                });
                const data = await res.json();
                if (activePackingUid.current !== packingUid) return;
                if (!res.ok || data.code !== 200) {
                    messageApi.error(data.msg || '生成原单号失败');
                    return;
                }
                const numbers = new Map((data.data?.boxes || []).map(box => [box.uid, box.transfer_id]));
                setCurrentDetail(previous => previous?.uid === packingUid ? {
                    ...previous,
                    boxes: (previous.boxes || []).map(box => numbers.has(box.uid)
                        ? { ...box, transfer_id: numbers.get(box.uid) } : box),
                } : previous);
                messageApi.success(`已为 ${numbers.size} 箱生成原单号`);
            } catch (error) {
                if (activePackingUid.current === packingUid) messageApi.error('生成原单号失败');
                console.error(error);
            } finally {
                originalGenerationPending.current = false;
                setGeneratingOriginalNumbers(false);
            }
        };
        const existingCount = selectedBoxes.filter(box => String(box.transfer_id || '').trim()).length;
        if (existingCount) {
            Modal.confirm({
                title: '确认生成原单号？',
                content: `将为所选 ${selectedBoxes.length} 箱随机生成并保存原单号，其中 ${existingCount} 箱已有的原单号将被替换。`,
                okText: '生成并替换', cancelText: '取消', onOk: generate,
            });
        } else {
            generate();
        }
    };

    const handleDeleteSelectedBoxes = () => {
        if (!currentDetail?.uid) return;

        const boxUids = selectedShipBoxUids.filter((uid) => allBatchCandidateUids.includes(uid));
        if (boxUids.length === 0) {
            messageApi.warning('请先选择要删除的箱子');
            return;
        }

        Modal.confirm({
            title: '确认彻底删除所选箱子吗？',
            content: `共选择 ${boxUids.length} 个箱子，此操作不可恢复，数据将从数据库中永久删除。`,
            okText: '删除',
            okType: 'danger',
            cancelText: '取消',
            onOk: async () => {
                setBatchDeleting(true);
                try {
                    const res = await fetch(`${endpoint}/cargo`, {
                        method: 'DELETE',
                        headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
                        body: JSON.stringify({ cargo_id_list: boxUids })
                    });
                    const data = await res.json();
                    if (!res.ok || data.code !== 200) {
                        messageApi.error(data.msg || '批量删除箱子失败');
                        return;
                    }
                    messageApi.success(`已删除 ${boxUids.length} 箱`);

                    setSelectedShipBoxUids([]);
                    await handleViewDetail(currentDetail.uid);
                } finally {
                    setBatchDeleting(false);
                }
            }
        });
    };

    const handleUndoShipBox = async (box) => {
        if (!canUndoShip || !box?.uid || !currentDetail?.uid
            || normalizeBoxStatus(box) !== BOX_STATUS.OUTBOUND) return;

        setUndoShippingBoxUid(box.uid);
        try {
            const res = await fetch(`${endpoint}/box/${box.uid}/undo-ship`, {
                method: 'POST',
                headers: getSafeHeader()
            });
            const data = await res.json();

            if (res.ok && data.code === 200) {
                messageApi.success('已撤销出库，箱子重新入库');
                if (editingBox?.uid === box.uid) {
                    setBoxEditVisible(false);
                    setEditingBox(null);
                }
                await handleViewDetail(currentDetail.uid);
            } else {
                messageApi.error(data.msg || '撤销出库失败');
            }
        } catch (error) {
            messageApi.error('撤销出库失败');
            console.error(error);
        } finally {
            setUndoShippingBoxUid(null);
        }
    };

    const allSelectableBoxUids = (currentDetail?.boxes || []).map((box) => box.uid);
    const allBatchCandidateUids = canEditBoxes
        ? (currentDetail?.boxes || [])
            .filter((box) => resolveBoxPolicy(box).archive_or_delete)
            .map((box) => box.uid)
        : [];
    const selectedSelectableCount = selectedShipBoxUids.filter((uid) => allSelectableBoxUids.includes(uid)).length;
    const selectedPrintableBoxUids = selectedShipBoxUids.filter((uid) => allSelectableBoxUids.includes(uid));
    const selectedOriginalNumberBoxes = (currentDetail?.boxes || []).filter(box => selectedShipBoxUids.includes(box.uid));
    const canGenerateSelectedOriginalNumbers = selectedOriginalNumberBoxes.length > 0
        && selectedOriginalNumberBoxes.every(box => resolveBoxPolicy(box).tracking_numbers && isBoxOriginalNumberEditable(box));
    const selectedBatchCount = selectedShipBoxUids.filter((uid) => allBatchCandidateUids.includes(uid)).length;
    const isShipAllChecked = allSelectableBoxUids.length > 0 && selectedSelectableCount === allSelectableBoxUids.length;
    const isShipIndeterminate = selectedSelectableCount > 0 && selectedSelectableCount < allSelectableBoxUids.length;
    const canBatchActions = canEditBoxes;
    const batchActionMenuItems = [];
    if (canEditBoxes) {
        batchActionMenuItems.push({ key: 'archive', label: '归档已选', danger: true });
        batchActionMenuItems.push({ key: 'delete', label: '删除已选', danger: true });
    }

    const resolvedBatchAction =
        batchActionMenuItems.find((item) => item.key === selectedBatchAction)?.key
        || batchActionMenuItems[0]?.key
        || null;

    const currentBatchActionMeta = batchActionMenuItems.find((item) => item.key === resolvedBatchAction);
    const currentBatchActionLoading =
        ['archive', 'delete'].includes(resolvedBatchAction) ? batchDeleting : false;

    const handleBatchActionExecute = () => {
        if (resolvedBatchAction === 'archive') {
            handleArchiveSelectedBoxes();
            return;
        }
        if (resolvedBatchAction === 'delete') {
            handleDeleteSelectedBoxes();
        }
    };

    const toggleShipBox = (boxUid, checked) => {
        setSelectedShipBoxUids((prev) => {
            if (checked) {
                return Array.from(new Set([...prev, boxUid]));
            }
            return prev.filter((id) => id !== boxUid);
        });
    };

    const toggleSelectAllShipBoxes = (checked) => {
        if (!checked) {
            setSelectedShipBoxUids((prev) => prev.filter((id) => !allSelectableBoxUids.includes(id)));
            return;
        }
        setSelectedShipBoxUids((prev) => Array.from(new Set([...prev, ...allSelectableBoxUids])));
    };

    if (loading) {
        return (
            <div style={{ padding: '24px', textAlign: 'center' }}>
                <Spin size="large" />
            </div>
        );
    }

    if (!currentDetail) {
        return (
            <div style={{ padding: '24px' }}>
                <Card>
                    <Text type="danger">未能获取到装箱单详情</Text>
                    <Button type="link" onClick={() => navigate('/packing-lists')}>返回列表</Button>
                </Card>
            </div>
        );
    }

    return (
        <div style={{ padding: screens.md ? '24px' : '12px' }}>
            {contextHolder}
            <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
                <Space align="center" style={{ flexShrink: 0 }}>
                    <Button
                        type="text"
                        icon={<ArrowLeftOutlined style={{ fontSize: screens.md ? '24px' : '20px' }} />}
                        onClick={() => navigate(-1)}
                        style={{ width: screens.md ? 40 : 32, height: screens.md ? 40 : 32, marginRight: 4 }}
                    />
                    <Title level={screens.md ? 2 : 4} style={{ margin: 0 }}>装箱单详情</Title>
                </Space>
                <Space wrap style={{ flex: '1 1 auto', justifyContent: 'flex-start' }}>
                    {currentDetail.status === 'draft' && (
                        <Button
                            type="primary"
                            icon={<CheckOutlined />}
                            onClick={handleCompleteCurrent}
                            loading={completing}
                        >
                            提交装箱单
                        </Button>
                    )}
                    {canEditPackingListDetail && canEditPackingListByPolicy && (
                        <Button
                            type="default"
                            icon={<EditOutlined />}
                            onClick={openCustomerEditModal}
                        >
                            编辑装箱单
                        </Button>
                    )}
                    {canEditBoxes && (
                        <Button
                            type="primary"
                            icon={<PlusOutlined />}
                            onClick={openAddBoxModal}
                        >
                            添加箱子
                        </Button>
                    )}
                    {canDeletePackingList && canArchivePackingListByPolicy && (
                        <Button
                            danger
                            onClick={handleArchiveCurrent}
                            loading={deleting}
                        >
                            归档装箱单
                        </Button>
                    )}
                    {canDeletePackingList && canArchivePackingListByPolicy && (
                        <Button
                            danger
                            icon={<DeleteOutlined />}
                            onClick={handleDeleteCurrent}
                            loading={deleting}
                        >
                            删除装箱单
                        </Button>
                    )}
                </Space>
            </div>

            <Card style={{ marginBottom: 16 }} bodyStyle={screens.md ? {} : { padding: 12 }}>
                <Descriptions bordered size={screens.md ? 'middle' : 'small'} column={{ xxl: 3, xl: 3, lg: 3, md: 2, sm: 1, xs: 1 }}>
                    <Descriptions.Item label="唛头">
                        <Text strong>{getMarkText(currentDetail)}</Text>
                    </Descriptions.Item>
                    <Descriptions.Item label="客户名">
                        <Space>
                            <Text>{currentDetail.customer_name || '-'}</Text>
                        </Space>
                    </Descriptions.Item>
                    <Descriptions.Item label="状态">
                        <Tag color={getPackingListStatusMeta(currentDetail).color}>
                            {getPackingListStatusMeta(currentDetail).text}
                        </Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="创建人">
                        {currentDetail.creator_name}
                    </Descriptions.Item>
                    <Descriptions.Item label="创建时间">
                        {currentDetail.create_date}
                    </Descriptions.Item>
                    <Descriptions.Item label="更新时间">
                        {currentDetail.update_date || '-'}
                    </Descriptions.Item>
                </Descriptions>
            </Card>

            {/* 照片 */}
            {currentDetail.photos && currentDetail.photos.length > 0 && (
                <Card title="照片" style={{ marginBottom: 16 }} bodyStyle={screens.md ? {} : { padding: 12 }}>
                    <Image.PreviewGroup>
                        <Space wrap>
                            {currentDetail.photos.map((url, idx) => (
                                <Image
                                    key={idx}
                                    src={url}
                                    width={120}
                                    height={120}
                                    style={{ objectFit: 'cover', borderRadius: '8px' }}
                                />
                            ))}
                        </Space>
                    </Image.PreviewGroup>
                </Card>
            )}

            {/* 箱子列表 */}
            <Card
                title={`箱子列表 (${currentDetail.boxes?.length || 0})`}
                headStyle={{ paddingBottom: 12 }}
                bodyStyle={screens.md ? {} : { padding: 0 }}
                extra={
                    ((currentDetail?.boxes || []).length > 0 || canBatchActions) ? (
                        <Space size={8} wrap style={{ marginBottom: 4 }}>
                            {canBatchActions && (
                                <Checkbox
                                    checked={isShipAllChecked}
                                    indeterminate={isShipIndeterminate}
                                    disabled={allSelectableBoxUids.length === 0}
                                    onChange={(e) => toggleSelectAllShipBoxes(e.target.checked)}
                                >
                                    全选
                                </Checkbox>
                            )}
                            {/* <Button
                            type="default"
                            icon={<PrinterOutlined />}
                            onClick={() => handlePrintPackingList(currentDetail?.uid)}
                            disabled={!currentDetail.boxes || currentDetail.boxes.length === 0}
                        >
                            打印全部
                        </Button> */}
                            {canBatchActions && (
                                <Button
                                    type="default"
                                    icon={<PrinterOutlined />}
                                    onClick={() => handlePrintPackingList(currentDetail?.uid, selectedPrintableBoxUids)}
                                    disabled={selectedSelectableCount === 0}
                                >
                                    打印已选({selectedSelectableCount})
                                </Button>
                            )}
                            {canBatchActions && (
                                <Button
                                    icon={<ReloadOutlined />}
                                    aria-label="生成原单号"
                                    onClick={handleGenerateSelectedOriginalNumbers}
                                    loading={generatingOriginalNumbers}
                                    disabled={!canGenerateSelectedOriginalNumbers || generatingOriginalNumbers || boxEditVisible}
                                    title="为所选箱子随机生成并保存原单号"
                                >
                                    生成原单号
                                </Button>
                            )}
                            {canBatchActions && (
                                <Dropdown.Button
                                    menu={{
                                        items: batchActionMenuItems,
                                        onClick: (e) => setSelectedBatchAction(e.key)
                                    }}
                                    type="primary"
                                    danger={!!currentBatchActionMeta?.danger}
                                    onClick={handleBatchActionExecute}
                                    loading={currentBatchActionLoading}
                                    disabled={selectedBatchCount === 0 || !resolvedBatchAction}
                                >
                                    {currentBatchActionMeta ? `${currentBatchActionMeta.label}(${selectedBatchCount})` : `批量操作(${selectedBatchCount})`}
                                </Dropdown.Button>
                            )}
                        </Space>
                    ) : null
                }
            >
                <List
                    bordered
                    dataSource={currentDetail.boxes || []}
                    renderItem={(box, idx) => {
                        const itemDetails = getBoxItemDetails(box);
                        const canEditBox = canEditBoxes && canOpenBoxEditor(box);
                        const canRestoreBox = canUndoShip && normalizeBoxStatus(box) === BOX_STATUS.OUTBOUND;
                        const canRemoveBox = canEditBoxes && resolveBoxPolicy(box).archive_or_delete;
                        const workerNames = Array.from(
                            new Set(
                                (Array.isArray(box?.workers) ? box.workers : [])
                                    .map((worker) => String(worker?.worker_name || '').trim())
                                    .filter(Boolean)
                            )
                        );
                        return (
                            <List.Item
                                actions={canEditBox || canRestoreBox || canRemoveBox ? [
                                    <div key="box-actions" className={styles.boxActions}>
                                        <div className={styles.boxActionRow} role="group" aria-label="编辑与出库操作">
                                            <div className={styles.boxActionSlot}>
                                                {canEditBox && (
                                                    <Button
                                                        type="link"
                                                        icon={<EditOutlined />}
                                                        disabled={generatingOriginalNumbers}
                                                        onClick={() => openBoxEditModal(box)}
                                                    >
                                                        编辑
                                                    </Button>
                                                )}
                                            </div>
                                            <div className={styles.boxActionSlot}>
                                                {canRestoreBox && (
                                                    <Popconfirm
                                                        title="撤销该箱子的出库？"
                                                        description="箱子将重新入库，并清除转单号和出库时间。"
                                                        okText="重新入库"
                                                        cancelText="取消"
                                                        onConfirm={() => handleUndoShipBox(box)}
                                                    >
                                                        <Button
                                                            type="link"
                                                            danger
                                                            loading={undoShippingBoxUid === box.uid}
                                                            disabled={undoShippingBoxUid !== null && undoShippingBoxUid !== box.uid}
                                                        >
                                                            撤销出库
                                                        </Button>
                                                    </Popconfirm>
                                                )}
                                            </div>
                                        </div>
                                        <div className={styles.boxActionRow} role="group" aria-label="归档与删除操作">
                                            <div className={styles.boxActionSlot}>
                                                {canRemoveBox && (
                                                    <Button
                                                        type="link"
                                                        danger
                                                        icon={<DeleteOutlined />}
                                                        loading={deletingBoxUid === box.uid}
                                                        onClick={() => handleArchiveBox(box)}
                                                    >
                                                        归档
                                                    </Button>
                                                )}
                                            </div>
                                            <div className={styles.boxActionSlot}>
                                                {canRemoveBox && (
                                                    <Button
                                                        type="link"
                                                        danger
                                                        loading={deletingBoxUid === box.uid}
                                                        onClick={() => handleDeleteBox(box)}
                                                    >
                                                        删除
                                                    </Button>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                ] : undefined}
                            >
                                {screens.md ? (
                                    <div style={{ display: 'flex', flexDirection: 'column', width: '100%', gap: '10px' }}>
                                        <div style={{ display: 'flex', width: '100%', alignItems: 'flex-start', flexWrap: 'nowrap', gap: '16px' }}>
                                            <div style={{ flex: '1 1 0', minWidth: 0 }}>
                                                <Text type="secondary" style={{ fontSize: '13px' }}>箱号</Text>
                                                <div style={{ marginTop: 4 }}>
                                                    <Space direction="vertical" size={6}>
                                                        {canBatchActions ? (
                                                            <Checkbox
                                                                aria-label={`箱子 ${box.box_number || (idx + 1)}`}
                                                                checked={selectedShipBoxUids.includes(box.uid)}
                                                                onChange={(e) => toggleShipBox(box.uid, e.target.checked)}
                                                            >
                                                                <Text strong>箱子 {box.box_number || (idx + 1)}</Text>
                                                            </Checkbox>
                                                        ) : (
                                                            <Text strong>箱子 {box.box_number || (idx + 1)}</Text>
                                                        )}
                                                        <div>
                                                            <Text type="secondary">订单号: </Text>
                                                            <Text>
                                                                {<Link to={box.target_order_uid ? `/orders/${box.target_order_uid}` : ``}>{String(box.target_order_id || '-').trim()}</Link>}
                                                            </Text>
                                                        </div>
                                                        {renderBoxStatusTag(box)}
                                                    </Space>
                                                </div>
                                            </div>

                                            <div style={{ flex: '1 1 0', minWidth: 0 }}>
                                                <Text type="secondary" style={{ fontSize: '13px' }}>品名明细</Text>
                                                <div style={{ marginTop: 4 }}>
                                                    {itemDetails.length > 0 ? (
                                                        itemDetails.map((row, itemIdx) => (
                                                            <div key={`${box.uid}-detail-${itemIdx}`}>
                                                                <Text>{row.item_name}</Text>
                                                                {row.customs_code && (
                                                                    <Text type="secondary" style={{ marginLeft: 8 }}>海关编码：{row.customs_code}</Text>
                                                                )}
                                                                <Text type="secondary" style={{ marginLeft: 8 }}>x{row.piece_count}</Text>
                                                            </div>
                                                        ))
                                                    ) : (
                                                        <Text type="secondary">-</Text>
                                                    )}
                                                </div>
                                            </div>

                                            <div style={{ flex: '1 1 0', minWidth: 0 }}>
                                                <Text type="secondary" style={{ fontSize: '13px' }}>统计</Text>
                                                <Space direction="vertical" size={2} style={{ marginTop: 4, display: 'flex' }}>
                                                    <Text>总件数: <Text strong>{box.piece_count || 0}</Text></Text>
                                                    <Text>总重量: <Text strong>{box.weight ? `${box.weight} kg` : '未称重'}</Text></Text>
                                                </Space>
                                            </div>

                                            <div style={{ flex: '1 1 0', minWidth: 0 }}>
                                                <Text type="secondary" style={{ fontSize: '13px' }}>备注</Text>
                                                <div style={{ marginTop: 4 }}>
                                                    <Text>{(box.remark || '').trim() || '-'}</Text>
                                                </div>
                                                <div style={{ marginTop: 6 }}>
                                                    <Text type="secondary">原单号: </Text>
                                                    <Text>{String(box.transfer_id || '').trim() || '-'}</Text>
                                                </div>
                                                <div>
                                                    <Text type="secondary">转单号（运单号）: </Text>
                                                    <Text>
                                                        {<Link to={box.target_order_uid ? `/orders/${box.target_order_uid}` : ``}>{String(box.waybill_id || '-').trim()}</Link>}
                                                    </Text>
                                                </div>
                                            </div>
                                        </div>

                                        <div style={{ width: '100%', borderTop: '1px solid #f0f0f0', paddingTop: 10 }}>
                                            <Text type="secondary" style={{ fontSize: '13px' }}>操作员</Text>
                                            <div style={{ marginTop: 4 }}>
                                                <Text>{workerNames.length > 0 ? workerNames.join('、') : '-'}</Text>
                                            </div>
                                        </div>
                                    </div>
                                ) : (
                                    <div style={{ display: 'flex', flexDirection: 'column', width: '100%', gap: '8px' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                                            <Space size={8}>
                                                {canBatchActions && (
                                                    <Checkbox
                                                        aria-label={`箱子 ${box.box_number || (idx + 1)}`}
                                                        checked={selectedShipBoxUids.includes(box.uid)}
                                                        onChange={(e) => toggleShipBox(box.uid, e.target.checked)}
                                                    />
                                                )}
                                                <Text strong style={{ fontSize: '15px' }}>箱号: {box.box_number || (idx + 1)}</Text>
                                                {renderBoxStatusTag(box)}
                                            </Space>
                                            <Space size={12}>
                                                <Text>重: <Text strong>{box.weight ? `${box.weight}kg` : '-'}</Text></Text>
                                                <Text>件: <Text strong>{box.piece_count || 0}</Text></Text>
                                            </Space>
                                        </div>

                                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                            <Text type="secondary" style={{ flexShrink: 0 }}>包含品名：</Text>
                                            <Text>{itemDetails.length > 0 ? Array.from(new Set(itemDetails.map(r => r.item_name))).join('、') : '-'}</Text>
                                        </div>

                                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                            <Text type="secondary" style={{ flexShrink: 0 }}>操作员：</Text>
                                            <Text>{workerNames.length > 0 ? workerNames.join('、') : '-'}</Text>
                                        </div>

                                        {box.remark?.trim() && (
                                            <div style={{ display: 'flex', gap: '8px' }}>
                                                <Text type="secondary" style={{ flexShrink: 0 }}>箱子备注：</Text>
                                                <Text>{box.remark.trim()}</Text>
                                            </div>
                                        )}

                                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                            <Text type="secondary" style={{ flexShrink: 0 }}>原单号：</Text>
                                            <Text>{String(box.transfer_id || '').trim() || '-'}</Text>
                                        </div>

                                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                            <Text type="secondary" style={{ flexShrink: 0 }}>转单号（运单号）：</Text>
                                            <Text>{String(box.waybill_id || '').trim() || '-'}</Text>
                                        </div>
                                    </div>
                                )}
                            </List.Item>
                        );
                    }}
                />
                <div style={{ marginTop: 16, padding: screens.md ? 0 : 16, textAlign: 'right' }}>
                    <Text>
                        总重量: <Text strong>
                            {(currentDetail.boxes || []).reduce((sum, b) => sum + (b.weight || 0), 0).toFixed(2)} kg
                        </Text>
                    </Text>
                </div>
            </Card>

            <Modal
                title="添加箱子"
                open={addBoxVisible}
                onCancel={() => setAddBoxVisible(false)}
                onOk={handleAddBox}
                okText="添加"
                cancelText="取消"
                confirmLoading={addingBox}
                width={screens.md ? 760 : '100%'}
            >
                <Form
                    form={boxForm}
                    layout="vertical"
                    initialValues={{ item_details: [{ item_name: '', customs_code: '', piece_count: null }] }}
                >
                    <Form.Item label="品名与件数" style={{ marginBottom: 12 }}>
                        <Form.List name="item_details">
                            {(fields, { add, remove }) => (
                                <div>
                                    {fields.map((field) => (
                                        <Space key={field.key} align="start" style={{ display: 'flex', width: '100%', marginBottom: 8, flexWrap: 'nowrap' }}>
                                            <Button
                                                type="text"
                                                icon={<CloseOutlined />}
                                                danger
                                                onClick={() => remove(field.name)}
                                                disabled={fields.length <= 1}
                                                style={{ marginTop: 4, padding: '4px 8px' }}
                                            />
                                            <Form.Item
                                                {...field}
                                                name={[field.name, 'item_name']}
                                                rules={[{ required: true, message: '请输入品名' }]}
                                                style={{ flex: 1, marginBottom: 0, minWidth: 60 }}
                                            >
                                                <Input
                                                    placeholder="品名"
                                                    onChange={event => handleItemNameChange(boxForm, field.name, event.target.value)}
                                                />
                                            </Form.Item>

                                            <Form.Item
                                                {...field}
                                                name={[field.name, 'customs_code']}
                                                style={{ width: screens.md ? 210 : 120, marginBottom: 0, minWidth: 90 }}
                                            >
                                                <AutoComplete
                                                    options={getCustomsCodeOptions(addBoxItemDetails[field.name]?.item_name)}
                                                    placeholder="海关编码"
                                                    allowClear
                                                />
                                            </Form.Item>

                                            <Form.Item
                                                {...field}
                                                name={[field.name, 'piece_count']}
                                                rules={[{ required: true, message: '请输入件数' }]}
                                                style={{ width: screens.md ? 140 : 90, marginBottom: 0, minWidth: 60 }}
                                            >
                                                <InputNumber min={1} precision={0} step={1} placeholder="件数" style={{ width: '100%' }} />
                                            </Form.Item>
                                        </Space>
                                    ))}

                                    <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({ item_name: '', customs_code: '', piece_count: null })}>
                                        新增品名件数
                                    </Button>
                                </div>
                            )}
                        </Form.List>
                    </Form.Item>

                    <Form.Item
                        name="weight"
                        label="重量 (kg)"
                        rules={[{ required: true, message: '请输入重量' }]}
                    >
                        <InputNumber min={0.01} step={0.1} style={{ width: '100%' }} placeholder="请输入重量" />
                    </Form.Item>

                    <Form.Item
                        name="worker_ids"
                        label="操作员 (最多4人)"
                        rules={[{ required: true, message: '请选择操作员' }]}
                    >
                        <Select mode="multiple" placeholder="选择操作员" maxTagCount={3}>
                            {workers.map((worker) => (
                                <Option key={worker.id} value={worker.id}>{worker.name}</Option>
                            ))}
                        </Select>
                    </Form.Item>

                    <Form.Item name="remark" label="备注" style={{ marginBottom: 0 }}>
                        <Input.TextArea rows={2} placeholder="可填写额外说明" />
                    </Form.Item>
                </Form>
            </Modal>

            <Modal
                title="编辑装箱单"
                open={customerEditVisible}
                onCancel={() => setCustomerEditVisible(false)}
                onOk={handleUpdateCustomer}
                okText="保存"
                cancelText="取消"
                confirmLoading={savingCustomer}
                okButtonProps={{
                    disabled:
                        normalizeMark(editingMark) === normalizeMark(getMarkText(currentDetail)) &&
                        normalizeCustomerId(editingCustomerId) === normalizeCustomerId(currentDetail?.customer_id) &&
                        (editingPackingStatus || 'draft') === (currentDetail?.status || 'draft') &&
                        isSameStringArray(
                            Array.isArray(currentDetail?.photos) ? currentDetail.photos : [],
                            (editingPhotos || []).map((item) => String(item || '').trim()).filter(Boolean)
                        )
                }}
            >
                <div style={{ marginBottom: 8 }}>
                    <Text type="secondary">唛头：{getMarkText(currentDetail)}</Text>
                </div>
                <Input
                    placeholder="请输入唛头"
                    value={editingMark}
                    onChange={(e) => setEditingMark(e.target.value)}
                    style={{ marginBottom: 12 }}
                />
                <Select
                    showSearch
                    allowClear
                    placeholder="请选择客户"
                    style={{ width: '100%' }}
                    optionFilterProp="children"
                    value={editingCustomerId}
                    onChange={(value) => setEditingCustomerId(value ?? null)}
                >
                    {customers.map((customer) => (
                        <Option key={customer.id} value={customer.id}>{customer.name}</Option>
                    ))}
                </Select>
                <Select
                    value={editingPackingStatus}
                    onChange={setEditingPackingStatus}
                    style={{ width: '100%', marginTop: 12 }}
                >
                    <Option value="draft">草稿</Option>
                    <Option value="completed">已完成</Option>
                </Select>

                <div style={{ marginTop: 12 }}>
                    <Text type="secondary">照片链接</Text>
                    {(editingPhotos || []).map((photo, idx) => (
                        <Space key={`photo-${idx}`} style={{ display: 'flex', marginTop: 8 }}>
                            <Input
                                value={photo}
                                placeholder="请输入照片URL"
                                onChange={(e) => {
                                    const next = [...(editingPhotos || [])];
                                    next[idx] = e.target.value;
                                    setEditingPhotos(next);
                                }}
                            />
                            <Button
                                danger
                                icon={<DeleteOutlined />}
                                onClick={() => {
                                    const next = [...(editingPhotos || [])];
                                    next.splice(idx, 1);
                                    setEditingPhotos(next);
                                }}
                            />
                        </Space>
                    ))}
                    <Button
                        type="dashed"
                        icon={<PlusOutlined />}
                        onClick={() => setEditingPhotos([...(editingPhotos || []), ''])}
                        style={{ marginTop: 8 }}
                    >
                        添加照片链接
                    </Button>
                </div>

                {normalizeMark(editingMark) === normalizeMark(getMarkText(currentDetail)) &&
                    normalizeCustomerId(editingCustomerId) === normalizeCustomerId(currentDetail?.customer_id) &&
                    (editingPackingStatus || 'draft') === (currentDetail?.status || 'draft') &&
                    isSameStringArray(
                        Array.isArray(currentDetail?.photos) ? currentDetail.photos : [],
                        (editingPhotos || []).map((item) => String(item || '').trim()).filter(Boolean)
                    ) && (
                        <div style={{ marginTop: 8 }}>
                            <Text type="secondary">当前未修改装箱单信息，保存按钮将不可用。</Text>
                        </div>
                    )}
            </Modal>

            <Modal
                title={editingBox ? `编辑箱子 ${editingBox.box_number || '-'}` : '编辑箱子'}
                open={boxEditVisible}
                onCancel={() => {
                    setBoxEditVisible(false);
                    setEditingBox(null);
                }}
                onOk={handleUpdateBox}
                okText="保存"
                cancelText="取消"
                confirmLoading={savingBox}
                okButtonProps={{ disabled: !editingBox || !canOpenBoxEditor(editingBox) }}
                width={screens.md ? 760 : '100%'}
            >
                {editingBox && (
                    <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                        <Space>
                            <Text type="secondary">当前状态</Text>
                            {renderBoxStatusTag(editingBox)}
                        </Space>
                    </div>
                )}
                <Form form={boxEditForm} layout="vertical">
                    <Form.Item
                        name="box_number"
                        label="箱号"
                        rules={[{ required: true, message: '请输入箱号' }]}
                    >
                        <InputNumber
                            min={1}
                            precision={0}
                            step={1}
                            disabled={!resolveBoxPolicy(editingBox).box_content || !isBoxIdentityEditable(editingBox)}
                            style={{ width: 200 }}
                        />
                    </Form.Item>

                    <Form.List name="item_details">
                        {(fields, { add, remove }) => (
                            <>
                                <Text type="secondary">品名明细</Text>
                                {fields.map((field) => (
                                    <Space key={field.key} align="start" style={{ display: 'flex', marginTop: 8, width: '100%', flexWrap: 'nowrap' }}>
                                        <Button
                                            type="text"
                                            danger
                                            icon={<CloseOutlined />}
                                            onClick={() => remove(field.name)}
                                            disabled={fields.length <= 1 || !resolveBoxPolicy(editingBox).box_content}
                                            style={{ marginTop: 4, padding: '4px 8px' }}
                                        />
                                        <Form.Item
                                            {...field}
                                            name={[field.name, 'item_name']}
                                            rules={[{ required: true, message: '请输入品名' }]}
                                            style={{ flex: 1, minWidth: 60, marginBottom: 8 }}
                                        >
                                            <Input
                                                placeholder="品名"
                                                disabled={!resolveBoxPolicy(editingBox).box_content}
                                                onChange={event => handleItemNameChange(boxEditForm, field.name, event.target.value)}
                                            />
                                        </Form.Item>
                                        <Form.Item
                                            {...field}
                                            name={[field.name, 'customs_code']}
                                            style={{ width: screens.md ? 210 : 120, minWidth: 90, marginBottom: 8 }}
                                        >
                                            <AutoComplete
                                                options={getCustomsCodeOptions(editBoxItemDetails[field.name]?.item_name)}
                                                placeholder="海关编码"
                                                allowClear
                                                disabled={!resolveBoxPolicy(editingBox).box_content}
                                            />
                                        </Form.Item>
                                        <Form.Item
                                            {...field}
                                            name={[field.name, 'piece_count']}
                                            rules={[{ required: true, message: '请输入件数' }]}
                                            style={{ width: screens.md ? 140 : 90, minWidth: 60, marginBottom: 8 }}
                                        >
                                            <InputNumber
                                                min={1}
                                                precision={0}
                                                step={1}
                                                disabled={!resolveBoxPolicy(editingBox).box_content}
                                                style={{ width: '100%' }}
                                                placeholder="件数"
                                            />
                                        </Form.Item>
                                    </Space>
                                ))}
                                <Button
                                    type="dashed"
                                    disabled={!resolveBoxPolicy(editingBox).box_content}
                                    onClick={() => add({ item_name: '', customs_code: '', piece_count: 1 })}
                                    icon={<PlusOutlined />}
                                >
                                    添加品名明细
                                </Button>
                            </>
                        )}
                    </Form.List>

                    <Space wrap style={{ marginTop: 12, width: '100%' }}>
                        <Form.Item name="weight" label="总重量(kg)" style={{ marginBottom: 0 }}>
                            <InputNumber
                                min={0.01}
                                step={0.1}
                                disabled={!resolveBoxPolicy(editingBox).box_weight}
                                style={{ width: 180 }}
                                placeholder={normalizeBoxStatus(editingBox) === BOX_STATUS.OUTBOUND ? '箱子已出库，重量不可修改' : '未称重可留空'}
                            />
                        </Form.Item>
                        <Form.Item name="transfer_id" label="原单号" style={{ marginBottom: 0 }}>
                            <Input
                                placeholder={isBoxOriginalNumberEditable(editingBox) ? '可选' : '箱子已出库，原单号不可修改'}
                                disabled={!resolveBoxPolicy(editingBox).tracking_numbers || !isBoxOriginalNumberEditable(editingBox)}
                                style={{ width: 220 }}
                            />
                        </Form.Item>
                        <Form.Item name="waybill_id" label="转单号（运单号）" style={{ marginBottom: 0 }}>
                            <Input
                                placeholder="可选"
                                disabled={!resolveBoxPolicy(editingBox).tracking_numbers}
                                style={{ width: 220 }}
                            />
                        </Form.Item>
                    </Space>

                    <Form.Item name="remark" label="备注" style={{ marginTop: 12 }}>
                        <Input.TextArea rows={3} placeholder="可选" disabled={!resolveBoxPolicy(editingBox).box_content} />
                    </Form.Item>

                    <Form.Item name="worker_ids" label="操作员">
                        <Select
                            mode="multiple"
                            placeholder="请选择操作员"
                            maxTagCount={3}
                            disabled={!resolveBoxPolicy(editingBox).box_workers}
                        >
                            {workers.map((worker) => (
                                <Option key={worker.id} value={worker.id}>{worker.name}</Option>
                            ))}
                        </Select>
                    </Form.Item>
                </Form>
            </Modal>
        </div>
    );
}
