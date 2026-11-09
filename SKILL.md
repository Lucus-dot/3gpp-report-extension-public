---
name: 3gpp-report-extension
version: "2.2.0"
description: "把某场 3GPP 会议的落槌结论，接进一份既有深度报告，产出一份「续篇」：按 WI 条目组织，每条给基线原状 / 本次进展（逐字原文 + 讨论链）/ 演进分析 / 遗留，再补定量折算、三列映射、增量清单与未收口。当用户要求「在 XX 报告基础上做 YY 会议的扩展 / 续篇」「给这份调研报告补上最新会议进展」「把新会议的 Agreement 接进四段式报告」时使用。触发词：续篇、扩展、基础上、会议进展补充、四段式扩展、接进报告。"
display_name: "3gpp-report-extension"
display_name_en: "3GPP Report Extension"
description_zh: "把某场 3GPP 会议的落槌结论接进既有深度报告，产出续篇：按 WI 条目组织，每条含基线原状 / 本次进展 / 演进分析 / 遗留。前提是已有一份可接的基准报告。"
description_en: "Fold one 3GPP meeting's agreed conclusions into an existing deep-dive report as a follow-up, organized by WID item. Requires an existing base report to extend."
category: writing
author: "lucus"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# 3GPP 基准报告 · 会议增量续篇

## 何时执行

同时满足三条才执行：
1. 已有一份**四段式深度报告**（基准报告）；
2. 用户给出某场 3GPP 会议的材料目录；
3. 用户要的是「在基准报告基础上接上这场会」——出现「续篇 / 扩展 / 基础上 / 补上进展 / 接进报告」等说法。

**不满足就停：**

| 情况 | 处置 |
|---|---|
| 没有基准报告 | 停。询问用户是否改用 `3gpp-ran-meeting-progress` 写单场会议进展。 |
| 要的是单场会议快照（谁主张什么） | 停。同上。 |
| 要的是会前 TDoc 观点归类 | 停。改用 `3gpp-proposal-analysis`。 |
| 只有 FL Summary、没有主席报告 | 停。落槌只认主席报告，让用户补齐。 |

## 产物

- `<基准报告名>_<会议>扩展_<日期>.md`（续篇）
- `_work_<议程项>/`：`wid.json` `blocks.json` `ffs.json` `issues.json` `flow.json` `rel.json` `calc.json`
- 同名 `_seal.json`（封存凭据）
- **基准报告一个字节都不改**（连 mtime 都不改）。

## 两条结构纪律

**对账单元 = Agreement 块；组织单元 = WI 条目。**

- 切块按行首 `Agreement:` / `Working assumption`，一块一条，差 1 条即错。
- 正文按 **WI 条目**（`A1/A2/B1…C5/P1/P2`，从基线抄）分节，不按 `AgN` 编号分节。
- 每个块在正文**出现且仅出现一次**。`check` 会数这一条。

**跨会议只认 WI 条目当主键。** `#126` 的 Ag1–Ag6 与 `#126b` 的 Ag1–Ag12 互不通用；Issue 编号每场会重切。上一场的 Agreement 只能作过渡桥，不能当挂接键。

## 禁止事项

1. **不改基准报告**。发现原报告有错，只在附录 B 登记。
2. **不合并 Agreement**。语义相近也不合并，一块一条。
3. **不替会议收敛**。原文写 `FFS` / `down-select one of the following`，原样照抄。
4. **不升格**。`can be configured to…` 不得改写成「必须」。
5. **不漏负结论**。没有 Agreement 的 WI 条目也要保留，写「本场无进展」并给判据。
6. **不省计数过程**。篇数、Agreement 数、WA 数都要写出数字 + 数法。
7. **不跳权威层级**。落槌只认主席报告（`Chair notes *_eom*`）；FL Summary 只作讨论脉络；TDoc 只作起点参考。
8. **不自拟标题**。续篇 H1、接续的「第N部分」、小节号、WI 条目表，全部来自基线。
9. **公司立场必须带出处**。每处标 `FL#k / Issue#x-y`；本场 FL 里查不到的公司名一律不写。
10. **不复述工具已经算好的事**。`blocks` 已定轮次，不要自己「按文档顺序推定」。

## 模型上下文纪律

不要一次读完全部素材。每个写作步骤只读**该步切片**：

| 步骤 | 只读这些 
|---|---|
| A5 判块归属 | 标了「需模型判定」的块原文 + 各候选 Issue 的 Proposal 段 |
| A6 命名 delta | 工具算好的 Proposal 差异 | 
| A7 写单块三段 | 1 块原文 + 该 Issue 的 FL 段 + `flow[k]` + 该 WI 的基线原节 | 
| B1 判 WI 归属 | `unmapped_issues` 的 Issue 标题 + `wid.json` + WID 原文相关段 | 
| B2 判关系 | 基线相关 Ag + 本场 Issue 标题 | 
| B4 写演进 | 该 WI 基线原状 + 本场该 WI 全部块原文 + 历次 Ag 编号 | 

**不许读**：41 篇 TDoc 全文、主席报告全文、整篇续篇。

## 执行步骤

```bash
S="<skill 目录>/scripts/skillctl.py"
W="_work_<议程项>"
```

### A1 抄基线，生骨架

```bash
python $S init --base "<基准报告>" --meeting "<会议>" --agenda "<议程项>"
```

读三行输出：`标题抄自基线` / `接续` / `WI 条目`。

- 报「基线报告里没找到一级标题」→ 停，让用户确认基准报告。
- 报「续篇起始小节 §x.y 不大于基线末节」→ 改节号，别硬冲。改法是**同目录建 `config.local.json`**：
  `{"required_sections": ["§4.7", "§4.8", …, "附录 A", "附录 B"]}`。它按顶层键覆盖 `config.json`，
  且已进 `.gitignore`——不要直接改 `config.json`，那是分发包的一部分，改了会把本项目报告的节号推给别人。
- 骨架已存在时 `init` 拒绝覆盖。先确认那份是不是上一轮产物，不要改名硬冲。

**完成标准**：续篇 H1 与基准报告 H1 逐字相同；`$W/wid.json` 条目数 == 基线「WID 目标 × … 总映射」表行数。

### A2 抽权威文本

```bash
python $S sources  "<会议目录>" --agenda "<议程项>"
python $S extract  "<Chair notes *_eom*.docx>" --out "$W/_eom_verbatim.txt"
python $S extract  "<FL Summary 1>.docx" --out "$W/_fl/R1-xxxxxxx.txt"   # 每份 FL 各来一次
```

- `sources` 报主席报告缺失 → 停，问用户要，不要找替代品。
- `sources` 报的「TDoc 夹文件数」**不是篇数**，不要填进文档。
- 抽出后打开 `_eom_verbatim.txt`，**裁掉目标议程项以外的段落**再写回。裁段由你做，`extract` 只给全文。

**完成标准**：`_eom_verbatim.txt` 只含目标议程项；每份 FL 都有对应 `.txt`；公式/表格丢失项已记录。

### A3 切块 + 定轮次

```bash
python $S blocks "$W/_eom_verbatim.txt" --out-dir "$W"
```

读输出的块数、FL 分隔行、轮次归属表、FFS 条数。

- 报「轮次回头」→ 说明混进了别的议程项，回 A2 重新裁段。
- 轮次由主席报告内嵌的 FL 分隔行给出，**不要自己按文档顺序推定**。

**完成标准**：`blocks.json` / `ffs.json` 已落盘；每块有 `fl_round` 且单调不回退。

### A4 抽议题骨架

```bash
python $S issues "$W/_fl/FL1.txt" "$W/_fl/FL2.txt" … --out-dir "$W"
```

文件顺序**早→晚**。骨架以最末一份 FL 为准。

记下「无立场段」的 Issue 编号——写解读时不能凭印象给它们补公司名。

**完成标准**：Issue 数与最末一份 FL 一致；每个 Issue 标了有/无立场段；跨轮骨架差异已列。

### A5 对齐：块 → Issue

```bash
python $S flow --blocks "$W/blocks.json" --issues "$W/issues.json" --out-dir "$W"
```

工具按 Proposal 段 n-gram 重叠给候选。**只看标了「需模型判定」的块**（通常 ≤5 条）：读该块原文 + 各候选 Issue 的 Proposal 段，定归属并抄出证据句写回 `flow.json`。其余块直接采用工具结论。

**完成标准**：全部块都有 Issue 归属；每个归属有 `evidence`，且能在对应 FL 文本里逐字找到。

### A6 串讨论链

对每个块，读 `flow.json` 的 `rounds`（该 Issue 在各轮 FL 的段落与 Proposal 编号），逐块做三件事：

1. 为每相邻两轮写一句 `delta`：「这一轮改了什么」。只给差异命名，不重读全文。
2. 核对 `origins_tdoc` / `proponents` 是否支撑「起点」。为空就写 `tdoc_reason="FL 未给起点"`。
3. **需要 TDoc 原文时**，只限三种情形之一：①该 Issue 在 FL 里只写 `See R1-xxx` 无总结段；②相邻两轮 Proposal 互斥且 FL 未判胜负；③WA 数值需溯源。
   ```bash
   python $S tdoc "<R1-xxxxxxx>.docx"
   ```
   并在 `tdoc_reason` 记触发编号。**全场上限 5 篇**，没记理由的抽取算违规。

**完成标准**：每块都有 `delta`；`origins` 为空时已显式写明；抽取的 TDoc 都有理由编号。

### A7 逐块写三段

一次只写一块。每块只读：该块原文 + 该 Issue 的 FL 段 + `flow[k]` + 该 WI 的基线原节。

写进续篇 §n.3 对应 WI 条目的「② 本次进展」里。块号**标在块上**（新结构里 Ag 不当标题），块标题另起一行：

```
**Ag3｜Msg2 FAC 粒度：三选一（含新增"折中项"）**　<sub>FL#3 · Issue#2-7</sub>

**`【原文】Ag3`**
> （逐字粘贴，含 Note 与 FFS 清单，不改写不翻译）

**`【解读】`**  ← 裁定了什么 / 与基线的差异 / 技术论据（引公司立场必标 `FL#k / Issue#x-y`）
**`【映射】`**  ← WI 条目 + 预估受影响 TS 功能块（不写条款号，除非已核实）
```

`Working assumption` 用 `WA<n>` 编号，与 `Ag` 分开计数，**同样三段齐全**（漏 `【映射】` 是最常见的偷工）。

> 排版清理可以，改写不行：docx 抽出来的原文常带行首 tab、被表格打断的清单（`X= 20m`）、
> 多余空格（`" RO pair "`）。这些**允许**在正文里整理干净——`compose` 会认正文里的版本，
> 不会用 `blocks.json` 的原始抽取把它冲回去。原文自带的错字（如 `For of dual…`）不许改，
> 在块后加一行 `〔校〕` 登记。

**完成标准**：每条 `【原文】` 与 `blocks.json` 对应块归一化后逐字相等；每个公司名都能在 FL 切片里定位并标了来源；每个 `【映射】` 的 WI 条目都在 `wid.json` 里。

### B1 挂接：Issue → WI 条目

```bash
python $S rel --flow "$W/flow.json" --wid "$W/wid.json" --out-dir "$W"
```

工具按 Issue 标题关键词挂到 WI 条目并列出 `unmapped_issues`。**只看未挂上的和双路冲突的**：读 Issue 标题与首段 + `wid.json` + 基线 WID 原文相关段，定归属。

落不到既有条目的，判是否派生新条目（`N` 系列），写明依据（WID 哪句 NOTE / 哪份 TS）。

**完成标准**：每个 Issue 都有 WI 归属或显式标「不属本 WI」；派生条目有依据句。

### B2 关系判定（判定要写回去）

对每个有块的 WI 条目判 `kind`，五选一：

| kind | 判据 | 附带必填 |
|---|---|---|
| `CONTINUE` 延续 | 基线与本场指向同一条目，含义一致 | — |
| `NEW` 新增 | 基线无对应条目 | 基线为何缺（WID 未列？NOTE 派生？他 WG 主导？） |
| `DERIVED` 派生 | 上一场某条讨论引出本条 | `base_ref` = 基线具体哪条 Ag / 哪句 NOTE |
| `SPLIT` 拆分 | 上一场一条在本场拆成多条 | `base_ref` + 按什么维度拆 |
| `RELATED` 关联 | 名称含义不同但相关 | 关联性：共享参数 / 依赖 / 冲突 |

判完写进 `patch.json`，再用 `--apply` 合并回 `rel.json`——**不写回去，判定就只活在正文里，下一场没法复用、审核者也没法复核**：

```bash
python $S rel --flow "$W/flow.json" --wid "$W/wid.json" --out-dir "$W" --apply "$W/patch.json"
```

`patch.json` 只放判定字段，形状：

```json
{"entries": [
  {"wi": "A1", "kind": "CONTINUE", "blocks": ["Ag1", "Ag2"]},
  {"wi": "B3", "kind": "CONTINUE", "blocks": [], "covered_by": "B1/B2"},
  {"wi": "N1", "kind": "DERIVED", "base_ref": "WID NOTE: backward compatibility ...",
   "title": "独立/共享 PRACH 资源", "blocks": ["Ag10"]}
]}
```

合并时工具会自检三件事并拦下：关系类型非法 / `DERIVED`、`SPLIT` 缺 `base_ref` / **同一个块挂到多个条目**。

**完成标准**：`--apply` 打印「关系类型齐全、派生有出处、块无重复无遗漏 ✓」。

### B3 按 WI 组装正文（`compose`）

结构是机械的，交给工具；内容是人写的，工具只负责把它搬到位：

```bash
python $S compose --rel "$W/rel.json" --blocks "$W/blocks.json" \
                  --target "<续篇>" --section 4.7
```

它按 `rel.json` 的条目顺序重排整节，做四件事：
① 生成节标题、`① 基线原状/② 本次进展/③ 演进分析/④ 遗留` 四段骨架、总表与**块数自证**；
② 每块按 `fl_round` 升序排列，块标签写成 `**【原文】AgN**`，块原文从 `blocks.json` 注入；
③ **保住你已经写的**：原文段、`【解读】`、`【映射】`、①③④ 全按块号/条目号搬过去，不重打；
④ 无进展条目写 `本场无进展`，指针条目写 `由 §x.y.z 的 AgN 覆盖`。

输出末尾会列**待填清单**（`① n 条 ｜ 【解读】n 块 ｜ 【映射】n 块 ｜ ③ n 条 ｜ ④ n 条`）——那张单子就是接下来要写的范围，按它逐项填。

要点：

- **可重跑**：`compose` 幂等。填完一段再跑一次，只重排结构、不动内容；改了 `rel.json` 的归属后重跑，块自动挪到新条目下，块数守恒由代码保证。
- **原文以正文为准**：已有正文里的原文段原样带走（含排版清理），只有正文里还没有的块才从 `blocks.json` 注入。反过来会让 `X = 20 m / 50 m / 150 m` 退回成 docx 抽出来的 `X= 20m`。
- **块号标在块上**：`**`【原文】Ag1`**`，上方再给一行 `**Ag1｜块标题**　<sub>FL#1 · Issue#2-1</sub>`。新结构里 Ag 不当标题，标不到块上 `check` 就数不到。
- **块标题与 `<sub>` 是内容，不是结构**：`blocks.json` 里没有 `block_title`，标题是你写在正文里的；`<sub>` 里的 `· Issue#x-y` 是 B2 判出来的归属。两者都由「正文优先」保住，工具只在块是**新注入**时才补 `**AgN**` 与 `FL#n`。看到重跑后标题或 Issue 归属变了，就是踩了 P18/P19。
- **跨条目的块用指针**（`covered_by`），不复制原文——复制直接破坏块数守恒。指针条目四段照写。
- **无进展条目保留**，②写判据（RAN4/RAN2 事项 / 未进议程）。不许删条目——删了就看不出哪一条在停滞。

**完成标准**：`compose` 打印「块：n/n 归位（每块一次）✓」且待填项归零；随后 `check` 无 ERROR。

### B4 演进分析

每条目写三件事：①本场推进了什么 ②与历次比差异在哪 ③关系类型带来什么影响。

必须同时引用**一处基线原文**与**一处本场原文**；不得引入切片之外的事实。写「停滞」要给判据（该条目下无 Agreement / 只有 FL 级 Agree）。

**完成标准**：每条目的 ③ 都有双引用；无切片外事实。

### B5 定量折算

先写清公式与假设（粒度定义、位宽 = ⌈log₂ 步数⌉、ppm 换算），再用工具复算：

```bash
python $S calc all --json
python $S calc tac --neg 2903.6 --pos 5807.2 --mu 0 1 2 3   # 需要指定参数时
```

工具输出原样贴进 §n.4，每条标 `【折算】`。至少做 1 处不相容性检查（某候选值与它自身约束是否冲突）。

**完成标准**：每个数字能指到「表-行-参数组」或 `calc` 复现；至少 1 条不相容性结论。

### B6 汇总、未收口与校验

1. §n.5 三列总映射：逐 WI 行，`WID 条目 | 上一场状态 | 本场状态 | 变化`。变化写成「由 A → B」。
2. §n.6 增量清单：每条给 `上次状态 / 本次状态 / 增量性质 / 依据`，性质只取 `裁决 / 新增 / 收紧 / 停滞`。**至少 1 条 `停滞`**。
3. §n.7 未收口：`ffs.json` 全量，按阻塞性排序，每项给 `WI 条目 / 未收口内容 / 决策点 / 可行解空间`。禁止写「需进一步讨论」。
4. 校验：
   ```bash
   python $S check "<续篇>" --eom "$W/_eom_verbatim.txt" --workdir "$W"
   ```

按 ERROR 处置，**不许改数字迁就工具**：

| ERROR | 处置 |
|---|---|
| H1 未抄基线 | 把续篇 H1 改回基线的 H1 |
| 块重复出现 / 编号不连续 | 回 A5 核归属，回 A7 补或删 |
| WI 条目缺段 | 补 ①/②/③/④ 中缺的那一段 |
| 未判关系类型 / DERIVED 缺 base_ref | 回 B2 填，用 `rel --apply` 写回 |
| 条目在正文没有独立小节 | 回 B3 补节，不许删 rel 里的条目 |
| 骨架尚未填实（0 块 + 有空格） | 不是缺陷，是还没开工：接着填 |
| 块数不自证 | 回 A3 重切，别改声明数字 |
| 花名册计数不自证 | 重数，使声明篇数 = 实际条数 |
| 表格未填写 | 把整行空单元格填实 |
| 原文定位不到（WARN） | 与 `_eom_verbatim.txt` diff：排印差异在附录 B 注明；改写则改回原文 |

5. 0 error 后封存：
   ```bash
   python $S seal "<续篇>" --workdir "$W"
   ```

**机器判不了的 4 项，逐条勾选后才算完成：**
- [ ] 该合并的没合并（`check` 只数数，数对不代表性对）
- [ ] §n.6 至少 1 条负增量
- [ ] §n.4 每个数字能指到表-行-参数组
- [ ] `【解读】` 没夹带新事实（"据说""实际上通过了"）

## references 谁在用

| 文件 | 调用方 | 什么时候读 |
|---|---|---|
| `references/01-skeleton.md` | **代码**：`init` 读取并替换占位符 | 不用你读。`init` 已把它填成你的续篇文件 |
| `references/00-provenance.md` | A2、B6 的必读项 | A2 开工前读（权威层级）；B6 读第四节（附录 B 写法） |
| `references/02-numeric-cookbook.md` | B5 的必读项 | B5 开工前读（公式、三个对照、TR 取数姿势） |
| `references/03-pitfalls.md` | A7、B3、B6 的必读项 | A7 读 P1–P4；B3 读 P14–P19（compose 的六个坑）；B6 回读 P12/P13 |

`skillctl run <阶段>` 会把该阶段的必读文件打出来，缺文件标 `✗`。按它读。

## 命令清单

```bash
python $S init    --base <基准报告> --meeting <会> --agenda <项>        # A1
python $S sources "<会议目录>" [--agenda 9.4.1]                        # A2
python $S extract "<docx>" [--out <txt>] [--head 20]                   # A2
python $S blocks  "<逐字文本>" --out-dir "$W"                          # A3
python $S issues  <FL1.txt> <FL2.txt> … --out-dir "$W"                 # A4
python $S flow    --blocks "$W/blocks.json" --issues "$W/issues.json" --out-dir "$W"   # A5/A6
python $S tdoc    "<R1-xxxxxxx>.docx"                                  # A6（按需，≤5 篇）
python $S rel     --flow "$W/flow.json" --wid "$W/wid.json" --out-dir "$W"             # B1
python $S rel     --flow … --wid … --out-dir "$W" --apply "$W/patch.json"              # B2（判定写回）
python $S compose --rel "$W/rel.json" --blocks "$W/blocks.json" \
                  --target "<续篇>" --section 4.7                        # B3（组装正文，可重跑）
python $S calc    all|tac|wf1|wf2|opt3|pos [--json]                    # B5
python $S check   "<续篇>" [--eom <逐字文本>] [--workdir "$W"]          # B6
python $S seal    "<续篇>" [--workdir "$W"]                            # B6

python $S plan | run <阶段> | gate <阶段> | done <阶段> --note "…" | status
python $S dispatch "<任务描述>"
```

`--eom` / `--workdir` 只要给过一次就记进状态，后续自动沿用。从没给过则跳过对应对账，并打印「未核对」。
自检：`python scripts/selftest.py`（20 条断言，改过 `scripts/` 就跑一遍）。
Windows 中文乱码：`set PYTHONUTF8=1`。状态文件：`<项目根>/.workbuddy/skill-state/3gpp-report-extension.json`。

## 细节去哪查

| 需要什么 | 看哪里 |
|---|---|
| 权威层级判定、标注四件套、附录 B 写法 | `references/00-provenance.md` |
| 骨架模板（`init` 读取并填充） | `references/01-skeleton.md` |
| 定时/频率/几何折算公式、TR 表取数姿势 | `references/02-numeric-cookbook.md` |
| 已知踩坑（合并、计数、量程…） | `references/03-pitfalls.md` |
| 为什么这么设计（两阶段、主键、切片预算） | `SPEC.md` |
| 输入输出定义、素材夹布局、与相邻技能边界、FAQ | `README.md` |
