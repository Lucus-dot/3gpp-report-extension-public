# 第三方材料与分发边界

本技能包里有一部分内容**不属于本仓库作者原创**。公开分发或再使用前请先读这一节。

## 1. 3GPP 会议材料

`example/` 下的样例文档引用了 3GPP 会议的**逐字结论原文**：

| 文件 | 含什么 |
|---|---|
| `example/_eom_941_verbatim.txt` | 主席报告（Chair notes）议程项 9.4.1 的纯文本抽取，约 11 KB |
| `example/R20_…_RAN1#126b扩展_20261026.md` | 17 处 `【原文】` 块，逐字照录 Agreement / Working Assumption |
| `example/R20_…_20260901.md` | 基准报告，引用基线结论与 WID 条目 |
| `example/RAN1#126b_GNSS_resilience_会议进展补充_20261026.md` | 反例对照文档，文末「最终落槌结论」逐字照录主席报告 |
| `example/RAN1#126b_NTN_DLCOMP_9.5.1_会议进展_20261026.md` | 另一议程项的反例对照文档，同体裁 |

上述段落的**版权属 3GPP 及其组织伙伴**（ARIB / ATIS / CCSA / ETSI / TTA / TTC / TSDSI），
不在本仓库的许可范围内。此处的引用仅用于说明「逐字溯源」这一方法，
每处都带 TDoc 编号（`R1-26xxxxx`）与 FL 轮次，可回到 3GPP 门户核对。
**这些材料的准确内容仍以 3GPP 官方发布为准。**

## 2. 不随仓库分发的目录

`example/RAN1#126b/`（约 50 MB）里有 100+ 份成员公司 TDoc 的 `.docx`、Chair notes、
Session Notes、下载缓存与运行日志，**已列入 `.gitignore`，不进版本库**：

- 版权归各提交公司，不能转分发；
- 体积过大，且属于可重新获取的原始素材。

需要复现样例时，请自行从 3GPP 门户下载对应 TDoc，文件名与编号在
`example/README.md` 与 `example/_verify/rel.json` 里都有记录。

## 3. 不含个人信息

已逐项检查：包内（`.gitignore` 覆盖范围之外的部分）不含邮箱、手机号、
API key、token、cookie、本机绝对路径或单位名称。

`example/RAN1#126b/tdoc_gui_run.log` 是唯一含本机路径的文件
（构建机的临时目录与桌面路径），它位于不随包分发的目录内。
**若用 zip / 网盘 / GUI 工具整目录上传，`.gitignore` 不生效**——打包前请确认该目录已排除。

## 4. 代码许可

本技能包的**代码尚未声明开源许可**。没有 `LICENSE` 文件时默认保留所有权利：
别人可以看到，但不能合法使用、修改或再分发。

要公开给别人用，请先选定一个许可证并加上 `LICENSE` 文件。若只打算自己用，
保持现状即可，但建议把仓库设为 private，避免他人误用。
