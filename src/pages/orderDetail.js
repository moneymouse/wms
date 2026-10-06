import React, { useCallback, useEffect, useRef, useState } from "react";
import {
    Badge,
    Button,
    Descriptions,
    Form,
    InputNumber,
    message,
    Modal,
    Popconfirm,
    Popover,
    Space,
    Select,
    Table,
    Tag,
    Timeline,
    Tooltip,
    Typography
} from "antd";
import orderProperty from "../common/orderProperty";
// import crypto from 'crypto';
import Input from "antd/es/input/Input";
import { endpoint } from "../config.js";
import { useNavigate, useParams } from "react-router-dom";
import getSafeHeader from '../common/safeHeader';
import styles from './orderDetail.module.css';
import ExportButton from "../components/ExportButton";
import trackStatus from "../common/trackStatus";
import GoodInput from "../components/GoodName";
import BoxAssignmentModal from "../components/BoxAssignmentModal";
import Transportation from "../components/transportation";
import { DeleteOutlined, DollarOutlined, HistoryOutlined, InboxOutlined, PrinterOutlined, ReloadOutlined } from "@ant-design/icons";
import { getUserRoles, hasPermission } from "../common/roleConfig";
import { normalizeOrderEditPolicy } from "../common/orderEditPolicy";
import { isBoxOriginalNumberEditable, isCargoOutboundOrLater } from "../common/cargoStatus";
import OrderHistoryDrawer from "../components/OrderHistoryDrawer";
import OrderReceiptButton from "../components/OrderReceiptButton";
import { buildCustomsCodeOptions } from "../common/customsCodeLookup";
import FeatureTour from "../components/FeatureTour";
import { COST_QUOTE_RECEIPT_TOUR, getCostQuoteReceiptChapter } from "../common/featureTourConfig";
import {
    clearFeatureTourFlow,
    getCurrentTourUser,
    readFeatureTourFlow,
    saveFeatureTourChapterState,
    saveFeatureTourFlow,
} from "../common/featureTourState";
import { calculateOrderBillingWeight, calculateReceivable } from "../common/receivable";

const passHash = '18667b982b1c774d3c096422e457906afb227cfc7f956d3f4fc1f9bc07b98862';
const quoteTourChapter = getCostQuoteReceiptChapter('quote');
const workflowStartTourChapter = getCostQuoteReceiptChapter('workflowStart');
const quoteTourTargets = {
    entry: '[data-tour="quote-entry"]',
    summary: '[data-tour="quote-summary"]',
    pricing: '[data-tour="quote-pricing"]',
    submit: '[data-tour="quote-submit"]',
    history: '[data-tour="quote-history"]',
    receiptMenu: '.tour-receipts-menu',
};

const verify = () => {
    // const now_time = (new Date()).getTime()
    // // 十分钟内有效
    // if (now_time - Number(window.localStorage.getItem('verified')) < 300000) return true;
    // // const pass = window.prompt('请输入管理员密码');
    // const pass = 0;
    // const hashFunction = crypto.createHash('sha256');
    // if (!pass || hashFunction.update(pass).digest().toString('hex') !== passHash) {
    //     window.localStorage.setItem('verified', now_time.toString());
    //     return true;
    // }
    // window.localStorage.setItem('verified', now_time.toString());
    return true;
}

let focusFlag = '';


function base64ToBlob(base64, mimeType) {
    const binary = window.atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
        bytes[i] = binary.charCodeAt(i);
    }
    return new Blob([bytes], { type: mimeType });
}

const fieldTooltipStyle = { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' };

const DetailText = ({ children, ...props }) => (
    <Tooltip title={children} styles={{ body: fieldTooltipStyle }}>
        <Typography.Text {...props}>{children}</Typography.Text>
    </Tooltip>
);

const CargoText = ({ value, suffix = '', ellipsis = false, title }) => {
    if (value === undefined || value === null || value === '') return null;
    const text = `${value}${suffix}`;
    return (
        <Typography.Text className={styles.cargoText} copyable={{ text }}>
            <Tooltip title={text} styles={{ body: fieldTooltipStyle }}>
                <span className={`${styles.cargoTextValue}${ellipsis ? ` ${styles.cargoTextEllipsis}` : ''}`} title={title}>
                    {text}
                </span>
            </Tooltip>
        </Typography.Text>
    );
};


const EditableCell = (props) => {
    const {
        editing,
        dataIndex,
        title,
        // inputType,
        record,
        index,
        children,
        onClick,
        onEnter,
        onBlur,
        generateButton,
        generatingNumber,
        ...restProps
    } = props;
    const dict = {
        weight: {
            addonAfter: 'kg'
        },
        price: {
            addonAfter: '元'
        },
        count: {
            addonAfter: '件'
        }
    }
    return (
        <td {...restProps}>
            {editing ? (
                <Space>
                    <Form.Item
                        name={dataIndex}
                        style={{ margin: 0 }}
                        rules={[{ required: false, message: `请输入 ${title}!` }]}
                    >
                        {dataIndex !== 'real_en_name' ? (
                            <Input
                                rootClassName={'myEditableCellInputIdToAvoidBlur'}
                                disabled={generatingNumber}
                                onBlur={onBlur}
                                ref={(node) => {
                                    if (focusFlag === dataIndex && node) {
                                        node.focus();
                                        focusFlag = '';
                                    }
                                    return () => {
                                        focusFlag = '';
                                    }
                                }}
                                onPressEnter={() => onEnter(dataIndex)}
                            />
                        ) : (
                            <GoodInput onEnter={() => onEnter(dataIndex)} onBlur={onBlur}
                                defaultValue={record[dataIndex]} />
                        )}
                    </Form.Item>
                    {generateButton}
                </Space>
            ) : (
                <div
                    className={dataIndex ? styles['editable-cell-value-wrap'] : ""}
                    style={{ paddingInlineEnd: 24 }}
                    onClick={onClick}
                >
                    {children}
                </div>
            )}
        </td>
    );
};

export default function OrderDetail() {
    // const _orderProperty = [...orderProperty];
    const { order_id } = useParams()
    const navigate = useNavigate();
    const { userId: tourUserId, roles: sessionRoles } = getCurrentTourUser();
    const canViewQuotes = hasPermission(sessionRoles, ['admin', 'store_manager', 'salesperson', 'finance']);
    const initialTourFlow = readFeatureTourFlow(tourUserId);
    const forceQuoteTour = initialTourFlow?.campaignId === COST_QUOTE_RECEIPT_TOUR.id
        && initialTourFlow.stage === 'quote';

    //message
    const [messageX, messageComponent] = message.useMessage();

    //description data状态管理
    const [descriptionData, setDescriptionData] = useState({});
    const orderDetailRequestId = useRef(0);
    const [jwtPayload, setJwtPayload] = useState({});
    const [historyOpen, setHistoryOpen] = useState(false);
    const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
    const [salesman, setSalesman] = useState(null);
    const [salesmanOptions, setSalesmanOptions] = useState([]);
    const [salesmanEditorValue, setSalesmanEditorValue] = useState(undefined);
    const [salesmanLoading, setSalesmanLoading] = useState(false);
    const [salesmanSaving, setSalesmanSaving] = useState(false);
    const [salesmanUsersLoading, setSalesmanUsersLoading] = useState(false);
    const [salesmanEditing, setSalesmanEditing] = useState(false);
    const [quoteForm] = Form.useForm();
    const [transportationModes, setTransportationModes] = useState([]);
    const [quoteModalOpen, setQuoteModalOpen] = useState(false);
    const [quoteSubmitting, setQuoteSubmitting] = useState(false);
    const [quoteHistory, setQuoteHistory] = useState([]);
    const quoteHistoryRequestId = useRef(0);
    const [quotePdfPrinting, setQuotePdfPrinting] = useState(false);
    const [form] = Form.useForm();
    const [editingKey, setEditingKey] = useState('');
    const editingCargoUidRef = useRef('');
    editingCargoUidRef.current = editingKey;
    const [generatingNumbers, setGeneratingNumbers] = useState(new Set());
    const numberGenerationInFlightRef = useRef(new Set());
    const numberGenerationContextRef = useRef(0);
    const [orderNumberEditing, setOrderNumberEditing] = useState(false);
    const [orderNumberDraft, setOrderNumberDraft] = useState('');
    const [orderNumberSaving, setOrderNumberSaving] = useState(false);
    const [cargoData, setCargoData] = useState([]);
    const cargoRequestId = useRef(0);
    const [selectedKeys, setSelectedKeys] = useState([]);
    const quoteUnitPrice = Form.useWatch('unit_price', quoteForm);
    const quoteSurcharge = Form.useWatch('surcharge', quoteForm);
    const [customsCodes, setCustomsCodes] = useState([]);
    const [customsCodesLoading, setCustomsCodesLoading] = useState(false);

    // 客户联系信息状态
    const [customerContact, setCustomerContact] = useState({ contextKey: null, phone: '', wechat: '' });
    const [customerContactLoading, setCustomerContactLoading] = useState(false);

    // 箱子分配模态框状态
    const [boxAssignmentVisible, setBoxAssignmentVisible] = useState(false);
    const [specialFieldDraft, setSpecialFieldDraft] = useState('');
    const specialFieldDraftRef = useRef('');
    const specialFieldCommitRef = useRef(false);
    const cargoSaveInFlightRef = useRef(new Set());

    useEffect(() => {
        setGeneratingNumbers(new Set(numberGenerationInFlightRef.current));
        setOrderNumberEditing(false);
        setOrderNumberSaving(false);
        return () => { numberGenerationContextRef.current += 1; };
    }, [order_id]);

    const fetchQuoteHistory = useCallback(async () => {
        if (!canViewQuotes) return [];
        const requestId = ++quoteHistoryRequestId.current;
        try {
            const res = await fetch(`${endpoint}/orders/${order_id}/quotes`, { headers: getSafeHeader() });
            const data = await res.json();
            if (requestId !== quoteHistoryRequestId.current) return [];
            if (res.ok && data.code === 200 && Array.isArray(data.data)) {
                setQuoteHistory(data.data);
                return data.data;
            }
        } catch (error) {
            console.error('获取报价历史失败:', error);
        }
        if (requestId === quoteHistoryRequestId.current) setQuoteHistory([]);
        return [];
    }, [order_id, canViewQuotes]);

    const fetchOrderDetail = useCallback(async () => {
        const requestId = ++orderDetailRequestId.current;
        try {
            const response = await fetch(`${endpoint}/orders/${order_id}`, { headers: getSafeHeader() });
            const result = await response.json();
            if (requestId !== orderDetailRequestId.current) return null;
            if (!response.ok || result.code !== 200 || !result.data) {
                message.error(result.msg || result.message || '获取订单详情失败');
                return null;
            }
            const data = result.data;
            setDescriptionData(data);
            setSalesman(data?.salesman || null);
            setSalesmanEditorValue(data?.salesman?.id ?? data?.salesman_id ?? undefined);
            await fetchQuoteHistory();
            return data;
        } catch (error) {
            if (requestId !== orderDetailRequestId.current) return null;
            console.error('获取订单详情失败:', error);
            message.error('获取订单详情失败');
            return null;
        }
    }, [order_id, fetchQuoteHistory]);

    const markVersionChanged = useCallback(async ({ reloadOrder = true } = {}) => {
        setHistoryRefreshKey(value => value + 1);
        if (reloadOrder) await fetchOrderDetail();
    }, [fetchOrderDetail]);

    const currentUserId = jwtPayload?.user_id ?? jwtPayload?.id ?? jwtPayload?.uid;
    const userRoles = getUserRoles(jwtPayload);
    const assignedSalesmanId = salesman?.id ?? descriptionData?.salesman_id;
    const isCurrentSalesman = currentUserId != null && assignedSalesmanId != null
        && String(currentUserId) === String(assignedSalesmanId);
    // 业务员只能查看自己负责订单的客户联系信息，管理员和店长保留完整权限。
    const canViewCustomerContact = String(descriptionData.uid || '') === String(order_id)
        && (hasPermission(userRoles, ['admin', 'store_manager'])
            || (hasPermission(userRoles, ['salesperson']) && isCurrentSalesman));
    const customerContactId = descriptionData.customer_ids?.[0] ?? descriptionData.customer_id;
    const customerContactKey = JSON.stringify([order_id, customerContactId, assignedSalesmanId, currentUserId]);
    const displayedCustomerContact = customerContact.contextKey === customerContactKey
        ? customerContact : { phone: '', wechat: '' };
    // 检查是否有分配箱子的权限
    const canAssignBoxes = hasPermission(userRoles, ['admin', 'store_manager', 'salesperson', 'clerk']);
    useEffect(() => {
        let active = true;
        setDescriptionData({});
        setSalesman(null);
        const jwt = localStorage.getItem('jwt');
        if (jwt) {
            try {
                const parts = jwt.split('.');
                if (parts.length === 3) {
                    setJwtPayload(JSON.parse(atob(parts[1])));
                }
            } catch (e) {
                console.error('解析 JWT 时出错:', e);
            }
        }

        fetchOrderDetail();

        (async () => {
            setSalesmanLoading(true);
            try {
                const res = await (await fetch(`${endpoint}/orders/${order_id}/salesman`, { headers: getSafeHeader() })).json();
                if (active && res.code === 200) {
                    setSalesman(res.data || null);
                    setSalesmanEditorValue(res.data?.id ?? undefined);
                    setDescriptionData(prev => ({ ...prev, salesman: res.data || null, salesman_id: res.data?.id ?? null }));
                }
            } finally {
                if (active) setSalesmanLoading(false);
            }
        })();
        return () => {
            active = false;
            orderDetailRequestId.current += 1;
            quoteHistoryRequestId.current += 1;
        };
    }, [order_id, fetchOrderDetail]);

    useEffect(() => {
        (async () => {
            setSalesmanUsersLoading(true);
            try {
                const res = await (await fetch(`${endpoint}/users/salespersons`, { headers: getSafeHeader() })).json();
                if (res.code === 200 && Array.isArray(res.data)) {
                    setSalesmanOptions(
                        res.data.map((user) => ({
                            value: user.id,
                            label: `${user.name || '-'} (${user.phone || '-'})`
                        }))
                    );
                }
            } finally {
                setSalesmanUsersLoading(false);
            }
        })();
    }, [jwtPayload]);

    useEffect(() => {
        let active = true;

        (async () => {
            setCustomsCodesLoading(true);
            try {
                const response = await fetch(`${endpoint}/customs-codes`, {
                    headers: getSafeHeader()
                });
                const result = await response.json();
                if (active && result.code === 200) {
                    setCustomsCodes(result.data || []);
                }
            } catch (error) {
                console.error('获取海关编码失败:', error);
            } finally {
                if (active) setCustomsCodesLoading(false);
            }
        })();

        return () => {
            active = false;
        };
    }, []);

    // 如果当前业务员不在 salesperson 列表中，将其加入选项
    useEffect(() => {
        if (salesman && salesman.id !== undefined && salesman.id !== null) {
            setSalesmanOptions((prev) => {
                if (prev.some((item) => Number(item.value) === Number(salesman.id))) {
                    return prev;
                }
                return [
                    { value: Number(salesman.id), label: `${salesman.name || '-'} (${salesman.phone || '-'})` },
                    ...prev
                ];
            });
        }
    }, [salesman]);

    // 获取客户联系信息
    useEffect(() => {
        let active = true;
        setCustomerContact({ contextKey: customerContactKey, phone: '', wechat: '' });
        setCustomerContactLoading(false);
        if (canViewCustomerContact && customerContactId != null) {
            (async () => {
                setCustomerContactLoading(true);
                try {
                    const response = await fetch(`${endpoint}/orders/${order_id}/customer-contact`, { headers: getSafeHeader() });
                    const res = await response.json();
                    if (active && response.ok && res.code === 200 && res.data) {
                        setCustomerContact({
                            contextKey: customerContactKey,
                            phone: res.data.phone || '',
                            wechat: res.data.wechat || ''
                        });
                    }
                } catch (e) {
                    if (active) console.error('获取客户联系信息失败:', e);
                } finally {
                    if (active) setCustomerContactLoading(false);
                }
            })();
        }
        return () => { active = false; };
    }, [canViewCustomerContact, customerContactId, customerContactKey, order_id]);
    const canQuote = hasPermission(userRoles, ['salesperson']) && isCurrentSalesman;
    const canViewOrderHistory = hasPermission(userRoles, ['admin', 'store_manager']);
    const canUndoOutbound = hasPermission(userRoles, ['admin', 'store_manager']);
    const [undoingCargoUid, setUndoingCargoUid] = useState(null);
    const cargoRemovalBlocked = record => record?.removal_allowed === false
        || (record?.removal_allowed == null && (isCargoOutboundOrLater(record) || Boolean(record?.date)));
    const removalBlockedMessage = '包裹已出库，请先撤销出库后再移除';
    const selectedRemovalBlocked = cargoData.some(record => selectedKeys.includes(record.uid) && cargoRemovalBlocked(record));
    const canEditSalesmanByRole = hasPermission(userRoles, ['admin']) || isCurrentSalesman;
    const editPolicy = normalizeOrderEditPolicy(descriptionData.edit_policy, {
        defaults: {
            order_fields: userRoles.length > 0,
            transportation: canEditSalesmanByRole,
            order_weight: userRoles.length > 0,
            salesman: canEditSalesmanByRole,
            customer_assignment: userRoles.length > 0,
            cargo_content: userRoles.length > 0,
            cargo_weight: userRoles.length > 0,
            box_content: hasPermission(userRoles, ['admin', 'store_manager', 'salesperson', 'clerk']),
            box_weight: hasPermission(userRoles, ['admin', 'store_manager', 'salesperson', 'worker']),
            tracking_numbers: hasPermission(userRoles, ['admin', 'store_manager', 'salesperson', 'clerk']),
            box_workers: hasPermission(userRoles, ['admin', 'store_manager', 'salesperson', 'clerk']),
            box_membership: canAssignBoxes,
            archive_or_delete: userRoles.length > 0,
            fully_outbound: descriptionData.edit_policy?.fully_outbound === true,
        },
    });
    const canEditSalesman = canEditSalesmanByRole && editPolicy.salesman;
    const canEditOrderField = (field) => {
        if (field === 'customer_name' || field === 'customer_ids' || field === 'customers') return false;
        if (field === 'total_weight') return editPolicy.order_weight;
        if (field === 'transportation') return editPolicy.transportation;
        if (field === 'update_date' || field === 'order_date') return false;
        return editPolicy.order_fields;
    };
    const canEditCargoField = (record, field) => {
        const isBox = !!record?.packing_list_uid;
        if (isBox && field === 'tag') return false;
        if (field === 'weight') {
            if (isCargoOutboundOrLater(record)) return false;
            return isBox ? editPolicy.box_weight : editPolicy.cargo_weight;
        }
        if (field === 'transfer_id') {
            return editPolicy.tracking_numbers && (!isBox || isBoxOriginalNumberEditable(record));
        }
        if (field === 'waybill_id') return editPolicy.tracking_numbers;
        return isBox ? editPolicy.box_content : editPolicy.cargo_content;
    };
    const canGenerateNumbers = String(descriptionData.uid || '') === String(order_id)
        && hasPermission(userRoles, ['admin', 'store_manager', 'salesperson', 'clerk']);
    const generationKey = (record) => `${order_id}:${record ? `cargo:${record.uid}` : 'order'}`;
    const generateNumber = async (record) => {
        const field = record ? 'transfer_id' : 'order_id';
        if (!canGenerateNumbers || !(record ? canEditCargoField(record, field) : canEditOrderField(field))) return;
        if (record ? editingCargoUidRef.current !== record.uid : !orderNumberEditing) return;
        const key = generationKey(record);
        if (numberGenerationInFlightRef.current.has(key)) return;
        if (record ? cargoSaveInFlightRef.current.has(record.uid) : orderNumberSaving) return;
        const context = numberGenerationContextRef.current;
        numberGenerationInFlightRef.current.add(key);
        if (record) cargoSaveInFlightRef.current.add(record.uid);
        setGeneratingNumbers(new Set(numberGenerationInFlightRef.current));
        const label = record ? '原单号' : '订单号';
        try {
            const url = record
                ? `${endpoint}/orders/${order_id}/cargo/${record.uid}/generate-original-number`
                : `${endpoint}/orders/${order_id}/generate-order-number`;
            const response = await fetch(url, {
                method: 'POST',
                headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ expected_value: (record || descriptionData)[field] ?? null }),
            });
            const result = await response.json();
            if (context !== numberGenerationContextRef.current) return;
            if (!response.ok || result.code !== 200 || !result.data?.[field]) {
                throw new Error(result.msg || result.message || (response.status === 409
                    ? '单号已被修改，请刷新页面后重试' : `生成${label}失败`));
            }
            const number = result.data[field];
            orderDetailRequestId.current += 1;
            if (record) {
                cargoRequestId.current += 1;
                setCargoData(current => current.map(item => item.uid === record.uid ? { ...item, transfer_id: number } : item));
                if (editingCargoUidRef.current === record.uid) form.setFieldsValue({ transfer_id: number });
            } else {
                setOrderNumberDraft(number);
            }
            setDescriptionData(current => ({
                ...current,
                ...(!record ? { order_id: number } : {}),
                ...(result.data.current_version != null ? {
                    current_version: Math.max(Number(current.current_version) || 0, Number(result.data.current_version) || 0),
                } : {}),
            }));
            setHistoryRefreshKey(value => value + 1);
            messageX.success(`${label}已生成并保存`);
        } catch (error) {
            if (context === numberGenerationContextRef.current) messageX.error(error.message || `生成${label}失败`);
        } finally {
            numberGenerationInFlightRef.current.delete(key);
            if (record) cargoSaveInFlightRef.current.delete(record.uid);
            setGeneratingNumbers(new Set(numberGenerationInFlightRef.current));
        }
    };
    const renderCargoNumberGeneration = (record) => canGenerateNumbers && isEditing(record) && canEditCargoField(record, 'transfer_id') ? (
        <Tooltip title="随机生成并保存原单号">
            <Button
                type="text"
                size="small"
                icon={<ReloadOutlined />}
                aria-label="生成原单号"
                className="myEditableCellInputIdToAvoidBlur"
                loading={generatingNumbers.has(generationKey(record))}
                disabled={generatingNumbers.has(generationKey(record))}
                onMouseDown={event => event.preventDefault()}
                onClick={event => {
                    event.stopPropagation();
                    generateNumber(record);
                }}
            />
        </Tooltip>
    ) : null;
    const finalQuote = quoteHistory.find(item => item.is_final);
    const canCollect = String(descriptionData.uid || '') === String(order_id) && hasPermission(userRoles, ['admin', 'salesperson', 'finance']);
    const currentTransportation = (descriptionData.transportation || '').trim();
    const currentQuoteMode = transportationModes.find(item => item.name === currentTransportation);
    const currentMinPrice = currentQuoteMode ? Number(currentQuoteMode.min_price || 0) : 0;
    const quoteTourSteps = quoteTourChapter.steps.map(step => ({
        ...step,
        target: () => document.querySelector(quoteTourTargets[step.key]),
    }));
    const quoteManualTourSteps = quoteTourSteps.filter(step => !step.autoOnly);

    const fetchTransportationModes = async () => {
        try {
            const res = await fetch(`${endpoint}/transportation-modes`, { headers: getSafeHeader() });
            const data = await res.json();
            if (data.code === 200) {
                setTransportationModes(data.data || []);
                return data.data || [];
            }
        } catch (error) {
            console.error('获取运输方式失败:', error);
        }
        return [];
    };

    const openQuoteModal = async () => {
        if (transportationModes.length === 0) {
            await fetchTransportationModes();
        }
        quoteForm.setFieldsValue({
            unit_price: undefined,
            surcharge: 0,
            quote_remark: '',
        });
        setQuoteModalOpen(true);
        fetchQuoteHistory();
    };

    const handleQuoteTourStepChange = async (nextStep, previousStep, mode) => {
        const activeSteps = mode === 'manual' ? quoteManualTourSteps : quoteTourSteps;
        const stepKey = activeSteps[nextStep]?.key;
        if (stepKey === 'receiptMenu') {
            setQuoteModalOpen(false);
            saveFeatureTourChapterState({
                userId: tourUserId,
                campaignId: COST_QUOTE_RECEIPT_TOUR.id,
                chapterId: quoteTourChapter.id,
                version: quoteTourChapter.version,
                status: 'completed',
            });
            saveFeatureTourChapterState({
                userId: tourUserId,
                campaignId: COST_QUOTE_RECEIPT_TOUR.id,
                chapterId: workflowStartTourChapter.id,
                version: workflowStartTourChapter.version,
                status: 'completed',
            });
            saveFeatureTourFlow({
                userId: tourUserId,
                campaignId: COST_QUOTE_RECEIPT_TOUR.id,
                stage: 'receipt-navigation',
            });
            return;
        }
        if (nextStep === 0) {
            setQuoteModalOpen(false);
            return;
        }
        if (!quoteModalOpen) await openQuoteModal();
    };

    useEffect(() => {
        if (!forceQuoteTour || !descriptionData.order_id || currentUserId == null || salesmanLoading) return;
        if (canQuote) return;

        messageX.warning('这笔订单不是由你负责的，请选择由你负责的订单继续报价引导');
        saveFeatureTourFlow({
            userId: tourUserId,
            campaignId: COST_QUOTE_RECEIPT_TOUR.id,
            stage: 'select-quote-order',
        });
        navigate('/orders');
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [canQuote, currentUserId, descriptionData.order_id, forceQuoteTour, salesmanLoading]);

    const submitQuote = async () => {
        try {
            const values = await quoteForm.validateFields();
            setQuoteSubmitting(true);
            const res = await fetch(`${endpoint}/orders/${order_id}/quotes`, {
                method: 'POST',
                headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    quote_remark: values.quote_remark,
                    unit_price: Number(values.unit_price || 0),
                    surcharge: Number(values.surcharge || 0),
                })
            });
            const data = await res.json();
            if (data.code === 200) {
                messageX.success(data.msg || '报价已提交');
                quoteForm.setFieldsValue({
                    unit_price: undefined,
                    surcharge: 0,
                    quote_remark: '',
                });
                if (data.data?.is_final && data.data?.transportation_name) {
                    setDescriptionData(prev => ({ ...prev, transportation: data.data.transportation_name }));
                }
                await markVersionChanged();
            } else {
                messageX.error(data.msg || '报价失败');
            }
        } catch (error) {
            if (error?.errorFields) return;
            messageX.error('报价失败');
            console.error(error);
        } finally {
            setQuoteSubmitting(false);
        }
    };

    const handlePrintQuotePdf = async () => {
        const previewWindow = window.open('', '_blank');
        if (!previewWindow) {
            messageX.warning('浏览器拦截了新窗口，请允许弹窗后重试');
            return;
        }
        previewWindow.document.write('正在生成报价单 PDF...');
        setQuotePdfPrinting(true);
        try {
            const res = await fetch(`${endpoint}/orders/${order_id}/quote-pdf`, {
                headers: getSafeHeader()
            });
            const data = await res.json();
            if (data.code !== 200) {
                throw new Error(data.msg || '生成报价单失败');
            }
            const blob = base64ToBlob(data.data, data.mime_type || 'application/pdf');
            const blobUrl = window.URL.createObjectURL(blob);
            previewWindow.location.href = blobUrl;
            window.setTimeout(() => window.URL.revokeObjectURL(blobUrl), 60 * 1000);
        } catch (error) {
            previewWindow.close();
            messageX.error(error?.message || '生成报价单失败');
            console.error(error);
        } finally {
            setQuotePdfPrinting(false);
        }
    };

    const handleSaveSalesman = async (userId) => {
        if (!canEditSalesman) {
            messageX.error('你没有权限修改业务员');
            return;
        }
        if (userId === undefined) {
            messageX.warning('请选择业务员');
            return;
        }
        const parsedUserId = Number(userId);
        if (Number.isNaN(parsedUserId)) {
            messageX.error('业务员ID无效');
            return;
        }
        setSalesmanSaving(true);
        try {
            const res = await (await fetch(`${endpoint}/orders/${order_id}/salesman`, {
                method: 'PUT',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ user_id: parsedUserId })
            })).json();
            if (res.code === 200) {
                setSalesman(res.data || null);
                setSalesmanEditorValue(res.data?.id ?? undefined);
                setDescriptionData(prev => ({ ...prev, salesman: res.data || null, salesman_id: res.data?.id ?? null }));
                setSalesmanEditing(false);
                messageX.success('业务员更新成功');
                await markVersionChanged();
                return;
            }
            messageX.error(res.msg || '业务员更新失败');
        } finally {
            setSalesmanSaving(false);
        }
    };

    const handleRemoveSalesman = async () => {
        if (!canEditSalesman) {
            messageX.error('你没有权限修改业务员');
            return;
        }
        setSalesmanSaving(true);
        try {
            const res = await (await fetch(`${endpoint}/orders/${order_id}/salesman`, {
                method: 'PUT',
                headers: {
                    ...getSafeHeader(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ user_id: null })
            })).json();
            if (res.code === 200) {
                setSalesman(null);
                setSalesmanEditorValue(undefined);
                setDescriptionData(prev => ({ ...prev, salesman: null, salesman_id: null }));
                setSalesmanEditing(false);
                messageX.success('业务员已移除');
                await markVersionChanged();
                return;
            }
            messageX.error(res.msg || '移除业务员失败');
        } finally {
            setSalesmanSaving(false);
        }
    };

    //纸箱表格
    const currentQuoteWeight = cargoData.reduce((sum, cargo) => sum + Number(cargo.weight || 0), 0);
    const currentBillingWeight = calculateOrderBillingWeight(cargoData.map(cargo => cargo.weight));
    const quoteReceivablePreview = calculateReceivable(
        currentBillingWeight,
        quoteUnitPrice,
        quoteSurcharge
    );
    const displayedQuoteReceivable = quoteReceivablePreview;
    const fetchCargoData = useCallback(async () => {
        const requestId = ++cargoRequestId.current;
        try {
            const { code, data } = await (await fetch(`${endpoint}/orders/${order_id}/cargo?time=${(new Date()).getTime()}`, { headers: getSafeHeader() })).json();
            if (requestId !== cargoRequestId.current) return;
            if (code === 500) {
                message.error("17Track 获取订单跟踪信息失败")
            }
            setCargoData((data || []).map(v => ({ ...v, key: v['uid'] })));
        } catch (error) {
            if (requestId !== cargoRequestId.current) return;
            console.error('获取包裹详情失败:', error);
            message.error('获取包裹详情失败');
        }
    }, [order_id]);
    useEffect(() => {
        setCargoData([]);
        setEditingKey('');
        setSelectedKeys([]);
        form.resetFields();
        fetchCargoData();
        return () => { cargoRequestId.current += 1; };
    }, [fetchCargoData, form]);
    const isEditing = (record) => {
        return record['uid'] === editingKey;
    }

    const edit = (record) => {
        if (!canEditCargoRecord(record)) return;
        form.setFieldsValue({
            ...record,
        });
        setEditingKey(record.uid);
    };
    const cancel = () => {
        setEditingKey('');
    };
    const canEditCargoRecord = (record) => [
        'transfer_id', 'waybill_id', 'tag', 'count', 'real_en_name', 'weight', 'price'
    ].some(field => canEditCargoField(record, field));
    const save = async (key) => {
        if (!verify()) {
            message.error("密码错误！");
            return;
        }
        if (cargoSaveInFlightRef.current.has(key)) return;
        let ownsSaveLock = false;
        try {
            const row = await form.validateFields();
            if (cargoSaveInFlightRef.current.has(key)) return;

            const newData = [...cargoData];
            const index = newData.findIndex((item) => key === item.uid);
            if (key) {
                const item = newData[index];
                if (!item) return;
                const changedRow = Object.fromEntries(
                    Object.entries(row).filter(([field, value]) => (
                        canEditCargoField(item, field)
                        && JSON.stringify(item[field] ?? null) !== JSON.stringify(value ?? null)
                    ))
                );
                if (Object.keys(changedRow).length === 0) {
                    setEditingKey('');
                    return;
                }
                cargoSaveInFlightRef.current.add(key);
                ownsSaveLock = true;
                const updateRes = await (await fetch(`${endpoint}/cargo/${key}`, {
                    headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
                    body: JSON.stringify(changedRow),
                    method: 'PUT'
                })).json();
                if (updateRes.code !== 200) {
                    message.error(updateRes.msg || '修改失败！');
                    return;
                }

                const updatedItem = {
                    ...item,
                    ...changedRow,
                };
                if (
                    Object.prototype.hasOwnProperty.call(changedRow, 'waybill_id')
                    && String(changedRow.waybill_id ?? '').trim().length > 0
                    && !isCargoOutboundOrLater(item)
                ) {
                    updatedItem.status = 1;
                }
                newData.splice(index, 1, updatedItem);
                setCargoData(current => current.map(cargo => cargo.uid === key ? { ...cargo, ...updatedItem } : cargo));
            } else {
                newData.push(row);
                setCargoData(newData);
            }
            setEditingKey('');
            message.success('修改成功！');
            await markVersionChanged();
        } catch (errInfo) {
            if (!errInfo?.errorFields) {
                message.error(errInfo?.message || '修改失败！');
            }
            console.log('Validate Failed:', errInfo);
        } finally {
            if (ownsSaveLock) cargoSaveInFlightRef.current.delete(key);
        }
    };
    const columns = [
        {
            title: '原单号',
            key: 'transfer_id',
            dataIndex: 'transfer_id',
            ellipsis: false,
            fixed: 'left',
            editable: true,
            width: 270,
            render: (text) => <CargoText value={text} />
        }, {
            title: '转单号（运单号）',
            key: 'waybill_id',
            dataIndex: 'waybill_id',
            ellipsis: { showTitle: false },
            fixed: 'left',
            editable: true,
            width: 200,
            render: (text) => <CargoText value={text} ellipsis />
        },
        {
            title: '唛头',
            key: 'tag',
            dataIndex: 'tag',
            ellipsis: false,
            editable: true,
            width: 150,
            render(text, record) {
                if (!text) return null;
                if (!record?.packing_list_uid) {
                    return <CargoText value={text} />;
                }
                return (
                    <Tooltip title={text} styles={{ body: fieldTooltipStyle }}>
                        <Button
                            type="link"
                            style={{
                                padding: 0,
                                height: 'auto',
                                width: '100%',
                                maxWidth: '100%',
                                whiteSpace: 'normal',
                                overflowWrap: 'anywhere',
                                wordBreak: 'break-all',
                                textAlign: 'left',
                                lineHeight: 1.5,
                            }}
                            onClick={(event) => {
                                event.stopPropagation();
                                navigate(`/packing-lists/${encodeURIComponent(record.packing_list_uid)}`);
                            }}
                        >
                            {text}
                        </Button>
                    </Tooltip>
                );
            }
        },
        // {
        //     title: '唛头',
        //     key: 'tag',
        //     dataIndex: 'tag',
        //     ellipsis: true,
        //     fixed: 'left',
        //     width: 120,
        //     render: (text, record, i) => text && <Typography.Text copyable key={i}>{text}</Typography.Text>
        // },
        {
            title: '申报数量(件)',
            key: 'count',
            dataIndex: 'count',
            ellipsis: false,
            editable: true,
            width: 150,
            render: (text) => <CargoText value={text} suffix="件" />
        },
        {
            title: '英文品名',
            key: 'real_en_name',
            dataIndex: 'real_en_name',
            ellipsis: false,
            editable: true,
            width: 150,
            render: (text) => <CargoText value={text} />
        },
        {
            title: '重量(KG)',
            key: 'weight',
            dataIndex: 'weight',
            ellipsis: false,
            editable: true,
            width: 150,
            render(text, record) {
                return <CargoText
                    value={text}
                    suffix="KG"
                    title={isCargoOutboundOrLater(record) ? '货物已出库，重量不可修改' : undefined}
                />
            }
        },
        {
            title: '申报价值',
            key: 'price',
            dataIndex: 'price',
            ellipsis: false,
            editable: true,
            width: 150,
            render: (text) => <CargoText value={text} />
        },
        {
            title: '状态',
            key: 'status',
            width: 220,
            dataIndex: 'status',
            render(statusText, record, i) {
                // 装箱单包裹在未出库时显示业务状态；已出库后切换为第三方轨迹状态。
                let effectiveStatusText = statusText;
                if (record?.packing_list_uid) {
                    const cargoStatus = Number(record?.status || 0);
                    if (cargoStatus !== 1) {
                        return <Tooltip title="待出库"><Badge status={'processing'} text={'待出库'} /></Tooltip>;
                    }

                    // For shipped packing-list boxes, prefer latest 17track status when available.
                    if (record?.track_status) {
                        effectiveStatusText = record.track_status;
                    }
                }

                const _trackStatus = trackStatus[effectiveStatusText] || {
                    status: 'default',
                    badgeText: String(effectiveStatusText ?? '未知状态'),
                    detail: false,
                    title: '状态'
                };
                const MyBadge = () => <Badge style={{ cursor: "pointer" }} status={_trackStatus.status || "processing"}
                    text={_trackStatus.badgeText} onClick={() => {
                        window.open("https://t.17track.net/zh-cn#nums=" + record['waybill_id'])
                    }} />;
                return _trackStatus.detail ?
                    <Popover trigger="hover" content={
                        <Timeline style={{ paddingTop: '1rem' }} reverse={false}
                            items={(record['events'] || []).map((item, i) => {
                                return {
                                    children:
                                        <Space>
                                            <div>{item?.time_raw?.date} {item?.time_raw?.time}</div>
                                            <div>{item?.location}, {item?.description}</div>
                                        </Space>,
                                    color: i === 0 ? _trackStatus.status === 'error' ? 'red' : '#1668dc' : 'gray'
                                }
                            })}>
                        </Timeline>
                    } title={<Typography.Text level={5}>{_trackStatus.title}</Typography.Text>} placement="top">
                        <Button type={"text"} style={{ padding: "unset", background: "transparent" }}><MyBadge /></Button>
                    </Popover>
                    : (<Tooltip title={_trackStatus.badgeText} styles={{ body: fieldTooltipStyle }}><span><MyBadge /></span></Tooltip>)
                // return text === 0 ? <Badge status={'default'} text={'在库'}/> :
                //     <Badge status={'success'} text={<Typography.Text>出库</Typography.Text>} style={{cursor: "pointer"}} onClick={() =>
                //     {window.open("https://t.17track.net/zh-cn#nums="+record['waybill_id'])}}/>

            }
        },
        {
            title: '出库日期',
            key: 'date',
            dataIndex: 'date',
            width: 200,
            render: (text) => <CargoText value={text} />
        }, {
            title: '创建日期',
            key: 'create_date',
            dataIndex: 'create_date',
            width: 200,
            render: (text) => <CargoText value={text} />
        }, {
            title: '更新日期',
            key: 'update_date',
            dataIndex: 'update_date',
            width: 200,
            render: (text) => <CargoText value={text} />
        },
        {
            title: '操作',
            key: 'x',
            dataIndex: '',
            fixed: 'right',
            align: 'center',
            width: 230,
            render(_, record) {
                const editable = isEditing(record);
                const removalBlocked = cargoRemovalBlocked(record);
                return editable ? (
                    <Space size={'middle'}>
                        <Button type={'text'}
                            onClick={() => save(record.uid)}
                            disabled={generatingNumbers.has(generationKey(record))}
                            style={{
                                color: "#1677FF"
                            }}
                        >
                            保存
                        </Button>
                        <Button danger type={'text'} className={'myEditableCellInputIdToAvoidBlur'}
                            onClick={cancel}>取消</Button>
                    </Space>
                ) : (
                    <Space size={'middle'}>
                        <Popconfirm
                            title="移除包裹关联"
                            description="你确认要将该包裹从当前订单中移除吗？"
                            onConfirm={() => handleDeleteCargo([record.uid])}
                            disabled={!editPolicy.box_membership || removalBlocked}
                            okText="确认移除"
                            cancelText="取消"
                        >
                            <Tooltip title={removalBlocked ? removalBlockedMessage : undefined}>
                                <span><Button type={'text'} danger disabled={!editPolicy.box_membership || removalBlocked}>移除</Button></span>
                            </Tooltip>
                        </Popconfirm>
                        {removalBlocked && canUndoOutbound && <Popconfirm title="撤销包裹出库" description="将包裹重新入库并清空转单号，原出库和成本历史保留。撤销后可移除包裹。"
                            onConfirm={() => handleUndoOutbound(record)} okText="确认撤销" cancelText="取消" disabled={!!undoingCargoUid}>
                            <Button type="text" loading={undoingCargoUid === record.uid} disabled={!!undoingCargoUid}>撤销出库</Button>
                        </Popconfirm>}
                        <Button type={'text'} style={{ color: "#1677FF" }} disabled={editingKey !== '' || !canEditCargoRecord(record) || generatingNumbers.has(generationKey(record))}
                            onClick={() => edit(record)}>
                            编辑
                        </Button>
                    </Space>);
            }
        }
    ];
    const mergedColumns = columns.map((col) => {
        if (!col.editable) {
            return col;
        }
        return {
            ...col,
            onCell: (record) => {
                const fieldEditable = canEditCargoField(record, col.dataIndex);
                return {
                    record,
                    // inputType: col.dataIndex === 'age' ? 'number' : 'text',
                    dataIndex: col.dataIndex,
                    title: col.title,
                    editing: isEditing(record) && fieldEditable,
                    generateButton: col.dataIndex === 'transfer_id' ? renderCargoNumberGeneration(record) : null,
                    generatingNumber: col.dataIndex === 'transfer_id' && generatingNumbers.has(generationKey(record)),
                    onEnter: async (flag) => {
                        if (cargoSaveInFlightRef.current.has(record.uid)) return;
                        await save(record.uid);
                        if (cargoSaveInFlightRef.current.has(record.uid)) return;
                        focusFlag = flag;
                        const index = cargoData.findIndex((item) => record.uid === item.uid);
                        if (index > -1 && index < cargoData.length - 1) {
                            edit(cargoData[index + 1]);
                        }
                    },
                    onBlur: async (e) => {
                        // 当点击了当前行的任意一个输入框（className里带有myEditableCellInputIdToAvoidBlur），
                        // 则跳过保存以及取消编辑当前行
                        if (e.relatedTarget
                            && e.relatedTarget.className.includes('myEditableCellInputIdToAvoidBlur')) {
                            return;
                        }
                        await save(record.uid);
                    },
                    onClick: () => {
                        if (!fieldEditable) return;
                        edit(record);
                    }
                }
            },
        };
    });
    // 从订单移除包裹（仅解绑，不删除包裹）
    const handleDeleteCargo = async (records) => {
        if (!editPolicy.box_membership) {
            messageX.warning('当前订单不允许新增、移除、分配或解绑箱子');
            return;
        }
        if (!verify()) {
            message.error('密码错误！');
            return;
        }

        const record_ids = records
            .map((r) => (typeof r === 'string' ? r : (r?.uid || r?.key)))
            .filter(Boolean);

        if (record_ids.length === 0) {
            messageX.warning('未找到可移除的包裹');
            return;
        }
        if (cargoData.some(record => record_ids.includes(record.uid) && cargoRemovalBlocked(record))) {
            messageX.warning(removalBlockedMessage);
            return;
        }

        const result = await (await fetch(`${endpoint}/cargo/unbind`, {
            headers: getSafeHeader(),
            body: JSON.stringify({ cargo_id_list: record_ids }),
            method: 'POST'
        })).json();
        if (result.code !== 200) {
            messageX.error(result.msg || '移除包裹失败');
            return;
        }

        // 更新页面：移除当前订单列表中已解绑包裹
        const successIds = result.data?.success || [];
        setCargoData(prevState => prevState.filter(item => !successIds.includes(item.key)));
        setSelectedKeys(prevState => prevState.filter(key => !successIds.includes(key)));

        messageX.success(`已从订单移除 ${successIds.length} 个包裹`);
        await markVersionChanged();
    }

    const handleUndoOutbound = async record => {
        if (!canUndoOutbound || undoingCargoUid) return;
        setUndoingCargoUid(record.uid);
        try {
            const response = await fetch(`${endpoint}/cargo/${record.uid}/undo-outbound`, { method: 'POST', headers: getSafeHeader() });
            const result = await response.json();
            if (!response.ok || result.code !== 200) throw new Error(result.msg || '撤销出库失败');
            messageX.success('已撤销出库，现在可以移除包裹');
            await fetchCargoData();
            await markVersionChanged();
        } catch (error) {
            messageX.error(error.message || '撤销出库失败');
        } finally {
            setUndoingCargoUid(null);
        }
    };

    const [count, setCount] = useState(1);//包装箱添加计数
    const handleAdd = async () => {
        if (!editPolicy.box_membership) {
            messageX.warning('当前订单不允许新增箱子');
            return;
        }
        // console.log(descriptionData)
        if (!descriptionData.order_id) {
            message.error("请先补充订单号");
            return
        }
        // console.log(count);
        const result = await (await fetch(`${endpoint}/orders/${order_id}/add_cargo`, {
            headers: getSafeHeader(),
            body: JSON.stringify({ cargo_count: count }),
            method: 'POST'
        })).json()
        if (result.code !== 200) {
            messageX.error(result.msg || '添加包裹失败');
            return;
        }
        const { data } = result;
        setCount(1);
        const data_with_key = data.map(r => ({ ...r, key: r.uid }));
        setCargoData(prevState => [...prevState, ...data_with_key]);
        // download
        // window.open(`${endpoint}/cargo/pdf/${cargo_id_list.join('_')}`);
        message.success('添加成功！');
        await markVersionChanged();
        // window.location.reload();
    }

    // 批量查询进度
    const handleQueryLogistics = () => {
        if (selectedKeys.length > 40) {
            message.error("查询订单量过多！");
            return;
        }
        const table = {}
        for (let d in cargoData) {
            table[cargoData[d]['key']] = cargoData[d];
        }
        console.log(table);
        const queryParams = selectedKeys.map(key => table[key]['waybill_id']);
        console.log(queryParams);
        window.open(`https://t.17track.net/zh-cn#nums=${queryParams.join(',')}`);

    }

    // 选择打印
    // 打印
    const handlePrint = () => {
        window.open(`${endpoint}/cargo/pdf/${selectedKeys.join('_')}`);
    }

    const [TransportationEditing, setTransportationEditing] = useState("")

    return (
        <>
            {messageComponent}
            <Space style={{ marginBottom: '2rem', width: '100%', justifyContent: 'space-between' }} align="center" wrap>
                <Space align="center" wrap>
                    <Typography.Title level={4}>订单详情/Order Detail</Typography.Title>
                    {/* {descriptionData.current_version > 0 && <Tag color="blue">V{descriptionData.current_version}</Tag>} */}
                </Space>
                <Space align="center" wrap>
                    {canViewOrderHistory && (
                        <Button type={"text"} icon={<HistoryOutlined />} onClick={() => setHistoryOpen(true)}>
                            修改历史
                        </Button>
                    )}
                </Space>
            </Space>
            <div>
                <Space style={{ marginBottom: '1rem' }} align="center" wrap size="small">
                    <Typography.Text strong>业务员：</Typography.Text>
                    {!salesmanEditing ? (
                        <Tooltip
                            title={salesman ? `${salesman.name || '-'}${salesman.phone ? ` / ${salesman.phone}` : ''}` : '未分配'}
                            styles={{ body: fieldTooltipStyle }}
                        >
                            <Input
                                readOnly
                                style={{ width: 240, height: 32 }}
                                value={salesman ? `${salesman.name || '-'}${salesman.phone ? ` / ${salesman.phone}` : ''}` : '未分配'}
                            />
                        </Tooltip>
                    ) : (
                        salesmanOptions.length > 0 ? (
                            <Select
                                style={{ width: 240 }}
                                size="middle"
                                placeholder="选择业务员"
                                loading={salesmanUsersLoading || salesmanLoading}
                                value={salesmanEditorValue}
                                onChange={(value) => setSalesmanEditorValue(value)}
                                options={salesmanOptions}
                            />
                        ) : (
                            <InputNumber
                                min={1}
                                placeholder="输入业务员ID"
                                style={{ width: 240, height: 32 }}
                                value={salesmanEditorValue}
                                onChange={(value) => setSalesmanEditorValue(value)}
                            />
                        )
                    )}
                    {canEditSalesman && !salesmanEditing && (
                        <Button
                            size="middle"
                            onClick={() => {
                                setSalesmanEditorValue(salesman?.id ?? undefined);
                                setSalesmanEditing(true);
                            }}
                        >
                            编辑
                        </Button>
                    )}
                    {canEditSalesman && salesmanEditing && (
                        <Button size="middle" type="primary" loading={salesmanSaving}
                            onClick={() => handleSaveSalesman(salesmanEditorValue)}>保存</Button>
                    )}
                    {canEditSalesman && salesmanEditing && (
                        <Button size="middle" onClick={() => {
                            setSalesmanEditorValue(salesman?.id ?? undefined);
                            setSalesmanEditing(false);
                        }}>取消</Button>
                    )}
                    {canEditSalesman && salesmanEditing && (
                        <Button size="middle" danger loading={salesmanSaving}
                            onClick={handleRemoveSalesman}>移除</Button>
                    )}
                    {canQuote && !salesmanEditing && (
                        <Button data-tour="quote-entry" size="middle" type="primary" icon={<DollarOutlined />} onClick={openQuoteModal}>
                            报价
                        </Button>
                    )}
                    {canCollect && !salesmanEditing && (
                        <OrderReceiptButton
                            key={order_id}
                            orderUid={order_id}
                            orderNumber={descriptionData.order_id}
                            customerId={descriptionData.customer_ids?.[0] || descriptionData.customer_id}
                            customerName={descriptionData.customer_name}
                        />
                    )}
                    {canQuote && !salesmanEditing && (
                        <FeatureTour
                            chapter={quoteTourChapter}
                            steps={quoteTourSteps}
                            autoSteps={quoteTourSteps}
                            manualSteps={quoteManualTourSteps}
                            eligible={canQuote}
                            autoEnabled={false}
                            forceAutoStart={forceQuoteTour}
                            onStart={(mode) => {
                                if (mode === 'auto') {
                                    saveFeatureTourFlow({
                                        userId: tourUserId,
                                        campaignId: COST_QUOTE_RECEIPT_TOUR.id,
                                        stage: 'quote',
                                    });
                                }
                            }}
                            onStepChange={handleQuoteTourStepChange}
                            onTourEnd={(status, mode) => {
                                setQuoteModalOpen(false);
                                if (mode !== 'auto') return;
                                if (status === 'completed') {
                                    saveFeatureTourFlow({
                                        userId: tourUserId,
                                        campaignId: COST_QUOTE_RECEIPT_TOUR.id,
                                        stage: 'receipt-entry',
                                    });
                                    navigate('/receipts');
                                } else {
                                    clearFeatureTourFlow(tourUserId);
                                }
                            }}
                            triggerAriaLabel="打开报价操作引导"
                        />
                    )}
                </Space>
            </div>
            <Modal
                title={`订单报价 ${descriptionData?.order_id || ''}`}
                open={quoteModalOpen}
                onCancel={() => setQuoteModalOpen(false)}
                onOk={submitQuote}
                confirmLoading={quoteSubmitting}
                okText="提交报价"
                cancelText="取消"
                width={760}
                okButtonProps={{ 'data-tour': 'quote-submit' }}
            >
                <Form form={quoteForm} layout="vertical">
                    <Descriptions data-tour="quote-summary" size="small" bordered style={{ marginBottom: 16 }}>
                        <Descriptions.Item label="当前运输方式">
                            {currentTransportation || '-'}
                        </Descriptions.Item>
                        <Descriptions.Item label="最低单价">
                            {currentMinPrice.toFixed(4)} CNY/kg
                        </Descriptions.Item>
                        <Descriptions.Item label="当前总重">
                            {currentQuoteWeight.toFixed(3)} kg
                        </Descriptions.Item>
                        <Descriptions.Item label="计费重量">
                            {currentBillingWeight} kg
                        </Descriptions.Item>
                        <Descriptions.Item label="应收账款">
                            <Typography.Text strong>{displayedQuoteReceivable.toFixed(2)} CNY</Typography.Text>
                        </Descriptions.Item>
                    </Descriptions>
                    <div data-tour="quote-pricing">
                        <Form.Item name="unit_price" label="每公斤单价 (CNY/kg)" rules={[{ required: true, message: '请输入每公斤单价' }]}>
                            <InputNumber min={0} precision={4} style={{ width: '100%' }} />
                        </Form.Item>
                        <Form.Item name="surcharge" label="附加费 (CNY)" rules={[{ required: true, message: '请输入附加费' }]}>
                            <InputNumber min={0} precision={2} style={{ width: '100%' }} />
                        </Form.Item>
                        <Form.Item name="quote_remark" label="报价说明">
                            <Input.TextArea rows={3} />
                        </Form.Item>
                    </div>
                </Form>
                <Space style={{ marginBottom: 12 }}>
                    <Typography.Text type={finalQuote ? 'success' : 'secondary'}>
                        {finalQuote
                            ? `${finalQuote.is_effective ? '当前有效报价' : '当前报价需重报'}：${Number(finalQuote.unit_price || 0).toFixed(4)} CNY/kg + ${Number(finalQuote.surcharge || 0).toFixed(2)} CNY，应收 ${Number(finalQuote.receivable_amount || 0).toFixed(2)} CNY`
                            : '暂无最终采纳报价'}
                    </Typography.Text>
                    <Button
                        icon={<PrinterOutlined />}
                        disabled={!finalQuote}
                        loading={quotePdfPrinting}
                        onClick={handlePrintQuotePdf}
                    >
                        打印报价单
                    </Button>
                </Space>
                <div data-tour="quote-history">
                    <Typography.Title level={5}>报价版本</Typography.Title>
                    <Table
                        size="small"
                        rowKey="id"
                        dataSource={quoteHistory}
                        pagination={false}
                        columns={[
                            { title: '版本', dataIndex: 'version_no', key: 'version_no', width: 70 },
                            { title: '渠道', dataIndex: 'transportation_name', key: 'transportation_name' },
                            { title: '单价', dataIndex: 'unit_price', key: 'unit_price', width: 100, render: v => Number(v || 0).toFixed(4) },
                            { title: '附加费', dataIndex: 'surcharge', key: 'surcharge', width: 90, render: v => Number(v || 0).toFixed(2) },
                            { title: '重量', dataIndex: 'weight_snapshot', key: 'weight_snapshot', width: 90, render: v => Number(v || 0).toFixed(3) },
                            { title: '应收', dataIndex: 'receivable_amount', key: 'receivable_amount', width: 100, render: v => Number(v || 0).toFixed(2) },
                            { title: '最低p', dataIndex: 'min_price', key: 'min_price', width: 90, render: v => Number(v || 0).toFixed(4) },
                            {
                                title: '状态', dataIndex: 'validity_status', key: 'validity_status', width: 110,
                                render: v => <Tag color={v === 'effective' ? 'green' : v === 'rejected' ? 'red' : 'blue'}>{({ effective: '有效', pending: '待审核', rejected: '已驳回', superseded: '已替代' })[v] || v}</Tag>
                            },
                            { title: '报价人', dataIndex: 'quoter_name', key: 'quoter_name', width: 100 },
                        ]}
                    />
                </div>
            </Modal>
            <Descriptions style={{ marginBottom: '2rem' }} bordered>
                {orderProperty.map((v, k) => {
                    const handleDescriptionDataChange = async (val) => {
                        if (descriptionData[v.name] === val) return;
                        //权限
                        if (!verify()) {
                            message.error('密码错误！');
                            return false;
                        }
                        //预检查
                        if (v.name === 'total_weight' && isNaN(val)) {
                            messageX.warning(`${v.label}请输入数字`)
                            return;
                        }

                        const response = await fetch(`${endpoint}/orders/${order_id}`, {
                            headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
                            body: JSON.stringify({ [v.name]: val }),
                            method: 'PUT'
                        });
                        const result = await response.json();
                        if (!response.ok || result.code !== 200) {
                            messageX.error(result.msg || result.message || `修改${v.label}失败`);
                            return false;
                        }
                        messageX.success(`修改${v.label}成功`);
                        setDescriptionData(prevState => ({ ...prevState, [v.name]: val }));
                        await markVersionChanged();
                        return true;
                    }

                    const beginSpecialFieldEdit = () => {
                        if (!canEditOrderField(v.name)) return;
                        const value = descriptionData[v.name] || '';
                        specialFieldDraftRef.current = value;
                        setSpecialFieldDraft(value);
                        setTransportationEditing(v.name);
                    };
                    const updateSpecialFieldDraft = (value) => {
                        specialFieldDraftRef.current = value;
                        setSpecialFieldDraft(value);
                    };
                    const commitSpecialFieldEdit = async () => {
                        if (specialFieldCommitRef.current) return;
                        specialFieldCommitRef.current = true;
                        setTransportationEditing('');
                        try {
                            await handleDescriptionDataChange(specialFieldDraftRef.current);
                        } finally {
                            specialFieldCommitRef.current = false;
                        }
                    };

                    if (v.name === 'order_id') {
                        const generating = generatingNumbers.has(generationKey());
                        const saveOrderNumber = async () => {
                            if (numberGenerationInFlightRef.current.has(generationKey()) || orderNumberSaving) return;
                            setOrderNumberEditing(false);
                            setOrderNumberSaving(true);
                            try {
                                await handleDescriptionDataChange(orderNumberDraft.trim());
                            } finally {
                                setOrderNumberSaving(false);
                            }
                        };
                        return (
                            <Descriptions.Item key={k} span={v.span || 1} label={v.label.split('/')[0]}>
                                <Space wrap>
                                    {orderNumberEditing ? (
                                        <Input
                                            autoFocus
                                            aria-label="订单号"
                                            value={orderNumberDraft}
                                            readOnly={generating}
                                            disabled={orderNumberSaving}
                                            onChange={event => setOrderNumberDraft(event.target.value)}
                                            onPressEnter={saveOrderNumber}
                                            onBlur={event => {
                                                if (event.relatedTarget?.closest('.myEditableCellInputIdToAvoidBlur')) return;
                                                saveOrderNumber();
                                            }}
                                            onKeyDown={event => {
                                                if (event.key === 'Escape') setOrderNumberEditing(false);
                                            }}
                                        />
                                    ) : (
                                        <DetailText
                                            copyable={!!descriptionData.order_id}
                                            editable={!canEditOrderField(v.name) || generating || orderNumberSaving ? false : {
                                                onStart: () => {
                                                    setOrderNumberDraft(descriptionData.order_id || '');
                                                    setOrderNumberEditing(true);
                                                },
                                            }}
                                        >{descriptionData.order_id}</DetailText>
                                    )}
                                    {orderNumberEditing && canGenerateNumbers && canEditOrderField(v.name) && (
                                        <Tooltip title="随机生成并保存订单号">
                                            <Button
                                                type="text"
                                                size="small"
                                                icon={<ReloadOutlined />}
                                                aria-label="生成订单号"
                                                className="myEditableCellInputIdToAvoidBlur"
                                                loading={generating}
                                                disabled={generating || orderNumberSaving}
                                                onMouseDown={event => event.preventDefault()}
                                                onClick={() => generateNumber()}
                                            />
                                        </Tooltip>
                                    )}
                                </Space>
                            </Descriptions.Item>
                        );
                    }

                    if (v.name === 'transportation') {
                        return (
                            <Descriptions.Item key={k} span={v.span || 1} label={v.label.split('/')[0]}>
                                {TransportationEditing === 'transportation' && canEditOrderField(v.name) ? (
                                    <Transportation
                                        onEnter={commitSpecialFieldEdit}
                                        onBlur={commitSpecialFieldEdit}
                                        onChange={updateSpecialFieldDraft}
                                        defaultValue={specialFieldDraft}
                                    />
                                ) : (
                                    <DetailText
                                        copyable={!!descriptionData[v.name]}
                                        editable={canEditOrderField(v.name) ? { onStart: beginSpecialFieldEdit } : false}
                                    >
                                        {descriptionData[v.name]}
                                    </DetailText>
                                )}
                            </Descriptions.Item>
                        );
                    }

                    if (v.name === 'post_code') {
                        return (
                            <Descriptions.Item key={k} span={v.span || 1} label={v.label.split('/')[0]}>
                                {TransportationEditing === 'post_code' && canEditOrderField(v.name) ? (
                                    <Select
                                        autoFocus
                                        showSearch
                                        allowClear
                                        loading={customsCodesLoading}
                                        value={descriptionData[v.name] || undefined}
                                        options={buildCustomsCodeOptions(customsCodes, '')}
                                        optionFilterProp="label"
                                        placeholder="输入品名搜索"
                                        style={{ width: '100%', minWidth: 0 }}
                                        popupMatchSelectWidth={false}
                                        onChange={(value) => {
                                            handleDescriptionDataChange(value || '');
                                            setTransportationEditing('');
                                        }}
                                        onBlur={() => setTransportationEditing('')}
                                        notFoundContent={customsCodesLoading ? '加载中...' : '未找到匹配的海关编码'}
                                    />
                                ) : (
                                    <DetailText
                                        copyable={!!descriptionData[v.name]}
                                        editable={canEditOrderField(v.name) ? {
                                            onStart: () => setTransportationEditing(v.name),
                                        } : false}
                                    >
                                        {descriptionData[v.name]}
                                    </DetailText>
                                )}
                            </Descriptions.Item>
                        );
                    }

                    return v.name === 'en_name' ? (
                        <Descriptions.Item style={TransportationEditing === 'en_name' ? { width: 300 } : {}} key={k} span={v.span || 1}
                            label={v.label.split('/')[0]}>
                            {TransportationEditing === 'en_name' && v.name === 'en_name' && canEditOrderField(v.name) ? (
                                <GoodInput onEnter={commitSpecialFieldEdit}
                                    onBlur={commitSpecialFieldEdit}
                                    onChange={updateSpecialFieldDraft}
                                    defaultValue={specialFieldDraft} />
                            ) : (
                                <>
                                    <DetailText
                                        copyable={!!descriptionData[v.name]}
                                        editable={canEditOrderField(v.name) ? {
                                            onStart: beginSpecialFieldEdit,
                                        } : false}>{descriptionData[v.name]}</DetailText>{descriptionData[v.name] &&
                                            <span>{v.name === 'total_weight' ? 'kg' : ''}</span>}
                                </>
                            )}
                        </Descriptions.Item>
                    ) : (
                        <Descriptions.Item key={k} span={v.span || 1} label={v.label.split('/')[0]}>
                            <DetailText
                                copyable={!!descriptionData[v.name]}
                                editable={!canEditOrderField(v.name) ? false : {
                                    onChange: handleDescriptionDataChange,
                                }}>{descriptionData[v.name]}</DetailText>{descriptionData[v.name] &&
                                    <span>{v.name === 'total_weight' ? 'kg' : ''}</span>}
                        </Descriptions.Item>
                    )
                })}
                {canViewCustomerContact && (
                    <>
                        <Descriptions.Item label="客户手机号">
                            {customerContactLoading ? '加载中...' : (
                                <DetailText copyable={!!displayedCustomerContact.phone}>
                                    {displayedCustomerContact.phone || '-'}
                                </DetailText>
                            )}
                        </Descriptions.Item>
                        <Descriptions.Item label="客户微信">
                            {customerContactLoading ? '加载中...' : (
                                <DetailText copyable={!!displayedCustomerContact.wechat}>
                                    {displayedCustomerContact.wechat || '-'}
                                </DetailText>
                            )}
                        </Descriptions.Item>
                    </>
                )}
            </Descriptions>
            <Typography.Title level={4} style={{ marginBottom: '2rem' }}>包裹详情/Cargo Detail</Typography.Title>
            <Typography.Title level={5}>添加包装箱</Typography.Title>
            <Space size='small' style={{ marginBottom: '2rem' }} align={'center'}>
                <InputNumber value={count} onChange={setCount} disabled={!editPolicy.box_membership} />
                <Button type={'primary'} onClick={handleAdd} disabled={!editPolicy.box_membership}>添加</Button>
                {canAssignBoxes && (
                    <Button
                        type={'default'}
                        icon={<InboxOutlined />}
                        disabled={!editPolicy.box_membership}
                        onClick={() => setBoxAssignmentVisible(true)}
                    >
                        从装箱单分配
                    </Button>
                )}
                <ExportButton selectedKeys={[descriptionData.uid]} onSuccess={() => setSelectedKeys([])}
                    selectedCargos={selectedKeys} data={[{ ...descriptionData, key: descriptionData.uid }]} />
                <Button onClick={handleQueryLogistics}>查询进度</Button>
                {selectedKeys.length > 0 && (
                    <Popconfirm
                        title={`批量移除 ${selectedKeys.length} 个包裹`}
                        description="确认将选中的包裹从当前订单移除吗？"
                        onConfirm={() => handleDeleteCargo(selectedKeys)}
                        disabled={!editPolicy.box_membership || selectedRemovalBlocked}
                        okText="确认移除"
                        cancelText="取消"
                    >
                        <Tooltip title={selectedRemovalBlocked ? '所选包裹包含已出库记录，请先撤销出库后再批量移除' : undefined}>
                            <span><Button danger icon={<DeleteOutlined />} disabled={!editPolicy.box_membership || selectedRemovalBlocked}>
                                批量移除（{selectedKeys.length}）
                            </Button></span>
                        </Tooltip>
                    </Popconfirm>
                )}
            </Space>

            {/* 箱子分配模态框 */}
            <BoxAssignmentModal
                visible={boxAssignmentVisible}
                onClose={() => setBoxAssignmentVisible(false)}
                customerId={descriptionData.customer_ids?.[0]}
                customerName={descriptionData.customer_name}
                orderUid={descriptionData.uid}
                onSuccess={(result) => {
                    message.success(`成功分配 ${result.success?.length || 0} 个箱子`);
                    fetchCargoData();
                    markVersionChanged();
                }}
            />

            <Form form={form} component={false}>
                <Table components={{ body: { cell: EditableCell } }} pagination={{ onChange: cancel }} dataSource={cargoData}
                    columns={mergedColumns}
                    onClick={console.log}
                    rowSelection={{
                        type: 'checkbox', onChange: (e) => {
                            setSelectedKeys(e);
                            console.log(e)
                        }, selectedRowKeys: selectedKeys
                    }}

                    scroll={{ y: 250 }} />
            </Form>
            <OrderHistoryDrawer
                open={historyOpen}
                onClose={() => setHistoryOpen(false)}
                orderUid={descriptionData.uid || order_id}
                orderId={descriptionData.order_id}
                customerName={descriptionData.customer_name}
                refreshKey={historyRefreshKey}
            />
        </>
    )

}
