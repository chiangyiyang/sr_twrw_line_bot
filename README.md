# sr_twrw_line_bot

## Docker 部署

1. 建立 `.env`（可沿用 `.env.example`）並設定 LINE Channel 憑證與資料庫相關環境變數，若需覆寫預設檔案路徑也可在此調整。
2. 執行下列指令建置並啟動服務：

   ```bash
   docker compose up --build
   ```

   預設會將本機的 `data/`、`storage/` 與 `static/` 掛載到容器中，並於 `PORT`（預設 8000）對外提供服務。

3. 若需停止：

   ```bash
   docker compose down
   ```

   如不需保留掛載資料，可視情況加上 `-v` 一併刪除相關 volume。

## Google 登入設定

1. 前往 [Google Cloud Console](https://console.cloud.google.com/) 建立 OAuth 2.0 Client ID（建議選擇「網頁應用程式」），並把 `http://localhost:8000/login.html` 與實際部署網址加入授權來源。
2. 在 `.env` 中設定：
   - `FLASK_SECRET_KEY`：Flask Session 用的簽章金鑰（務必改為隨機字串）。
   - `GOOGLE_CLIENT_ID`：步驟 1 取得的 Client ID。
   - `GOOGLE_ALLOWED_EMAILS`：允許登入的帳號（逗號分隔，可留空）。
   - `GOOGLE_ALLOWED_DOMAINS`：允許登入的網域（逗號分隔，可留空）。
   - `SESSION_COOKIE_SECURE`：若部署於 HTTPS/反向代理後方，請設為 `1`。
3. 重新啟動服務後，造訪 `/login.html` 以 Google 帳號登入；登入成功後才能開啟 `/events_admin.html`，並可使用事件的新增、編輯、刪除、匯出與匯入功能。

## 系統稽核日誌

- 服務會自動將 `/api/*`、`/auth/*` 與 `/callback` 等 HTTP 請求，以及 LINE 聊天互動寫入 `data/audit_logs.db`。可透過環境變數 `AUDIT_LOG_DB_PATH` 改寫儲存位置，或以 `AUDIT_LOG_ENABLED=0` 關閉。
- 新增 `/api/audit-logs` API（需登入）支援條件篩選、分頁、JSON/CSV 匯出，可於後台查核操作歷程。
- 報表後台（事件 CRUD、匯入匯出、照片上傳/刪除）與 Google 登入、LINE 回報事件等關鍵流程都會額外寫入動作明細（操作者、來源 IP、資源 ID、結果與摘要）。
- 新增受保護的 `/audit_logs.html` 頁面可視覺化瀏覽、匯出（JSON/CSV）與清除日誌，`events_admin.html` 頂部提供快速連結；清除功能會要求輸入 DELETE 並可選擇只刪除指定時間前的紀錄。
