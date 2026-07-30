# Windows VTT pilot

本流程只處理最終輪廓編譯後的 Variable Font，不會改寫或取代正式的 unhinted build。
Pilot 字集為「日、田、國、圓」，先解決 9–16 PPEM 的框線、內白與橫豎畫一致性。

## 1. 取得固定輸入

1. 在 GitHub Actions 找到成功的 **Build font and release** run，記下網址末端的 run ID。
2. 確認組織已核准 VTT 授權後，手動執行 **Prepare Windows VTT pilot**，填入該 run ID、
   完整 head commit SHA，並勾選安裝與使用授權確認。PR build 預設拒絕，刻意使用時須
   另外確認。
3. 下載 `vtt-pilot-workspace-<run-id>` artifact。
4. 核對 `manifest.json`，不要重新命名或另行轉存輸入字型。

Workflow 使用具備 `self-hosted`、`Windows`、`X64`、`vtt` labels 的自有 Windows
10／11 runner，並綁定 `vtt-licensed` environment；repository 管理者必須先為該
environment 設定 required reviewers，讓每次執行都經人工核准。安裝腳本會實際檢查
Windows caption 與 x64 架構，不只信任 runner label。VTT 官方未將 GitHub hosted 的
Windows Server image 列為支援環境，也不應在未確認授權前將專有工具搬進第三方 hosted
runner。

Workflow 會從 Microsoft Download Center 下載 VTT 6.35 x64 MSI，驗證 Authenticode 與
固定 SHA-256，靜默安裝後執行 `vttshell.exe -?`。它不會上傳 MSI 或 VTT binaries。
`vttshell-help.txt` 是該次 runner 實際安裝版本的命令列契約，不以未驗證的網路範例代替。
`run-metadata.json` 另保存來源 workflow、run URL、event、branch 與 commit SHA。

## 2. 在 Windows VTT 編輯

1. 在 Windows 10／11 安裝
   [Microsoft Visual TrueType 6.35](https://www.microsoft.com/download/details.aspx?id=103335)。
2. 開啟 `KumamaruSans-wght-VTT-source.ttf`，保留原始 glyph order、point order、
   contours、components、advance width 與 variation axes。
3. 先建立 font program、pre-program、CVT 與 Variation CVT，再處理 `日田國圓`。
4. 每個 glyph 至少檢查 9、10、11、12、13、14、16 PPEM，以及 `wght` 100、400、700。
5. 儲存含 `TSI*` source tables 的 editable source；不要把它當成發行字型。

第一輪目標不是讓所有筆畫機械式等寬，而是：

- 外框上下左右的黑度穩定，不因 rounding 造成單邊突然加粗。
- 「日／田」內橫位置與 counter 分配在相鄰 PPEM 不跳動。
- 「國／圓」內外框不互相擠壓，Regular 之外的軸端仍可辨識。
- 不改動 outline 或 point order；outline 變動必須回到 unhinted source pipeline。

## 3. Contract gates

Editable source：

```powershell
python -m kumamaru.vtt_contract validate `
  --baseline .\KumamaruSans-wght-VTT-source.ttf `
  --font .\KumamaruSans-wght-VTT-editable.ttf `
  --stage source `
  --report .\vtt-source-report.json
```

先驗證 editable source，再以 VTTShell `-a` 編譯所有 programs、以 `-s` 只移除 VTT
source 並保留 compiled hints，最後驗證 delivery font：

```powershell
.\scripts\windows\compile-vtt.ps1 `
  -BaselineFont .\KumamaruSans-wght-VTT-source.ttf `
  -SourceFont .\KumamaruSans-wght-VTT-editable.ttf `
  -OutputFont .\build\vtt\KumamaruSans-wght-VTT-compiled.ttf
```

Compiled gate 會要求 `cvt `、`fpgm`、`prep`、Variable Font 的 `cvar`、四個 pilot glyph
的 bytecode，並拒絕所有 `TSI*`，包含已淘汰的 private source tables。兩個 stage 都會
比對完整 glyph order、cmap、metrics、variation tables、outline coordinates、on/off-curve
flags、components 與 point order。

腳本刻意不覆寫任何輸入或既有輸出。VTTShell 與 contract 先寫入同目錄的唯一暫存檔，
全部通過才發布；失敗會清除本次建立的暫存與半成品。成功後保留：

- `.with-source.ttf`：完成 `-a`、尚未執行 `-s` 的除錯中間檔。
- `.source-report.json`：editable source contract。
- `.compiled-report.json`：delivery contract 與 SHA-256。

## 4. A/B proof

將 compiled font 帶回專案後產生相同 matrix：

```bash
kumamaru raster-proof \
  --font build/vtt/KumamaruSans-wght-VTT-compiled.ttf \
  --variation wght=400 \
  --output build/raster-proof-vtt
```

同時保留 `build/raster-proof-unhinted`。Pilot 通過人工 A/B 與 Windows DirectWrite
檢視以前，不得接入 package／release。
