# Codex 任務：建立「熊丸體（Kumamaru Sans）」字型改造工具鏈

> 請不要只回覆計畫。請直接在目前 repository 中完成本文件定義的 MVP、執行測試，並在最後列出變更檔案、實際執行過的指令、產物位置與已知限制。

## 1. 背景與目標

我們要以 **IBM Plex Sans TC** 為基礎，製作一套暫名為 **熊丸體（Kumamaru Sans）** 的繁體中文圓體。

設計方向不是對整個字形做模糊、膨脹或單純套全域圓角，而是：

1. 保留 IBM Plex Sans TC 原本的字面、重心、骨架與辨識度。
2. 將明顯的外角與內角適度圓化。
3. 將橫、豎等筆畫末端改成圓頭。
4. 移除或收斂 IBM Plex Sans TC 部分筆畫末端的喇叭口、楔形腳、短 spur；例如「個」可看到一些不希望保留的黑體腳。
5. 保留有語意與辨識功能的鉤、挑、撇、捺，不可把所有突出部位一律刪掉。
6. 建立可重複執行、可檢視差異、可逐字覆寫規則的開源工具鏈，而不是只輸出一次性的字型檔。

目前字型名稱為暫名，所有 metadata 必須集中設定，之後可一次改名：

- 英文 family name：`Kumamaru Sans`
- 繁體中文 family name：`熊丸體`
- repository/package slug：`kumamaru`

## 2. 本次交付範圍

本次只做 **Regular、靜態 TTF、受控字形子集的 MVP**。

必須完成：

- 讀取使用者提供的 `IBMPlexSansTC-Regular.ttf`。
- 檢查字型格式、表格、字數、UPM、輪廓類型及 SHA-256。
- 可只針對指定 glyph／Unicode 進行轉換。
- 實作線段型角落的圓化。
- 實作線段型筆畫末端的圓頭化。
- 實作「腳／喇叭口」候選偵測，預設只產生報告；由 override 明確套用。
- 可用 glyph、contour、segment 或 candidate ID 做例外設定。
- 直接修改 TTF `glyf` 輪廓，盡可能保留原字型的 `cmap`、`GSUB`、`GPOS`、`GDEF`、`BASE`、`vhea`、`vmtx`、度量與 glyph order。
- 移除已失效的 TrueType hinting。
- 正確改寫字型名稱與授權 metadata，不得把 `Plex` 當成新字型的主要名稱。
- 輸出原版／修改版／疊圖比較的靜態 HTML + SVG proof。
- 提供單元測試、整合測試與 CI。

本次不做：

- GUI 字型編輯器。
- Variable Font。
- OTF/CFF 輸入與輸出。
- 一次處理全部八個 weight。
- 全字庫自動判斷後直接發布。
- 機器學習、OCR、以 raster image 反推輪廓。
- 自動 hinting。
- 宣稱產物已達正式發布品質。

## 3. 重要限制

### 3.1 不可下載非官方字型

程式不得從任意字型下載站抓取 IBM Plex Sans TC。預設輸入位置：

```text
vendor/IBMPlexSansTC-Regular.ttf
```

`vendor/` 預設加入 `.gitignore`。CLI 也必須接受任意 `--input` 路徑。

若目前 repository 沒有輸入字型：

- 仍須完成專案骨架、幾何演算法、使用 FontTools 產生的合成 fixture、單元測試與 CI。
- `smoke`／integration command 必須清楚提示缺少哪個檔案。
- 不得因此只留下 TODO 或空函式。

### 3.2 不要把完整字型經 UFO round-trip 當作 MVP 主流程

MVP 優先直接使用 `fontTools.ttLib.TTFont` 替換 `glyf` 表中的目標 glyph，原因是要降低遺失或重建 OpenType 排版表格的風險。

`ufo-extractor`、`ufoLib2`、`ufo2ft` 可以保留為未來 OTF/UFO 支援的研究項目，但本次主流程不可依賴它們重新編譯整套字型。

### 3.3 原始 hinting 必須移除

修改 glyph 點數後，原本 TrueType instructions 可能引用錯誤的 point index。輸出前必須：

- 清除修改 glyph 的 instructions。
- 為避免混合狀態造成不可預期行為，MVP 預設移除整套字型的 glyph instructions 與 `cvt `、`fpgm`、`prep` 等 hinting tables。
- 正確重算 `maxp`、bbox、checksum 與相關資料。
- 在 build report 明確標示輸出為 unhinted。

### 3.4 幾何修改必須保守

遇到無法高信心處理的 glyph，不得硬改。應：

- 跳過該 corner／terminal。
- 在 JSON report 中寫出原因。
- 在 proof 中標示 warning。
- 允許後續使用 override 強制處理或整字跳過。

## 4. 技術選型

使用 Python 3.11+。

必要依賴：

- `fonttools`
- `skia-pathops`：只用於輪廓 simplify、boolean cleanup、偵測明顯自交；不可把 Bézier 全部粗暴轉成低精度多邊形。
- `typer` 或標準 `argparse`：建立 CLI，擇一即可。
- `PyYAML`：讀取 glyph override。
- `uharfbuzz`：驗證修改前後 shaping 結果。

開發依賴：

- `pytest`
- `pytest-cov`
- `ruff`
- `mypy`
- `fontbakery`，執行 universal profile。

不要依賴 FontForge 才能執行核心 build；FontForge 只可作為人工檢視建議工具。

## 5. 建議 repository 結構

可依現有 repository 慣例調整，但責任分層必須清楚：

```text
.
├── pyproject.toml
├── README.md
├── Makefile
├── .gitignore
├── .github/
│   └── workflows/
│       └── ci.yml
├── LICENSE
├── LICENSES/
│   ├── OFL-1.1.txt
│   └── UPSTREAM.md
├── vendor/
│   └── .gitkeep
├── config/
│   ├── regular.toml
│   ├── overrides.yaml
│   └── glyphsets/
│       ├── smoke.txt
│       ├── review.txt
│       └── hooks.txt
├── src/kumamaru/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── font_io.py
│   ├── metadata.py
│   ├── model.py
│   ├── report.py
│   ├── render.py
│   ├── validate.py
│   ├── geometry/
│   │   ├── bezier.py
│   │   ├── contour.py
│   │   ├── vectors.py
│   │   └── winding.py
│   └── filters/
│       ├── corner_rounding.py
│       ├── terminal_rounding.py
│       ├── spur_detection.py
│       └── cleanup.py
├── tests/
│   ├── fixtures/
│   ├── golden/
│   ├── test_corner_rounding.py
│   ├── test_terminal_rounding.py
│   ├── test_spur_detection.py
│   ├── test_font_roundtrip.py
│   └── test_metadata.py
└── build/
```

`build/` 與使用者提供的字型檔不可 commit。

## 6. CLI 規格

建立 `kumamaru` console command，至少有以下 subcommands。

### 6.1 inspect

```bash
kumamaru inspect \
  --input vendor/IBMPlexSansTC-Regular.ttf \
  --output build/inspection.json
```

輸出至少包含：

- 檔案 SHA-256。
- sfnt flavor。
- tables 清單。
- `unitsPerEm`。
- glyph count、glyph order hash。
- Unicode cmap count。
- simple/composite glyph 數量。
- 有無 `fvar`、`CFF `、`CFF2`。
- 有無 TrueType hinting tables。
- family、subfamily、full name、PostScript name。
- `OS/2.fsType`。
- 目標 smoke glyph 是否存在。

遇到非靜態 TTF 或沒有 `glyf` table，必須以可理解的錯誤退出。

### 6.2 analyze

```bash
kumamaru analyze \
  --input vendor/IBMPlexSansTC-Regular.ttf \
  --glyphs config/glyphsets/smoke.txt \
  --config config/regular.toml \
  --output build/analysis.json
```

只分析、不修改。每個 glyph 輸出：

- contour 數。
- line／quadratic segment 數。
- 可圓化 corner 清單。
- terminal 候選。
- spur／flare 候選。
- 每個候選的穩定 `candidate_id`、contour index、segment range、方向、confidence、理由與幾何數值。
- 略過項目與原因。

`candidate_id` 必須能在相同輸入 SHA 與設定下穩定重現。

### 6.3 build

```bash
kumamaru build \
  --input vendor/IBMPlexSansTC-Regular.ttf \
  --output build/KumamaruSans-Regular.ttf \
  --glyphs config/glyphsets/smoke.txt \
  --config config/regular.toml \
  --overrides config/overrides.yaml \
  --report build/build-report.json
```

需求：

- 只修改 glyph set 指定的字。
- 未指定 glyph 的 `glyf` binary 應盡可能保持 byte-identical。
- glyph advance width、vertical advance、glyph order、cmap 不得改變。
- 支援 `--dry-run`。
- 支援 `--strict-upstream-sha`；開啟時若 SHA 不符設定便停止。
- 任何 glyph 失敗不可靜默忽略；須寫入 report，並由設定決定整體 build 是否 fail。

### 6.4 proof

```bash
kumamaru proof \
  --before vendor/IBMPlexSansTC-Regular.ttf \
  --after build/KumamaruSans-Regular.ttf \
  --glyphs config/glyphsets/smoke.txt \
  --analysis build/analysis.json \
  --output build/proof
```

輸出純靜態檔案：

```text
build/proof/index.html
build/proof/assets/...
build/proof/glyphs/U500B.svg
```

每個 glyph 頁面至少顯示：

- 原版。
- 修改版。
- 疊圖。
- 可切換輪廓 point／segment index。
- contour 使用不同可辨識樣式。
- corner、terminal、spur candidate 的位置與 ID。
- bbox、point count、修改數與 warning。

首頁提供以下 specimens：

```text
個國固圓圖問間開關體熊丸
小水心事我成也孔兒光永必民
體鬱鑿龜齒齊龍藝響
熊丸體的圓角與收筆測試。ABC abc 0123456789
```

不需使用 React、Vite 或其他 bundler；簡單 HTML/CSS/少量原生 JS 即可。

### 6.5 validate

```bash
kumamaru validate \
  --before vendor/IBMPlexSansTC-Regular.ttf \
  --after build/KumamaruSans-Regular.ttf \
  --glyphs config/glyphsets/smoke.txt \
  --output build/validation.json
```

驗證規則見第 12 節。

## 7. 字形清單格式

`config/glyphsets/*.txt` 每行接受：

- 單一實際字元，例如 `個`。
- `U+500B`。
- glyph name。
- `#` 開頭註解。

需要去重並保留檔案順序。

`smoke.txt` 至少包含：

```text
個
國
固
圓
圖
問
間
開
關
體
熊
丸
小
水
心
事
我
成
也
孔
兒
光
永
必
民
A
B
a
b
0
8
```

## 8. 內部輪廓模型

建立明確、可測試的中介模型，不要把所有邏輯塞在 FontTools pen callback 中。

至少需要：

```python
@dataclass(frozen=True)
class Point:
    x: float
    y: float

@dataclass
class LineSegment:
    start: Point
    end: Point

@dataclass
class QuadraticSegment:
    start: Point
    control: Point
    end: Point

@dataclass
class Contour:
    segments: list[LineSegment | QuadraticSegment]
    closed: bool
    source_contour_index: int

@dataclass
class GlyphOutline:
    glyph_name: str
    contours: list[Contour]
    width: int
```

要求：

- 將 TrueType implied on-curve points展開成明確 segment。
- 序列化回 `TTGlyphPen` 時仍輸出合法 closed contour。
- 原本未修改的 quadratic segment 不應因整體格式轉換而被重擬合。
- 座標最後使用 OpenType rounding 規則轉為整數。
- 所有 geometry function 都要處理零長度 segment、重複點與接近共線的數值問題。

## 9. 角落圓化演算法

MVP 只需可靠處理 **line-to-line join**。若 corner 任一側是 quadratic curve，可先跳過並寫入 report，不可假裝已支援。

### 9.1 corner 辨識

對 closed contour 的每個 line-line join：

1. 取得前一段進入 corner 的方向與下一段離開 corner 的方向。
2. 排除零長度 segment。
3. 計算 interior angle、signed turn 與 contour orientation。
4. 排除接近直線的 join。
5. 根據 contour orientation + signed turn 判斷相對於填色區是 convex outer corner 或 concave inner corner。
6. 若相鄰 segment 太短，跳過或縮小 radius，不可產生反轉輪廓。

### 9.2 建立圓角

設定以 em 比例表示，再依 UPM 換算：

```toml
[rounding]
outer_radius_em = 0.024
inner_radius_em = 0.008
min_interior_angle_deg = 25.0
max_interior_angle_deg = 165.0
max_trim_segment_ratio = 0.42
min_segment_length_em = 0.008
collinear_tolerance_deg = 4.0
```

line-line join 的基礎作法：

1. 依 interior angle 算出兩側 trim distance。
2. trim distance 不得超過任一相鄰 segment 的設定比例。
3. 將原 corner 替換成兩個 tangent points。
4. 以原 corner 作為 quadratic control point，建立 tangent-continuous 的圓滑連接。
5. 若 inner corner 造成輪廓自交或小洞消失，回退到原 corner 並報 warning。

不要求第一版是數學上的精確圓弧，但要：

- 兩端切線連續。
- 結果 deterministic。
- 不產生 NaN、無限值、開放輪廓或 segment 反向。
- 單元測試覆蓋 90°、銳角、鈍角、concave、極短 segment。

## 10. 筆畫末端圓頭與去腳

這是本專案最重要、也最容易誤判的部分。必須分成「候選分析」與「實際套用」。

### 10.1 terminal 候選

在 closed contour 中找出可能代表筆畫端帽的局部 segment chain：

- 中央有一段短 cap，或由數段短線構成 cap。
- cap 兩側最終連接到兩條長度較長、近似平行、走向相反的 shaft sides。
- cap 方向大致垂直於 shaft axis。
- terminal 位於該局部筆畫方向的極值附近。
- shaft sides 之間的距離可作為正常 stroke width 估計。

支援最多向兩側各回溯數個短 segment，以涵蓋喇叭口由斜線組成的情況。

### 10.2 spur／flare 候選

計算：

- `shaft_width`：離末端稍內側、兩條 shaft side 的距離。
- `terminal_width`：端部最大寬度。
- `flare_ratio = terminal_width / shaft_width`。
- `flare_depth`：從正常 shaft 開始偏離到端部極值的距離。

當 `flare_ratio`、`flare_depth`、方向一致性等條件達標時，產生候選與 confidence，但預設不套用。

建議設定：

```toml
[terminal]
enabled = true
parallel_tolerance_deg = 12.0
perpendicular_tolerance_deg = 18.0
min_side_length_em = 0.045
max_cap_chain_length = 5
round_cap = true

[spur_detection]
enabled = true
report_only = true
min_flare_ratio = 1.12
max_flare_depth_em = 0.055
min_confidence_to_auto_apply = 0.98
```

MVP 預設 `report_only = true`。只有以下情況可以實際去腳：

- `overrides.yaml` 明確引用 `candidate_id`；或
- 使用者明確將 `report_only` 關閉，而且 confidence 高於門檻。

### 10.3 重建圓頭

對確認套用的 terminal：

1. 找到正常 shaft 的兩條 side line。
2. 移除 flare chain 與原 cap。
3. 使用 `shaft_width` 建立新端點。
4. 以兩段 quadratic curves 建立半圓近似，確保與 shaft sides 相切。
5. 保留筆畫長度的視覺極值；除非 override 指定，不可無故縮短整根筆畫。
6. cleanup 後若自交、面積異常或 bbox 改變過大，回退並報錯。

### 10.4 不可誤刪的形狀

下列情況預設不得自動去腳：

- 鉤的末端，例如「小、水、心、事、我、成」。
- 撇、捺、挑的方向性尖端。
- 孤立的點。
- 交叉筆畫產生的局部突出。
- 很短且無法估計正常 shaft width 的輪廓。

這些 glyph 必須出現在 `hooks.txt`，用於 regression test。

## 11. overrides.yaml

實作可擴充 schema，至少支援：

```yaml
glyphs:
  U+500B:
    skip: false
    outer_radius_em: 0.022
    inner_radius_em: 0.007
    operations:
      - type: apply_terminal_candidate
        candidate_id: "PLACEHOLDER_FROM_ANALYSIS"
      - type: skip_corner
        contour: 0
        segment: 12

  U+5FC3:
    disable_spur_removal: true

  U+6C34:
    disable_spur_removal: true
```

若還沒有實際輸入字型，`U+500B` 的 candidate ID 不可亂填。先保留註解範例，並讓 README 說明如何從 `analysis.json`／proof 複製 ID。

需要驗證 schema：

- 未知 glyph、candidate、contour 或 segment 應報錯或 warning，不可無聲失效。
- strict mode 下視為 build failure。

## 12. 字型重建與表格保存

### 12.1 targeted glyph

對目標 glyph：

- 若是 simple glyph，讀取並重建。
- 若是 composite glyph：
  - 預設解析成實際輪廓後，只將該 glyph 重建為 simple glyph。
  - 不得修改 component glyph，避免同一修改被套用兩次。
  - report 必須記錄 composite 被 decomposed。

### 12.2 未修改 glyph

未在 glyph set 中的 glyph：

- 不改 outline。
- 不改 hmtx/vmtx。
- validate 時比較原始與輸出 glyph binary；若非必要改變便 fail。

### 12.3 允許改變的 tables

通常允許：

- `glyf`
- `loca`
- `head`
- `maxp`
- `name`
- `OS/2` 的明確 metadata 欄位
- `post` 的必要名稱資料
- hinting tables 被移除
- `DSIG` 被移除，因原簽章不再有效

其他 tables 應在 validate 中比較 compiled bytes。若改變必須列入 report 並解釋。

### 12.4 overlap cleanup

只針對修改 glyph 執行 cleanup。使用 `skia-pathops` 後必須確認：

- contour winding 合法。
- 沒有 open contour。
- 沒有零面積 contour。
- 沒有明顯自交。
- cleanup 不得讓 point count 爆炸；超過設定門檻則回退。

## 13. Metadata 與授權

IBM Plex 的字型授權是 SIL Open Font License 1.1，且 `Plex` 是 Reserved Font Name。輸出的 modified font：

- 主要 family/full/PostScript name 不得包含 `Plex`。
- 必須保留 IBM 原始 copyright attribution。
- 必須加上本專案為 modified version 的說明。
- 不得暗示 IBM 認可或背書熊丸體。
- 產出的字型仍使用 OFL 1.1。
- 程式碼可使用 MIT；請在 repository 清楚區分 code license 與 generated font license。

需設定／更新至少以下 name IDs：

- 0 Copyright
- 1 Family
- 2 Subfamily
- 3 Unique identifier
- 4 Full name
- 5 Version
- 6 PostScript name
- 13 License description
- 14 License URL
- 16 Typographic family
- 17 Typographic subfamily

Regular 建議值：

```text
Family: Kumamaru Sans
Traditional Chinese family: 熊丸體
Subfamily: Regular
Full name: Kumamaru Sans Regular
PostScript name: KumamaruSans-Regular
Version: Version 0.1.0
OS/2 achVendID: KUMA
```

加入繁體中文 localized name record；至少支援 Windows zh-TW 與 Unicode name record。

metadata 必須由 `config/regular.toml` 控制，不得散落 hardcode。

## 14. 驗證與驗收條件

`kumamaru validate` 必須執行以下檢查並輸出 JSON：

### 14.1 基本有效性

- `TTFont(..., lazy=False)` 可完整載入與重新儲存。
- 有 `glyf`、`loca`、`cmap`、`head`、`hhea`、`hmtx`、`maxp`、`name`、`OS/2`。
- 沒有 CFF/CFF2/fvar。
- 所有 glyph 均能 draw。
- 沒有非有限座標、open contour、無效 bbox。

### 14.2 字符與排版保存

修改前後必須相同：

- glyph count。
- glyph order。
- best cmap mapping。
- hmtx、vmtx。
- `GSUB`、`GPOS`、`GDEF`、`BASE`、`vhea` 等非允許變更 tables 的 compiled bytes。

### 14.3 shaping regression

用 `uharfbuzz` 對以下內容比較修改前後的 glyph sequence、cluster 與 advance：

- 水平繁體中文。
- Latin + 數字。
- 標點。
- direction `ttb` 且啟用 `vert`、`vrt2` 的垂直排版測試。

outline 可不同，但 shaping 結果必須相同。

### 14.4 幾何限制

對每個修改 glyph：

- advance 不變。
- bbox 改變不得超過設定門檻，預設每側 `0.08em`。
- point count 增幅不得超過預設 3 倍。
- contour area 不得突然接近 0 或翻倍。
- cleanup 後不可自交。

### 14.5 未修改 glyph

從 glyph set 之外隨機抽樣至少 100 個 glyph，比較原始與輸出 outline binary；應完全相同。

### 14.6 外部 QA

提供 Makefile target：

```bash
make lint
make test
make smoke
make validate
make fontbakery
make proof
```

`make fontbakery` 執行：

```bash
fontbakery check-universal --json build/fontbakery.json build/KumamaruSans-Regular.ttf
```

已知 warning 可以記錄，但不可用大量 exclusion 讓結果看起來全綠。

## 15. 測試策略

### 15.1 不依賴 IBM 字型的 CI fixture

使用 FontTools `FontBuilder` 在 tests 中建立小型合成 TTF，包含：

- 矩形外角。
- concave notch。
- 過短 segment。
- 一般方頭 stem。
- 有喇叭口的 stem。
- 有 hook 的形狀。
- composite glyph。
- 基本 cmap、hmtx、vmtx、name。

CI 必須能在沒有 IBM binary 的情況下完整跑 unit tests。

### 15.2 golden tests

對合成 fixture 儲存 deterministic 的：

- segment JSON。
- SVG path。
- corner／terminal candidate report。

避免以平台相關的 antialiasing PNG 作為唯一 golden test。

### 15.3 integration tests

若 `vendor/IBMPlexSansTC-Regular.ttf` 存在才執行：

- inspect。
- smoke analyze。
- smoke build。
- proof。
- validate。

若不存在，在 CI 顯示 skip，不得 fail。

## 16. 預設設定檔

建立 `config/regular.toml`，大致如下，可依實測調整：

```toml
[font]
family_name = "Kumamaru Sans"
family_name_zh_hant = "熊丸體"
style_name = "Regular"
version = "0.1.0"
vendor_id = "KUMA"
strict_upstream_sha = false
upstream_sha256 = ""

[rounding]
enabled = true
outer_radius_em = 0.024
inner_radius_em = 0.008
min_interior_angle_deg = 25.0
max_interior_angle_deg = 165.0
max_trim_segment_ratio = 0.42
min_segment_length_em = 0.008
collinear_tolerance_deg = 4.0

[terminal]
enabled = true
parallel_tolerance_deg = 12.0
perpendicular_tolerance_deg = 18.0
min_side_length_em = 0.045
max_cap_chain_length = 5
round_cap = true

[spur_detection]
enabled = true
report_only = true
min_flare_ratio = 1.12
max_flare_depth_em = 0.055
min_confidence_to_auto_apply = 0.98

[cleanup]
enabled = true
max_point_growth_ratio = 3.0
max_bbox_change_em = 0.08
fail_on_self_intersection = true

[build]
strip_hinting = true
remove_dsig = true
fail_on_glyph_error = true
```

## 17. README 必須包含

- 專案目標與目前只支援 Regular TTF MVP 的限制。
- 安裝方法。
- 使用者應從 IBM 官方來源取得字型，並放到 `vendor/`；不得引導至第三方下載站。
- 完整 inspect → analyze → proof → overrides → build → validate 流程。
- 「個」如何透過 candidate ID 套用去腳。
- 為何不能把所有鉤都當 spur 刪掉。
- 為何輸出先移除 hinting。
- 授權與 Reserved Font Name 注意事項。
- 產物尚需人工逐字校對，不可把自動 build 當成最終設計。

## 18. 執行順序

請依序完成，不要先寫一個無法驗證的全字庫演算法：

1. 建立 packaging、CLI、合成 fixture、CI。
2. 實作 `inspect` 與 table-preservation 基礎測試。
3. 實作輪廓 parser／serializer。
4. 實作 line-line corner rounding 與單元測試。
5. 實作 terminal／flare candidate analyzer。
6. 實作 override 與確認後的 round-cap／remove-flare。
7. 實作 targeted glyph build、strip hinting、metadata rename。
8. 實作 proof。
9. 實作 validate、HarfBuzz regression、FontBakery target。
10. 若 IBM TTF 存在，跑 smoke integration 並針對「個」輸出分析結果；不可在沒有 proof 的情況下自稱去腳已完全正確。

## 19. MVP Definition of Done

只有全部符合才算完成：

- `pip install -e .` 成功。
- `kumamaru --help` 可用。
- 沒有 IBM binary 時，所有 unit tests 與 CI 通過。
- 有 IBM Regular TTF 時，可完成 inspect、analyze、smoke build、proof、validate。
- 輸出的字型 family 為 `Kumamaru Sans`／`熊丸體`，主要名稱沒有 `Plex`。
- smoke glyph 的角落有實際改變。
- terminal／spur candidate 會顯示在分析報告與 proof。
- 只有 override 或超高 confidence 才會實際去腳。
- 「心、水、我、成」等測試字不會被預設 spur removal 破壞。
- glyph order、cmap、metrics、OpenType shaping 與垂直排版行為保持一致。
- 未修改 glyph outline 保持不變。
- 原 hinting 與失效 DSIG 已移除。
- build、analysis、validation 都有 machine-readable JSON report。
- README 清楚揭露目前限制與人工校對需求。

## 20. 最後回報格式

完成後請回覆：

```markdown
## 完成項目

## 主要設計決策

## 變更檔案

## 執行過的指令與結果

## 產物位置

## 「個」的分析結果

## 尚未完成／已知限制
```

不要把未執行的測試寫成已通過，也不要把候選偵測寫成已完成字型設計。
