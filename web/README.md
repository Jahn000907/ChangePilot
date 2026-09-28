# ChangePilot Web

智能工作台包含企业智能助手、多会话历史、供应商停产分析与物料替代评估。企业数据中心仍为只读。聊天建议仅预填可确认字段；正式工作流必须由员工补全信息并主动启动。

当前包含“智能工作台”和只读“企业数据中心”。

```powershell
npm install
npm run dev
```

API 默认地址为 `http://localhost:8000`。若需调整，请将 `.env.example` 复制为
`.env.local` 并设置 `VITE_API_BASE_URL`。
