# 開發文件

本文件說明熊丸體的預覽下載、授權、本地開發、建置、驗證與發行流程。

## 下載預覽字型（GitHub Actions）

正式 Release 尚未穩定釋出時，可從 build artifact 取得最新預覽檔。
`main` 每次 push、PR，以及手動 **Run workflow** 都會建置字型：

1. 開啟 [Actions → Build font and release](https://github.com/gnehs/Kumamaru-Sans/actions/workflows/build-release.yml)
2. 點選最新一次 **成功（綠色 ✓）** 的 run（確認對應 commit）
3. 頁面底部 **Artifacts** 下載 `kumamaru-sans-build`（通常保留約 30 天）
4. 解壓後可取得 8 個靜態 TTF、`KumamaruSans[wght].ttf`、完整 zip 與 `SHA256SUMS`

注意：

- 下載 artifact 需要登入 GitHub，且你必須能存取此 repository
- Artifact 是自動化產物，**尚未等同人工校對完成的正式版**
- 推送版本 tag（例如 `0.2.3`）且 build 通過時，另於 [Releases](https://github.com/gnehs/Kumamaru-Sans/releases) 提供 9 個單獨 TTF、完整 zip 與 `SHA256SUMS`

完整 zip 將字型分成 `Static/` 與 `Variable/`。兩者是同一個熊丸體 family 的不同發行格式；
請擇一安裝，不要同時安裝，以免靜態 Regular 與 Variable Font 的預設 Regular 發生重複。

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

常用 Make 目標：`make lint`、`make test`、`make smoke`、`make full`、`make validate`、
`make validate-full`、`make fontbakery`、`make proof`、`make source-inspect`、
`make source-round`、`make source-build-instances`、`make source-build-variable`、
`make source-fontbakery`。

- `smoke`：只處理測試字集
- `full`：處理 best cmap 中每個不重複的 encoded glyph（可安裝預覽應以此為準）

缺少上游字型時，相依的 smoke／integration 應跳過，不應下載替代字型。

### 多字重 Glyphs source 建置

IBM 在
[`@ibm/plex-sans-tc@1.1.1` release](https://github.com/IBM/plex/releases/tag/%40ibm/plex-sans-tc%401.1.1)
另附可編輯的 `sources.zip`。正式預覽 build 以其中的三個 master
（Thin／Regular／Bold）同步修改輪廓，避免把各字重獨立圓角後破壞插值相容性。

先安裝 source 額外依賴：

```bash
python -m pip install -e '.[source,dev]'
```

將官方壓縮檔解到下列預設位置；完整來源與衍生 `.glyphs` 都不納入版本控制：

```text
vendor/ibm-plex-sans-tc/sources/masters/IBM Plex Sans TC.glyphs
```

先用小字集快速檢查，再執行正式全字庫轉換：

```bash
# 檢查官方 source 身分、masters 與所選 glyph 的拓撲相容性
make source-inspect PYTHON=.venv/bin/python

# 對 smoke glyphs 在三個 masters 同步加入 cubic 圓角
make source-round-smoke PYTHON=.venv/bin/python

# 對全部 exporting glyphs 執行正式轉換
make source-round PYTHON=.venv/bin/python

# 用 fontmake 編出 Thin／Regular／Bold master TTF，供 proof 與差異研究
make source-build-masters PYTHON=.venv/bin/python

# 從三個 masters 內插並編出 8 個正式 instance
make source-build-instances PYTHON=.venv/bin/python

# 從同一組 masters 編出連續的 wght 100–700 Variable Font
make source-build-variable PYTHON=.venv/bin/python

# 驗證完整產物集合、metadata、fvar／STAT 與 release-critical FontBakery checks
python -m kumamaru.source_validation \
  build/source/instance-ttf \
  'build/source/variable-ttf/KumamaruSans[wght].ttf' \
  --config config/regular.toml
make source-fontbakery PYTHON=.venv/bin/python
```

Variable Font 會輸出到
`build/source/variable-ttf/KumamaruSans[wght].ttf`，預設位置為 Regular 400，
並保留 Thin、ExtraLight、Light、Regular、Text、Medium、SemiBold、Bold
八個 named instances。

也可直接使用 CLI，為各 master 指定以 font units 表示的半徑：

```bash
kumamaru source-round \
  --input 'vendor/ibm-plex-sans-tc/sources/masters/IBM Plex Sans TC.glyphs' \
  --output 'build/source/Kumamaru Sans.glyphs' \
  --all-glyphs \
  --radius Thin=28 --radius Regular=48 --radius Bold=68 \
  --inner-radius Thin=18 --inner-radius Regular=32 --inner-radius Bold=46 \
  --normalize-ibm-plex-sans-tc \
  --report build/source/rounding-report.json
```

多字重流程已接入 GitHub Actions 並作為預覽 Release 的建置來源，但仍有下列限制：

- 處理封閉輪廓上、跨所有 masters 拓撲一致的黑色外角、白色 counter 與結構凹角，以及通過幾何安全門檻的平切筆畫端點。
- 結構凹角沿用較小的 inner radius，避免交會處與外角使用相同的大半徑。
- 任一 master 不安全時，該候選會整組跳過，不會只修改部分字重。
- 含 bracket layer 的所選 glyph 會整字跳過；後續需實作 bracket-aware 映射。
- 尚未移植靜態 TTF pipeline 的 spur override；圓頭 terminal 目前只涵蓋可由單一直線 cap 與兩側 shaft 安全辨識的輪廓。
- `fontmake` 會由 Glyphs source 重新編譯 OpenType tables，因此不追求與 IBM 發行 TTF 二進位等價；
  每次自動 build 仍須通過專案 metadata、字集、`fvar`／`STAT` 與 FontBakery gates。

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

可再生輸出位於 `build/`。靜態 TTF 位於 `build/source/instance-ttf/`，Variable Font 位於
`build/source/variable-ttf/`，來源清單、圓角報告與 FontBakery 報告位於 `build/source/`。
發行 zip 會包含 `Static/`、`Variable/`、`Reports/`、OFL、上游 attribution 與 checksums；
原始 IBM source、衍生 `.glyphs` 與含 `before.ttf` 的 proof 不會上傳至 Actions artifact／Release。
