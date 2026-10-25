import React from 'react';
import { createBrowserRouter } from "react-router-dom";
import App from "./App";
import NewOrder from "./pages/newOrder";
import OrderList from "./pages/orderList";
import OrderDetail from "./pages/orderDetail";
import Normal from "./pages/normal";
import UploadOrder from "./common/uploadOrder";
import Logs from "./pages/logs";
import Scanner from "./pages/scanner";
import Login from "./pages/login";
import AdminPage from "./pages/admin";
import StorageManagement from "./pages/storageManagement";
import CustomerManagement from "./pages/customerManagement";
import PackingListCreate from "./pages/packingListCreate";
import PackingListList from "./pages/packingListList";
import PackingListDetail from "./pages/packingListDetail";
import ForgetPassword from "./pages/forgetPassword";
import Settings from "./pages/settings";
import WorkDetails from "./pages/workDetails";
import BonusEstimate from "./pages/bonusEstimate";
import FinanceHub from "./pages/financeHub";
import CostManagement from "./pages/costManagement";
import AuditLogs from "./pages/auditLogs";
import Receipts from "./pages/receipts";
import { PaperIntakeUploadDetail } from "./pages/intakes";
import ShippingConfirmationDrafts from "./pages/shippingConfirmationDrafts";
import OrderExceptions from "./pages/orderExceptions";

// 移除 LogsRoute 组件，因为权限检查逻辑已经移到 Logs 组件内部

const router = createBrowserRouter([{
    path: '/', element: <App />, children: [{
        path: "", element: <NewOrder />, index: true
    }, {
        path: 'orders', element: <OrderList />
    }, {
        path: 'order-exceptions', element: <OrderExceptions />
    }, {
        path: 'orders/:order_id', element: <OrderDetail />
    }, {
        path: 'upload', element: <UploadOrder />
    }, {
        path: 'logs', element: <Logs />
    }, {
        path: 'admin', element: <AdminPage />
    }, {
        path: 'storage-management', element: <StorageManagement />
    }, {
        path: 'customers', element: <CustomerManagement />
    }, {
        path: 'packing-list/new', element: <PackingListCreate />
    }, {
        path: 'packing-lists', element: <PackingListList />
    }, {
        path: 'packing-lists/:uid', element: <PackingListDetail />
    }, {
        path: 'packing-list/upload/:uid', element: <PaperIntakeUploadDetail />
    }, {
        path: 'shipping-confirmation-drafts', element: <ShippingConfirmationDrafts />
    }, {
        path: 'shipping-confirmation-drafts/:uid', element: <ShippingConfirmationDrafts />
    }, {
        path: 'work-details', element: <WorkDetails />
    }, {
        path: 'bonus', element: <BonusEstimate />
    }, {
        path: 'bonus-estimate', element: <BonusEstimate />
    }, {
        path: 'finance', element: <FinanceHub />
    }, {
        path: 'receipts', element: <Receipts />
    }, {
        path: 'cost-management', element: <CostManagement />
    }, {
        path: 'settings', element: <Settings />
    }, {
        path: 'audit-logs', element: <AuditLogs />
    }]
}, {
    path: '/normal/:status', element: <Normal />,
}, {
    path: '/scan', element: <Scanner />
}, {
    path: 'login', element: <Login />
}, {
    path: 'forget_password', element: <ForgetPassword />
}]);

export default router;
