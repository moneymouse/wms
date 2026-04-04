# Frontend 前端模块

## 功能概述
前端模块存放前端静态资源文件，包括HTML、CSS、JavaScript等。为WMS系统提供用户界面。

## 目录结构

### static/
静态资源目录，包含：
- JavaScript文件
- CSS样式文件
- 图片资源
- 字体文件
- 其他前端静态资源

## 集成方式
- Flask应用配置 `static_folder="frontend/static"`
- 通过Flask的静态文件服务提供前端资源
- 前后端通过RESTful API通信

## 技术栈
前端使用标准的Web技术栈，与Flask后端通过HTTP API交互。
