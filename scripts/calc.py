# -*- coding: utf-8 -*-
"""定量折算库 —— 供 3gpp-report-extension / skillctl calc 使用。

设计原则：
1. 只用标准库；不依赖 numpy/pandas，任何 python3 都能跑。
2. 每个函数都返回 dict（含 formula / assumptions），便于原文照贴进报告。
3. 全部按"覆盖"语义取整（ceil），与"量程至少要覆盖到多少"的工程语言一致。
"""

import math

# TS 38.211: Tc = 1/(480000 * 4096) s
TC_S = 1.0 / (480000 * 4096)
C_M_S = 3.0e8
LEGACY_TA_MULT = 16 * 64          # 16*64*Tc/2^mu
LEGACY_RAR_TAC_MAX = 3846         # 12 bit 字段，T_A 上限
LEGACY_RAR_TAC_BITS = 12


# 常量默认写在模块里；config.json 的 `constants` 段可覆盖（见 configure）。
# 两处同时存在的理由：脚本要能脱离 skillctl 单独 import 使用，配置要能被项目改写。
_CONSTANT_MAP = (
    ("Tc_s", "TC_S"),
    ("c_m_s", "C_M_S"),
    ("legacy_ta_mult", "LEGACY_TA_MULT"),
    ("legacy_rar_tac_max", "LEGACY_RAR_TAC_MAX"),
    ("legacy_rar_tac_bits", "LEGACY_RAR_TAC_BITS"),
)


def configure(constants=None):
    """用 config.json 的 `constants` 覆盖内置常量。

    为什么需要这一步：早先 config.json 里记了一份常量、calc.py 里又自带一份，
    而**只有 calc.py 那份参与计算** —— config.json 里的数字改了根本不生效，
    SKILL.md 却写着 config.json 是「机器可读的常量」。两份真值迟早漂移。
    现在由 skillctl 加载配置后调用本函数灌进来；只接受正数，坏值直接跳过。
    """
    if not constants:
        return {}
    applied = {}
    for cfg_key, mod_name in _CONSTANT_MAP:
        v = constants.get(cfg_key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            globals()[mod_name] = v
            applied[cfg_key] = v
    return applied


def _bits_cover(step_max):
    """覆盖 ±step_max 所需的 signed 位宽（补码：n 位可表示 -2^(n-1) .. 2^(n-1)-1）。

    注意是 `log2(step_max + 1)` 不是 `log2(step_max)`：n 位补码的**最大正数**是
    2^(n-1)-1（正数那一半要减 1），所以「能表示到 +step_max」要求
    2^(n-1)-1 >= step_max，即 n = ceil(log2(step_max+1)) + 1。

    用旧写法在 step_max 恰为 2 的整数次幂时会**少算 1 位**：
    step_max=2 → 旧给 2 位（可表示 -2..1，装不下 +2），正确是 3 位。
    这正是本技能铁律第 1 条最在意的那种「差 1 条也算错」。
    """
    step_max = max(1, int(step_max))
    return int(math.ceil(math.log2(step_max + 1))) + 1


def legacy_ta_gran_us(mu):
    """legacy TA 粒度（us）：16*64*Tc/2^mu。"""
    return LEGACY_TA_MULT * TC_S / (2 ** mu) * 1e6


def legacy_ta_max_us(mu):
    """legacy RAR TAC 的最大单向推进量（us）：T_A max * 粒度。"""
    return LEGACY_RAR_TAC_MAX * legacy_ta_gran_us(mu)


def tac_range(neg_us, pos_us=2 * 2903.6, mu_list=(0, 1, 2, 3)):
    """TAC 量程 -> 各 numerology 的位宽。

    neg_us / pos_us：负向/正向需要覆盖的最大量（us）。
    """
    rows = []
    for mu in mu_list:
        g = legacy_ta_gran_us(mu)
        n_pos = int(math.ceil(pos_us / g))
        n_neg = int(math.ceil(neg_us / g))
        rows.append({
            "mu": mu,
            "scs_khz": 15 * (2 ** mu),
            "gran_us": round(g, 6),
            "steps_pos": n_pos,
            "steps_neg": n_neg,
            "bits_signed": _bits_cover(max(n_pos, n_neg)),
        })
    span = neg_us + pos_us
    return {
        "formula": "gran=16*64*Tc/2^mu; steps=ceil(range/gran); bits=ceil(log2(steps))+1",
        "range_us": [-neg_us, pos_us],
        "span_us": round(span, 3),
        "legacy_single_side_us": round(legacy_ta_max_us(0), 3),
        "legacy_ratio": round(span / legacy_ta_max_us(0), 3),
        "rows": rows,
    }


def ppm(hz, fc_ghz):
    return hz / (fc_ghz * 1e9) * 1e6


def hz_from_ppm(p, fc_ghz):
    return p * 1e-6 * fc_ghz * 1e9


def fac_wf1(range_khz, k=8, scs_list=(15, 30, 60, 120), fc_ghz=30.0):
    """SCS-based 粒度（WF1）：gran = SCS/2^k。"""
    rows = []
    for scs in scs_list:
        gran_hz = scs * 1000.0 / (2 ** k)
        steps = int(math.ceil(range_khz * 1000.0 / gran_hz))
        rows.append({
            "scs_khz": scs,
            "gran_hz": round(gran_hz, 4),
            "gran_ppm": round(ppm(gran_hz, fc_ghz), 6),
            "steps": steps,
            "bits_signed": _bits_cover(steps),
        })
    return {
        "framework": "WF1",
        "formula": "gran = SCS/2^k; steps = ceil(range/gran); bits = ceil(log2(steps))+1",
        "k": k,
        "fc_ghz_for_ppm": fc_ghz,
        "range_khz": range_khz,
        "rows": rows,
    }


def fac_wf2(range_khz, p=0.01, fc_ghz=30.0):
    """PPM-based 粒度（WF2）：gran = p(ppm) * fc。"""
    gran_hz = hz_from_ppm(p, fc_ghz)
    steps = int(math.ceil(range_khz * 1000.0 / gran_hz))
    return {
        "framework": "WF2",
        "formula": "gran = p*1e-6*fc; steps = ceil(range/gran); bits = ceil(log2(steps))+1",
        "p_ppm": p,
        "fc_ghz": fc_ghz,
        "gran_hz": round(gran_hz, 4),
        "range_ppm": round(ppm(range_khz * 1000.0, fc_ghz), 4),
        "steps": steps,
        "bits_signed": _bits_cover(steps),
    }


def opt3_k(scs_khz, fc_ghz, target_ppm=0.01):
    """Option 3：k 取使 SCS/2^k 折算后 < target_ppm 的最小整数。

    用 while 循环而不是 `ceil(log2(need))`，有两个原因：
      1. 边界：need 恰为 2 的整数次幂时，`ceil(log2(64))=6` 给出的 k=6 使
         gran 恰好等于 target，严格小于不成立 —— 旧实现会返回一个
         **自己都判定为不满足**的 k_min（自相矛盾）。正确值是 7。
      2. 浮点：`log2` 在幂次边界上可能给出 5.9999999 或 6.0000001，取整方向不可靠。
    循环直接按定义判 `gran < target`，没有这两类误差。
    """
    target_hz = target_ppm * 1e-6 * fc_ghz * 1e9
    scs_hz = scs_khz * 1000.0
    k = 0
    while scs_hz / (2 ** k) >= target_hz and k < 64:   # 上限防呆，正常几步就退出
        k += 1
    gran_hz = scs_khz * 1000.0 / (2 ** k)
    return {
        "formula": "k = ceil(log2(SCS / (target_ppm*1e-6*fc)))",
        "scs_khz": scs_khz,
        "fc_ghz": fc_ghz,
        "target_ppm": target_ppm,
        "k": k,
        "gran_hz": round(gran_hz, 4),
        "gran_ppm": round(ppm(gran_hz, fc_ghz), 6),
        "satisfies": ppm(gran_hz, fc_ghz) < target_ppm,
    }


def opt3_table(cases, target_ppm=0.01, forced_k=8):
    """Option 3 不相容性检查表：若强制定 k=forced_k 会怎样。"""
    out = []
    for fc_ghz, scs_khz in cases:
        r = opt3_k(scs_khz, fc_ghz, target_ppm)
        gran_forced = scs_khz * 1000.0 / (2 ** forced_k)
        out.append({
            "fc_ghz": fc_ghz,
            "scs_khz": scs_khz,
            "k_min": r["k"],
            "gran_ppm_at_k_min": r["gran_ppm"],
            "gran_ppm_if_k_forced": round(ppm(gran_forced, fc_ghz), 6),
            "forced_satisfies": ppm(gran_forced, fc_ghz) < target_ppm,
        })
    return {
        "formula": "k_min = ceil(log2(SCS/(target*1e-6*fc)))",
        "target_ppm": target_ppm,
        "forced_k": forced_k,
        "rows": out,
    }


def pos_timing(x_m, mu=0):
    """位置量化误差 -> 环回定时误差 -> 折合 legacy TA 步数。"""
    one_way_ns = x_m / C_M_S * 1e9
    rt_ns = 2 * one_way_ns
    g = legacy_ta_gran_us(mu) * 1000.0  # ns
    return {
        "formula": "t_rt = 2*x/c; steps = t_rt / (16*64*Tc/2^mu)",
        "x_m": x_m,
        "one_way_ns": round(one_way_ns, 2),
        "round_trip_ns": round(rt_ns, 2),
        "ta_steps_at_mu": {str(m): round(rt_ns / (legacy_ta_gran_us(m) * 1000.0), 3) for m in (0, 1, 2, 3)},
        "ta_steps_mu0": round(rt_ns / g, 3),
    }


def pos_doppler(x_m, fc_ghz=30.0, v_kmps=7.56, slant_km=600.0):
    """位置量化误差 -> 多普勒误差（量级估算）。

    灵敏度约 (fc/c)*(v/d)：横向单位向量对角位置的偏导。
    """
    sens = (fc_ghz * 1e9 / C_M_S) * (v_kmps * 1000.0 / (slant_km * 1000.0))
    return {
        "formula": "sens ≈ (fc/c)*(v/d); df = sens * x",
        "x_m": x_m,
        "fc_ghz": fc_ghz,
        "v_kmps": v_kmps,
        "slant_km": slant_km,
        "sens_hz_per_m": round(sens, 4),
        "df_hz": round(sens * x_m, 1),
    }


def fac_step_hz(scs_khz=15, k=8):
    return scs_khz * 1000.0 / (2 ** k)


def all_tables():
    """默认全套（与 RAN1#126b 报告 §4.8 一致，参数可在 CLI 覆盖）。"""
    return {
        "tac": tac_range(2903.6, 2 * 2903.6),
        "wf1": fac_wf1(127.08, k=8, fc_ghz=30.0),
        "wf2_ka": fac_wf2(127.08, 0.01, 30.0),
        "wf2_s": fac_wf2(15.444, 0.01, 2.0),
        "wf1_s": fac_wf1(15.444, k=8, scs_list=(15, 30), fc_ghz=2.0),
        "opt3": opt3_table([(30.0, 15), (30.0, 30), (30.0, 60), (30.0, 120), (2.0, 15), (2.0, 30)]),
        "pos_timing": [pos_timing(x) for x in (20, 50, 150)],
        "pos_doppler": [
            pos_doppler(x, 30.0, 7.56, 600.0) for x in (20, 150)
        ],
    }
