# sr_twrw_line_bot

## Docker 部署

1. 建立 `.env`（可沿用 `.env.example`）設定 LINE Channel 相關變數與資料庫環境變數（若需要覆寫預設路徑）。
2. 執行下列指令建置並啟動：

```bash
docker compose up --build
```

> 預設會將本機 `data/`、`storage/` 與 `static/` 掛載到容器中，並在 `PORT`（預設 8000）提供服務。

3. 如需停止：

```bash
docker compose down
```

可選擇加入 `-v` 一併刪除掛載 volume（若不需要保留資料）。***
