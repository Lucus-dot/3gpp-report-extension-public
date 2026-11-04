# -*- coding: utf-8 -*-
"""交付物结构校验（doclint）——供 skillctl check 使用。

只做「机械可判定」的检查，不做文学评价。四类：
  A. 骨架：必需章节是否齐全、编号是否续接
  B. 标注：每条 Agreement 是否具备 原文/解读/映射 三块；折算标记是否成对
  C. 表格：Markdown 表格列数是否一致（最容易出错的排版项）
  D. 禁忌：占位符残留、已知错误写法、计数沿用
"""

import hashlib
import io
import os
import re
import unicodedata

TBL_PLACEHOLDER = "\x00PIPE\x00"
RE_DECLARED_COUNT = re.compile(r"(\d+)\s*篇公司贡献")

# ---------------------------------------------------------------------------
# 主席报告块数对账（铁律 1「不合并」的机器可判部分）
#
# 铁律 1 说「差 1 条也算错」，但一直没有任何代码能验这件事 —— check 从不读主席
# 报告，SKILL.md 却把「N = 主席报告切分块数」列在「机器可判」清单里。这句是**虚标**。
# 现在 check 可以接收 `--eom <逐字文本>`，按锚点逐块计数，与产物里的 AgN/WA 对账。
#
# 锚点只认行首的 `Agreement:` / `Working assumption`：主席报告正文里出现
# "reached agreement on" 之类的叙述不会被误数。
# ---------------------------------------------------------------------------
RE_EOM_AG = re.compile(r"(?m)^[ \t]*Agreement[ \t]*:")
RE_EOM_WA = re.compile(r"(?mi)^[ \t]*Working[ \t]+assumption[ \t]*:?")
# 产物侧【原文】块的起始写法（见 references/01-skeleton.md）：
#     **`【原文】`**
# 只认这种独占一行的块起始，否则正文里解释标记用法的句子也会被当成块。
RE_ORIGIN_START = re.compile(
    # 两种写法都认：
    #   **`【原文】`**            旧式（Ag 是标题，块内不重标号）
    #   **`【原文】Ag1`**         新式（按 WI 分节后 Ag 不再当标题，只能标在块上）
    # 整行吃掉，m.end() 落在「原文正文」上，溯源探针才不会把块号也算进去。
    r"(?m)^[ \t]*\*\*[ \t]*`?【原文】[ \t]*(?:(?:Ag|WA)\s*\d+)?[ \t]*`?[ \t]*\*\*[ \t]*$")
RE_MARK_ANY = re.compile(r"【[^】]{1,4}】")


def _norm_for_match(s):
    """把两侧文本压成可比较的形态：全角转半角、去排版标记、去标点与空白。

    只用于「这句话在不在原文里」的定位，不用于语义判断。保留字母数字与汉字。
    """
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"[`*_#>|\s]+", " ", s)
    s = re.sub(r"[，。；：、（）()\[\]【】…—\-–—·]", "", s)
    return s.strip()


def _roster_check(lines):
    """铁律「计数自证」的机器可判部分：文中声明的篇数 vs 花名册实际条目数。

    为什么不用正则查字面量：config.json 里原先那条
    `共 \\d+ 篇公司贡献（非 ?40` 带一段必须出现的字面量，**从不命中**；
    而把它改成 `共?\\s*\\d+\\s*篇公司贡献` 又会误伤两类正确写法 ——
    标题「41 篇公司贡献（按主席报告 tdoc 列表顺序）」、以及附录 B 里
    引用旧错值的更正行。真正该判的是**声明的数字与花名册条数对不对得上**，
    这正是 03-pitfalls P2 自己写的校验（"花名册行数 × 2 = 文中声明篇数"）。
    """
    decl, decl_line = None, None
    for i, l in enumerate(lines):
        if not l.lstrip().startswith("#"):
            continue
        m = RE_DECLARED_COUNT.search(l)
        if m:
            decl, decl_line = int(m.group(1)), i + 1
            break
    if decl is None:
        return {}

    i = decl_line
    while i < len(lines) and not lines[i].strip().startswith("|"):
        i += 1
    rows = []
    while i < len(lines) and lines[i].strip().startswith("|"):
        rows.append(lines[i])
        i += 1
    if not rows:
        return {"roster_declared": decl}

    entries = 0
    tdoc_cols = [k for k, c in enumerate(_split_row(rows[0]))
                 if "tdoc" in c.lower()]
    if not tdoc_cols:
        # 表头里没有 TDoc 列，说明紧跟标题的不是花名册（可能是别的索引表）——
        # 这时硬数就会把无关表格的数当成花名册条数，宁可跳过。
        return {"roster_declared": decl, "roster_declared_line": decl_line}
    for r in rows[1:]:                       # 跳过表头
        cells = _split_row(r)
        if not cells:
            continue
        if all(x == "" for x in cells):
            continue
        if all(re.fullmatch(r":?-{2,}:?", x) for x in cells if x):
            continue                          # 分隔行
        # 只数「表头写着 TDoc 的那几列」：4 列压缩排版（TDoc|公司|TDoc|公司）每行两组，
        # 逐篇索引表（#|TDoc|公司|立场）每行一组，用同一套规则都算得对。
        entries += sum(1 for k in tdoc_cols if k < len(cells) and cells[k].strip())
    return {"roster_declared": decl, "roster_entries": entries,
            "roster_declared_line": decl_line}


def _read(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def _md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def _eom_audit(text, eom_text):
    """主席报告块数对账 + 原文块可溯源。

    返回：
      anchors    主席报告里 Ag / WA 的块数（按行首锚点计）
      blocks     产物里 `**`【原文】`**` 块的实际个数
      trace_bad  [(序号, 前若干字)] 在逐字文本里定位不到的原文块
    """
    n_ag = len(RE_EOM_AG.findall(eom_text))
    n_wa = len(RE_EOM_WA.findall(eom_text))

    starts = [m.end() for m in RE_ORIGIN_START.finditer(text)]
    neom = _norm_for_match(eom_text)
    trace_bad = []
    for i, pos in enumerate(starts, 1):
        seg = text[pos:]
        m = RE_MARK_ANY.search(seg)
        if m:
            seg = seg[:m.start()]
        # 原文块到小节边界即止
        for cut in ("\n### ", "\n## ", "\n---"):
            k = seg.find(cut)
            if k >= 0:
                seg = seg[:k]
        n = _norm_for_match(seg)
        if len(n) < 12:
            continue                       # 空块/占位，由别的检查管
        probe = n[:45]
        if probe not in neom:
            trace_bad.append((i, probe))
    return {"eom_agreements": n_ag, "eom_was": n_wa, "eom_blocks": n_ag + n_wa,
            "origin_blocks": len(starts), "trace_bad": trace_bad}


def _split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    s = s.replace("\\|", TBL_PLACEHOLDER)
    return [c.strip().replace(TBL_PLACEHOLDER, "|") for c in s.split("|")]


def check(path, required_sections=None, forbidden=None,
          base_report=None, base_mtime=None, base_md5=None, eom=None, workdir=None):
    res = {"file": os.path.abspath(path), "errors": [], "warnings": [], "stats": {}}
    if not os.path.isfile(path):
        res["errors"].append("文件不存在：%s" % path)
        return res

    text = _read(path)
    lines = text.splitlines()
    res["stats"]["lines"] = len(lines)
    res["stats"]["chars"] = len(text)
    res["stats"]["bytes"] = os.path.getsize(path)
    res["stats"]["mtime"] = os.path.getmtime(path)

    # ---------- A0. 标题必须抄基线 ----------
    # 续篇是她续写的，标题属于「既成事实」，不是本次可创作的字段。
    # 让模板自带标题的后果：换一个 WI 就整篇挂错名，而 check 完全看不出来。
    m_h1 = re.search(r"(?m)^#[ \t]+(.+?)[ \t]*$", text)
    res["stats"]["h1"] = m_h1.group(1).strip() if m_h1 else None
    if base_report and os.path.isfile(base_report):
        btxt = _read(base_report)
        mb = re.search(r"(?m)^#[ \t]+(.+?)[ \t]*$", btxt)
        if mb and m_h1:
            if mb.group(1).strip() != m_h1.group(1).strip():
                res["errors"].append(
                    "H1 未抄基线：续篇「%s」≠ 基线「%s」——续篇标题必须与基准报告一致"
                    % (m_h1.group(1).strip()[:48], mb.group(1).strip()[:48]))

    # ---------- A. 骨架 ----------
    if required_sections:
        missing = [s for s in required_sections if s not in text]
        if missing:
            res["errors"].append("缺必需章节：%s" % ", ".join(missing))

    h2 = [l.strip() for l in lines if l.startswith("## ")]
    res["stats"]["h2"] = h2
    h3 = [l.strip() for l in lines if l.startswith("### ")]
    res["stats"]["h3_count"] = len(h3)

    # 小节编号连续性（§4.5 / §4.6 ... 只看 h2 上的 §x.y）
    sec_nums = []
    for l in h2:
        m = re.match(r"^##\s*§?(\d+)\.(\d+)", l)
        if m:
            sec_nums.append((int(m.group(1)), int(m.group(2))))
    if len(sec_nums) >= 2:
        base = sec_nums[0][0]
        minor = [n[1] for n in sec_nums if n[0] == base]
        expect = list(range(minor[0], minor[0] + len(minor)))
        if minor != expect:
            res["errors"].append("小节编号不连续：实际 %s，期望 %s" % (minor, expect))

    # ---------- B. 标注 ----------
    mk = {"original": text.count("【原文】"), "analysis": text.count("【解读】"),
          "derived": text.count("【折算】"), "mapping": text.count("【映射】")}
    res["stats"]["markers"] = mk
    if mk["original"] == 0:
        res["errors"].append("全篇没有【原文】块：结论无从溯源")
    if mk["analysis"] == 0:
        res["errors"].append("全篇没有【解读】块")
    if "定量" in text and mk["derived"] == 0:
        res["warnings"].append("含「定量」章节但无【折算】标记：自查推导是否被误标为原文")

    # Agreement 小节：旧结构是 ### x.y.z　AgN｜标题（WID ...）；
    # 新结构（按 WI 条目分节）里 AgN 不再当标题，而是 "【原文】AgN（FL#k，Issue#x-y）" 的标签。
    ags, h3_ag = [], []
    for l in h3:
        m = re.search(r"Ag\s*(\d+)\s*｜", l)
        if m:
            h3_ag.append(int(m.group(1)))
    lab = re.findall(r"【原文】\s*\**\s*(Ag|WA)\s*(\d+)", text)
    res["stats"]["block_labels"] = ["%s%s" % (a, b) for a, b in lab]
    if h3_ag:
        # 旧结构：标题连续
        if sorted(h3_ag) != list(range(1, len(h3_ag) + 1)):
            res["errors"].append("Agreement 编号不连续/重复：%s（期望 1..%d）"
                                 % (h3_ag, len(h3_ag)))
        ags = h3_ag
    elif lab:
        # 新结构：块数守恒——每个块在全文出现且仅出现一次
        names = ["%s%s" % (a, b) for a, b in lab]
        dup = sorted(set(n for n in names if names.count(n) > 1),
                     key=lambda s: (s[:2], int(s[2:])))
        if dup:
            res["errors"].append(
                "块重复出现：%s——按 WI 分节后每个 Agreement/WA 只能挂在一个条目下，"
                "重复即为跨条目复制" % "、".join(dup))
        for pre in ("Ag", "WA"):
            got = sorted(int(n[len(pre):]) for n in set(names) if n.startswith(pre))
            if got and got != list(range(1, len(got) + 1)):
                res["errors"].append("%s 编号不连续：%s（期望 1..%d）"
                                     % (pre, got, len(got)))
        ags = sorted(int(n[2:]) for n in set(names) if n.startswith("Ag"))
    # WA 计数必须**去重**：新结构里同一个块既有 `**WA1｜标题**` 又有 `【原文】WA1` 标签，
    # 直接 findall 会把它数成 2 条，块数对账就会莫名其妙多出块来（实测 2 条 WA 数成 4 条）。
    if lab:
        was = len(set(b for a, b in lab if a == "WA"))
    else:
        was = len(set(re.findall(r"WA\s*(\d+)\s*｜", text)))
    res["stats"]["agreements"] = ags
    res["stats"]["warnings_count"] = was
    if h3_ag and ags:
        expect = list(range(1, len(ags) + 1))
        if sorted(ags) != expect:
            res["errors"].append("Agreement 编号不连续/重复：%s（期望 1..%d）" % (ags, len(ags)))

    # 每条 Agreement 小节内是否三块齐全（只对旧结构的标题式小节生效）
    blocks = re.split(r"\n(?=### )", text)
    for b in blocks:
        m = re.search(r"Ag\s*(\d+)\s*｜", b.split("\n")[0]) if b.startswith("### ") else None
        if not m:
            continue
        miss = [k for k in ("【原文】", "【解读】", "【映射】") if k not in b]
        if miss:
            res["errors"].append("Ag%d 小节缺标注：%s" % (int(m.group(1)), "、".join(miss)))

    # ---------- B2. 按 WI 条目分节的结构（有 rel.json 才启用） ----------
    rel = None
    if workdir:
        import json as _json
        p = os.path.join(workdir, "rel.json")
        if os.path.isfile(p):
            with io.open(p, "r", encoding="utf-8") as f:
                rel = _json.load(f)
            ents = rel.get("entries") or []
            res["stats"]["wi_entries"] = len(ents)
            no_kind = [e.get("wi") for e in ents if not (e.get("kind") or "").strip()]
            if no_kind:
                res["errors"].append("WI 条目未判关系类型（rel.kind）：%s"
                                     % "、".join(str(x) for x in no_kind))
            bad_ref = [e.get("wi") for e in ents
                       if (e.get("kind") or "") in ("DERIVED", "SPLIT") and not e.get("base_ref")]
            if bad_ref:
                res["errors"].append("DERIVED/SPLIT 缺 base_ref（说不出从哪一条派生/拆出）：%s"
                                     % "、".join(str(x) for x in bad_ref))
            # 四段齐全 + 覆盖全部 WI 条目
            heads = {}
            for idx, l in enumerate(lines):
                m = re.match(r"^###\s+[\d.]+\s*[　 ]\s*([A-Z]{1,2}\d{1,2}(?:/[A-Z]{1,2}\d{1,2})*)", l)
                if m:
                    end = len(lines)
                    for k in range(idx + 1, len(lines)):
                        if lines[k].startswith("### ") or lines[k].startswith("## "):
                            end = k
                            break
                    heads[m.group(1)] = "\n".join(lines[idx:end])
            missing_wi = [e.get("wi") for e in ents if e.get("wi") not in heads]
            if missing_wi:
                res["errors"].append("以下 WI 条目在正文中没有独立小节：%s"
                                     % "、".join(str(x) for x in missing_wi))
            for code, body in heads.items():
                need = ["基线原状", "本次进展", "演进分析", "遗留"]
                miss = [n for n in need if n not in body]
                if miss:
                    res["errors"].append("WI 条目 %s 缺段：%s" % (code, "、".join(miss)))
            res["stats"]["wi_heads"] = sorted(heads)
    else:
        res["warnings"].append("未核对 WI 分节结构（未提供 _work 目录 / rel.json）")

    # ---------- C. 表格 ----------
    tbl_no, i, bad = 0, 0, []
    empty_rows = []          # 整行空单元格 = 骨架还没填
    while i < len(lines):
        if lines[i].strip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                j += 1
            tbl_no += 1
            ncol = len(_split_row(lines[i]))
            for k in range(i, j):
                c = len(_split_row(lines[k]))
                if c != ncol:
                    bad.append({"table": tbl_no, "line": k + 1, "expect": ncol, "got": c})
                cells = _split_row(lines[k])
                # 分隔行 `|---|---|`：每个单元格都是纯 -（带不带冒号都行）。
                # 注意别用 `all(... for x in cells if x != "")` —— 空单元格被过滤掉后
                # all() 作用在空序列上恒为真，整行空的占位行会被误判成分隔行而跳过。
                is_sep = bool(cells) and all(
                    x != "" and re.fullmatch(r":?-{2,}:?", x) for x in cells)
                if not is_sep and cells and all(x == "" for x in cells):
                    empty_rows.append(k + 1)
            i = j
        else:
            i += 1
    res["stats"]["tables"] = tbl_no
    res["stats"]["empty_table_rows"] = len(empty_rows)
    if bad:
        for b in bad[:10]:
            res["errors"].append("第 %d 行表格列数不一致（表#%d 期望 %d 列，实得 %d 列）"
                                 % (b["line"], b["table"], b["expect"], b["got"]))
    if empty_rows:
        # 没有这条，刚 init 出来的空骨架能拿 0 error 直接过闸并被 seal ——
        # 「check 返回 0 error」这道门禁等于没有。
        res["errors"].append("表格未填写：%d 行整行空单元格（行号 %s%s）—— 骨架占位尚未填实，不可交付/封存"
                             % (len(empty_rows), "、".join(str(n) for n in empty_rows[:8]),
                                "…" if len(empty_rows) > 8 else ""))

    # ---------- D. 禁忌 ----------
    # 豁免：若命中行本身是在「引用错误写法并纠正」（勘误登记/反例说明），降级为 warning。
    EXCUSE = ("更正", "应为", "原表述", "错误写法", "反例", "✗", "不得写成",
              "原文如此", "照抄原文", "勘误")
    for f in (forbidden or []):
        for i, line in enumerate(lines):
            if not re.search(f["pattern"], line):
                continue
            if any(k in line for k in EXCUSE):
                res["warnings"].append("第 %d 行命中禁忌「%s」，但该行属勘误/反例语境（已豁免）：%s"
                                       % (i + 1, f["pattern"], line.strip()[:70]))
            else:
                res["errors"].append("第 %d 行命中禁忌「%s」：%s"
                                     % (i + 1, f["pattern"], f["why"]))

    # 空章节（h2 之后 3 行内又出现下一个 h2 且无正文）
    for idx, l in enumerate(lines):
        if l.startswith("## "):
            body = []
            for k in range(idx + 1, min(idx + 12, len(lines))):
                if lines[k].startswith("## "):
                    break
                if lines[k].strip():
                    body.append(lines[k])
            if len(body) < 2:
                res["warnings"].append("章节疑似为空：%s（第 %d 行）" % (l.strip(), idx + 1))

    # ---------- 计数自证（P2） ----------
    roster = _roster_check(lines)
    if roster:
        res["stats"].update(roster)
        d, e = roster.get("roster_declared"), roster.get("roster_entries")
        if d is not None and e is not None and d != e:
            res["errors"].append(
                "计数不自证：正文声明「%d 篇公司贡献」（第 %s 行），花名册实际 %d 条 —— "
                "必须按主席报告 tdoc 列表逐条计数（P2：沿用上一场的数字会差 1）"
                % (d, roster.get("roster_declared_line"), e))

    # ---------- 原件保护 ----------
    # 铁律第 5 条「不改原件」是 SKILL.md S6 的硬门禁之一。早先这里写的是
    # `base_unchanged = True` —— 一个**无论原件是否被改都恒为真的绿灯**，
    # 而且 skillctl 从来没传过 base_report，这段压根不会执行。
    # 现在拿 init 时登记的基线（mtime + md5）真比对；没有基线就明说"未核对"。
    if base_report:
        res["stats"]["base_report"] = os.path.abspath(base_report)
        if not os.path.isfile(base_report):
            res["warnings"].append("基准报告已不在原处，无法核对原件：%s" % base_report)
            res["stats"]["base_unchanged"] = None
        elif base_mtime is None:
            res["warnings"].append("未登记基准报告基线（先跑 skillctl init --base <基准报告>）："
                                   "本次**未做**原件保护核对，不要当成已通过")
            res["stats"]["base_unchanged"] = None
        else:
            cur_mtime = os.path.getmtime(base_report)
            cur_md5 = _md5(base_report)
            same_mtime = abs(cur_mtime - float(base_mtime)) < 1e-6
            same_md5 = (not base_md5) or (cur_md5 == base_md5)
            res["stats"]["base_mtime"] = cur_mtime
            res["stats"]["base_mtime_baseline"] = float(base_mtime)
            res["stats"]["base_md5"] = cur_md5
            res["stats"]["base_unchanged"] = bool(same_mtime and same_md5)
            if not (same_mtime and same_md5):
                why = []
                if not same_mtime:
                    why.append("mtime 变了")
                if not same_md5:
                    why.append("内容变了")
                res["errors"].append("基准报告被改动（%s）：%s —— 违反铁律「不改原件」，先还原再交付"
                                     % ("、".join(why), base_report))

    # ---------- 主席报告块数对账（需要 --eom） ----------
    # 这是铁律 1 唯一能机器判的部分：产物 AgN/WA 的条数必须等于主席报告的锚点数。
    # 没给 --eom 就明说"未核对"，不要默认通过（与原件保护同一个道理）。
    if eom:
        if not os.path.isfile(eom):
            res["warnings"].append("主席报告逐字文本不存在，未做块数对账：%s" % eom)
        else:
            au = _eom_audit(text, _read(eom))
            res["stats"].update(au)
            res["stats"]["eom"] = os.path.abspath(eom)
            got = len(ags) + was
            res["stats"]["progress"] = {"blocks_filled": got,
                                        "blocks_expected": au["eom_blocks"]}
            if au["eom_blocks"] and got == 0:
                # 区分「还没填」与「填错了」：这两种在审核者眼里完全是两回事，
                # 混成一句 ERROR 会让人以为稿子写坏了。
                if res["stats"].get("empty_table_rows"):
                    res["errors"].append(
                        "骨架尚未填实：0 个【原文】块 / 主席报告 %d 条锚点，"
                        "且还有 %d 行表格是空的 —— 这是 init 出来的空骨架，填完再 check"
                        % (au["eom_blocks"], res["stats"]["empty_table_rows"]))
                else:
                    res["errors"].append(
                        "找不到任何【原文】AgN/WA 块（主席报告有 %d 条锚点）"
                        "—— 若已写正文，检查 Agreement 是否被写成普通段落；"
                        "按 WI 分节的结构里每块必须带【原文】AgN 标签" % au["eom_blocks"])
            elif au["eom_blocks"] and got != au["eom_blocks"]:
                res["errors"].append(
                    "块数不自证：产物 %d 条（Ag %d + WA %d），主席报告锚点 %d 条"
                    "（Agreement %d + WA %d）—— 铁律「不合并」要求逐块切分，差 1 条也算错"
                    % (got, len(ags), was, au["eom_blocks"],
                       au["eom_agreements"], au["eom_was"]))
            if au["origin_blocks"] and got and au["origin_blocks"] != got:
                res["warnings"].append(
                    "【原文】块 %d 个，但 Ag+WA 小节 %d 个 —— 可能漏贴原文或合并了小节"
                    % (au["origin_blocks"], got))
            for i, probe in au["trace_bad"]:
                res["warnings"].append(
                    "第 %d 个【原文】块在逐字文本里定位不到（前 45 字：%s…）"
                    "—— 可能是排印差异，也可能是改写；请与 _eom_*.txt diff 后确认"
                    % (i, probe[:45]))

    res["ok"] = not res["errors"]
    return res


def render(res):
    out = []
    out.append("文件：%s" % res["file"])
    s = res.get("stats", {})
    out.append("规模：%s 行 / %s 字符 / 表 %s 个 / h3 %s 个"
               % (s.get("lines"), s.get("chars"), s.get("tables"), s.get("h3_count")))
    mk = s.get("markers", {})
    if mk:
        out.append("标注：【原文】%d  【解读】%d  【折算】%d  【映射】%d"
                   % (mk["original"], mk["analysis"], mk["derived"], mk["mapping"]))
    bl = s.get("block_labels") or []
    if bl:
        n_ag = sum(1 for x in bl if x.startswith("Ag"))
        n_wa = sum(1 for x in bl if x.startswith("WA"))
        out.append("块标签：【原文】Ag %d + WA %d = %d 块（去重后 %d 块）"
                   % (n_ag, n_wa, len(bl), len(set(bl))))
    if s.get("agreements"):
        out.append("Agreement：%s 条（编号 %s）" % (len(s["agreements"]), s["agreements"]))
    if s.get("empty_table_rows"):
        out.append("表格未填：%s 行整行空" % s["empty_table_rows"])
    if s.get("roster_entries") is not None:
        ok = s.get("roster_declared") == s.get("roster_entries")
        out.append("计数自证：声明 %s 篇 / 花名册 %s 条 %s"
                   % (s.get("roster_declared"), s.get("roster_entries"), "✓" if ok else "✗"))
    if s.get("eom_blocks"):
        got = len(s.get("agreements") or []) + (s.get("warnings_count") or 0)
        out.append("块数对账：产物 %d 条（Ag %d + WA %d）/ 主席报告 %d 条（Agreement %d + WA %d）%s"
                   % (got, len(s.get("agreements") or []), s.get("warnings_count") or 0,
                      s.get("eom_blocks"), s.get("eom_agreements"), s.get("eom_was"),
                      "✓" if got == s.get("eom_blocks") else "✗"))
        pct = 100.0 * got / s["eom_blocks"]
        out.append("完成度：%d/%d = %.0f%%%s"
                   % (got, s["eom_blocks"], pct,
                      "（空骨架，未开工）" if got == 0
                      else "" if got == s["eom_blocks"]
                      else "（还差 %d 块）" % (s["eom_blocks"] - got)))
        bad = len(s.get("trace_bad") or [])
        out.append("原文溯源：%d 块中 %d 块可定位%s"
                   % (s.get("origin_blocks") or 0,
                      (s.get("origin_blocks") or 0) - bad,
                      "" if not bad else "，%d 块需人工确认" % bad))
    elif s.get("eom"):
        out.append("块数对账：未核对（逐字文本不可读）")
    else:
        # 与「原件保护」同一个立场：没做就说没做，不能让它看起来像通过了。
        out.append("块数对账：未核对（未提供主席报告逐字文本，加 --eom 或 init --eom）")
    if "base_unchanged" in s:
        v = s.get("base_unchanged")
        out.append("原件保护：%s" % ("基准报告未改动 ✓" if v else "基准报告已被改动 ✗")
                   if v is not None else "原件保护：未核对（缺基线）")
    out.append("")
    if res["errors"]:
        out.append("ERROR × %d" % len(res["errors"]))
        for e in res["errors"]:
            out.append("  ✗ " + e)
    if res["warnings"]:
        out.append("WARN × %d" % len(res["warnings"]))
        for w in res["warnings"]:
            out.append("  ! " + w)
    if res.get("ok"):
        out.append("结论：PASS（0 error）")
    else:
        out.append("结论：FAIL（%d error）" % len(res["errors"]))
    return "\n".join(out)
