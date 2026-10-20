# 帳本 Ledger

把投資（台股、美股）和現金帳戶放在同一本帳裡的 Mac 桌面 app。交易用一行字記，報價和匯率自動抓，資料只存在本機。

## 需要

- macOS
- [uv](https://docs.astral.sh/uv/)（`brew install uv`）
- Node.js（`brew install node`）

## 安裝

```sh
git clone https://github.com/Nobby3190/Portfolio-Ledger.git
cd Portfolio-Ledger
./scripts/build_app.sh --install
```

會產生 `dist/帳本 Ledger.app` 並複製到「應用程式」。不加 `--install` 就只產生、不複製。

## 不打包直接執行

```sh
uv sync
npm --prefix frontend install
npm --prefix frontend run build
uv run portfolio-ledger
```

## 資料

資料庫在 `~/Library/Application Support/帳本 Ledger/data.db`，每次啟動自動備份到同資料夾的 `backups/`（保留 10 份）。
