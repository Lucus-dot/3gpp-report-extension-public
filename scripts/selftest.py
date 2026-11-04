# -*- coding: utf-8 -*-
"""自检：用合成夹具验证 doclint 的新校验能真的抓到问题。

用法： python scripts/selftest.py
退出码 0 = 全部通过。

为什么要这个：`check` 的「允许通过」很容易验证（跑一份合格稿子即可），
「该抓的能不能抓住」却不会自然暴露 —— 写错正则、写错分支，结果都是 PASS。
这里对每条新校验构造一个「必须报错」的样本。
"""

import io
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import doclint    # noqa: E402
import skillctl   # noqa: E402

H1 = "# 某 WI 深度调研报告（四段式）"
SECS = ["§4.5", "§4.6", "§4.7", "§4.8", "§4.9", "§4.10", "§4.11", "§4.12",
        "附录 A", "附录 B"]

WI_SECTION_OK = """
### 4.7.1　A1｜双 PRACH（本场：CONTINUE）

**① 基线原状**
> 基线已定 Alt1-4 为 baseline。

**② 本次进展**

**【原文】Ag1（FL#1，Issue#2-1）**
> For GNSS-resilient ... separate ROs in the time domain.

**【解读】**
1. 裁定了 TDM。

**【映射】** WI **A1**｜TS 38.211

**③ 演进分析**
基线只定方法，本场定了传输域。

**④ 遗留**
FFS: Other details
"""


def build_doc(body):
    parts = [H1, "", "## 续篇：RAN1#127 扩展（议程项 9.4.1）", "", body, ""]
    for s in SECS:
        parts.extend(["## %s　占位节" % s, "", "占位正文，防止被判为空章节。", ""])
    return "\n".join(parts)


def run_check(doc_text, rel_entries=None, base_text=None, eom_text=None):
    d = tempfile.mkdtemp(prefix="selftest_")
    try:
        doc = os.path.join(d, "doc.md")
        with io.open(doc, "w", encoding="utf-8", newline="") as f:
            f.write(doc_text)
        base = None
        if base_text:
            base = os.path.join(d, "base.md")
            with io.open(base, "w", encoding="utf-8", newline="") as f:
                f.write(base_text)
        eom = None
        if eom_text:
            eom = os.path.join(d, "_eom.txt")
            with io.open(eom, "w", encoding="utf-8", newline="") as f:
                f.write(eom_text)
        wd = os.path.join(d, "_work_9_4_1")
        os.makedirs(wd)
        if rel_entries is not None:
            with io.open(os.path.join(wd, "rel.json"), "w", encoding="utf-8") as f:
                json.dump({"entries": rel_entries}, f, ensure_ascii=False)
        return doclint.check(doc, SECS, [], base_report=base, eom=eom, workdir=wd)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _has(res, needle):
    return any(needle in e for e in res["errors"])


# --------------------------------------------------------------------------
# 每条 case 返回 (是否通过, 失败时的说明)
# --------------------------------------------------------------------------
def t_ok():
    r = run_check(build_doc(WI_SECTION_OK),
                  [{"wi": "A1", "kind": "CONTINUE", "base_ref": ""}])
    return (not r["errors"], " | ".join(r["errors"]))


def t_h1_not_copied():
    r = run_check(build_doc(WI_SECTION_OK).replace(H1, "# 我自己起的标题"),
                  [{"wi": "A1", "kind": "CONTINUE"}],
                  base_text=H1 + "\n\n## 第一部分　X\n")
    return (_has(r, "H1 未抄基线"), " | ".join(r["errors"]))


def t_block_dup():
    r = run_check(build_doc(WI_SECTION_OK + WI_SECTION_OK),
                  [{"wi": "A1", "kind": "CONTINUE"}])
    return (_has(r, "块重复出现"), " | ".join(r["errors"]))


def t_ag_gap():
    r = run_check(build_doc(WI_SECTION_OK.replace("Ag1", "Ag2")),
                  [{"wi": "A1", "kind": "CONTINUE"}])
    return (_has(r, "编号不连续"), " | ".join(r["errors"]))


def t_missing_part():
    r = run_check(build_doc(WI_SECTION_OK.replace("**③ 演进分析**", "**（缺）**")),
                  [{"wi": "A1", "kind": "CONTINUE"}])
    return (_has(r, "缺段"), " | ".join(r["errors"]))


def t_no_kind():
    r = run_check(build_doc(WI_SECTION_OK), [{"wi": "A1", "kind": ""}])
    return (_has(r, "未判关系类型"), " | ".join(r["errors"]))


def t_derived_no_ref():
    r = run_check(build_doc(WI_SECTION_OK), [{"wi": "A1", "kind": "DERIVED"}])
    return (_has(r, "base_ref"), " | ".join(r["errors"]))


def t_entry_no_section():
    r = run_check(build_doc(WI_SECTION_OK),
                  [{"wi": "A1", "kind": "CONTINUE"}, {"wi": "A2", "kind": "NEW"}])
    return (_has(r, "没有独立小节"), " | ".join(r["errors"]))


# WA 块在正文里必然出现两次字符串：一次是 `**WA1｜标题**`（块标题），一次是
# `【原文】WA1`（块标签）。第一版计数用 findall 直接数，2 条 WA 被数成 4 条，
# 块数对账就报"产物 16 条 / 锚点 14 条"。这条用例锁住去重。
WA_DOC = WI_SECTION_OK + """
**WA1｜TAC 量程**　<sub>FL#1 · Issue#2-6</sub>

**【原文】WA1（FL#1，Issue#2-6）**
> The value range for TAC in msg2 should cover at least this range: [ −2903.6 µs .. +2×2903.6 µs ]

**【解读】**
1. 量程暂定，可缩减。

**【映射】** WI **A2**
"""
WA_EOM = ("R1-2607812\tFL Summary #1: X\tModerator (Thales)\n\n"
          "Agreement:\nAAA BBB CCC DDD EEE FFF.\n\n"
          "Working assumption:\nIII JJJ KKK LLL MMM NNN.\n")


def t_wa_dedup():
    r = run_check(build_doc(WA_DOC), [{"wi": "A1", "kind": "CONTINUE"}],
                  eom_text=WA_EOM)
    s = r["stats"]
    bad = [e for e in r["errors"] if "块数不自证" in e]
    ok = (not bad) and s.get("warnings_count") == 1
    return (ok, "WA 计为 %s 条；%s" % (s.get("warnings_count"), " | ".join(r["errors"])))


def t_rel_apply_dup():
    """rel --apply 必须抓出「同一个块挂到两个条目」——这正是块数守恒的判定层入口。"""
    d = tempfile.mkdtemp(prefix="selftest_rel_")
    try:
        flow = {"flows": [{"block_id": "Ag1", "issue": "Issue#2-1"},
                          {"block_id": "Ag2", "issue": "Issue#2-2"}]}
        rel = {"entries": [{"wi": "A1", "kind": "", "blocks": ["Ag1", "Ag2"]},
                           {"wi": "A2", "kind": "", "blocks": []}]}
        patch = {"entries": [{"wi": "A1", "kind": "CONTINUE", "blocks": ["Ag1", "Ag2"]},
                             {"wi": "A2", "kind": "CONTINUE", "blocks": ["Ag1"]}]}
        for name, obj in (("flow.json", flow), ("rel.json", rel), ("patch.json", patch)):
            with io.open(os.path.join(d, name), "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False)
        rc = skillctl._rel_apply(os.path.join(d, "flow.json"),
                                 os.path.join(d, "flow.json"),
                                 d, "", os.path.join(d, "patch.json"), True)
        return (rc == 1, "退出码 %s（期望 1：块重复应被拦下）" % rc)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 工具层 ----------------
V = ("R1-2607812\tFL Summary #1: X\tModerator (Thales)\n\n"
     "Agreement:\nAAA BBB CCC DDD.\nFFS: xxx\n\n"
     "R1-2607814\tFL Summary #3: X\tModerator (Thales)\n\n"
     "Agreement:\nEEE FFF GGG HHH.\n\n"
     "Working assumption:\nIII JJJ KKK LLL.\n")


def t_blocks_basic():
    b, _seps = skillctl.build_blocks(V)
    got = [(x["id"], x["fl_round"]) for x in b]
    want = [("Ag1", 1), ("Ag2", 3), ("WA1", 3)]
    return (got == want, str(got))


def t_blocks_ffs():
    b, _seps = skillctl.build_blocks(V)
    return (b[0]["ffs"] == ["xxx"], str(b[0]["ffs"]))


def t_overlap():
    same = skillctl._overlap("alpha beta gamma delta",
                             "alpha beta gamma delta")
    contain = skillctl._overlap("alpha beta gamma delta",
                               "xx alpha beta gamma delta yy")
    diff = skillctl._overlap("alpha beta gamma delta", "zeta eta theta iota")
    # 同文 = 1；被更长文本包含时 <1（余弦压掉膨胀）；无关 = 0
    return (abs(same - 1.0) < 1e-9 and 0.0 < contain < 1.0 and diff == 0.0,
            "%s / %s / %s" % (same, contain, diff))


def _mk_compose_env(doc_body=None):
    """造一套 compose 的输入：blocks.json / rel.json / 一份带 §4.7 的续篇。"""
    d = tempfile.mkdtemp(prefix="selftest_compose_")
    blocks = {"blocks": [
        {"id": "Ag1", "kind": "agreement", "text": "AAA BBB CCC", "fl_round": 1, "ffs": ["xxx"]},
        {"id": "Ag2", "kind": "agreement", "text": "DDD EEE FFF", "fl_round": 3, "ffs": []},
    ]}
    rel = {"entries": [
        {"wi": "A1", "title": "甲", "kind": "CONTINUE", "blocks": ["Ag1", "Ag2"]},
        {"wi": "A2", "title": "乙", "kind": "CONTINUE", "blocks": []},
        {"wi": "B3", "title": "丙", "kind": "CONTINUE", "blocks": [], "covered_by": "A1"},
    ]}
    for name, obj in (("blocks.json", blocks), ("rel.json", rel)):
        with io.open(os.path.join(d, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
    body = doc_body if doc_body is not None else "**② 本次进展**\n\n**`【原文】`** <AgN>\n> 占位\n\n"
    doc = ("# 标题\n\n## §4.7　按 WI 条目的本场进展\n\n" + body +
           "\n## §4.8　占位\n\n占位正文。\n")
    tgt = os.path.join(d, "doc.md")
    with io.open(tgt, "w", encoding="utf-8", newline="") as f:
        f.write(doc)
    return d, tgt


def t_compose_blocks_once():
    d, tgt = _mk_compose_env()
    try:
        rc = skillctl.cmd_compose(os.path.join(d, "rel.json"),
                                  os.path.join(d, "blocks.json"),
                                  tgt, "", "4.7", True)
        txt = io.open(tgt, encoding="utf-8").read()
        labs = re.findall(r"【原文】((?:Ag|WA)\d+)", txt)
        ok = (rc == 0 and labs == ["Ag1", "Ag2"]
              and txt.count("**① 基线原状**") == 3
              and txt.count("**④ 遗留**") == 3)
        return (ok, "rc=%s labs=%s 四段=%d" % (rc, labs, txt.count("**① 基线原状**")))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_compose_idempotent():
    # 用「有块」的正文跑：空标签夹具压根不生成块，测不到块标题被重复复制。
    d, tgt = _mk_compose_env(
        "### 4.7.1　A1｜甲（本场：CONTINUE，2 块）\n\n"
        "**① 基线原状**\n基线。\n\n"
        "**② 本次进展**\n\n"
        "**Ag1｜块的标题**　<sub>FL#1 · Issue#2-7</sub>\n\n"
        "**`【原文】Ag1`**\n> AAA BBB CCC\n\n"
        "**`【解读】`**\n解读。\n\n"
        "**`【映射】`** WI **A1**｜预估受影响：TS 38.211\n\n"
        "**③ 演进分析**\n演进。\n\n"
        "**④ 遗留**\n- 无。\n")
    try:
        for _ in range(2):
            skillctl.cmd_compose(os.path.join(d, "rel.json"),
                                 os.path.join(d, "blocks.json"), tgt, "", "4.7", True)
        a = io.open(tgt, encoding="utf-8").read()
        skillctl.cmd_compose(os.path.join(d, "rel.json"),
                             os.path.join(d, "blocks.json"), tgt, "", "4.7", True)
        b = io.open(tgt, encoding="utf-8").read()
        # 重跑不应该多出分隔线或块标题
        return (a == b, "重跑后 %d → %d 字符" % (len(a), len(b)))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_compose_preserve():
    """已写好的解读/映射/块标题，重排后必须一字不差地留下。"""
    body = ("### 4.7.1　A1｜甲（本场：CONTINUE，2 块）\n\n"
            "**① 基线原状**\n基线已定 X。\n\n"
            "**② 本次进展**\n\n"
            "**Ag1｜块的标题**　<sub>FL#1 · Issue#1-1</sub>\n\n"
            "**`【原文】Ag1`**\n> AAA BBB CCC\n\n"
            "**`【解读】`**\n1. 我的解读不能丢。\n\n"
            "**`【映射】`** WI **A1**｜预估受影响：TS 38.211\n\n"
            "**③ 演进分析**\n我的演进行。\n\n"
            "**④ 遗留**\n- 我的遗留。\n")
    d, tgt = _mk_compose_env(body)
    try:
        skillctl.cmd_compose(os.path.join(d, "rel.json"),
                             os.path.join(d, "blocks.json"), tgt, "", "4.7", True)
        txt = io.open(tgt, encoding="utf-8").read()
        need = ["我的解读不能丢", "TS 38.211", "我的演进行", "我的遗留", "基线已定 X", "**Ag1｜块的标题**"]
        miss = [n for n in need if n not in txt]
        return (not miss, "丢了：%s" % miss if miss else "6 处全部保留")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_compose_keeps_sub():
    """块标题 `<sub>` 里带着 Issue 归属，重排不能把它退化成只有 `FL#n`。

    `Issue#x-y` 来自 B2 的 flow 判定，blocks.json 里没有；用算出来的轮次重建
    sub 会把手写的溯源标注抹平——正是 compose 第一版踩过的坑。
    """
    body = ("### 4.7.1　A1｜甲（本场：CONTINUE，2 块）\n\n"
            "**① 基线原状**\n基线。\n\n"
            "**② 本次进展**\n\n"
            "**Ag1｜块的标题**　<sub>FL#1 · Issue#2-7</sub>\n\n"
            "**`【原文】Ag1`**\n> AAA BBB CCC\n\n"
            "**`【解读】`**\n解读。\n\n"
            "**`【映射】`** WI **A1**｜预估受影响：TS 38.211\n\n"
            "**③ 演进分析**\n演进。\n\n"
            "**④ 遗留**\n- 无。\n")
    d, tgt = _mk_compose_env(body)
    try:
        for _ in range(2):                    # 跑两遍：退化只在第二轮才暴露
            skillctl.cmd_compose(os.path.join(d, "rel.json"),
                                 os.path.join(d, "blocks.json"), tgt, "", "4.7", True)
        txt = io.open(tgt, encoding="utf-8").read()
        kept = "<sub>FL#1 · Issue#2-7</sub>" in txt      # Ag1：沿用正文的带 Issue 版
        fb = "<sub>FL#3</sub>" in txt                    # Ag2：正文没有，回退到算出的轮次
        return (kept and fb and txt.count("<sub>") == 2,
                "sub %d 处 / 保管=%s / 回退=%s" % (txt.count("<sub>"), kept, fb))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_compose_dup_block():
    d, tgt = _mk_compose_env()
    try:
        p = os.path.join(d, "rel.json")
        rel = json.load(io.open(p, encoding="utf-8"))
        rel["entries"][1]["blocks"] = ["Ag1"]      # Ag1 同时挂在 A1 与 A2
        json.dump(rel, io.open(p, "w", encoding="utf-8"), ensure_ascii=False)
        rc = skillctl.cmd_compose(p, os.path.join(d, "blocks.json"), tgt, "", "4.7", True)
        return (rc == 1, "退出码 %s（期望 1）" % rc)
    finally:
        shutil.rmtree(d, ignore_errors=True)


BASE_TXT = ("# 基线标题\n\n## 第一部分　甲\n\n### 1.1 甲一\n\n"
            "## 第三部分　丙（按会议顺序）\n\n### 3.4 丙末\n\n"
            "## 4.3 WID 目标 × 进展 总映射表\n\n"
            "| WID 目标项 | 负责 WG | 进展 | 状态 |\n|---|---|---|---|\n"
            "| A1 双 PRACH | RAN1 | Ag5 | 定基线 |\n"
            "| B1/B2 连接态 TA | RAN1 | — | 进行中 |\n")



def _mk_base():
    d = tempfile.mkdtemp(prefix="selftest_base_")
    p = os.path.join(d, "base.md")
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(BASE_TXT)
    return p


def t_base_h1_part():
    r = skillctl.read_base(_mk_base())
    return (r["h1"] == "基线标题" and "第三部分" in r["part_line"],
            "%s / %s" % (r["h1"], r["part_line"]))


def t_base_wid():
    r = skillctl.read_base(_mk_base())
    codes = [e["code"] for e in r["wid"]]
    return (codes == ["A1", "B1/B2"], str(codes))


CASES = [
    ("合格稿：0 error", t_ok),
    ("H1 未抄基线 → 报错", t_h1_not_copied),
    ("块重复出现 → 报错", t_block_dup),
    ("Ag 编号跳号 → 报错", t_ag_gap),
    ("WI 条目缺「演进分析」→ 报错", t_missing_part),
    ("WI 条目没判 kind → 报错", t_no_kind),
    ("DERIVED 缺 base_ref → 报错", t_derived_no_ref),
    ("WA 块不被数成两条（块数对账仍通过）", t_wa_dedup),
    ("rel --apply 抓出块挂两处", t_rel_apply_dup),
    ("rel 有条目但正文无小节 → 报错", t_entry_no_section),
    ("切块：2 Ag + 1 WA 且轮次 #1/#3/#3", t_blocks_basic),
    ("切块：FFS 抽取", t_blocks_ffs),
    ("n-gram：同文=1.0 / 异文=0", t_overlap),
    ("骨架：H1 与「第N部分」抄基线", t_base_h1_part),
    ("骨架：WI 条目表含 B1/B2 合并行", t_base_wid),
    ("compose：每块一次 + 四段齐全", t_compose_blocks_once),
    ("compose：重跑幂等（不多出分隔线/标题）", t_compose_idempotent),
    ("compose：已写的解读/映射/演进/遗留全部留住", t_compose_preserve),
    ("compose：块标题 <sub> 的 Issue 归属不被抹掉", t_compose_keeps_sub),
    ("compose：块挂两处 → 拒绝组装", t_compose_dup_block),
]


def main():
    ok, fail = 0, []
    for name, fn in CASES:
        try:
            good, detail = fn()
        except Exception as e:                       # noqa: BLE001
            good, detail = False, "%s: %s" % (type(e).__name__, e)
        if good:
            ok += 1
            print("  ✓ %s" % name)
        else:
            fail.append(name)
            print("  ✗ %s  → %s" % (name, detail))
    print("\n%d/%d 通过" % (ok, len(CASES)))
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
