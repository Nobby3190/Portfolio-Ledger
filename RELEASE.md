# 發佈流程

從改版本號到測試者下載安裝的完整步驟。以下以 `2.2.0` 為例，換成實際版本。

## 一次性設定（只做一次）

### 1. GitHub CLI

```sh
brew install gh
gh auth login            # 選 GitHub.com → HTTPS → 用瀏覽器登入
```

### 2. 建立 repo 並推上去

```sh
cd ~/Desktop/個人事物相關/個人專案/Portfolio-Ledger
gh repo create Portfolio-Ledger --public --source=. --push \
  --description "把台股、美股和現金帳戶記在同一本帳裡的 Mac 桌面 app：一行字記交易，報價和匯率自動抓，資料只存在本機。"
```

要給別人下載 Release，repo 用 Public 最簡單；若用 `--private`，得到 repo 的 Settings → Collaborators 把每位測試者加進來。

### 3. 改用 uv 管理的 Python 打包

Homebrew 的 Python 是針對本機 macOS 編的（目前 minos 26.0），打包後別人舊版 macOS 會打不開。改用 uv 的 Python（支援到 macOS 11 左右）：

```sh
uv python install 3.14
rm -rf .venv
uv venv --python-preference only-managed --python 3.14
uv sync
```

確認：`.venv/bin/python -c 'import sys; print(sys.base_prefix)'` 應該在 `~/.local/share/uv/python/` 底下，而不是 `/opt/homebrew`。

## 每次發版

### 1. 改版本號（三處）

- `pyproject.toml` → `version = "2.2.0"`（App 的 Info.plist 從這裡讀）
- `frontend/package.json` → `"version": "2.2.0"`
- `DESIGN.md` 開頭的「目前版本」

### 2. 測試

```sh
uv run pytest
npm --prefix frontend run typecheck
```

### 3. Commit、打 tag、推上 GitHub

```sh
git add -A
git commit -m "帳本 Ledger 2.2.0：<這版重點>"
git tag v2.2.0
git push && git push --tags
```

### 4. 打包

```sh
./scripts/build_app.sh
```

檢查最低 macOS 版本（應該是 11.x，**不是** 26.0）：

```sh
vtool -show-build "dist/帳本 Ledger.app/Contents/Frameworks/Python.framework/Versions/3.14/Python" | grep minos
```

自己先開一次 `dist/帳本 Ledger.app` 確認能正常啟動。

### 5. 壓縮

一定要用 `ditto`；Finder 的「壓縮」或 `zip` 可能弄壞簽章。

```sh
ditto -c -k --keepParent "dist/帳本 Ledger.app" Ledger-2.2.0-arm64.zip
```

### 6. 建立 Release

```sh
gh release create v2.2.0 Ledger-2.2.0-arm64.zip \
  --title "帳本 Ledger 2.2.0" \
  --notes-file release-notes.md
rm Ledger-2.2.0-arm64.zip
```

`release-notes.md` 每次寫一份（不用 commit），內容 = 這版改了什麼 + 下面的「安裝說明」整段。

想先自己看過再公開，加 `--draft`，到 GitHub 網頁上按 Publish。

### 7. 傳連結給測試者

```
https://github.com/<帳號>/Portfolio-Ledger/releases/latest
```

請他們在 repo 的 **Issues** 回報問題，附上 macOS 版本和截圖。

## 安裝說明（貼進 Release notes）

```markdown
## 安裝

需要 Apple Silicon（M1 以後）的 Mac，macOS 13 以上。不需要另外安裝 Python 或任何東西。

1. 下載下方的 `Ledger-x.y.z-arm64.zip`，解壓縮，把「帳本 Ledger」拖進「應用程式」
2. 第一次打開會被 macOS 擋下（App 沒有 Apple 開發者簽章）。打開「終端機」貼上：

       xattr -cr "/Applications/帳本 Ledger.app"

   之後就能正常開啟。
   （或：先開一次 → 系統設定 → 隱私權與安全性 → 拉到底按「強制打開」）

更新：下載新版，直接覆蓋「應用程式」裡的舊版，資料會保留。

資料只存在你自己的電腦：`~/Library/Application Support/帳本 Ledger/`，每次啟動自動備份到同資料夾的 `backups/`。
```

## 已知限制

- **只支援 Apple Silicon**：`build_app.sh` 只產生 arm64。Intel Mac 無法執行。
- **沒有正式簽章**：只有 ad-hoc 簽章，所以測試者要多做上面第 2 步。要免除這步需加入 Apple Developer Program（US$99/年），用 Developer ID 簽章並送 notarization。
