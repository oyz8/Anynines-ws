# Anynines 平台

# ⭐ **觉得有用？给个 Star 支持一下！**
一键将 **代理服务 (VLESS/Trojan/Shadowsocks) + 哪吒监控 Agent** 部署到 [anynines](https://paas.anynines.com/) 云平台，自动生成订阅链接并打印节点信息。

## 📁 仓库结构

```
你的仓库/
├── .cfignore                # 排除 README.md
├── .github/
│   └── workflows/
│       └── deploy.yml       # GitHub Actions 工作流（自动部署）
├── app.py                   # 主程序（代理 + 哪吒线程）
├── index.html               # 首页（建议大家用Ai生成独一无二的静态html网页覆盖此文件）
├── manifest.yml             # Cloud Foundry 部署清单（不含敏感变量）
├── requirements.txt         # Python 依赖
└── README.md                # 说明文档（不会被上传）
```

---

## 🛠️ 使用步骤

### 第一步：Fork仓库

1. 点击本仓库右上角的 **Fork**  

### 第二步：配置 GitHub Secrets

进入仓库 `Settings` → `Secrets and variables` → `Actions`，点击 `New repository secret`，依次添加以下变量：

| 变量名                 | 示例值                             | 必填 | 说明                                                                               |
| ------------------- | ------------------------------- | -- | -------------------------------------------------------------------------------- |
| `CF_CREDENTIALS`         | `user@example.com-----mypassword123`               | ✅  | 你的 anynines 账号凭据，格式：`邮箱-----密码`（五个短横线分隔） |
| `SUB_PATH`  | 默认 `sub`   | ✅  | 订阅路径，请设置一个独一无二的 token    |
| `UUID`       | `c202b33e-03d9-406c-9bba-1ca228036028`| ✅  | 节点 UUID，建议使用 [uuidgenerator.net](https://www.uuidgenerator.net/) 生成  |
| `SERVER`  | `nezha.com:443`  | ❌  | 哪吒面板地址；不使用可留空  |
| `CLIENT_SECRET` | `NEZHA_KEY`| ❌  | 哪吒客户端密钥；不使用可留空  |
| `NAME`     | 默认 `Anynines`  | ❌  | 节点名称前缀  |
| `AUTO_ACCESS`     | 默认 `false` | ❌  | 是否开启自动访问保活，`true` 或 `false`  |
| `PRINT_NODE_INFO`     | 默认 `true` | ❌  | 是否在日志中显示订阅链接和节点配置，`true` 或 `false`  |


### 第三步：运行工作流并获取节点

1. 进入仓库 `Actions` 标签页  
2. 在左侧找到 **执行部署** 工作流，点击 `Run workflow` → `Run workflow` 手动触发  
3. 点击刚刚运行的 workflow，展开 `执行部署` 和 `打印节点信息` 步骤查看实时日志  

部署成功后，你会在日志末尾看到类似输出：

```
📡 订阅链接: https://app-xxxxc.de.a9sapp.eu/sub

==================== 节点配置（base64） ====================
dmxlc3M6Ly81YzNiMjWF6b24uY29t...

==========================================================
```

直接复制节点链接，导入到你的代理客户端即可使用。

---

**⚠️ 源代码来自老王**：[python-ws](https://github.com/eooce/python-ws)

**⚠️ 免责声明**：本脚本仅供学习交流使用，使用者需遵守 [anynines](https://www.anynines.com/) 的服务条款。因使用本脚本造成的任何问题，作者不承担任何责任。
