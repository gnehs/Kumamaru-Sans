# 熊丸體（Kumamaru Sans）

> **開發中（Work in Progress）**  
> 熊丸體仍在積極開發與人工校對中。目前產物僅供預覽與測試，**請勿視為可正式上線的成品字型**。字形品質、字集覆蓋與細節都會持續變動，自動 build 結果也需要人工審查。

熊丸體是以 [IBM Plex Sans TC](https://github.com/IBM/plex) 為上游的保守、可稽核字型改造。它只圓化明確的外角與經確認的收筆，並盡量保存字面、骨架、度量與 OpenType 行為；不是全域模糊或圓角化工具。

目前僅有 **Regular 靜態 TrueType（`glyf`）MVP**。不支援 OTF/CFF、Variable Font 或自動 hinting。

## 下載預覽字型（GitHub Actions）

正式 Release 尚未穩定釋出時，可從 CI 的 build artifact 取得最新預覽檔：

1. 開啟 [Actions → Build font and release](https://github.com/gnehs/Kumamaru-Sans/actions/workflows/build-release.yml)
2. 點選最新一次 **成功（綠色 ✓）** 的 run
3. 頁面底部 **Artifacts** 下載 build artifact（通常保留約 30 天）
4. 解壓後取得 `KumamaruSans-Regular.ttf` 等產物

注意：

- 下載 artifact 需要登入 GitHub，且你必須能存取此 repository
- Artifact 是自動化產物，**尚未等同人工校對完成的正式版**
- 若推送了版本 tag（例如 `0.2.3`）且 build 通過，也會在 [Releases](https://github.com/gnehs/Kumamaru-Sans/releases) 提供 TTF／zip／`SHA256SUMS`

也可在 Actions 頁面以 **Run workflow** 手動觸發建置。

## 授權與名稱

- 本 repository 程式碼：[MIT License](LICENSE)
- 產生的修改字型：[SIL Open Font License 1.1](LICENSES/OFL-1.1.txt)  
  詳見 [LICENSES/UPSTREAM.md](LICENSES/UPSTREAM.md)

IBM 已將 `Plex` 宣告為 Reserved Font Name。輸出名稱應為 `Kumamaru Sans`／`熊丸體`，不得使用 `Plex`，也不得暗示 IBM 認可或背書本專案。

## 本地開發

需 Python 3.11+：

```bash
python -m pip install -e '.[dev]'
kumamaru --help
```

### 取得上游字型

從 [IBM Plex 官方 repository](https://github.com/IBM/plex) 的 release 或 `@ibm/plex-sans-tc` 取得 IBM Plex Sans TC Regular，放到：

```text
vendor/IBMPlexSansTC-Regular.ttf
```

字型二進位不納入版本控制；請勿使用第三方字型下載站。

### 建置與驗證

候選分析與實際去腳必須分開：先預覽，再人工選取 candidate，最後重建與驗證。

```bash
# 檢查輸入
kumamaru inspect --input vendor/IBMPlexSansTC-Regular.ttf --output build/inspection.json

# 分析（不修改字型）
kumamaru analyze --input vendor/IBMPlexSansTC-Regular.ttf \
  --glyphs config/glyphsets/smoke.txt --config config/regular.toml \
  --output build/analysis.json

# 建置與 proof
kumamaru build --input vendor/IBMPlexSansTC-Regular.ttf \
  --output build/KumamaruSans-Regular.ttf --glyphs config/glyphsets/smoke.txt \
  --config config/regular.toml --overrides config/overrides.yaml \
  --report build/build-report.json

kumamaru proof --before vendor/IBMPlexSansTC-Regular.ttf \
  --after build/KumamaruSans-Regular.ttf --glyphs config/glyphsets/smoke.txt \
  --analysis build/analysis.json --build-report build/build-report.json \
  --output build/proof

# 驗證
kumamaru validate --before vendor/IBMPlexSansTC-Regular.ttf \
  --after build/KumamaruSans-Regular.ttf --glyphs config/glyphsets/smoke.txt \
  --output build/validation.json
```

常用 Make 目標：`make lint`、`make test`、`make smoke`、`make full`、`make validate`、`make validate-full`、`make fontbakery`、`make proof`。

- `smoke`：只處理測試字集  
- `full`：處理 best cmap 中每個不重複的 encoded glyph（可安裝預覽應以此為準）

缺少上游字型時，相依的 smoke／integration 應跳過，不應下載替代字型。

### 去腳與鉤的原則

- **「個」等字的去腳**：須從 `analysis.json`／proof 複製真實 `candidate_id` 寫入 `config/overrides.yaml`，不可猜測 ID；重建後用疊圖檢查。
- **不預設刪除所有鉤**：鉤、挑、撇、捺與孤立點常影響辨識；預設只報告 spur/flare，高風險字見 `config/glyphsets/hooks.txt`。
- **移除 hinting**：圓角會改變點索引，原 TrueType instructions 可能失效；MVP 預設移除 hinting 並標示 unhinted。

### 發行 tag

推送與專案版本一致的 `MAJOR.MINOR.PATCH` tag 時，workflow 會在驗證通過後建立 GitHub Release：

```bash
git tag 0.2.3
git push origin 0.2.3
```

請先確認 `pyproject.toml`、`src/kumamaru/__init__.py` 與 `config/regular.toml` 版本一致。

## 產物

可再生輸出位於 `build/`（inspection、analysis、build、validation JSON 與 HTML/SVG proof）。發行時請連同 OFL 與上游 attribution 一併提供。原始 IBM TTF 與含 `before.ttf` 的 proof 不會上傳至 Actions artifact／Release。
