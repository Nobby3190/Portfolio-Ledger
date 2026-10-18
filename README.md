# 帳本 Ledger

把投資（台股、美股）和現金帳戶放在同一本帳裡的 Mac 桌面 app。交易用一行字記，報價和匯率自動抓，資料只存在本機。

設計與規格見 [DESIGN.md](DESIGN.md)。

發佈到 GitHub 給別人下載：見 [RELEASE.md](RELEASE.md)。

打包：`./scripts/build_app.sh` 產生 `dist/帳本 Ledger.app`（加 `--install` 複製到「應用程式」）。Icon 由 `packaging/make_icon.py` 畫出，`./scripts/make_icon.sh` 轉成 `packaging/Ledger.icns`。

## 開發

```sh
uv sync
npm --prefix frontend install
npm --prefix frontend run build   # 輸出到 src/portfolio_ledger/ui
uv run portfolio-ledger
```

前端熱更新：`npm --prefix frontend run dev`，另一個終端機 `LEDGER_DEV_URL=http://localhost:5175 uv run portfolio-ledger`。

測試：`uv run pytest`、`npm --prefix frontend run typecheck`。

資料庫：`~/Library/Application Support/帳本 Ledger/data.db`，每次啟動自動備份到同資料夾的 `backups/`（保留 10 份）。
