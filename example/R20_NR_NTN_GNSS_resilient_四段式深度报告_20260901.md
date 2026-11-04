# 3GPP R20 · 5G-A NR NTN — GNSS resilient 深度调研报告（SI→TR→WI→RAN1 四段式）

> 范围：Release 20 中 **5G-Advanced（A 线）NR NTN** 这一条主线，主题 = **GNSS resilient NR-NTN operation**。
> 逻辑链：**SI 立项（RAN#108）→ SI 研究产出 TR 38.742（封板 RAN#112）→ 基于 TR 转 WI（RAN#112 批准）→ RAN1 启动 WID 规范工作（RAN1#126 起）**。
> 一手源文件：`docs/RP-251863…doc`（SID）、`docs/RP-261568…doc`（WID）、`docs/TR38.742-v20.0.0.txt`（TR）、`docs/R1-2606912.txt`（RAN1#126 FL#6）。
> 说明：SID/WID 原为旧版 `.doc`，已用 `extract_doc.py` 抽取正文；TR 已抽取为纯文本。

**范围边界（厘清"为什么只写 GNSS resilient"）**：R20 的 5G-A NTN 是一个 umbrella，除本报告的 **GNSS resilient NR-NTN**（NR 轨道、唯一 SI→WI、RAN1 主导）外，还并行挂着 **IoT_NTN_Ph4（含 Voice over NTN）、LTE_TN_NR_NTN_HO_enh** 共 2 个直接 WI——后两者属 **LTE/IoT NTN 轨道**（4G，TS 36.x，LTE RAN2 主导），不在本报告范围。R20 5G-A NTN 的「2+1」WI 全景与 NTN 双 RAT 划分，详见《R20_NTN_双线逻辑梳理_20260831.md》第 0.1 / 0.2 节。

---

## 第一部分　SI 立项（RP-251863，RAN#108 批准）

### 1.1 原文核心内容（SID：New SID）

| 字段 | 内容 |
|---|---|
| 会议 / 日期 | 3GPP TSG RAN Meeting **#108**，Prague, Czech Republic, **2025-06-09 ~ 13** |
| 文档号 | **RP-251863**（rev 过程稿曾用 RP-251933 / RP-251934 状态报告） |
| 来源 | Thales（Moderator：Mohamed El Jaafari） |
| 标题 | Study on GNSS resilient NR-NTN operation |
| 文档类型 | New SID（Study Item） |
| 议程项 | 15.1.5 Non-Terrestrial Networks (NTN) for NR Phase 4 |
| 目标 Release | **Rel-20** |
| 牵头/协作 WG | Primary **RAN1**，Secondary **RAN4** |
| Acronym（批准时） | `FS_NR_NTN_GNSS_resilient`（UID 1080071） |

**关联 Work/Study Item（依赖关系）：**
- `NR_NTN_solutions`（Rel-16/17，800099 / 860046）— 基础研究与基本上行同步流程
- `NR_NTN_enh`（Rel-18，941006）— NR NTN 增强
- `NR_NTN_Ph3`（Rel-19，1020097）— NR NTN Phase 3

**Justification（立项理由，原文摘录）：**
> UEs compatible with Rel-17/18/19 and supporting NTN access are expected to be equipped with GNSS … These UEs should support uplink time and frequency pre-compensation based on their GNSS-acquired position. The GNSS availability is therefore essential for NTN access … Additionally, GNSS availability may be useful for higher layer procedures such as location-based conditional handovers.
> However, GNSS information in UE may be **temporarily unavailable** or available but **degraded** … These occurrences are becoming more and more common and result in a 3GPP NTN service that is not very robust.
> The main reasons: potential GNSS **jamming** (denial of service); potential GNSS **spoofing** and other effects (poor geometry, local blockages, solar storm, or increased GNSS measurement period to save UE power); UE in adverse environment where NTN access is possible but GNSS signal too weak (link budget margin difference) … The dependency on GNSS renders the NR NTN system less resilient, as it relies on an external third-party system.

**Objective of Core part WI（SI 研究目标，原文）：**
> The study will be carried assuming that the GNSS information in UE with GNSS capability may be
> 1/ temporarily unavailable or 2/ available but with GNSS position accuracy degradation or 3/ available but with increased GNSS measurement period for power saving purpose.
> **This study will initially focus on 1/** (where GNSS information is temporarily unavailable).
> Note: This study does not include any enhancement on positioning for the above scenario.
> - Study GNSS resilient NR-NTN operation **[RAN1, RAN4]**
> - Assess impact on initial access and connected mode procedures for NR-NTN, including potential implications if any on RAN4 RRM specifications
> - Aim to **minimize physical layer procedures impact**
> - **Avoid physical layer channel/signal changes**
> - Backward compatible issues with legacy NTN capable UEs will be assessed and should be prevented
> - Applicable to NGSO and GSO constellations, NTN operating in below and above 10 GHz frequency bands, transparent and regenerative satellites
> - **Check in RAN#112 (June, 2026)** to decide whether to proceed with normative work, extend the study item, or postpone normative work to Release 21

**Expected Output（SI 产出）：** 一份 TR——"NR-NTN resiliency to unavailable-degraded GNSS"，for info **RAN#111**、for approval **RAN#112**。

**支持公司（Supporting IMs，节选）：** Thales, Airbus, Amazon, Ericsson, Eutelsat, Huawei, Inmarsat, Intelsat, Iridium, Qualcomm, Samsung, Sateliot, Viasat, ZTE, Xiaomi, Nokia, MediaTek, LG, Sharp, Skylo, Keysight 等（SID 列了约 50 家，覆盖卫星运营商、设备商、车企、科研机构）。

### 1.2 第一部分小结

- **为什么立这个 SI**：Rel-17/18/19 的 NR NTN 把"上行时间/频率预补偿"完全建立在 UE 自带 GNSS 之上；一旦 GNSS 不可用/被压制（干扰、欺骗、几何差、遮挡、太阳风暴、或为省电拉长轴测周期），UE 就无法正确算 TA/Doppler，导致 PRACH 失败或连接态失步。SI 的目标是**降低对 GNSS 的依赖、提升 NTN 韧性**，而非增强定位本身。
- **范围约束（很关键）**：① 先聚焦"GNSS 临时不可用"（场景 1），降级/省电场景留作后续；② **不改物理层信道/信号**，尽量小改物理层流程；③ 必须与存量 NTN UE 后向兼容；④ 覆盖 NGSO/GSO、<10GHz 与 >10GHz、透传与再生卫星。
- **这是 R20 中唯一新立的 NR-NTN 研究项**；检查点设在 **RAN#112（2026-06）**——届时决定"转 WI / 延长 SI / 推到 Rel-21"。后续事实：RAN#112 选择了**转 WI**。

---

## 第二部分　TR 38.742 研究（SI 的产出，v2.0.0 封板）

> TR 38.742 v2.0.0 即 SI 研究的最终结论文档，于 RAN#112 批准。章节结构：§4 动机、§5 假设与参数、§6 GNSS 临时不可用的影响评估、§7 候选方案评估、§8 结论与建议、Annex A 版本-会议变更史。

### 2.1 出发点与假设场景

**Scope（TR §1，原文摘录）：**
> This technical report addresses the study of GNSS resilient operation in NR-NTN, targeting Release 20 … ensure NR-NTN functionality in scenarios where GNSS **is temporarily unavailable** while maintaining service. The study specifically investigates the impact of GNSS temporary unavailability on **initial access and connected mode procedures** … aims to **minimize modifications to physical layer procedures and avoid any changes to physical layer channels and signals**. Maintaining **backward compatibility with legacy NTN-capable UEs** is a key requirement.
> The scope encompasses NR-NTN operating over both **NGSO and GSO** satellite constellations, spanning frequency bands **below and above 10 GHz**, and considering both **transparent and regenerative** satellite architectures.

**GNSS 假设状态（SI 目标定义的三类）：**
1. GNSS 信息**临时不可用**（SI 首要聚焦）；
2. GNSS 可用但**位置精度降级**；
3. GNSS 可用但为**省电拉长测量周期**。

**评估场景（来自 SI 协定，TR §5 采纳）：**
- 卫星轨道：**GSO / LEO-1200 / LEO-600**；波束尺寸取 TR 38.821 表 6.1.1.1-1/2 的值；
- 最小仰角：LEO 30°、GSO 12.5°；
- 频段：**FR1 NTN（2GHz / Ku 14GHz）与 FR2 NTN（30GHz）**；
- UE 类型：手持（L/S 频段）、VSAT（Ku/Ka）；UE 速度 3 / 120 / 1500 km/h（1500 为航空场景）；
- 波束/小区类型：（准）对地固定波束（Earth-fixed）与对地移动波束（Earth-moving）。

> 两个核心场景（SI 已锁定）：**Scenario 1**＝UE 无法依赖 GNSS 做服务链路上行时间/频率补偿；**Scenario 2**＝有历史 GNSS 位置但已一段时间 T 未更新、精度降级（T 值 FFS）。

### 2.2 影响评估（TR §6：GNSS 临时不可用到底造成什么）

**初始接入影响（§6.1）：**
- 推导了 **differential delay（单向/环回）与 differential Doppler（DL/UL 环回）** 的计算结果与限值；
- 给出各 **PRACH preamble 格式的 differential RTD 上限** 与 **differential Doppler 上限**（§6.1.3 / §6.1.4）；
- **NR PRACH 性能评估（§6.1.5）**：当 UE 无 GNSS 预补偿时，TA 与 Doppler 残差超出既有 PRACH 格式容限，导致随机接入检测概率下降——这是"GNSS 不可用→接入失败"的量化证据。

**连接态影响（§6.2）：**
- 方法学 + 评估指标（§6.2.1/2），**连接态评估结果（§6.2.3）**：无 GNSS 时 TA 漂移 / 频偏累积，若不校正会触发失步（out-of-sync）与 RLC/ MAC 重传恶化。

> 一句话：§6 把"GNSS 不可用"翻译成了**可量化的 PRACH 容限违规 + 连接态同步失稳**，为后面方案提供了"要解决到什么程度"的标尺。

### 2.3 技术方案分支（TR §7：候选方案 + 原理 + 收益空间）

TR §7 评估了两大类候选方案，并在 §7.3 做后向兼容评估、§7.4 做 RRM/RF/解调影响评估。**下方"是否进入 WID"依据 RAN1#126 的 6 条 Agreement 判定。**

#### A. 初始接入类候选方案（§7.1，编号 1A–1G）

| 方案分支 | 原理 | 收益空间 | 进入 WID？ |
|---|---|---|---|
| **1A 双 PRACH 序列**（同格式、不同根） | UE 发**两条 PRACH 前导**（不同根），扩大可容忍的 TA/Doppler 不确定窗口，使至少一条能被 gNB 解出；变体含共轭根分 RO / 同 RO 重叠 / 相位偏移(PSK)区分 / 非共轭根 / 不同格式 / 多参考位置或多公共 TA | 直接对冲"无 GNSS 预补偿导致 PRACH 失败"，恢复初始接入成功率 | **是**（WID A1；Ag5 选定 Alt1-4 基线，Ag6 继续研究 1A-1~1A-3 变体） |
| **1B TA 命令（Msg2/RAR）** | 网络在 RAR 里给**扩展量程的 TAC**，校正首传残差 timing | 首传后仍残差的 TA 被闭环拉回，避免后续失步 | **是**（WID A2/B1；Ag4） |
| **1C 频率调整命令 FAC（Msg2/RAR）** | RAR 携带 **FAC** 校正残差频偏 | 闭环校正频偏，提升后续 UL 解调 | **是**（WID A2/B4；Ag3） |
| **1D 参考位置法（对地固定小区）** | 网络下发**波束参考位置 + 卫星星历**，UE 自行算 TA/Doppler 做开环预补偿 | 无需 GNSS 即可获得接近准确的开环预补偿 | **是**（WID C1；Ag1） |
| **1E 辅助信息开环预补偿（变体）** | 网络提供辅助信息（assistance info）支撑开环预补偿 | 同上，配合 1D | **是**（WID C1） |
| **1F/1G 公共 TA/Doppler 信息法（对地移动小区）** | 网络下发**服务链路公共 TA/Doppler 信息**，UE 用于开环预补偿 | 对地移动波束下无 GNSS 时仍能预补偿 | **是**（WID C1；Ag2） |

#### B. 连接态类候选方案（§7.1.9–7.1.15，编号 2A–2F）

| 方案分支 | 原理 | 收益空间 | 进入 WID？ |
|---|---|---|---|
| **2A TA 控制（复用 NTN 既有闭环 TA）** | 连接态复用 legacy closed-loop TA for NTN | 复用既有机制、改动最小 | **是**（WID B1/B2） |
| **2B 隐式 FAC（针对 TA 漂移）** | 用 FAC 隐式校正 TA 漂移 | 漂移场景自动跟偏 | **是**（WID B3） |
| **2C 显式 FAC（连接态）** | 连接态显式下发频率调整命令 | 持续校正频偏 | **是**（WID B4） |
| **2D/2E/2F** | 连接态 TA/频控的其他细化变体 | 进一步细化校正策略 | 待 #126-bis 收敛（属 WID B 系列） |

#### C. 开环预补偿总框架（§7.2 / Solution 3）

- **Open-loop UL time/frequency pre-compensation**：UE 在无 GNSS 时，依据网络下发的**辅助信息 / 参考位置（对地固定）/ 公共 TA-Doppler（对地移动）/ 卫星星历**做开环预补偿；若仍有"最后已知 GNSS 位置且仍有效"，则直接用它做开环预补偿（WID C2）。
- 这是把 A 类（1D/1E/1F/1G）与 C 类串起来的**总思路**：网络侧给"位置/时序基准"，UE 侧据此替代 GNSS 完成预补偿。

**§7.4 RRM/RF/解调影响**：研究指出潜在影响落在 **TS 38.133（RRM）、TS 38.101-5（UE RF/性能）、TS 38.108（SAN RF）**，以及 PRACH/PUSCH 解调性能——这直接决定了 WID 的 Performance part 与受影响 TS 清单。

### 2.4 TR 结论（§8 Conclusion and recommendations）

TR §8 的结论被 WID 的 Justification 权威引用，核心如下（WID 原文）：
> Building on the completed study item FS_NR_NTN_GNSS_resilient, documented in **TR 38.742 v2.0.0**, RAN1 has identified a set of recommended enhancements to enable resilient NR-NTN operation in scenarios where GNSS information is unavailable, degraded, or unreliable. **The study concluded that enhancements for both initial access and connected mode are needed**, including mechanisms for **UE time/frequency pre-compensation, network-provided assistance information, enhanced PRACH transmission, and timing/frequency control procedures** adapted to GNSS-challenged conditions.
> In addition, the study identified potential impacts on **RRM, RF and demodulation requirements**, including aspects related to initial transmit timing, gradual and closed-loop timing/frequency correction, mobility and measurement requirements, initial frequency offset, and PRACH/PUSCH demodulation performance, with potential specification impacts in **TS 38.133, TS 38.101-5 and TS 38.108**.
> The study therefore provides **sufficient technical basis to progress to normative work for Rel-20** …

> 即：SI 结论 = "初始接入 + 连接态都需要增强"，并给出"开环预补偿 + 双 PRACH + Msg2 TAC/FAC + 连接态 TA/FAC 控制"的方案族，且确认对 RRM/RF/解调有影响——这整套**直接变成 WID 的目标**。

---

## 第三部分　WI scope（RP-261568，RAN#112 批准）

### 3.1 原文核心内容（WID：New WID）

| 字段 | 内容 |
|---|---|
| 会议 / 日期 | 3GPP TSG RAN Meeting **#112**，Singapore, **2026-06-08 ~ 11** |
| 文档号 | **RP-261568**（rev RP-261553） |
| 来源 | Thales（Moderator） |
| 标题 | GNSS (Global Navigation Satellite System) resilient NR-NTN (Non-Terrestrial Networks) operation |
| 文档类型 | New WID（Work Item） |
| 议程项 | 9.1.1 New WI/SI proposals for NR for REL-20 |
| Acronym | **NR_NTN_GNSS_resilient** |
| 牵头/协作 WG | Primary **RAN1**，Secondary **RAN4, RAN2** |
| Rapporteur | Lead: Mohamed El Jaafari (Thales, RAN1/RAN2/RAN4 core)；Co: Lingyu Gao (CATT, RAN4 performance) |

**关联（父/依赖）：** `FS_NR_NTN_solutions`(Rel-16)、`NR_NTN_solutions`(Rel-17)、`NR_NTN_enh`(Rel-18)、`NR_NTN_Ph3`(Rel-19)、`FS_NR_NTN_GNSS_resilient`(1080071，本 SI)。

**Justification（含 TR 结论引用，见第二部分 2.4）**——明确"基于已完成的 SI（TR 38.742 v2.0.0）转规范"。

**Objective of Core part WI（WID 核心目标，原文逐条）：**
> **For GNSS-resilient Initial Access in NR NTN,** specify:
> - Transmission of **two PRACH sequences** using the same existing PRACH format and different roots and any related MAC impact. **[RAN1, RAN2]**
> - **TA command and frequency adjustment command in Msg2.** **[RAN1] [RAN2]**
> - RRM requirements for initial transmit timing and frequency. **[RAN4]**
>
> **For GNSS resilient NR-NTN operation in Connected Mode,** specify:
> - **TA control** **[RAN1]**; Reuse of legacy closed-loop TA for NTN; Implicit (based on FAC) for TA drift; **Explicit frequency adjustment command (FAC) for connected mode.** **[RAN1] [RAN2]**
> - Study and specify if necessary RRM requirements: transmit timing, gradual timing adjustment, timing advance, frequency correction. **[RAN4]**
>
> **For both connected and idle mode,** specify the following enhancements:
> - For scenarios where UE cannot rely on its GNSS for timing and frequency compensation on the service link, **open-loop uplink time and frequency pre-compensation** at the UE based on **[RAN1, RAN2]**:
>   - Assistance information provided by network
>   - **Reference-location-based approach** for (quasi) Earth-fixed cell
>   - **Common TA/Doppler-information-based approach** for Earth-moving cell
>   - Satellite ephemeris
> - For scenarios where last known GNSS location is available and still sufficiently valid, this location is used for uplink open-loop time and frequency pre-compensation **[RAN1]**.
> - Study and specify, if necessary, **RF requirements for frequency error** for GNSS-resilient NR-NTN operation when the UE has frequency correction from the SAN **[RAN4]**
> - Specify changes to **mobility procedures**, if necessary **[RAN2]**
> - Existing RRM requirements for measurement used for cell reselection, HO, CHO and RRC connection mobility control are considered as the baseline and should be reused to the maximum extent. New RRM requirements can be considered, if justified **[RAN4]**
> - NOTE: backward compatibility and coexistence with legacy NTN capable UE should be guaranteed.

**Objective of Performance part WI（WID 性能目标）：**
> - Specify **demodulation performance requirements: PRACH, (if needed) PUSCH.** **[RAN4]**
> - Specify necessary **RRM performance requirements and test cases** corresponding to the core requirements. **[RAN4]**

**Impacted existing TS / TR（WID 受影响规范清单）：**

| TS/TR | 标题 | 完成全会 | 属性 |
|---|---|---|---|
| 38.211 | NR; Physical channels and modulation | RAN#114 | Core |
| 38.212 | NR; Multiplexing and channel coding | RAN#114 | Core |
| 38.213 | NR; Physical layer procedures for control | RAN#114 | Core |
| 38.214 | NR; Physical layer procedures for data | RAN#114 | Core |
| 38.300 | NR; Overall description; Stage-2 | RAN#115 | Core |
| 38.304 | NR; UE procedures in Idle / RRC Inactive | RAN#115 | Core |
| 38.306 | NR; UE radio access capabilities | RAN#115 | Core |
| 38.321 | NR; MAC protocol | RAN#115 | Core |
| 38.331 | NR; RRC protocol | RAN#115 | Core |
| 38.101-5 | NR; UE RF/performance, part 5 Sat | RAN#115 | Core |
| 38.133 | NR; RRM requirements | RAN#115 | Core |
| 38.101-5 / 38.133 / 38.108 / 38.181 | （Perf 部分） | RAN#117 | Perf |

**支持公司（节选）：** Thales, Airbus, Amazon, Apple, AST SpaceMobile, CATT, Ericsson, Eutelsat, Huawei, InterDigital, MediaTek, Nokia, Qualcomm, Samsung, Sateliot, Viasat, ZTE 等（WID 列约 35 家）。

### 3.2 第三部分小结

- **SI→WI 的映射非常直接**：TR §7 的方案族 = WID 的目标项。WID 把研究结论固化成 4 组可规范目标：**初始接入（A1–A3）/ 连接态（B1–B5）/ 空闲+连接开环预补偿（C1–C5）/ 性能（P1–P2）**。
- **责任划分清晰**：RAN1 主导物理层（PRACH 双序列、Msg2 TAC/FAC、开环预补偿、TA 控制）；RAN2 负责 MAC（双 PRACH 的 MAC 影响、Msg2 RAR 结构、移动性流程）；RAN4 负责 RRM/RF/解调性能（初始发射时序/频率、频偏 RF 要求、PRACH/PUSCH 解调、测试例）。
- **封版节奏**：Core part 规范在 **RAN#114 / RAN#115** 完成，Perf part 在 **RAN#117**。
- **后向兼容硬约束**：所有改动不得破坏存量 NTN UE（NOTE 明确写进 WID）。

---

## 第四部分　RAN1 基于 WID 的研究（按会议顺序）

> 进入 WID 规范阶段后，RAN1 按 WID 目标逐条推进。当前（2026-09）已发生 **RAN1#126（马斯特里赫特，2026-08-24~28）**，下一场 **RAN1#126-bis（韩国，2026-10-12~16）** 为收口会。

### 4.1 会议轴（WID 阶段）

| 会议 | 时间 / 地点 | 性质 | 主要内容 |
|---|---|---|---|
| RAN#112 | 2026-06 / Singapore | 全会批准 WID | WI `NR_NTN_GNSS_resilient` 立项（RP-261568） |
| **RAN1#126** | **2026-08-24~28 / Maastricht** | **WI 启动（首场 RAN1）** | **40 篇文稿，产出 6 条 Agreement + 2 组 Working Assumption** |
| RAN1#126-bis | 2026-10-12~16 / 韩国 | 收口（预定） | 待开：RO 决策、TAC/FAC 数值与粒度下选、RAN2 RAR、RAN4 RRM/RF |

### 4.2 RAN1#126 的 6 条 Agreement（原文）逐条映射到 WID 目标

**Agreement 1 — 对地固定小区开环预补偿（参考位置法）**
> For open-loop UL time/frequency pre-compensation on the service link in (quasi) Earth-fixed cells, for initial access support a **reference-location-based approach together with satellite ephemeris** where: for one SSB beam per cell, cell specific reference location is supported; for multiple SSB beams per cell, SSB beam specific reference location is supported; the association between reference location and the applicable SSB beam should be defined. (FFS: cell specific ref location in this case; FFS: multiple ref locations per SSB beam; signalling details separate proposal.)
→ **映射 WID：C1（Reference-location-based approach for (quasi) Earth-fixed cell + Satellite ephemeris）。状态：基线已定，信令细节 FFS。**

**Agreement 2 — 对地移动小区开环预补偿（公共 TA/Doppler 法）**
> For open-loop UL time/frequency pre-compensation on the service link in Earth-moving cells, for initial access support a **common TA/Doppler-information-based approach** where: cell specific / SSB beam specific common TA/Doppler on the service link is supported …
→ **映射 WID：C1（Common TA/Doppler-information-based approach for Earth-moving cell）。状态：基线已定。**

**Agreement 3 — Msg2/RAR 中的 FAC（频率调整命令）**
> For **frequency adjustment command (FAC) support in Msg2/RAR**, RAN1 is to consider: defining the FAC range to address at least the largest residual frequency errors reported in TR 38.742; defining the FAC granularity; supporting negative/positive FAC. It is up to RAN2 to decide whether a new MAC RAR is needed or the current RAR structure can be reused with extensions. (range/granularity values and unit discussed separately; indication of TAC and FAC jointly or not discussed separately.)
→ **映射 WID：A2（frequency adjustment command in Msg2）+ B4（Explicit FAC for connected mode）。状态：方向锁定，数值/粒度/RAR 结构 FFS。**

**Agreement 4 — Msg2/RAR 中的 TA 命令（TAC 扩展）**
> For **TA command in Msg2/RAR**, RAN1 to consider: Extending TAC range to address at least largest residual timing errors reported in TR 38.742; keep the current TA granularity as baseline; either negative/positive TAC or mitigated via higher-layer configured/predefined TA offset; RAN2 decides new MAC RAR or reuse; range/granularity values discussed separately.
→ **映射 WID：A2（TA command in Msg2）+ B1/B2（TA control / Reuse legacy closed-loop TA for NTN）。状态：方向锁定。**

**Agreement 5 — 双 PRACH 序列选定基线**
> For the solution involving **transmission of two PRACH sequences with the same existing PRACH format and different roots**, **Alt 1-4 is adopted as baseline**. (FFS: whether same RO and/or separate ROs in time domain can be used; decision next meeting.)
→ **映射 WID：A1（two PRACH sequences, same format, different roots）。状态：基线选定（Alt1-4），RO 配置 FFS。**

**Agreement 6 — 继续研究 Solution 1A 变体**
> Further study the following Solution 1A variants: **Variant 1A-1** (two PRACH sequences same format different roots: Alt1-1 conjugate-root different RACH occasions; Alt1-2 conjugate-root same time within one RO overlapping; Alt1-3 two-root with phase shift/PSK differentiation; Alt1-4 two-root not necessarily conjugate); **Variant 1A-2** (two PRACH sequences using different PRACH formats); **Variant 1A-3** (multiple PRACH sequences using multiple reference locations or common TAs/Dopplers on service link).
→ **映射 WID：A1（细化双 PRACH 序列的多种实现方式）。状态：继续研究，下会 down-select。**

**Working Assumptions（FAC 粒度，待下会收敛）：**
- WF1：FAC 粒度 = SCS×2^k，k 候选 {10 / 8 / 6}（其他值可议）；
- WF2：FAC 粒度候选 {0.01 ppm / 0.1 ppm / 0.05 ppm}（其他值可议）；
- FFS：定义 1 个还是多个粒度。

### 4.3 WID 目标 × RAN1#126 进展 总映射表

| WID 目标项 | 负责 WG | RAN1#126 进展 | 状态 |
|---|---|---|---|
| A1 双 PRACH 序列（同格式不同根） | RAN1/RAN2 | Ag5 选定 Alt1-4 基线；Ag6 继续研究 1A-1~1A-3 变体 | **已定基线，变体待收敛** |
| A2 Msg2 TA 命令 + FAC | RAN1/RAN2 | Ag4（TAC 扩量程）、Ag3（FAC 量程/粒度/正负） | **方向锁定，数值 FFS** |
| A3 初始发射时序/频率 RRM | RAN4 | 未在 #126 物理层协议会深入（RAN4 事项） | 待 RAN4 |
| B1/B2 连接态 TA 控制（复用闭环 TA） | RAN1 | Ag4 隐含覆盖（TAC 扩展 + 复用） | 进行中 |
| B3 隐式 FAC（TA 漂移） | RAN1 | 随 FAC 框架一并考虑 | 进行中 |
| B4 显式 FAC（连接态） | RAN1/RAN2 | Ag3 明确 | 方向锁定 |
| B5 连接态 RRM（时序/渐变/TA/频校） | RAN4 | RAN4 事项 | 待 RAN4 |
| C1 开环预补偿（辅助信息/参考位置/公共 TA-Doppler/星历） | RAN1/RAN2 | **Ag1（对地固定：参考位置法）、Ag2（对地移动：公共 TA-Doppler 法）** | **两法均定基线** |
| C2 最后已知 GNSS 位置仍有效时用于预补偿 | RAN1 | 纳入 C1 框架（WID 原文） | 基线 |
| C3 SAN 频校后的 UE 频偏 RF 要求 | RAN4 | RAN4 事项 | 待 RAN4 |
| C4 移动性流程改动（必要时） | RAN2 | 随 RAN2 RAR/流程 | 待 RAN2 |
| C5 复用既有 RRM（重选/HO/CHO） | RAN4 | 基线原则已写进 WID | 基线 |
| P1 PRACH/PUSCH 解调性能 | RAN4 | RAN4 Perf | 待 RAN4 |
| P2 RRM 性能要求 + 测试例 | RAN4 | RAN4 Perf | 待 RAN4 |

### 4.4 第四部分小结与 #126-bis 待办

- **RAN1#126 已完成"开环预补偿两条路线（Ag1/Ag2）+ 双 PRACH 基线（Ag5/Ag6）+ Msg2 TAC/FAC 方向（Ag3/Ag4）"的框架性锁定**，覆盖 WID 中 RAN1 主导的物理层主体。
- **尚未收敛、留待 RAN1#126-bis（2026-10 韩国）收口的事项**：
  1. 双 PRACH 的 **RO 配置**（同 RO 还是分 RO）——Ag5 的 FFS；
  2. **TAC 与 FAC 是否联合指示**、RAR 结构是否新建——RAN2 决策（Ag3/Ag4）；
  3. **FAC 粒度 / 量程 / 单位** 的 down-select（WF1/WF2）；
  4. **TAC 量程/粒度具体数值**；
  5. RAN4 侧的 **RRM/RF/解调性能**（A3/B5/C3/P1/P2）与既有规范的冲突评估与新增要求——这部分在 #126 物理层会上未展开，是 #126-bis 及之后 RAN4 的关键工作量。
- 整体节奏与 WID 封版目标一致：Core part 在 **RAN#114/115**、Perf part 在 **RAN#117** 完成。

---

## 附：关键文档与会议索引

| 文档/会议 | 编号 | 时间 | 角色 |
|---|---|---|---|
| SI 立项 | RP-251863（New SID） | RAN#108 / 2025-06 | SI 启动 |
| SI 状态报告 | RP-251934 | RAN#109 / 2025-09 | SI 进度（完成度 10%） |
| SI 产出 TR | TR 38.742 v2.0.0 | RAN#112 / 2026-06 批准 | SI 封板 |
| WI 立项 | RP-261568（New WID） | RAN#112 / 2026-06 | 转规范 |
| RAN1#125 FL#6 | R1-2603746 | SI 收口（v1.2.0） | SI 末段 |
| **RAN1#126 FL#1–6** | R1-2605604~09, R1-2606912 | 2026-08 Maastricht | **WI 启动，6 Agreement** |
| RAN1#126-bis | （预定） | 2026-10-12~16 韩国 | WI 收口（待开） |
