# 熊丸體（Kumamaru Sans）

> **開發中（Work in Progress）**  
> 熊丸體仍在積極開發與人工校對中。目前產物僅供預覽與測試，**請勿視為可正式上線的成品字型**。字形品質、字集覆蓋與細節都會持續變動，自動 build 結果也需要人工審查。

熊丸體是以 [IBM Plex Sans TC](https://github.com/IBM/plex) 為上游的保守、可稽核字型改造。它只圓化明確的外角與經確認的收筆，並盡量保存字面、骨架、度量與 OpenType 行為；不是全域模糊或圓角化工具。

目前提供 TrueType（`glyf`）預覽版：

- 8 個靜態字重：Thin 100、ExtraLight 200、Light 300、Regular 400、Text 450、Medium 500、SemiBold 600、Bold 700
- `wght` 100–700 Variable Font，預設 Regular 400，包含上述 8 個 named instances

靜態版與 Variable Font 屬於同一個 `Kumamaru Sans`／`熊丸體` family。安裝時請依使用環境
選擇其中一種格式，不要同時安裝兩套，以免 Regular face 被作業系統視為重複字型。
目前不提供 OTF/CFF，也不執行自動 hinting。

預覽下載、授權、本地開發、建置與發行方式請參閱 [開發文件](DEVELOPMENT.md)。
