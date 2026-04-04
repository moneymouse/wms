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
import CustomerManagement from "./pages/customerManagement";

// 移除 LogsRoute 组件，因为权限检查逻辑已经移到 Logs 组件内部

const router = createBrowserRouter([{
    path: '/', element: <App />, children: [{
        path: "", element: <NewOrder />, index: true
    }, {
        path: 'orders', element: <OrderList />
    }, {
        path: 'orders/:order_id', element: <OrderDetail />
    }, {
        path: 'upload', element: <UploadOrder />
    }, {
        path: 'logs', element: <Logs />
    }, {
        path: 'admin', element: <AdminPage />
    }, {
        path: 'customers', element: <CustomerManagement />
    }]
}, {
    path: '/normal/:status', element: <Normal />,
}, {
    path: '/scan', element: <Scanner />
}, {
    path: 'login', element: <Login />
}]);

export default router;