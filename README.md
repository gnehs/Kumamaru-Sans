# 熊丸體（Kumamaru Sans）

熊丸體是以 IBM Plex Sans TC 為上游的保守、可稽核字型改造工具鏈。它只圓化明確的角與經確認的收筆，並盡量保存字面、骨架、度量與 OpenType 排版行為；不是全域模糊或圓角化工具。

外露筆端、外輪廓角與尖銳筆尖會圓化；筆畫交匯形成的內角與短肩則保持原樣，
避免十字與接筆被誤改成圓洞，同時保留一般 90° 外角的圓角。

目前只有 **Regular 靜態 TrueType（`glyf`）MVP**。完整 build 會處理 best
cmap 中每個不重複的 encoded glyph，並可由版本 tag 自動建立 GitHub Release；
不支援 OTF/CFF、Variable Font 或自動 hinting。所有輸出仍須逐字人工校對，
不可將自動 build 視為最終設計。

## 安裝

需 Python 3.11 以上：

```bash
python -m pip install -e '.[dev]'
kumamaru --help
```

本專案是 Python 工具鏈，未使用 npm 或 pnpm。

## 取得上游字型

請從 [IBM Plex 官方 repository](https://github.com/IBM/plex) 的 release 或官方 `@ibm/plex-sans-tc` 套件取得 IBM Plex Sans TC Regular，放到：

```text
vendor/IBMPlexSansTC-Regular.ttf
```

字型二進位檔刻意不納入版本控制；請勿使用第三方字型下載站。CLI 也接受任意本機 `--input` 路徑。

## 完整工作流程

候選分析與實際去腳必須分開。先做不套用 spur/flare 的安全預覽，再人工選取 candidate，最後重建與驗證。

1. 檢查輸入格式、表格、metadata 與 SHA-256。

   ```bash
   kumamaru inspect --input vendor/IBMPlexSansTC-Regular.ttf --output build/inspection.json
   ```

2. 分析 smoke glyph；只產生可重現的 corner、terminal 與 spur/flare candidate ID，不修改字型。

   ```bash
   kumamaru analyze --input vendor/IBMPlexSansTC-Regular.ttf \
     --glyphs config/glyphsets/smoke.txt --config config/regular.toml \
     --output build/analysis.json
   ```

3. 建置未套用任何去腳 candidate 的預覽字型並產生 proof。預設 `spur_detection.report_only = true`，所以 spur/flare 只會被報告。

   ```bash
   kumamaru build --input vendor/IBMPlexSansTC-Regular.ttf \
     --output build/KumamaruSans-preview.ttf --glyphs config/glyphsets/smoke.txt \
     --config config/regular.toml --overrides config/overrides.yaml \
     --report build/preview-report.json
   kumamaru proof --before vendor/IBMPlexSansTC-Regular.ttf \
     --after build/KumamaruSans-preview.ttf --glyphs config/glyphsets/smoke.txt \
     --analysis build/analysis.json --build-report build/preview-report.json \
     --output build/proof-preview
   ```

   在 `build/proof-preview/index.html` 比對原版、修改版、疊圖、輪廓索引與 candidate ID。

4. 人工確認後才在 `config/overrides.yaml` 套用 candidate。必須從 `analysis.json` 或 proof 複製實際 ID，不能猜測 ID。

   ```yaml
   glyphs:
     U+500B:
       operations:
         - type: apply_terminal_candidate
           candidate_id: "<copy-the-exact-id-from-analysis>"
   ```

   ```bash
   kumamaru build --input vendor/IBMPlexSansTC-Regular.ttf \
     --output build/KumamaruSans-Regular.ttf --glyphs config/glyphsets/smoke.txt \
     --config config/regular.toml --overrides config/overrides.yaml \
     --report build/build-report.json
   kumamaru proof --before vendor/IBMPlexSansTC-Regular.ttf \
     --after build/KumamaruSans-Regular.ttf --glyphs config/glyphsets/smoke.txt \
     --analysis build/analysis.json --build-report build/build-report.json \
     --output build/proof
   ```

5. 驗證 glyph order、cmap、metrics、OpenType tables、shaping 與幾何限制。

   ```bash
   kumamaru validate --before vendor/IBMPlexSansTC-Regular.ttf \
     --after build/KumamaruSans-Regular.ttf --glyphs config/glyphsets/smoke.txt \
     --output build/validation.json
   ```

可使用 `make lint`、`make test`、`make smoke`、`make full`、`make validate`、`make validate-full`、`make fontbakery`、`make proof`。`smoke` 只修改測試字集；可安裝或發布的完整預覽必須使用 `full`，它會處理 best cmap 中每個不重複的 encoded glyph。缺少上游字型時，依賴它的 smoke/integration 工作應清楚跳過，不應下載替代字型。

## 「個」的去腳

「個」可能含有不適合圓體的腳或喇叭口，但不能以 Unicode 或肉眼規則直接刪除。先在 `analysis.json`／proof 找到 `U+500B` 的高信心 candidate，確認它不是結構性筆畫後，再把完整 `candidate_id` 寫入 override。重新 build 後，必須以疊圖檢查筆畫長度、洞口與鄰近結構。

候選偵測只輔助審查，不取代設計判斷。

## 為何不刪除所有鉤

鉤、挑、撇、捺與孤立點常承擔字形辨識與書寫方向。「心」、「水」、「我」、「成」的末端突出不等於黑體腳；一律移除會改變結構或破壞輪廓。因此預設只報告 spur/flare，並以 `config/glyphsets/hooks.txt` 保護高風險字；實際去腳須明確 override 或符合刻意設定的極高 confidence 門檻。

## 為何移除 hinting

TrueType hinting 指令引用 glyph 點索引；圓角與圓頭會增加、刪除或移動點，原指令可能因此失效。MVP 預設移除所有 glyph instructions 與相關 hinting tables，並在 build report 標示 unhinted，以避免混用有效和失效的 hinting。這是安全取捨，並不代表螢幕最佳化已完成。

## 授權與名稱

本 repository 的程式碼採 [MIT License](LICENSE)。工具所產生的 IBM Plex Sans TC 修改字型仍必須採 [SIL Open Font License 1.1](LICENSES/OFL-1.1.txt)，並保留上游 copyright、Reserved Font Name 宣告與 OFL 條文。上游歸屬與發行要求詳見 [LICENSES/UPSTREAM.md](LICENSES/UPSTREAM.md)。

IBM 已將 `Plex` 宣告為 Reserved Font Name。修改版本的使用者可見主要名稱、family、full name 與 PostScript name 均不得使用它，除非另有書面許可；輸出應為 `Kumamaru Sans`／`熊丸體`，且不得暗示 IBM 認可或背書本專案。

## 產物

可再生輸出位於 `build/`：inspection、analysis、build、validation JSON 與靜態 HTML/SVG proof。發行字型時，請連同 OFL 及上游 attribution 文件一起提供。

## GitHub Actions 建置與發行

`Build font and release` workflow 可由 Actions 頁面手動執行；它會從 IBM 官方
`@ibm/plex-sans-tc@1.1.1` release 下載固定版本的 hinted Regular TTF，驗證
archive 與 TTF 的 SHA-256，然後執行 lint、tests、inspect、analyze、build、
proof、validate 與 FontBakery。

手動 workflow 只上傳 30 天期 build artifact。推送與專案版本一致的
`MAJOR.MINOR.PATCH` tag（例如 `0.2.3`）時，workflow 會在 build 與核心
validation 通過後，自動建立公開 GitHub Release，並上傳：

- `KumamaruSans-Regular.ttf`
- `KumamaruSans-MAJOR.MINOR.PATCH.zip`
- `SHA256SUMS`

FontBakery 的完整 JSON 會放在 zip 與 Actions artifact 中；目前 unhinted MVP
可能有已知 FontBakery FAIL，因此不以 exclusion 隱藏結果。原始 IBM TTF 與
包含 `before.ttf` 的 proof 不會上傳。

```bash
git tag 0.2.3
git push origin 0.2.3
```

建立 release tag 前，請確認 `pyproject.toml`、`src/kumamaru/__init__.py` 與
`config/regular.toml` 的版本一致。建議在 GitHub repository 設定 tag ruleset，
限制誰可以建立 `0.*` release tags。
