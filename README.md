# Getting Started with Create React App

## 创建订单地址解析

在创建订单的“详细地址”输入框粘贴完整收件地址后，点击下方“解析地址”，后端通过 DeepSeek Function Calling 提取固定结构的国家二字码、邮编、省/州、城市，以及文本中明确包含的收件人、电话和邮箱。国家名称拼写会结合地址上下文修正，例如将 `SPIAN` 识别为 `SPAIN` 并返回 `ES`；前端将 `ES` 映射为现有的 `SPAIN` 国家选项。解析结果不返回详细地址，前端也忽略该字段，保留原输入的详细地址。缺失信息和解析期间手动修改的字段保留原值。成功修正和补全不产生警告；仅失败或结果存在歧义时显示简短处理提示。

后端用国家二字码和邮编调用 [API Ninjas Postal Code API](https://api-ninjas.com/api/postalcode)，将查询结果的 `city` 回填城市、`region` 回填 `province`（州/省），再返回前端保存表单草稿。包括美国地址在内，均使用该邮编接口。缺少国家或邮编、API 密钥未配置、查询失败或无匹配结果时，保留 DeepSeek 原始提取值，并显示简短原因。

同一邮编返回多条结果时，后端先按城市和 region 去重，比较时忽略大小写、空白和标点。优先选取与 DeepSeek 提取的城市匹配的唯一结果，必要时结合省/州进一步匹配；仍有歧义时保留原城市和省/州，仅在全部候选共享同一个非空 region 时回填该 region，并简短提示确认城市或省/州。

接口为 `POST /api/orders/parse-address`，沿用登录认证，返回的地址字段保持为 `country`、`province`、`city`、`zip_code`、`receiver`、`receiver_phone`、`mail` 和 `warnings`。配置只读取后端 `env.toml` 顶层的 `deepseek_api_key`、`deepseek_base_url`、`deepseek_model`、`deepseek_timeout_seconds` 和 `api_ninjas_api_key`，每次调用重新读取，不读取环境变量或后端 `.env`。DeepSeek 的默认值为：空密钥、`https://api.deepseek.com`、`deepseek-flash`、90 秒；空 DeepSeek 密钥禁用解析。`api_ninjas_api_key` 默认为空，未配置时仅跳过邮编补全并显示提示；邮编请求固定超时为 10 秒。新部署先在后端执行 `cp env.toml.example env.toml` 并填写密钥，Docker Compose 在运行时只读挂载，密钥只保存在后端。接口说明见后端 `doc/API-v1.15.md`。

## 手写装箱单

该功能使用正式系统的登录、路由和后端 API。进入“创建装箱单”后切换到“拍照上传纸质单”，可拍照、选图或下载 A4 空白模板。提交照片即可，补充信息均选填；上传成功后留在创建页继续操作。

操作人员在“我的装箱单”查看本人手动创建和拍照上传的记录。纸单显示“待核对”，确认后可查看正式装箱单。文员、业务员、店长和管理员从“装箱单列表”进入“待核对纸质单”，对照原图核对内容并绑定真实工人；确认时自动保存修改后生成装箱单。

开发使用 `npm start`，默认后端为 `http://localhost:5001/api`；正式构建使用 `npm run build`，默认后端为同源 `/api`。如需调整地址，使用 `REACT_APP_API_ENDPOINT`。无需独立预览服务、测试账号或预览数据库。

空白模板通过 `GET /api/intakes/template` 带登录鉴权下载，文件名为 `paper-packing-list-a4.pdf`。该请求和纸单上传都沿用系统的 `x-token`、`x-time` 认证头。

This project was bootstrapped with [Create React App](https://github.com/facebook/create-react-app).

## Available Scripts

In the project directory, you can run:

### `npm start`

Runs the app in the development mode.\
Open [http://localhost:3000](http://localhost:3000) to view it in your browser.

The page will reload when you make changes.\
You may also see any lint errors in the console.

### `npm test`

Launches the test runner in the interactive watch mode.\
See the section about [running tests](https://facebook.github.io/create-react-app/docs/running-tests) for more
information.

### `npm run build`

Builds the app for production to the `build` folder.\
It correctly bundles React in production mode and optimizes the build for the best performance.

The build is minified and the filenames include the hashes.\
Your app is ready to be deployed!

See the section about [deployment](https://facebook.github.io/create-react-app/docs/deployment) for more information.

### `npm run eject`

**Note: this is a one-way operation. Once you `eject`, you can't go back!**

If you aren't satisfied with the build tool and configuration choices, you can `eject` at any time. This command will
remove the single build dependency from your project.

Instead, it will copy all the configuration files and the transitive dependencies (webpack, Babel, ESLint, etc) right
into your project so you have full control over them. All of the commands except `eject` will still work, but they will
point to the copied scripts so you can tweak them. At this point you're on your own.

You don't have to ever use `eject`. The curated feature set is suitable for small and middle deployments, and you
shouldn't feel obligated to use this feature. However we understand that this tool wouldn't be useful if you couldn't
customize it when you are ready for it.

## Learn More

You can learn more in
the [Create React App documentation](https://facebook.github.io/create-react-app/docs/getting-started).

To learn React, check out the [React documentation](https://reactjs.org/).

### Code Splitting

This section has moved
here: [https://facebook.github.io/create-react-app/docs/code-splitting](https://facebook.github.io/create-react-app/docs/code-splitting)

### Analyzing the Bundle Size

This section has moved
here: [https://facebook.github.io/create-react-app/docs/analyzing-the-bundle-size](https://facebook.github.io/create-react-app/docs/analyzing-the-bundle-size)

### Making a Progressive Web App

This section has moved
here: [https://facebook.github.io/create-react-app/docs/making-a-progressive-web-app](https://facebook.github.io/create-react-app/docs/making-a-progressive-web-app)

### Advanced Configuration

This section has moved
here: [https://facebook.github.io/create-react-app/docs/advanced-configuration](https://facebook.github.io/create-react-app/docs/advanced-configuration)

### Deployment

This section has moved
here: [https://facebook.github.io/create-react-app/docs/deployment](https://facebook.github.io/create-react-app/docs/deployment)

### `npm run build` fails to minify

This section has moved
here: [https://facebook.github.io/create-react-app/docs/troubleshooting#npm-run-build-fails-to-minify](https://facebook.github.io/create-react-app/docs/troubleshooting#npm-run-build-fails-to-minify)
