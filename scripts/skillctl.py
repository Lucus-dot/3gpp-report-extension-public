# -*- coding: utf-8 -*-
"""skillctl —— 技能调度与流程编排工具（3gpp-report-extension 的执行引擎）

用法（在项目根目录）：
  skillctl list                                列出已安装技能
  skillctl dispatch "给 3GPP 会议进展写续篇"     任务 -> 技能路由（top-N）
  skillctl plan                                打印本技能的阶段计划
  skillctl run S2                              进入某阶段：打印工作单并置为 in_progress
  skillctl gate S2                             只看该阶段的过闸清单（自查用）
  skillctl done S2 --note "12 条 Ag 已抽取"      标记阶段完成
  skillctl status                              查看整体进度
  skillctl init --base <基准报告> --meeting RAN1#127 --agenda 9.4.1
                                               生成续篇骨架（拒绝覆盖已有文件）
  skillctl calc all                            定量折算（tac|wf1|wf2|opt3|pos|all）
  skillctl check <文件>                         交付物结构/标注/表格/禁忌校验
  skillctl seal <文件>                          校验通过后生成封存凭据

通用参数：--root <项目根>  --json  --skills-root <技能库根>
退出码：0 成功；1 校验失败；2 参数/状态错误
"""

import argparse
import datetime as dt
import io
import json
import math
import os
import re
import sys
import unicodedata
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import calc as calclib        # noqa: E402
import doclint                # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CFG_PATH = os.path.join(SKILL_DIR, "config.json")
CFG_LOCAL = os.path.join(SKILL_DIR, "config.local.json")
DEFAULT_SKILLS_ROOT = os.path.join(os.path.expanduser("~"), ".workbuddy", "skills")


# --------------------------------------------------------------------------
# 基础设施
# --------------------------------------------------------------------------
def _merge_cfg(base, over):
    """把 config.local.json 叠到 config.json 上。

    为什么需要它：`required_sections` 是按**某一份基准报告**定的节号（§4.5…§4.12），
    换一份报告就得改。改在 config.json 里，等于把本项目的结构写进分发包——别人
    clone 下来拿到的是你那份的节号，自己改了下次 pull 还冲突。
    `.gitignore` 早就写了 `config.local.json`，但代码从来不读它，是句空头承诺。

    合并规则：顶层键覆盖；`constants` / `markers` 是字典，按子键合并（只想改一个常量
    时不必抄整个段）；列表（如 `required_sections`）**整体替换**——半覆盖的节号列表
    没有意义，只会让 init 生成一份 check 判不过的骨架。
    """
    out = dict(base or {})
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            merged = dict(out[k])
            merged.update(v)
            out[k] = merged
        else:
            out[k] = v
    return out


def load_cfg():
    with io.open(CFG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if os.path.isfile(CFG_LOCAL):
        try:
            with io.open(CFG_LOCAL, "r", encoding="utf-8") as f:
                cfg = _merge_cfg(cfg, json.load(f))
        except ValueError as e:
            # 坏 JSON 直接忽略而不是中断：覆盖文件是可选件，不该让整个技能起不来
            print("⚠ config.local.json 不是合法 JSON，已忽略：%s" % e, file=sys.stderr)
    # config.json 里的 constants 之前没人读，calc 一直用自己的内置值；灌进去让配置真正生效
    calclib.configure(cfg.get("constants"))
    return cfg


RE_SEC = re.compile(r"§?\s*(\d+)\.(\d+)")


def section_plan(cfg):
    """从 required_sections 反解（大节号, 首小节号, 期望小节列表）。

    为什么不让 init 和 check 各读一个字段：`required_sections` 是字面量列表
    （§4.5…§4.12），而 init 用的是 `default_first_section`。两者只要不同步，
    init 就会生成一份 check 永远判不过的骨架 —— 而使用者根本不知道错在哪。
    以 required_sections 为唯一真值，init 跟着它走；default_* 仅作缺省回落。
    """
    nums = []
    for s in (cfg.get("required_sections") or []):
        m = RE_SEC.search(s)
        if m:
            nums.append((int(m.group(1)), int(m.group(2))))
    if nums:
        major = nums[0][0]
        first = min(n[1] for n in nums if n[0] == major)
        later = sorted(n[1] for n in nums if n[0] == major)
        return major, first, ["§%d.%d" % (major, k) for k in later]
    return (int(cfg.get("default_major_section", 4)),
            int(cfg.get("default_first_section", 5)), [])


def find_root(explicit=None):
    if explicit:
        return os.path.abspath(explicit)
    cur = os.path.abspath(os.getcwd())
    while True:
        if os.path.isdir(os.path.join(cur, ".workbuddy")) or os.path.isdir(os.path.join(cur, "docs")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return os.path.abspath(os.getcwd())
        cur = parent


def state_path(root, cfg):
    return os.path.join(root, cfg["state_rel"].replace("/", os.sep))


def load_state(root, cfg):
    p = state_path(root, cfg)
    if os.path.isfile(p):
        with io.open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"skill": cfg["skill"], "root": root, "created": None, "stages": {},
            "base_report": None, "target": None, "log": []}


def save_state(root, cfg, st):
    p = state_path(root, cfg)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    return p


def now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def _md5(path):
    import hashlib
    with open(path, "rb") as f:          # with：不关句柄在 Windows 上会锁住文件，改完删不掉
        return hashlib.md5(f.read()).hexdigest()


def _dw(s):
    """显示宽度：CJK / 全角字符占 2 格。

    `"%-22s" % name` 按**字符数**补空格，而阶段名是中文：
    「定量折算」4 字符占 8 格、「未收口、待办与时序倒推」11 字符占 22 格，
    混排时 goal 列会歪成锯齿，看不出同一列。
    """
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def _pad(s, width):
    return s + " " * max(0, width - _dw(s))


# --------------------------------------------------------------------------
# 技能索引与路由
# --------------------------------------------------------------------------
def _unquote(s):
    """去掉 YAML 标量外层的成对引号。

    frontmatter 里 `name: "论文写作大纲生成器"` 很常见，不剥引号的话
    `list` 会把引号原样打印出来，而依赖 `desc.startswith("[TODO")` 的
    「模板未填」判定也会因为开头的 `"` 而**永远失效**。
    """
    s = (s or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1].strip()
    return s


def scan_skills(skills_root):
    out = []
    if not os.path.isdir(skills_root):
        return out
    for name in sorted(os.listdir(skills_root)):
        d = os.path.join(skills_root, name)
        p = os.path.join(d, "SKILL.md")
        if not os.path.isfile(p):
            continue
        head = ""
        try:
            with io.open(p, "r", encoding="utf-8") as f:
                head = f.read(4000)
        except Exception:
            pass
        nm, desc = name, ""
        m = re.search(r"^---\s*(.*?)\s*---", head, re.S)
        fm = m.group(1) if m else ""
        mm = re.search(r"^name:\s*(.+)$", fm, re.M)
        if mm:
            nm = _unquote(mm.group(1))
        md = re.search(r"^description:\s*(.+)$", fm, re.M)
        if md:
            desc = _unquote(md.group(1))
        out.append({
            "dir": d, "name": nm, "description": desc,
            "has_config": os.path.isfile(os.path.join(d, "config.json")),
            "has_scripts": os.path.isdir(os.path.join(d, "scripts")),
            "todo_template": desc.startswith("[TODO"),
        })
    return out


def _terms(s):
    s = s.lower()
    s = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", s)
    toks = set()
    for w in s.split():
        if w.isascii():
            if len(w) >= 2:
                toks.add(w)
        else:
            for i in range(len(w) - 1):
                toks.add(w[i:i + 2])
            if len(w) >= 2:
                toks.add(w)
    return toks


def dispatch(query, skills, top=3):
    q = _terms(query)
    ranked = []
    for s in skills:
        if s["todo_template"]:
            continue
        desc = _terms(s["description"])
        name = _terms(s["name"].replace("-", " "))
        if not (desc or name):
            continue
        hit_desc = q & desc
        hit_name = q & name
        # 名称命中权重更高；描述命中按比例
        score = len(hit_name) * 3.0 + len(hit_desc) * 1.0
        if not score:
            continue
        denom = math.sqrt(max(1, len(q)) * max(1, len(desc) + len(name)))
        ranked.append({
            "name": s["name"], "dir": s["dir"],
            "score": round(score / denom, 3),
            "hits": sorted(hit_name | hit_desc)[:12],
            "description": s["description"][:160],
        })
    ranked.sort(key=lambda x: -x["score"])
    return ranked[:top]


# --------------------------------------------------------------------------
# 阶段编排
# --------------------------------------------------------------------------
def get_stage(cfg, sid):
    sid = sid.upper()
    for s in cfg["stages"]:
        if s["id"] == sid:
            return s
    return None


def cmd_plan(cfg, as_json):
    if as_json:
        print(json.dumps([{k: s[k] for k in ("id", "name", "goal", "outputs")} for s in cfg["stages"]],
                         ensure_ascii=False, indent=2))
        return 0
    print("技能：%s v%s —— %s" % (cfg["skill"], cfg["version"], cfg["title"]))
    print("=" * 74)
    for s in cfg["stages"]:
        print("%-3s %s %s" % (s["id"], _pad(s["name"], 24), s["goal"]))
        for o in s["outputs"]:
            print("      → %s" % o)
    return 0


def cmd_run(cfg, root, sid, as_json):
    st = load_state(root, cfg)
    stage = get_stage(cfg, sid)
    if not stage:
        print("未知阶段：%s（可选 %s）" % (sid, ", ".join(s["id"] for s in cfg["stages"])), file=sys.stderr)
        return 2
    rec = st["stages"].setdefault(stage["id"], {})
    if rec.get("status") != "done":
        rec["status"] = "in_progress"
        rec["started"] = rec.get("started") or now()
        save_state(root, cfg, st)

    if as_json:
        print(json.dumps(stage, ensure_ascii=False, indent=2))
        return 0

    bar = "=" * 72
    print(bar)
    print("阶段 %s　%s" % (stage["id"], stage["name"]))
    print(bar)
    print("目标：%s" % stage["goal"])
    print("输入：%s" % " / ".join(stage["inputs"]))
    # 必读文件：不打印出来的话，references/ 里那些踩坑与折算规矩没人会去看，
    # 等于约束只写在"可选阅读"里。缺文件也要报，不静默跳过。
    reads = stage.get("reads") or []
    if reads:
        print("")
        print("必读（动手前用 Read 读完）：")
        for r in reads:
            p = os.path.join(SKILL_DIR, r.replace("/", os.sep))
            mark = "✓" if os.path.isfile(p) else "✗ 文件缺失"
            print("  [%s] %s" % (mark, r))
    print("")
    print("工作单：")
    for i, s in enumerate(stage["steps"], 1):
        print("  %d. %s" % (i, s))
    print("")
    print("过闸清单（全过才可 done）：")
    for g in stage["gates"]:
        print("  [ ] %s" % g)
    print("")
    print("出口：%s" % " / ".join(stage["outputs"]))
    print(bar)
    print("完成本阶段后执行： skillctl done %s --note \"一句话摘要\"" % stage["id"])
    return 0


def cmd_gate(cfg, sid):
    stage = get_stage(cfg, sid)
    if not stage:
        print("未知阶段：%s" % sid, file=sys.stderr)
        return 2
    print("%s %s —— 过闸清单" % (stage["id"], stage["name"]))
    for i, g in enumerate(stage["gates"], 1):
        print("  [ ] %d. %s" % (i, g))
    return 0


def cmd_done(cfg, root, sid, note):
    st = load_state(root, cfg)
    stage = get_stage(cfg, sid)
    if not stage:
        print("未知阶段：%s" % sid, file=sys.stderr)
        return 2
    rec = st["stages"].setdefault(stage["id"], {})
    rec.update({"status": "done", "done": now(), "note": note or rec.get("note", "")})
    st["log"].append({"ts": now(), "stage": stage["id"], "action": "done", "note": note or ""})
    save_state(root, cfg, st)
    print("✓ %s 已标记完成%s" % (stage["id"], ("：" + note) if note else ""))
    nxt = [s["id"] for s in cfg["stages"]
           if st["stages"].get(s["id"], {}).get("status") != "done"]
    print("下一阶段：%s" % (nxt[0] if nxt else "全部完成，可 seal 交付"))
    return 0


def cmd_status(cfg, root, as_json):
    st = load_state(root, cfg)
    if as_json:
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0
    print("项目根：%s" % root)
    if st.get("base_report"):
        print("基准报告：%s" % st["base_report"])
    if st.get("target"):
        print("续篇目标：%s" % st["target"])
    print("-" * 60)
    done = 0
    for s in cfg["stages"]:
        r = st["stages"].get(s["id"], {})
        mark = {"done": "✓", "in_progress": "▶"}.get(r.get("status"), "·")
        done += 1 if r.get("status") == "done" else 0
        line = " %s %-3s %s" % (mark, s["id"], _pad(s["name"], 24))
        if r.get("done"):
            line += " %s" % r["done"]
        print(line)
        if r.get("note"):
            print("        └ %s" % r["note"])
    print("-" * 60)
    print("进度：%d/%d" % (done, len(cfg["stages"])))
    return 0


# --------------------------------------------------------------------------
# init / seal
# --------------------------------------------------------------------------
RE_BASE_H1 = re.compile(r"(?m)^#[ \t]+(.+?)[ \t]*$")
RE_BASE_PART = re.compile(r"(?m)^##[ \t]+第([一二三四五六七八九十]+)部分[　 \t]*[:：]?[　 \t]*(.+?)[ \t]*$")
RE_BASE_SEC = re.compile(r"(?m)^#{2,4}[ \t]+§?[ \t]*(\d+)\.(\d+)(?:\.\d+)?[　 \t]+(.+?)[ \t]*$")
RE_WID_OFFICIAL = re.compile(
    r"^([A-Z]{1,2}\d{1,2}(?:\s*/\s*[A-Z]{1,2}\d{1,2})*)(?:[　 \t]+|[｜|:：])[　 \t]*(.+)$")


def read_base(path):
    """从基准报告里读「该怎么写」，而不是让模板决定。

    H1 / 第N部分 / 末节号 / WI 条目表，全部是基线的既有事实。模板只声明有哪些字段，
    填什么由这里给。基线段不存在时返回空，由调用方降级而不是瞎编。
    """
    text = _read_text(path)
    m = RE_BASE_H1.search(text)
    h1 = m.group(1).strip() if m else ""
    parts = [(c, t) for c, t in RE_BASE_PART.findall(text)]
    secs = [(int(a), int(b), t) for a, b, t in RE_BASE_SEC.findall(text)]
    last = max(secs, key=lambda x: (x[0], x[1])) if secs else (0, 0, "")
    # 末个「第N部分」的标题就是续篇要接的那一部分。逐字保留（含括注），
    # 因为「接续哪一部分」是可核对的定位信息，改写就等于自拟。
    part_line = ""
    if parts:
        c, t = parts[-1]
        part_line = "第%s部分　%s" % (c, t)
    wid = []
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if not ln.startswith("##"):
            continue
        if "WID" in ln and ("映射" in ln or "目标" in ln):
            j = i + 1
            in_tbl = False
            while j < len(lines):
                cur = lines[j]
                if cur.startswith("#"):
                    break
                if cur.strip().startswith("|"):
                    in_tbl = True
                    cells = [c.strip() for c in cur.strip().strip("|").split("|")]
                    mm = RE_WID_OFFICIAL.match(cells[0]) if cells else None
                    if mm:
                        wid.append({
                            "code": mm.group(1),
                            "title": mm.group(2),
                            "wg": cells[1] if len(cells) > 1 else "",
                            "base": cells[2] if len(cells) > 2 else "",
                            "status": cells[3] if len(cells) > 3 else "",
                        })
                elif in_tbl and not cur.strip():
                    pass
                j += 1
            if wid:
                break
    return {"h1": h1, "parts": parts, "part_line": part_line,
            "last_major": last[0], "last_minor": last[1], "last_title": last[2],
            "wid": wid}


def cmd_init(cfg, root, base, meeting, agenda, out, dry, eom=None):
    tpl_path = os.path.join(SKILL_DIR, "references", "01-skeleton.md")
    if not os.path.isfile(tpl_path):
        print("找不到骨架模板：%s" % tpl_path, file=sys.stderr)
        return 2
    with io.open(tpl_path, "r", encoding="utf-8") as f:
        tpl = f.read()
    # 模板自身文件头的说明性 HTML 注释不进入产物（否则占位符会被替换成实际值，注释变成噪音）
    if tpl.lstrip().startswith("<!--") and "-->" in tpl:
        tpl = tpl.split("-->", 1)[1].lstrip("\r\n")

    base_abs = os.path.abspath(base) if base else ""
    if base_abs and not os.path.isfile(base_abs):
        print("基准报告不存在：%s" % base_abs, file=sys.stderr)
        return 2
    if eom and not os.path.isfile(eom):
        print("主席报告逐字文本不存在：%s" % os.path.abspath(eom), file=sys.stderr)
        print("（S1 的产物 _eom_<agenda>_verbatim.txt；先导出再登记，否则块数对账无从做起）",
              file=sys.stderr)
        return 2
    if not out:
        b = os.path.splitext(os.path.basename(base_abs))[0] if base_abs else "report"
        # 默认写到**基准报告所在的目录**，而不是项目根：一篇文章及其全部资产本来就该在一个夹里。
        # 早先用 root（向上找到的 .workbuddy 所在处），结果报告在 example/ 却把续篇生成到好几层之外。
        out_dir = os.path.dirname(base_abs) if base_abs else root
        out = os.path.join(out_dir, "%s_%s扩展_%s.md"
                           % (b, (meeting or "meeting"), dt.date.today().strftime("%Y%m%d")))
    out = os.path.abspath(out)

    if os.path.exists(out):
        print("拒绝覆盖：目标文件已存在 → %s" % out, file=sys.stderr)
        print("（本技能不允许覆盖既有文件；请用 --out 指定新文件名）", file=sys.stderr)
        return 2

    major, first, plan = section_plan(cfg)
    if cfg.get("default_first_section") not in (None, first):
        print("⚠ config.json 自身不一致：default_first_section=%s，但 required_sections "
              "从 §%d.%d 起。以 required_sections 为准（否则生成的骨架 check 永远判不过）。"
              % (cfg.get("default_first_section"), major, first), file=sys.stderr)

    # 骨架里所有「具体内容」都从基线取：H1、接续哪一部分、末节号、WI 条目表。
    rb = read_base(base_abs) if base_abs else {}
    if rb.get("last_major") and rb["last_major"] != major:
        print("⚠ 基线末节在 §%d.%d，但 config 的 required_sections 写的是 §%d.*。"
              % (rb["last_major"], rb["last_minor"], major), file=sys.stderr)
    if rb.get("last_minor") and first <= rb["last_minor"]:
        print("⚠ 续篇起始小节 §%d.%d 不大于基线末节 §%d.%d，会与基线重号。"
              % (major, first, rb["last_major"], rb["last_minor"]), file=sys.stderr)
    if not rb.get("h1"):
        print("✗ 基线报告里没找到一级标题（`# ...`）。续篇标题必须抄基线，不能自拟。",
              file=sys.stderr)
        return 2
    if not rb.get("wid"):
        print("⚠ 基线里没找到 WI 条目表（含「WID 目标」+「映射」的二级节 + 表）。"
              "归类与挂接都靠 WI 条目当主键，缺表时 map.json 无从建起。", file=sys.stderr)

    body = (tpl
            .replace("{{BASE_H1}}", rb["h1"])
            .replace("{{BASE_PART_LINE}}", rb.get("part_line") or "<基线的第N部分>")
            .replace("{{BASE_REPORT}}", os.path.basename(base_abs) if base_abs else "<基准报告>")
            .replace("{{MEETING}}", meeting or "<本次会议>")
            .replace("{{AGENDA}}", agenda or "<议程项>")
            .replace("{{DATE}}", dt.date.today().isoformat())
            .replace("{{FIRST_SECTION}}", str(first)))
    # 大节号与小节号联动：SB = required_sections 的大节号（默认 4），S1..S8 依次递增
    body = body.replace("{{SB}}", str(major))
    for i in range(1, 9):
        body = body.replace("{{S%d}}" % i, str(first + i - 1))

    if dry:
        print("[dry-run] 将写入：%s" % out)
        print("[dry-run] 基准报告：%s" % base_abs)
        if eom:
            print("[dry-run] 主席报告逐字文本：%s" % os.path.abspath(eom))
        print("[dry-run] 骨架字符数：%d" % len(body))
        print("---- 前 12 行 ----")
        for l in body.splitlines()[:12]:
            print(l)
        return 0

    os.makedirs(os.path.dirname(out), exist_ok=True)
    # 固定写 LF：Windows 下文本模式会把 \n 翻译成 \r\n，同一份 md 里混着两套行尾，
    # 后续用 diff / 行号定位时都对不上。
    with io.open(out, "w", encoding="utf-8", newline="") as f:
        f.write(body)
    # WI 条目表必须落盘：Phase B 的归类/挂接/守恒校验全部以它为键
    workd = os.path.join(os.path.dirname(out), "_work_" +
                         (re.sub(r"[^0-9A-Za-z]+", "_", agenda).strip("_") or "work"))
    if not os.path.isdir(workd):
        os.makedirs(workd)
    wid_path = _dump(os.path.join(workd, "wid.json"), {
        "source": base_abs, "base_h1": rb.get("h1"),
        "base_part_line": rb.get("part_line"),
        "base_last_section": "§%d.%d" % (rb.get("last_major", 0), rb.get("last_minor", 0)),
        "entries": rb.get("wid") or []})
    st = load_state(root, cfg)
    if st.get("target") and os.path.abspath(st["target"]) != out:
        st["stages"] = {}          # 换了目标文件 → 阶段进度重置
        st["log"].append({"ts": now(), "stage": "init", "action": "reset_stages",
                          "prev_target": st["target"]})
    st["created"] = st.get("created") or now()
    st["base_report"] = base_abs
    # 登记原件基线：S6 那道「基准报告 mtime 未变」的门禁靠这两个值才判得出来，
    # 没有基线就只能写"未核对"，不能假装通过。
    st["base_mtime"] = os.path.getmtime(base_abs) if base_abs else None
    st["base_md5"] = _md5(base_abs) if base_abs else None
    # 登记主席报告逐字文本：S1 的产物就是这个文件，之后 check/seal 靠它做块数对账。
    # 不登记就得每次手打 --eom，实际结果一定是没人打、这条门禁形同虚设。
    if eom:
        st["eom"] = os.path.abspath(eom)
    st["target"] = out
    st["log"].append({"ts": now(), "stage": "init", "action": "create", "target": out})
    save_state(root, cfg, st)
    print("✓ 已生成续篇骨架：%s" % out)
    print("  标题抄自基线：%s" % rb["h1"])
    print("  接续：%s" % (rb.get("part_line") or "（基线无第N部分标题）"))
    print("  WI 条目：%d 条 → %s" % (len(rb.get("wid") or []), wid_path))
    print("下一步： skillctl run A1")
    return 0


# --------------------------------------------------------------------------
# 素材清点（S0/S1 的机械可判部分）
#
# 素材夹的布局一直只是 README 里的散文约定，没有任何代码认它，于是「FL Summary
# 是不是按编号排齐了」「主席报告在不在」只能靠眼睛看。S1 的门禁里最常翻车的两件事
# （FL#1 被当成 tdoc 清单、沿用上一场的篇数）都跟清点有关，所以让它机器可判。
# --------------------------------------------------------------------------
DOC_EXT = (".docx", ".doc", ".pdf", ".txt", ".md")
TDOC_EXT = (".docx", ".doc", ".pdf")     # 公司 TDoc 只算原始文档，不算我们自己抽的 _txt_
RE_CHAIR = re.compile(r"eom", re.I)
RE_FL_DIR = re.compile(r"fl[\s_\-]*summary", re.I)
RE_FL_FILE = re.compile(r"(fl[\s_\-]*summary|^R1[\s_\-]*\d)", re.I)

# ---------------------------------------------------------------------------
# docx 文本抽取（零依赖：docx 就是 zip + word/document.xml）
#
# 为什么不直接读文件名：S1 最常翻车的一件事就是「FL Summary 的轮次」——
# 文件名里的 R1-xxxxxxx 是**文稿号**，不是轮次；真实样例里编号最小的那份其实是 **FL#2**。
# 轮次写在文档标题里（"Title: FL Summary #2: …"），只能打开文档读。
#
# 已知限制（如实写明，不假装无损）：
#   - 公式（oMath）抽不出来，表格能抽出文本但会丢结构；
#   - 页眉页脚、批注不抽（只抽 document.xml）；
#   - .doc（老格式）和 .pdf 抽不了，会明确返回 None。
# ---------------------------------------------------------------------------
RE_WP = re.compile(r"<w:p(?:\s+[^>]*)?>(.*?)</w:p>", re.S)
RE_WT = re.compile(r"<w:t(?:\s+[^>]*)?>(.*?)</w:t>", re.S)
# 标题写法实测是 "FL Summary #2: …" —— "Summary" 是可有可无的中缀，必须容忍，
# 否则 `(?:FL)\s*#` 在 "FL Summary #2" 上匹配不到（第一版就漏了，导致明明读到了标题却判"未确认"）。
RE_FL_ROUND = re.compile(r"(?i)(?:FLS|FL|Feature Lead)(?:\s+Summary)?\s*#\s*(\d+)")
RE_TITLE = re.compile(r"(?i)^\s*title\s*:\s*(.+)$", re.M)
RE_AGENDA = re.compile(r"(?i)^\s*agenda\s*item\s*:\s*([\d.]+)", re.M)


def _unesc(s):
    s = re.sub(r"&lt;", "<", s)
    s = re.sub(r"&gt;", ">", s)
    s = re.sub(r"&quot;", '"', s)
    s = re.sub(r"&apos;", "'", s)
    s = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), s)
    return re.sub(r"&amp;", "&", s)


def docx_paras(path):
    """读 docx 的段落文本；读不了（非 docx / 损坏 / .doc / .pdf）返回 None。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        try:
            xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", "replace")
        except Exception:
            return None
        out = []
        for seg in RE_WP.findall(xml):
            t = _unesc("".join(RE_WT.findall(seg))).strip()
            if t:
                out.append(t)
        return out
    if ext in (".txt", ".md"):
        try:
            with io.open(path, "r", encoding="utf-8", errors="replace") as f:
                return [l.strip() for l in f if l.strip()]
        except OSError:
            return None
    return None


def fl_meta(path):
    """从 FL Summary 的内容里读轮次与标题。返回 (轮次 or None, 标题 or None, 议题 or None)。"""
    paras = docx_paras(path)
    if not paras:
        return None, None, None
    head = "\n".join(paras[:40])

    m = RE_TITLE.search(head)
    title = m.group(1).strip() if m else None

    rnd = None
    if title:
        m2 = RE_FL_ROUND.search(title)
        if m2:
            rnd = int(m2.group(1))
    if rnd is None:
        hits = [int(x) for x in RE_FL_ROUND.findall(head)]
        if hits:
            # 标题没写就取正文里出现最多的那个值
            rnd = max(set(hits), key=hits.count)

    m3 = RE_AGENDA.search(head)
    return rnd, title, (m3.group(1) if m3 else None)


def _fmt_size(n):
    if n >= 1024 * 1024:
        return "%.1f MB" % (n / 1048576.0)
    return "%.1f KB" % (n / 1024.0)


def _num_of(name):
    """从文件名里取最后一个数字串，用作排序键（R1-2607813 → 2607813）。"""
    m = re.findall(r"\d+", os.path.basename(name))
    return int(m[-1]) if m else -1


def _find_fl_dir(root):
    if not os.path.isdir(root):
        return None
    for d in sorted(os.listdir(root)):
        full = os.path.join(root, d)
        if os.path.isdir(full) and RE_FL_DIR.search(d):
            return full
    return None


def _walk_docs(root, exts=DOC_EXT):
    out = []
    for r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.lower().endswith(exts):
                out.append(os.path.join(r, f))
    return sorted(out)


def cmd_sources(cfg, path, agenda, as_json=False):
    root = os.path.abspath(path)
    if not os.path.isdir(root):
        print("会议目录不存在：%s" % root, file=sys.stderr)
        return 2

    # 只看根目录的「一手源」，不递归：根目录下 by_agenda/ 里是 TDoc、_work_*/ 里是过程产物，
    # 递归会把它们全当成 FL Summary 或主席报告（第一版就踩了这个坑：认出了 20+ 份"FL Summary"）。
    root_docs = sorted(os.path.join(root, f) for f in os.listdir(root)
                       if os.path.isfile(os.path.join(root, f))
                       and f.lower().endswith(DOC_EXT)
                       and not f.startswith("_"))       # `_` 开头是我们自己的抽取/过程产物
    fl_dir = _find_fl_dir(root)

    chair = [p for p in root_docs if RE_CHAIR.search(os.path.basename(p))]
    verbatim = sorted(os.path.join(root, f) for f in os.listdir(root)
                      if f.startswith("_eom") and "verbatim" in f.lower())

    if fl_dir:
        fl = _walk_docs(fl_dir)
    else:
        fl = [p for p in root_docs
              if RE_FL_FILE.search(os.path.basename(p)) and p not in chair]

    # 轮次靠内容确认，不靠文件名：标题里写着 "FL Summary #2"，那才是轮次。
    # 只有 `FL summary/` 夹里的文件才做这件事（其他地方的 R1-*.docx 是公司 TDoc，不是 FL）。
    fl_rows = []
    for p in fl:
        rnd, title, ag = fl_meta(p)
        fl_rows.append({"path": p, "num": _num_of(p), "round": rnd,
                        "title": title, "agenda": ag,
                        "confirmed": rnd is not None})
    all_confirmed = bool(fl_rows) and all(r["confirmed"] for r in fl_rows)
    if all_confirmed:
        fl_rows.sort(key=lambda r: (r["round"], r["num"]))
    else:
        # 有读不出轮次的，就退回「编号小的靠前」——这一步只认 FL summary 夹内的文件
        fl_rows.sort(key=lambda r: r["num"])
    fl = [r["path"] for r in fl_rows]
    nums = [r["num"] for r in fl_rows]
    rounds = [r["round"] for r in fl_rows]

    # 公司 TDoc：给了议程项就进 by_agenda/9/9.4/9.4.1/（逐级累加，不是把 9.4.1 拆成三级数字），
    # 否则数整棵 by_agenda
    tdoc_dir, tdoc_n = None, None
    by_agenda = os.path.join(root, "by_agenda")
    if os.path.isdir(by_agenda):
        if agenda:
            parts = [p for p in agenda.split(".") if p]
            levels = [".".join(parts[:i + 1]) for i in range(len(parts))]
            cand = os.path.join(by_agenda, *levels)
            if os.path.isdir(cand):
                tdoc_dir, tdoc_n = cand, len(_walk_docs(cand, TDOC_EXT))
        if tdoc_n is None:
            tdoc_dir, tdoc_n = by_agenda, len(_walk_docs(by_agenda, TDOC_EXT))

    errs, warns = [], []
    if not chair:
        errs.append("没有找到主席报告（Chair notes …_eom*.docx）—— 落槌结论无从取得，S1 阻塞")
    if fl_dir is None and fl:
        warns.append("FL Summary 散在根目录（%d 份）—— 建议单独建 `FL summary/` 子夹，"
                     "否则会和主席报告、TDoc 混在一起" % len(fl))
    if not fl:
        warns.append("没有找到 FL Summary —— 会少一层讨论脉络（不阻塞，但 §n.5.4 的收口时间线会缺）")
    if not verbatim:
        warns.append("没有 `_eom_*.txt` 逐字摘录 —— 那是 S1 的产物；`check --eom` 的对账依赖它")
    if tdoc_n == 0 and agenda:
        warns.append("议程 %s 下没有 TDoc（by_agenda/%s/）—— 篇数为 0 时先怀疑路径，别直接写 0"
                     % (agenda, "/".join(agenda.split("."))))

    # FL 序列：轮次由内容确认；确认不了才用编号升序（只对 FL summary 夹内的文件）
    unconfirmed = [r for r in fl_rows if not r["confirmed"]]
    if unconfirmed:
        warns.append("%d/%d 份 FL Summary 读不出轮次（%s）—— 已退回「编号小的靠前」推定；"
                     "读不出的通常是 .doc/.pdf/加密件，转成 .docx 后重跑可确认"
                     % (len(unconfirmed), len(fl_rows),
                        "、".join(os.path.basename(r["path"]) for r in unconfirmed[:3])))
    if all_confirmed and len(rounds) >= 2:
        if any(b - a != 1 for a, b in zip(rounds, rounds[1:])):
            warns.append("轮次不连续：#%s —— 中间有缺环，核对 _download_log.csv"
                         % " → #".join(str(r) for r in rounds))
        if nums == sorted(nums) and rounds != sorted(rounds):
            warns.append("轮次顺序与编号顺序不一致（编号 %s 对应轮次 #%s）—— 这正是"
                         "「编号 ≠ 轮次」的实证，别用编号推轮次"
                         % ("、".join(str(n) for n in nums),
                            "、#".join(str(r) for r in rounds)))
    if all_confirmed and rounds and min(rounds) != 1:
        warns.append("最早一份是 FL#%d（不是 #1）—— 常见坑：把最早那份当成 tdoc 清单；"
                     "若确实缺 #1，去会务站确认是否另有文件" % min(rounds))

    seq = [(r["round"], r) for r in fl_rows]
    dup = sorted({n for n in nums if nums.count(n) > 1})
    gap = len(nums) >= 2 and any(b - a != 1 for a, b in zip(nums, nums[1:]))

    anchors = None
    if verbatim:
        with io.open(verbatim[0], "r", encoding="utf-8") as f:
            txt = f.read()
        anchors = {"agreement": len(doclint.RE_EOM_AG.findall(txt)),
                   "wa": len(doclint.RE_EOM_WA.findall(txt))}

    def rel(p):
        return os.path.relpath(p, root)

    rep = {
        "meeting_dir": root,
        "agenda": agenda or None,
        "chair": [{"file": rel(p), "size": _fmt_size(os.path.getsize(p))} for p in chair],
        "verbatim": [{"file": rel(p), "size": _fmt_size(os.path.getsize(p))} for p in verbatim],
        "fl_dir": rel(fl_dir) if fl_dir else None,
        "fl": [{"round": r["round"], "round_confirmed": r["confirmed"],
                "num": r["num"], "file": rel(r["path"]),
                "title": r["title"],
                "agenda": r["agenda"],
                "size": _fmt_size(os.path.getsize(r["path"]))} for _, r in seq],
        "fl_all_confirmed": all_confirmed,
        "fl_gap": gap,
        "fl_duplicate": dup,
        "tdoc_dir": rel(tdoc_dir) if tdoc_dir else None,
        "tdoc_count": tdoc_n,
        "anchors": anchors,
        "blockers": errs,
        "warnings": warns,
    }

    if as_json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 1 if errs else 0

    print("素材清点：%s" % root)
    if agenda:
        print("议程项：%s" % agenda)
    print("")
    print("★★★ 主席报告（唯一落槌来源）")
    if chair:
        for p in chair:
            print("  ✓ %s %s" % (_pad(rel(p), 50), _fmt_size(os.path.getsize(p))))
    else:
        print("  ✗ 未找到（阻塞）")

    print("★★ FL Summary（会中刷新，会有多份）")
    if fl:
        for i, (rnd, r) in enumerate(seq, 1):
            tag = ("FL#%d" % rnd) if r["confirmed"] else ("#%d?" % i)
            how = "内容确认" if r["confirmed"] else "编号推定"
            ttl = r["title"] or "(未读到标题)"
            print("  %2d. %s  %s" % (i, _pad(tag, 9), _pad(rel(r["path"]), 40))
                  + _fmt_size(os.path.getsize(r["path"])))
            print("        %s｜%s" % (how, ttl[:60]))
        if all_confirmed:
            print("  轮次：#%s —— 全部由文档标题确认（编号 %s 仅供排序）"
                  % (" → #".join(str(r) for r in rounds), "、".join(str(n) for n in nums)))
        else:
            print("  轮次：未能全部确认，按编号升序推定 %s" % " → ".join(str(n) for n in nums))
        if dup:
            print("  ⚠ 重复编号：%s" % ", ".join(str(n) for n in dup))
    else:
        print("  — 无（不阻塞）")

    print("★ 公司 TDoc")
    if tdoc_n is not None:
        print("  %d 个文件   %s/" % (tdoc_n, rep["tdoc_dir"]))
        print("  ⚠ 这是**夹里的文件数**，不是「公司贡献篇数」：同一家会有多版本 revision、"
              "还混着 session notes")
        print("  ⚠ 篇数只能按主席报告的 tdoc 列表逐条数（铁律 6），数完写进 §n.5 花名册")
    else:
        print("  — 无 by_agenda/")

    print("S1 产物")
    if verbatim:
        for p in verbatim:
            nline = len(io.open(p, encoding="utf-8").read().splitlines())
            print("  ✓ %s %s / %d 行"
                  % (_pad(rel(p), 46), _fmt_size(os.path.getsize(p)), nline))
        if anchors:
            print("  锚点：Agreement %d + Working assumption %d = **%d 块**"
                  "（`check --eom` 会拿这个数对账）"
                  % (anchors["agreement"], anchors["wa"],
                     anchors["agreement"] + anchors["wa"]))
    else:
        print("  — 未生成")

    print("")
    for w in warns:
        print("WARN  ! %s" % w)
    for e in errs:
        print("ERROR ✗ %s" % e)
    print("结论：%s" % ("阻塞 —— 缺主席报告，S1 无法开工" if errs else "素材齐备（阻塞项 0）"))
    return 1 if errs else 0


def cmd_extract(path, out=None, head=0, as_json=False):
    """把 docx 抽成纯文本段落（S1「导出逐字摘录」这一步的工具）。

    为什么要自己带一个：S1 的门禁里「抽出目标议程项段落并逐字保存」原本只能靠模型/人工
    另想办法，工具链上是个空洞。docx 就是 zip + XML，标准库足够。
    能力边界也如实体现在输出里：公式（oMath）抽不出、表格丢结构、页眉页脚与批注不抽。
    """
    p = os.path.abspath(path)
    if not os.path.isfile(p):
        print("文件不存在：%s" % p, file=sys.stderr)
        return 2
    paras = docx_paras(p)
    if paras is None:
        print("抽不出文本：%s" % p, file=sys.stderr)
        print("（只支持 .docx 与 .txt/.md；.doc / .pdf 请先转成 .docx）", file=sys.stderr)
        return 2

    if as_json:
        print(json.dumps({"file": p, "paragraphs": len(paras),
                          "text": paras if head <= 0 else paras[:head]},
                         ensure_ascii=False, indent=2))
        return 0

    if out:
        with io.open(out, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(paras))
        print("✓ 抽取 %d 段 → %s" % (len(paras), out))
        print("  ⚠ 已知丢失：公式（oMath）、表格结构、页眉页脚与批注。"
              "逐字摘录涉及公式时，需回到 document.xml 核对。", file=sys.stderr)
    if head > 0:
        for l in paras[:head]:
            print(l)
    elif not out:
        for l in paras[:40]:
            print(l)
        print("…（共 %d 段；`--head N` 看更多，`--out <file>` 落盘）" % len(paras))
    return 0


def cmd_seal(cfg, root, path, eom=None, workdir=None):
    st = load_state(root, cfg)
    res = doclint.check(path, cfg["required_sections"], cfg["forbidden_patterns"],
                        base_report=st.get("base_report"),
                        base_mtime=st.get("base_mtime"),
                        base_md5=st.get("base_md5"),
                        eom=eom or st.get("eom"),
                        workdir=workdir)
    if not res["ok"]:
        print(doclint.render(res))
        print("\n校验未通过，拒绝封存。", file=sys.stderr)
        return 1
    h = _md5(path)
    seal = {
        "file": res["file"], "md5": h, "sealed_at": now(),
        "lines": res["stats"]["lines"], "chars": res["stats"]["chars"],
        "markers": res["stats"]["markers"],
        "agreements": res["stats"]["agreements"],
        "tables": res["stats"]["tables"],
        # 对账结果也入凭据：将来「这条数是怎么来的」要能从 seal.json 反查
        "eom_blocks": res["stats"].get("eom_blocks"),
        "eom_agreements": res["stats"].get("eom_agreements"),
        "eom_was": res["stats"].get("eom_was"),
        "origin_blocks": res["stats"].get("origin_blocks"),
        "trace_unlocated": len(res["stats"].get("trace_bad") or []),
        "skill": cfg["skill"], "version": cfg["version"],
    }
    out = os.path.splitext(path)[0] + "_seal.json"
    with io.open(out, "w", encoding="utf-8") as f:
        json.dump(seal, f, ensure_ascii=False, indent=2)
    print(doclint.render(res))
    print("\n✓ 封存凭据：%s" % out)
    return 0


# --------------------------------------------------------------------------
# calc 子命令
# --------------------------------------------------------------------------
def _pp(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_calc(what, args):
    if what == "tac":
        r = calclib.tac_range(args.neg, args.pos, tuple(args.mu))
        if args.json:
            _pp(r)
            return 0
        print("TAC 量程折算（formula: %s）" % r["formula"])
        print("量程 [%.1f, +%.1f] µs，跨度 %.1f µs；legacy 单向上限 %.3f µs；跨度比 %.2f×"
              % (r["range_us"][0], r["range_us"][1], r["span_us"], r["legacy_single_side_us"], r["legacy_ratio"]))
        print("%-4s %-9s %-12s %-11s %-11s %s" % ("µ", "SCS/kHz", "粒度/µs", "正侧步数", "负侧步数", "signed 位宽"))
        for row in r["rows"]:
            print("%-4d %-9d %-12.6f %-11d %-11d %d"
                  % (row["mu"], row["scs_khz"], row["gran_us"], row["steps_pos"], row["steps_neg"], row["bits_signed"]))
        return 0

    if what == "wf1":
        r = calclib.fac_wf1(args.range_khz, k=args.k, fc_ghz=args.fc)
        if args.json:
            _pp(r)
            return 0
        print("FAC 粒度 · WF1（gran = SCS/2^%d），量程 ±%.2f kHz @ %.0f GHz"
              % (r["k"], r["range_khz"], r["fc_ghz_for_ppm"]))
        print("%-9s %-12s %-11s %-8s %s" % ("SCS/kHz", "gran/Hz", "gran/ppm", "步数", "signed 位宽"))
        for row in r["rows"]:
            print("%-9d %-12.4f %-11.6f %-8d %d"
                  % (row["scs_khz"], row["gran_hz"], row["gran_ppm"], row["steps"], row["bits_signed"]))
        return 0

    if what == "wf2":
        rows = [calclib.fac_wf2(args.range_khz, args.ppm, fc) for fc in args.fc_list]
        if args.json:
            _pp({"framework": "WF2", "range_khz": args.range_khz, "ppm": args.ppm, "rows": rows})
            return 0
        for r in rows:
            print("WF2 p=%.3f ppm, fc=%.1f GHz, 量程 ±%.2f kHz → gran=%.1f Hz, %.2f ppm, 步数 %d, 位宽 %d"
                  % (r["p_ppm"], r["fc_ghz"], r["range_khz"], r["gran_hz"], r["range_ppm"], r["steps"], r["bits_signed"]))
        return 0

    if what == "opt3":
        r = calclib.opt3_table([(args.fc, s) for s in (15, 30, 60, 120)], args.ppm, args.k)
        if args.json:
            _pp(r)
            return 0
        print("Option 3 相容性检查（target < %.3f ppm，强制定 k=%d）" % (r["target_ppm"], r["forced_k"]))
        print("%-9s %-9s %-7s %-16s %-16s %s"
              % ("fc/GHz", "SCS/kHz", "k_min", "k_min 时 ppm", "强制 k 时 ppm", "强制 k 是否合规"))
        for row in r["rows"]:
            print("%-9.1f %-9d %-7d %-16.6f %-16.6f %s"
                  % (row["fc_ghz"], row["scs_khz"], row["k_min"],
                     row["gran_ppm_at_k_min"], row["gran_ppm_if_k_forced"],
                     "✓" if row["forced_satisfies"] else "✗"))
        return 0

    if what == "pos":
        if args.json:
            _pp({
                "pos_timing": [calclib.pos_timing(x) for x in (20, 50, 150)],
                "pos_doppler": [calclib.pos_doppler(x, 30.0, 7.56, 600.0) for x in (20, 150)],
                "legacy_ta_gran_us_mu0": calclib.legacy_ta_gran_us(0),
                "fac_step_hz_15k_k8": calclib.fac_step_hz(15, 8),
            })
            return 0
        print("位置量化误差 → 定时误差（legacy TA 粒度 µ=0 = %.6f µs）" % calclib.legacy_ta_gran_us(0))
        for x in (20, 50, 150):
            r = calclib.pos_timing(x)
            print("  X=%3d m → 单程 %.2f ns, 环回 %.2f ns, ≈ %.2f 个 TA 步长(µ=0)"
                  % (x, r["one_way_ns"], r["round_trip_ns"], r["ta_steps_mu0"]))
        print("位置量化误差 → 多普勒误差（量级估算）")
        for x in (20, 150):
            r = calclib.pos_doppler(x, 30.0, 7.56, 600.0)
            print("  X=%3d m @Ka/LEO600 天底(v=7.56 km/s, d=600 km) → 灵敏度 %.3f Hz/m, Δf ≈ %.1f Hz"
                  % (x, r["sens_hz_per_m"], r["df_hz"]))
        print("  （15 kHz SCS 下 FAC 粒度 = %.2f Hz，可作对照）" % calclib.fac_step_hz(15, 8))
        return 0

    # all
    t = calclib.all_tables()
    if args.json:
        _pp(t)
        return 0
    print("=" * 78)
    print("A. TAC 位宽（WA 量程 [-2903.6, +5807.2] µs）")
    r = t["tac"]
    print("   跨度 %.1f µs；legacy 12-bit 单向上限 %.3f µs；跨度比 %.2f×"
          % (r["span_us"], r["legacy_single_side_us"], r["legacy_ratio"]))
    for row in r["rows"]:
        print("   µ=%d (%3d kHz) 粒度 %.6f µs → 正 %d / 负 %d 步 → %d bit"
              % (row["mu"], row["scs_khz"], row["gran_us"], row["steps_pos"], row["steps_neg"], row["bits_signed"]))
    print("=" * 78)
    print("B. FAC 粒度 · WF1(k=8) @Ka 30 GHz，量程 ±127.08 kHz")
    for row in t["wf1"]["rows"]:
        print("   SCS %3d kHz: gran %8.4f Hz = %.6f ppm → %d 步 → %d bit"
              % (row["scs_khz"], row["gran_hz"], row["gran_ppm"], row["steps"], row["bits_signed"]))
    print("=" * 78)
    print("C. FAC 粒度 · WF2(0.01 ppm)")
    for k, lbl in (("wf2_ka", "Ka 30 GHz / ±127.08 kHz"), ("wf2_s", "S 2 GHz / ±15.444 kHz")):
        r = t[k]
        print("   %-26s gran %.1f Hz = %.2f ppm 量程 → %d 步 → %d bit"
              % (lbl, r["gran_hz"], r["range_ppm"], r["steps"], r["bits_signed"]))
    print("D. FAC 粒度 · WF1(k=8) @S 2 GHz，量程 ±15.444 kHz")
    for row in t["wf1_s"]["rows"]:
        print("   SCS %3d kHz: gran %8.4f Hz = %.6f ppm → %d 步 → %d bit"
              % (row["scs_khz"], row["gran_hz"], row["gran_ppm"], row["steps"], row["bits_signed"]))
    print("=" * 78)
    print("E. Option 3 相容性（target < 0.01 ppm；k=[8] 是否够）")
    for row in t["opt3"]["rows"]:
        print("   fc %5.1f GHz SCS %3d kHz → k_min=%2d (%.6f ppm) | 若定 k=8: %.6f ppm %s"
              % (row["fc_ghz"], row["scs_khz"], row["k_min"], row["gran_ppm_at_k_min"],
                 row["gran_ppm_if_k_forced"], "OK" if row["forced_satisfies"] else "✗ 违反"))
    print("=" * 78)
    print("F. 参考位置粒度 X")
    for r in t["pos_timing"]:
        print("   X=%3d m → 环回 %.2f ns ≈ %.2f TA 步(µ=0)" % (r["x_m"], r["round_trip_ns"], r["ta_steps_mu0"]))
    for r in t["pos_doppler"]:
        print("   X=%3d m @Ka/LEO600 → Δf ≈ %.1f Hz（FAC 步长 %.1f Hz@15 kHz）"
              % (r["x_m"], r["df_hz"], calclib.fac_step_hz(15, 8)))
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Phase A：blocks / issues / flow / tdoc
# --------------------------------------------------------------------------
RE_BLOCK_AG = re.compile(r"(?m)^[ \t]*Agreement[ \t]*:")
RE_BLOCK_WA = re.compile(r"(?mi)^[ \t]*Working[ \t]+assumption[ \t]*:?")
RE_FL_SEP = re.compile(
    r"(?m)^(R1-\d+)[ \t]+.*?(?:FLS|FL|Feature Lead)(?:\s+Summary)?\s*#\s*(\d+)", re.I)
RE_FFS = re.compile(r"(?m)^[ \t]*FFS\s*[:：][ \t]*(.*)$", re.I)
RE_TOPIC = re.compile(r"(?m)^[ \t]*(?:\[P\d+\][ \t]*)?Topic[ \t]*#?[ \t]*(\d+)[ \t]*(?:[:：][ \t]*)?(.*)$", re.I)
RE_ISSUE = re.compile(
    r"(?m)^[ \t]*(?:\[P\d+\][ \t]*)?Issue[ \t]*#?[ \t]*(\d+)-(\d+)[ \t]*(?:[:：][ \t]*)?(.*)$", re.I)
RE_PROPOSAL = re.compile(
    r"(?m)^[ \t]*(?:\[P\d+\][ \t]*)?(?:Initial[ \t]+)?Proposal[ \t]+"
    r"(\d+-\d+-\d+(?:-v\d+)?)[ \t]*$", re.I)
RE_COMPANIES = re.compile(r"(?m)^[ \t]*(?:\[P\d+\][ \t]*)?(Companies|Proponents)[ \t]*[:：][ \t]*(.*)$", re.I)
RE_SEE_TDOC = re.compile(r"\bSee[ \t]+(R1-\d+)", re.I)
# 段落边界：只认「结构标题」，不认内容锚点。
# `Agreement:` 在 FL 正文里常是被引用的上一场结论（Background 段），不是章节界；
# 早先把它当边界，FL#5 的 Issue#1-1 被截成 151 字符，Ag9 就再也匹配不上了。
RE_STOP = re.compile(r"(?m)^[ \t]*(?:\[P\d+\][ \t]*)?"
                     r"(?:Topic|Issue|Proposals?[ \t]+for[ \t]+online[ \t]+session|"
                     r"Conclusion|Annex|Appendix)[ \t]*", re.I)
MAX_ISSUE_CHARS = 20000

_WORD = re.compile(r"[a-z0-9]+")


def _toks(s):
    return _WORD.findall(s.lower())


def _grams(s, n=4):
    t = _toks(s)
    if len(t) < n:
        return set([" ".join(t)]) if t else set()
    return set(" ".join(t[i:i + n]) for i in range(len(t) - n + 1))


def _overlap(block_text, target_text, n=4):
    """块与目标段的 4-gram 余弦相似度（0~1）。

    用余弦而不是「块被目标包含的比例」：后者在目标段异常长（FL 末尾的 Annex 把
    后面所有内容都吞进来）时会饱和成 1.000，导致所有块都挂到同一个 Issue 上。
    余弦里分母带 |target|，段越长分数越低，正好压掉这种膨胀。
    """
    bg = _grams(block_text, n)
    tg = _grams(target_text, n)
    if not bg or not tg:
        return 0.0
    inter = len(bg & tg)
    return inter / ((len(bg) ** 0.5) * (len(tg) ** 0.5))


def _work_dir(out_dir, agenda):
    if out_dir:
        return out_dir
    tag = re.sub(r"[^0-9A-Za-z]+", "_", agenda or "work").strip("_")
    return os.path.join(os.getcwd(), "_work_%s" % (tag or "work"))


def _dump(path, obj):
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    return path


def _read_text(path):
    with io.open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _find_workdir(target):
    """续篇旁边（或续篇所在目录）的 _work_<agenda>；找不到就返回空，交给 check 降级为警告。"""
    if not target:
        return ""
    d = os.path.dirname(os.path.abspath(target))
    for base in (d, os.path.dirname(d)):
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        hits = [n for n in names if n.startswith("_work_")
                and os.path.isdir(os.path.join(base, n))]
        if hits:
            return os.path.join(base, hits[0])
    return ""


def build_blocks(text):
    """按 Agreement / Working assumption 切块，并按内嵌 FL 分隔行定轮次。"""
    marks = []
    for m in RE_BLOCK_AG.finditer(text):
        marks.append((m.start(), m.end(), "agreement"))
    for m in RE_BLOCK_WA.finditer(text):
        marks.append((m.start(), m.end(), "wa"))
    # WA 正则可能吞掉 Agreement 内部的行；只保留不重叠的、按位置排序
    marks.sort()
    dedup = []
    for s, e, k in marks:
        if dedup and s < dedup[-1][1]:
            # 与上一块重叠：保留更早者（Agreement 优先）
            continue
        dedup.append((s, e, k))

    seps = [(m.start(), m.group(1), int(m.group(2))) for m in RE_FL_SEP.finditer(text)]

    blocks = []
    for i, (s, e, kind) in enumerate(dedup, 1):
        nxt = dedup[i][0] if i < len(dedup) else len(text)
        # 块尾还要停在下一个 FL 分隔行：分隔行是轮次标记，不是上一块的内容。
        # 不切的话，`R1-2607813  FL Summary #2  Moderator (Thales)` 会被当成上一块的原文
        # 抄进续篇——compose 直接从 blocks.json 注入原文，这个污染会原样出现在正文里。
        for pos, _t, _k in seps:
            if s < pos < nxt:
                nxt = pos
                break
        body = text[e:nxt]
        # 块尾截到下一个 Topic/Issue 或大段分隔
        body = body.strip("\r\n")
        # 轮次 = 该块起点之前最近的一条 FL 分隔行
        rnd, r1 = None, None
        for pos, tdoc, k in seps:
            if pos < s:
                rnd, r1 = k, tdoc
        if rnd is None:
            rnd, r1 = 1, None      # 首块之前没有分隔行 → 归 FL#1
        ffs = [x.strip() for x in RE_FFS.findall(body) if x.strip()]
        blocks.append({
            "id": "%s%d" % ("Ag" if kind == "agreement" else "WA", sum(
                1 for b in blocks if b["kind"] == kind) + 1),
            "kind": kind,
            "text": body,
            "chars": len(body),
            "fl_round": rnd,
            "fl_tdoc": r1,
            "ffs": ffs,
        })
    return blocks, seps


def cmd_blocks(verbatim, out_dir="", agenda="", as_json=False):
    p = os.path.abspath(verbatim)
    if not os.path.isfile(p):
        print("文件不存在：%s" % p, file=sys.stderr)
        return 2
    text = _read_text(p)
    blocks, seps = build_blocks(text)
    if not blocks:
        print("没切出任何块：确认这是主席报告目标议程项的逐字文本（含 'Agreement:' 行）", file=sys.stderr)
        return 2

    rounds = {}
    for b in blocks:
        rounds.setdefault(b["fl_round"], []).append(b["id"])
    # 单调性：轮次序列不能回头（块按文档顺序，轮次应非递减）
    seq = [b["fl_round"] for b in blocks]
    back = [i for i in range(1, len(seq)) if seq[i] < seq[i - 1]]
    # 未裁段的自检：整本主席报告会切出上百块，且 FL 分隔行往往不在目标议程项之外出现。
    # 不提示的话，agent 会照着 242 块往下写，直到全文崩掉才发现。
    warn = []
    if len(blocks) > 30:
        warn.append("块数 %d 远超单议程项常见量级（十余条）——确认 `_eom` 文本是否只含目标议程项，"
                    "没裁段就回 A2 裁。" % len(blocks))
    if not seps:
        warn.append("没找到任何 FL 分隔行（`R1-xxxxxxx  FL Summary #k`）——"
                    "要么这一段主席报告确实没内嵌，要么裁段时把分隔行裁掉了；轮次会全部归 FL#1。")

    ffs = [{"block": b["id"], "text": t} for b in blocks for t in b["ffs"]]
    d = _work_dir(out_dir, agenda)
    if not os.path.isdir(d):
        os.makedirs(d)
    bp = _dump(os.path.join(d, "blocks.json"), {
        "source": p, "blocks": blocks,
        "fl_separators": [{"line_pos": s, "tdoc": t, "round": k} for s, t, k in seps],
        "rounds": rounds, "warnings": warn})
    fp = _dump(os.path.join(d, "ffs.json"), {"source": p, "ffs": ffs})

    if as_json:
        print(json.dumps({"blocks": len(blocks), "rounds": rounds,
                          "ffs": len(ffs), "files": [bp, fp]}, ensure_ascii=False, indent=2))
        return 0

    print("切块：%d 块（Agreement %d + Working assumption %d）"
          % (len(blocks), sum(1 for b in blocks if b["kind"] == "agreement"),
             sum(1 for b in blocks if b["kind"] == "wa")))
    print("FL 分隔行：%d 条  → %s" % (len(seps), "、".join(
        "#%d=%s" % (k, t) for _, t, k in seps) or "无（全部归 FL#1）"))
    print("")
    print("轮次归属：")
    for k in sorted(rounds):
        print("  FL#%-3d %s" % (k, "、".join(rounds[k])))
    if back:
        print("\n✗ 轮次回头：第 %s 块处 fl_round 下降。主席报告块序应单调，"
              "检查是否混入了别的议程项段落。" % "、".join(str(i + 1) for i in back),
              file=sys.stderr)
    for w in warn:
        print("\n⚠ %s" % w, file=sys.stderr)
    print("\nFFS 行：%d 条" % len(ffs))
    print("→ %s" % bp)
    print("→ %s" % fp)
    return 1 if back else 0


def split_issues(text):
    """把一份 FL 的纯文本切成 Topic/Issue 树，并记每个 Issue 的四类片段。"""
    tps = [(m.start(), int(m.group(1)), m.group(2).strip()) for m in RE_TOPIC.finditer(text)]
    iss = [(m.start(), int(m.group(1)), int(m.group(2)), m.group(3).strip())
           for m in RE_ISSUE.finditer(text)]
    out = []
    seen_ids = {}
    for i, (s, a, b, title) in enumerate(iss):
        iid = "Issue#%d-%d" % (a, b)
        # 同一 Issue 在 FL 末尾常被再抽一次（「Companies are invited to elaborate」之类的收口段）。
        # 只认首次出现为主段，后续出现记为 revisit，不单独成节点。
        if iid in seen_ids:
            seen_ids[iid]["revisits"] += 1
            continue
        nxt = iss[i + 1][0] if i + 1 < len(iss) else len(text)
        for ts, _, _ in tps:
            if s < ts < nxt:
                nxt = ts
                break
        # 兜底边界：末尾 Annex / 下一个 Agreement 段落不能算进本 Issue。
        # 不设这道界，FL 末个 Issue 会一路吞到文件尾，n-gram 匹配时把所有块都吸走。
        for bm in RE_STOP.finditer(text, s + 1, nxt):
            nxt = bm.start()
            break
        if nxt - s > MAX_ISSUE_CHARS:
            nxt = s + MAX_ISSUE_CHARS
        seg = text[s:nxt]
        comp = [(g1, g2.strip()) for g1, g2 in RE_COMPANIES.findall(seg)]
        props = []
        pms = list(RE_PROPOSAL.finditer(seg))
        for j, m in enumerate(pms):
            pend = pms[j + 1].start() if j + 1 < len(pms) else len(seg)
            props.append({"id": m.group(1), "text": seg[m.end():pend].strip()})
        seen = RE_SEE_TDOC.findall(seg)
        topic = None
        for ts, tnum, ttitle in tps:
            if ts < s:
                topic = (tnum, ttitle)
        node = {
            "id": iid,
            "topic": "Topic#%d" % topic[0] if topic else None,
            "topic_title": topic[1] if topic else None,
            "title": title,
            "start": s, "end": nxt, "chars": nxt - s,
            "companies": comp,
            "proposals": props,
            "see_tdoc": sorted(set(seen)),
            "revisits": 0,
            "text": seg,
        }
        seen_ids[iid] = node
        out.append(node)
    # 提案编号自带归属：`Proposal 2-4-1` 属于 `Issue#2-4`。
    # 用它把「Proposals for online session」这类收口段里的提案追回各自 Issue ——
    # 在线会段的提案常常是会议最终结论的直接前身（如 X ≤ 20/50/150 m），
    # 只按位置切段会把它漏掉，导致对应的 Agreement 匹配不上任何 Issue。
    by_id = {x["id"]: x for x in out}
    allp = list(RE_PROPOSAL.finditer(text))
    for j, m in enumerate(allp):
        pid = m.group(1)
        parts = pid.split("-")
        if len(parts) < 2:
            continue
        host = by_id.get("Issue#%s-%s" % (parts[0], parts[1]))
        if not host:
            continue
        if any(p["id"] == pid for p in host["proposals"]):
            continue
        pend = allp[j + 1].start() if j + 1 < len(allp) else len(text)
        body = text[m.end():pend]
        # 只取到下一个结构标题为止，避免又把整段尾巴拉进来；
        # 同时切在 `(Proposed) working assumption` 前 —— 收口段里 WA 紧跟提案，
        # 不切的话 TAC/FAC 量程会被算进上一个 Issue，WA1/WA2 就会挂错。
        sm = RE_STOP.search(body)
        if sm:
            body = body[:sm.start()]
        wm = re.search(r"(?mi)^[ \t]*(?:Proposed[ \t]+)?Working[ \t]+assumption", body)
        if wm:
            body = body[:wm.start()]
        host["proposals"].append({"id": pid, "text": body.strip()[:4000],
                                  "from_recap": True})
    return out, tps


def cmd_issues(files, out_dir="", agenda="", as_json=False):
    if not files:
        print("用法：skillctl issues <FL1.txt> [FL2.txt ...] --out-dir _work_941", file=sys.stderr)
        return 2
    per_file, all_ids = [], []
    for f in files:
        p = os.path.abspath(f)
        if not os.path.isfile(p):
            print("文件不存在：%s" % p, file=sys.stderr)
            return 2
        items, tps = split_issues(_read_text(p))
        per_file.append({"file": p, "issues": items,
                         "topics": [{"no": n, "title": t} for _, n, t in tps]})
        for it in items:
            if it["id"] not in all_ids:
                all_ids.append(it["id"])

    # 骨架以「最末一份 FL」为基准（轮次靠文件名顺序不可靠，交给调用方按轮次给序）
    base = per_file[-1]["issues"] if per_file else []
    base_ids = [x["id"] for x in base]
    diff = {"only_in_earlier": sorted(set(all_ids) - set(base_ids)),
            "only_in_latest": sorted(set(base_ids) - set(all_ids))}

    merged = []
    for it in base:
        hits = [pf["file"] for pf in per_file
                if any(x["id"] == it["id"] for x in pf["issues"])]
        merged.append({
            "id": it["id"], "topic": it["topic"], "topic_title": it["topic_title"],
            "title": it["title"], "chars": it["chars"],
            "companies": [c for c in it["companies"]],
            "proposal_ids": [p["id"] for p in it["proposals"]],
            "see_tdoc": it["see_tdoc"],
            "revisits": it.get("revisits", 0),
            "seen_in": [os.path.basename(h) for h in hits],
        })

    d = _work_dir(out_dir, agenda)
    if not os.path.isdir(d):
        os.makedirs(d)
    out = _dump(os.path.join(d, "issues.json"), {
        "files": per_file, "skeleton_base": per_file[-1]["file"] if per_file else None,
        "issues": merged, "cross_round_diff": diff})

    if as_json:
        print(json.dumps({"issues": len(merged), "diff": diff, "file": out},
                         ensure_ascii=False, indent=2))
        return 0
    print("FL 文件：%d 份" % len(per_file))
    print("议题骨架（以 %s 为基准）：%d 个 Issue / %d 个 Topic"
          % (os.path.basename(per_file[-1]["file"]) if per_file else "-",
             len(merged), len(per_file[-1]["topics"]) if per_file else 0))
    nocomp = [x["id"] for x in merged if not x["companies"]]
    print("  有立场段：%d   无立场段：%d %s"
          % (len(merged) - len(nocomp), len(nocomp),
             ("（" + "、".join(nocomp[:6]) + ("…" if len(nocomp) > 6 else "") + "）") if nocomp else ""))
    if diff["only_in_earlier"] or diff["only_in_latest"]:
        print("  跨轮骨架差异：早份独有 %s；末份独有 %s"
              % (diff["only_in_earlier"] or "无", diff["only_in_latest"] or "无"))
    print("→ %s" % out)
    return 0


def cmd_flow(blocks_json, issues_json, out_dir="", agenda="", as_json=False, min_score=0.06):
    bp = os.path.abspath(blocks_json)
    ip = os.path.abspath(issues_json)
    for p in (bp, ip):
        if not os.path.isfile(p):
            print("文件不存在：%s" % p, file=sys.stderr)
            return 2
    bj = json.loads(_read_text(bp))
    ij = json.loads(_read_text(ip))
    blocks = bj["blocks"]
    # Issue 全量（含每份 FL 的正文），用于匹配与串链
    full = {}
    for pf in ij["files"]:
        for it in pf["issues"]:
            full.setdefault(it["id"], []).append((os.path.basename(pf["file"]), it))
    latest_file = os.path.basename(ij.get("skeleton_base") or "")
    ordered = []
    for iid in [x["id"] for x in ij["issues"]]:
        ordered.append(iid)
    for iid in full:
        if iid not in ordered:
            ordered.append(iid)

    flows = []
    for b in blocks:
        cands = []
        for iid in ordered:
            # 逐份 FL 单独打分取最大，而不是把所有 FL 的 Proposal 拼成一段。
            # 拼接会让「末份 FL 里把全部结论又复述一遍」的那一段变成万能吸铁石。
            best = 0.0
            for _fname, it in full.get(iid, []):
                # 先跟 Proposal 段比；Proposal 没命中再拿整段兜底（短块如「X ≤ 20/50/150 m」
                # 在自己的 Proposal 里可能只写了一半，语义落在正文里）。
                tgts = [x["text"][:8000] for x in it["proposals"]]
                tgts.append(it["text"][:6000])
                for t in tgts:
                    best = max(best, _overlap(b["text"], t))
            if best >= min_score:
                cands.append({"issue": iid, "score": round(best, 3)})
        cands.sort(key=lambda x: -x["score"])
        cands = cands[:3]

        chosen = cands[0]["issue"] if cands else None
        rounds, origins, props = [], set(), set()
        if chosen:
            for fname, it in full.get(chosen, []):
                rounds.append({
                    "fl": fname,
                    "is_latest": fname == latest_file,
                    "proposals": [p["id"] for p in it["proposals"]],
                    "companies": len(it["companies"]),
                    "chars": it["chars"],
                })
                origins.update(it["see_tdoc"])
                for _kind, val in it["companies"]:
                    for m in re.finditer(r"[A-Z][A-Za-z&\.\- ]{2,30}", val):
                        nm = m.group(0).strip(" .-")
                        if nm:
                            props.add(nm)
        # 收口状态：看主句动作，而不是只看有没有 FFS
        low = b["text"].lower()
        head = low[:400]
        if re.search(r"to down-select|to discuss|to consider|to study|for further study", head):
            status = "未裁决"
        elif "ffs" in low:
            status = "部分收口"
        else:
            status = "落槌"
        flows.append({
            "block_id": b["id"], "fl_round": b["fl_round"],
            "issue": chosen,
            "issue_title": (full.get(chosen) or [("", {})])[0][1].get("title", "") if chosen else "",
            "candidates": cands,
            "needs_model": (not cands) or (len(cands) > 1 and
                                           cands[0]["score"] - cands[1]["score"] < 0.03),
            "rounds": rounds,
            "origins_tdoc": sorted(origins),
            "proponents": sorted(props),
            "final_status": status,
            "final_status_is_tool_guess": True,
            "delta": "",
            "tdoc_reason": "",
        })

    d = _work_dir(out_dir, agenda)
    if not os.path.isdir(d):
        os.makedirs(d)
    out = _dump(os.path.join(d, "flow.json"), {
        "blocks": bp, "issues": ip, "flows": flows,
        "note": "delta / tdoc_reason 由模型填；needs_model=true 的块需模型定 issue"})

    if as_json:
        print(json.dumps({"flows": len(flows),
                          "needs_model": [f["block_id"] for f in flows if f["needs_model"]],
                          "file": out}, ensure_ascii=False, indent=2))
        return 0
    print("讨论链：%d 块" % len(flows))
    print("")
    print("%-6s %-6s %-14s %-7s %s" % ("块", "轮次", "Issue", "分数", "状态"))
    for f in flows:
        sc = ("%.3f" % f["candidates"][0]["score"]) if f["candidates"] else "-"
        flag = "  ← 需模型判定" if f["needs_model"] else ""
        print("%-6s FL#%-3d %-14s %-7s %s%s"
              % (f["block_id"], f["fl_round"], f["issue"] or "UNMAPPED", sc,
                 f["final_status"], flag))
    need = [f["block_id"] for f in flows if f["needs_model"]]
    print("")
    print("需模型判定：%s" % ("、".join(need) if need else "无"))
    print("→ %s" % out)
    return 0


def cmd_tdoc(path, out="", head=0, as_json=False):
    p = os.path.abspath(path)
    if not os.path.isfile(p):
        print("文件不存在：%s" % p, file=sys.stderr)
        return 2
    paras = docx_paras(p)
    if paras is None:
        print("抽不出文本：%s" % p, file=sys.stderr)
        return 2
    if not out:
        base = os.path.splitext(os.path.basename(p))[0]
        d = os.path.join(os.getcwd(), "_tdoc")
        if not os.path.isdir(d):
            os.makedirs(d)
        out = os.path.join(d, base + ".txt")
    with io.open(out, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(paras))
    print("✓ 抽取 %d 段 → %s" % (len(paras), out))
    print("  ⚠ TDoc 属按需取用：必须在 flow.json 的 tdoc_reason 里记触发条件编号与理由。",
          file=sys.stderr)
    if head > 0:
        for l in paras[:head]:
            print(l)
    return 0


RE_WI_HINT = [
    (r"prach|RO[ -]?pair|RO configuration|root sequence|SSB-to-RO|RAR window|RA-RNTI|Preamble", "A1"),
    (r"TAC in Msg2|FAC in Msg2|Msg2", "A2"),
    (r"TA control|TA drift", "B1/B2"),
    (r"FA control|FAC", "B4"),
    (r"Reference-location|TA/Doppler|pre-comp|last known", "C1"),
    (r"mobility|RRM|RF|demod|test", "C4"),
]


REL_KINDS = ("CONTINUE", "NEW", "DERIVED", "SPLIT", "RELATED")


def _rel_apply(fj, wj, out_dir, agenda, patch_path, as_json=False):
    """把模型对每个 WI 条目的判定（kind / base_ref / blocks / covered_by）合并进 rel.json。

    合并而非覆盖：工具算出来的 base_text / issues 保留，模型只补判定字段。
    新增条目（N1–N4 这类基线没有的派生条目）用 patch 追加。
    """
    d = _work_dir(out_dir, agenda)
    rp = os.path.join(d, "rel.json")
    if not os.path.isfile(rp):
        print("还没有 rel.json：先跑一次不带 --apply 的 rel 生成底稿", file=sys.stderr)
        return 2
    if not os.path.isfile(patch_path):
        print("patch 不存在：%s" % patch_path, file=sys.stderr)
        return 2
    rel = json.loads(_read_text(rp))
    patch = json.loads(_read_text(patch_path))
    ents, order = {}, []
    for e in rel.get("entries") or []:
        ents[e["wi"]] = e
        order.append(e["wi"])
    added, changed = [], []
    for pe in patch.get("entries") or []:
        wi = (pe.get("wi") or "").strip()
        if not wi:
            print("patch 里有条目缺 wi", file=sys.stderr)
            return 2
        if wi in ents:
            for k in ("kind", "base_ref", "evidence", "blocks", "issues",
                      "title", "covered_by", "note"):
                if k in pe:
                    ents[wi][k] = pe[k]
            changed.append(wi)
        else:
            for k, v in (("title", ""), ("kind", ""), ("base_ref", ""),
                         ("evidence", ""), ("blocks", []), ("issues", [])):
                pe.setdefault(k, v)
            ents[wi] = pe
            order.append(wi)
            added.append(wi)

    # --- 判定结果的自校验：这三条错了，正文的块数守恒一定跟着错 ---
    bad_kind = [w for w in order if (ents[w].get("kind") or "") not in REL_KINDS]
    no_ref = [w for w in order
              if ents[w].get("kind") in ("DERIVED", "SPLIT") and not ents[w].get("base_ref")]
    seen = {}
    for w in order:
        for b in ents[w].get("blocks") or []:
            seen.setdefault(b, []).append(w)
    dup = {b: w for b, w in seen.items() if len(w) > 1}
    all_blocks = [f["block_id"] for f in json.loads(_read_text(fj))["flows"]]
    orphan = [b for b in all_blocks if b not in seen]

    _dump(rp, dict(rel, entries=[ents[w] for w in order]))
    problems = []
    if bad_kind:
        problems.append("关系类型未填/非法：%s（须为 %s）"
                        % ("、".join(bad_kind), "/".join(REL_KINDS)))
    if no_ref:
        problems.append("DERIVED/SPLIT 缺 base_ref：%s" % "、".join(no_ref))
    if dup:
        problems.append("块被挂到多个条目：%s"
                        % "、".join("%s→%s" % (b, "+".join(w)) for b, w in dup.items()))
    if orphan:
        problems.append("有块没挂到任何条目：%s" % "、".join(orphan))

    if as_json:
        print(json.dumps({"added": added, "changed": changed, "problems": problems,
                          "file": rp}, ensure_ascii=False, indent=2))
        return 0 if not problems else 1
    print("已合并判定：新增 %d 条（%s）  更新 %d 条"
          % (len(added), "、".join(added) or "无", len(changed)))
    print("块覆盖：%d/%d" % (len(seen), len(all_blocks)))
    if problems:
        print("\n判定有问题：")
        for p in problems:
            print("  ✗ " + p)
    else:
        print("判定自检：关系类型齐全、派生有出处、块无重复无遗漏 ✓")
    print("→ %s" % rp)
    return 0 if not problems else 1


def cmd_rel(flow_json, wid_json, out_dir="", agenda="", as_json=False, apply=""):
    """把 flow.json 的「块→Issue」与 wid.json 的「WI 条目」拼成 B2 的判定表。

    工具只做机械部分：Issue 按关键词给 WI 候选、块按 Issue 挂到 WI 下。
    关系类型（CONTINUE/NEW/DERIVED/SPLIT/RELATED）与 base_ref 留给模型填。

    --apply patch.json：把模型判定写回 rel.json。
    没有这个回写口，模型判完的结果就只活在正文里，下一场没法复用，也审不出来。
    """
    fj, wj = os.path.abspath(flow_json), os.path.abspath(wid_json)
    for p in (fj, wj):
        if not os.path.isfile(p):
            print("文件不存在：%s" % p, file=sys.stderr)
            return 2
    if apply:
        return _rel_apply(fj, wj, out_dir, agenda, apply, as_json)
    flows = json.loads(_read_text(fj))["flows"]
    wids = json.loads(_read_text(wj))["entries"]

    issue_wi, unmapped, issue_title = {}, [], {}
    for f in flows:
        iid = f.get("issue")
        if not iid:
            continue
        title = f.get("issue_title") or ""
        issue_title[iid] = title
        if iid in issue_wi:
            continue
        hit = None
        hay = "%s %s" % (iid, title)
        for pat, code in RE_WI_HINT:
            if re.search(pat, hay, re.I):
                hit = code
                break
        issue_wi[iid] = hit
        if not hit:
            unmapped.append(iid)

    entries = {}
    for w in wids:
        entries[w["code"]] = {
            "wi": w["code"], "title": w["title"], "wg": w["wg"],
            "base_text": w.get("base", ""), "base_status": w.get("status", ""),
            "kind": "", "base_ref": "", "evidence": "",
            "blocks": [], "issues": [],
        }
    for f in flows:
        iid = f.get("issue")
        code = issue_wi.get(iid)
        if code and code in entries:
            entries[code]["blocks"].append(f["block_id"])
            if iid not in entries[code]["issues"]:
                entries[code]["issues"].append(iid)

    d = _work_dir(out_dir, agenda)
    if not os.path.isdir(d):
        os.makedirs(d)
    out = _dump(os.path.join(d, "rel.json"), {
        "flow": fj, "wid": wj,
        "note": "kind/base_ref/evidence 由模型填；blocks 由工具按 Issue→WI 挂接",
        "issue_to_wi": {k: v for k, v in issue_wi.items()},
        "unmapped_issues": unmapped,
        "entries": [entries[c] for c in [w["code"] for w in wids]]})

    if as_json:
        print(json.dumps({"entries": len(entries), "unmapped": unmapped, "file": out},
                         ensure_ascii=False, indent=2))
        return 0
    print("WI 条目：%d   已挂块：%d/%d 块"
          % (len(entries), sum(len(e["blocks"]) for e in entries.values()), len(flows)))
    for c in [w["code"] for w in wids]:
        e = entries[c]
        mark = "—" if not e["blocks"] else "、".join(e["blocks"])
        print("  %-6s %-28s %s" % (c, e["title"][:26], mark))
    if unmapped:
        print("\n未挂上的 Issue（需模型定 WI）：%s" % "、".join(unmapped))
    print("→ %s" % out)
    print("模型下一步：给每个有块的条目填 kind / base_ref / evidence")
    return 0


# ---------------------------------------------------------------------------
# B3　compose：按 rel.json 组装正文
#
# 这一步存在的理由：结构（哪条 WI 在前面、哪块挂哪、块序、四段标题）是机械的，
# 让模型手工拼，就会拼出块数不守恒、块号漏标、节号不连续这类错——而且每场都要再错一次。
# 内容（①基线原状 / ②解读映射 / ③演进 / ④遗留）是人写的，重排时必须原样带走。
# ---------------------------------------------------------------------------

SEG_BASE, SEG_NOW, SEG_EVOL, SEG_LEFT = "**① 基线原状**", "**② 本次进展**", "**③ 演进分析**", "**④ 遗留**"
SEG_JIE, SEG_MAP = "**`【解读】`**", "**`【映射】`**"

# 占位符指纹：段里出现这些字样，就当作「还没填」，重排时用模板占位替换掉，
# 免得把模板提示语当成正文一路带下去。真实内容里不会出现这些串。
PH = ("逐字粘贴", "从基准报告抄该条目", "本场推进了什么", "原样列出；标是否阻塞",
      "这条裁定了什么", "判据待填", "预估受影响：TS xxx", "（待填）")

PH_BASE = ("> 从基准报告抄该条目已定的内容（含上一场是哪条 Ag 落槌）。"
           "不许改写、不许只写\"已覆盖\"。")
PH_EVOL = ("> 本场推进了什么 / 与历次比差异在哪 / 关系类型（延续·派生·拆分·关联）带来什么影响。\n"
           "> 必须同时引用一处基线原文与一处本场原文。")
PH_LEFT = "> 该 WI 下所有 `FFS:` 原样列出；标是否阻塞 Core 封版。"
PH_JIE = ("1. 这条裁定了什么、排除了什么\n"
          "2. 与基线原状的差异（由 A 变成 B）\n"
          "3. 技术论据（为什么是这个结果）——**凡引公司立场，必须标来源 `FL#k / Issue#x-y`**")
PH_NOW_EMPTY = "**本场无进展。**（判据待填：RAN4/RAN2 事项？未进议程？）"

RE_SUB = re.compile(r"^###\s+[\d.]+\s*[　 ]\s*([A-Z]{1,2}\d{1,2}(?:/[A-Z]{1,2}\d{1,2})*)")


def _is_ph(s):
    return (not s) or any(k in s for k in PH)


def _clean(s):
    """去掉段首尾的空行与 `---` 分隔线。

    分隔线是**结构**，由 compose 统一发。若让它跟着段内容来回搬，
    每跑一次就多一条（实测第二次 compose 会凭空插进 6 条 `---`）。
    """
    s = (s or "").strip()
    s = re.sub(r"^(?:-{3,}[ \t]*\n+)+", "", s)
    s = re.sub(r"(?:\n+-{3,}[ \t]*)+\s*$", "", s)
    return s.strip()


def _seg(body, start, end=None):
    """取 body 里 start 标记之后、end 标记之前的内容。"""
    i = body.find(start)
    if i < 0:
        return ""
    i += len(start)
    if end:
        j = body.find(end, i)
        return body[i:j if j >= 0 else None]
    return body[i:]


def parse_section(sec_text):
    """把已有正文拆成可复用的碎片：{wi: {base, evol, left, title}} + {block: {title, raw, jie, map}}。

    `raw` 是正文里已经排好的原文段。**必须保住**：docx 抽出来的原文带行首 tab、
    被表格打断的列表（`X= 20m`）、多余空格（`" RO pair "`），正文里已经人工清理过一轮。
    用 blocks.json 去覆盖等于把清理成果冲掉——`X = 20 m / 50 m / 150 m` 会退回成 `X= 20m`。
    新块（正文里还没有的）才从 blocks.json 注入。
    """
    keep_wi, keep_blk = {}, {}
    subs = re.split(r"(?m)^###[ \t]+", sec_text)[1:]
    for sub in subs:
        first, _, rest = sub.partition("\n")
        m = RE_SUB.match("### " + first)
        if not m:
            continue
        wi = m.group(1)
        keep_wi[wi] = {
            "title": re.sub(r"（本场[^）]*）\s*$", "", first.split("　", 1)[-1]).split("｜", 1)[-1].strip(),
            "base": _clean(_seg(rest, SEG_BASE, SEG_NOW)),
            "evol": _clean(_seg(rest, SEG_EVOL, SEG_LEFT)),
            "left": _clean(_seg(rest, SEG_LEFT)),
            "now": _clean(_seg(rest, SEG_NOW, SEG_EVOL)),
        }
        now = _seg(rest, SEG_NOW, SEG_EVOL)
        # 逐个块切：块标签是 **`【原文】AgN`**（新式）或 **`【原文】`**（旧式，块号在别处）
        marks = list(re.finditer(r"\*\*`?【原文】`?[ \t]*(?:(Ag|WA)\d+)?[ \t]*`?\*\*", now))
        for k, mk in enumerate(marks):
            mm = re.search(r"(Ag|WA)(\d+)", mk.group(0))
            if not mm:
                continue            # 旧式空标签且块号不在这行：跳过，交给正文层报错
            bid = mm.group(1) + mm.group(2)
            end = marks[k + 1].start() if k + 1 < len(marks) else len(now)
            chunk = now[mk.end():end]
            # 截断点落在「下一块的标签」之前，中间还夹着下一块的标题行——
            # 不摘掉的话，raw 会把它带进上一块，compose 再生成一次标题 → 标题重复。
            # 标题行有两种：`**Ag3｜…**　<sub>…</sub>`（有人工标题）与 `**Ag3**`
            # （blocks.json 没有 block_title 时生成的裸标记），两种都得摘。
            cl = chunk.rstrip("\n").split("\n")
            while cl and not cl[-1].strip():
                cl.pop()
            if cl and re.match(r"^\*\*(?:Ag|WA)\d+(?:｜.*)?\*\*(?:[ \t\u3000]*<sub>.*</sub>)?$",
                               cl[-1].strip()):
                cl.pop()
                while cl and not cl[-1].strip():
                    cl.pop()
            chunk = "\n".join(cl)
            # 块标题：标签上方紧邻的非空行
            prev = [l for l in now[:mk.start()].rstrip().split("\n")]
            btitle, bsub = "", ""
            if prev and re.match(r"^\*\*(?:Ag|WA)\d+", prev[-1].strip()):
                btitle = re.sub(r"\s*<sub>.*?</sub>\s*$", "", prev[-1]).strip()
                if re.match(r"^\*\*(?:Ag|WA)\d+\*\*$", btitle):
                    btitle = ""      # 裸块标记：本来就没有标题，别把它当成标题
                # `<sub>` 里除了能算出来的 `FL#n`，还有算不出来的 `· Issue#x-y` 归属
                # （来自 B2 的 flow 判定）。丢了它，重跑一次就把溯源标注抹平。
                ms = re.search(r"<sub>(.*?)</sub>\s*$", prev[-1])
                if ms:
                    bsub = ms.group(1).strip()
            keep_blk[bid] = {
                "title": btitle,
                "sub": bsub,
                "raw": _clean(_seg(chunk, "", SEG_JIE)),
                "jie": _seg(chunk, SEG_JIE, SEG_MAP).strip(),
                "map": _seg(chunk, SEG_MAP).strip(),
            }
    return keep_wi, keep_blk


def cmd_compose(rel_json, blocks_json, target="", out="", sec="", as_json=False):
    for p in (rel_json, blocks_json):
        if not os.path.isfile(p):
            print("文件不存在：%s" % p, file=sys.stderr)
            return 2
    if not sec:
        print("缺 --section：要组装的是哪一节，如 4.7", file=sys.stderr)
        return 2
    if not target:
        print("缺 --target：往哪份续篇里组装（先 init 生出骨架）", file=sys.stderr)
        return 2
    target = os.path.abspath(target)
    if not os.path.isfile(target):
        print("续篇不存在：%s" % target, file=sys.stderr)
        return 2

    rel = json.loads(_read_text(rel_json))
    bj = json.loads(_read_text(blocks_json))
    bmap = {b["id"]: b for b in bj["blocks"]}
    order_in_doc = {b["id"]: i for i, b in enumerate(bj["blocks"])}
    ents = [e for e in rel.get("entries") or [] if (e.get("wi") or "").strip()]

    # ffs.json / flow.json 在同目录就带上：前者自动生成 ④，后者给块补「宿主 Issue」
    ffs, blk_issue = [], {}
    fp = os.path.join(os.path.dirname(blocks_json), "ffs.json")
    if os.path.isfile(fp):
        ffs = json.loads(_read_text(fp)).get("ffs") or []
    qp = os.path.join(os.path.dirname(blocks_json), "flow.json")
    if os.path.isfile(qp):
        for f in json.loads(_read_text(qp)).get("flows") or []:
            if f.get("issue"):
                blk_issue[f["block_id"]] = f["issue"]

    # ---------- 判定层自检（正文层由 check 兜，这里先拦住明显的） ----------
    seen, dup, unknown = {}, {}, []
    for e in ents:
        for b in e.get("blocks") or []:
            seen.setdefault(b, []).append(e["wi"])
            if b not in bmap:
                unknown.append(b)
    for b, ws in seen.items():
        if len(ws) > 1:
            dup[b] = ws
    orphan = [b for b in bmap if b not in seen]
    problems = []
    if dup:
        problems.append("块被挂到多个条目：%s"
                        % "、".join("%s→%s" % (b, "+".join(w)) for b, w in dup.items()))
    if unknown:
        problems.append("rel.json 引用了 blocks.json 里没有的块：%s" % "、".join(sorted(set(unknown))))
    if orphan:
        problems.append("有块没挂到任何条目（正文会缺块）：%s" % "、".join(orphan))
    if problems:
        for p in problems:
            print("✗ " + p, file=sys.stderr)
        print("先修 rel.json（`rel --apply`）再组装。", file=sys.stderr)
        return 1

    # ---------- 读旧正文，保住已写的内容 ----------
    doc = _read_text(target)
    i = doc.find("## §" + sec)
    if i < 0:
        print("续篇里没有 `## §%s` 这一节：先 `init` 生成骨架，或把 --section 指对" % sec,
              file=sys.stderr)
        return 2
    j = len(doc)
    for m in re.finditer(r"(?m)^##\s+§", doc[i + 3:]):
        j = i + 3 + m.start()
        break
    keep_wi, keep_blk = parse_section(doc[i:j])

    # ---------- 节号：按 rel 顺序连号 ----------
    nums = {e["wi"]: "%s.%d" % (sec, n) for n, e in enumerate(ents, 1)}
    wl = {e["wi"]: (e.get("blocks") or []) for e in ents}

    def title_of(e):
        """标题优先取正文里已有的（人写的、更具体），其次取 rel.json 的（WID 表原词）。

        反过来会让每次 compose 都把人工润色的标题打回 WID 表原文，白改。
        """
        t = (keep_wi.get(e["wi"]) or {}).get("title") or ""
        if t and not _is_ph(t) and "一句话标题" not in t:
            return t.strip()
        return (e.get("title") or "").strip()

    def block_sort(bid):
        b = bmap[bid]
        return (b.get("fl_round") or 0, order_in_doc.get(bid, 0))

    out_lines = ["## §%s　按 WI 条目的本场进展（%d 条目，每条四段）" % (sec, len(ents)), ""]
    out_lines += [
        "> **两个单元必须分开**：**组织单元 = WI 条目**（跨会议不变）；"
        "**对账单元 = Agreement 块**（本场 %d 条，逐字可溯源）。" % len(bmap),
        "> 每个条目一节，节内固定四段：① **基线原状**（抄基准报告）② **本次进展**"
        "（逐块【原文】/【解读】/【映射】，块序按 FL 轮次升序）③ **演进分析** ④ **遗留**。",
        "> **块数守恒**：本场 %d 块在全文出现且仅出现一次。一个块同时涉及两个条目时，"
        "**主挂一处、另一处写指针**（`covered_by`），不复制原文。" % len(bmap),
        "> **无进展条目一律保留**并写明原因——删掉就看不出哪一条在停滞。",
        "",
        "**关系类型图例**：`CONTINUE` 基线已有、本场继续 ｜ `NEW` 基线完全没有 ｜ "
        "`DERIVED` 由基线某条派生（须注明 base_ref）｜ `SPLIT` 由基线一条拆为多条 ｜ "
        "`RELATED` 名称不同但有关联。",
        "",
        "| # | WI 条目 | 关系 | 本场块 | FL 轮次 |",
        "|---|---|---|---|---|",
    ]
    for e in ents:
        bs = sorted(e.get("blocks") or [], key=block_sort)
        rounds = ["#%s" % bmap[b].get("fl_round") for b in bs]
        out_lines.append("| %s | **%s** %s | %s | %s | %s |" % (
            nums[e["wi"]], e["wi"], title_of(e),
            e.get("kind") or "—",
            "、".join(bs) if bs else ("—（由 %s 覆盖）" % e["covered_by"]
                                      if e.get("covered_by") else "—"),
            " / ".join(rounds) if rounds else ("见 §%s" % nums.get(e.get("covered_by"), "")
                                              if e.get("covered_by") else "无进展")))
    total = sum(len(e.get("blocks") or []) for e in ents)
    out_lines += ["",
                  "**块数自证**：%s = **%d** %s" % (
                      " + ".join("%d（%s）" % (len(e.get("blocks") or []), e["wi"])
                                 for e in ents if e.get("blocks")),
                      total, "✓" if total == len(bmap) else "✗"),
                  "", "---", ""]

    gaps = {"base": 0, "jie": 0, "map": 0, "evol": 0, "left": 0}
    reused = injected = 0
    for idx, e in enumerate(ents):
        wi = e["wi"]
        kw = keep_wi.get(wi, {})
        bs = sorted(e.get("blocks") or [], key=block_sort)
        if idx:
            out_lines += ["---", ""]          # 分隔线统一在节前发，第一节除外
        if bs:
            tail = "%d 块" % len(bs)
        elif e.get("covered_by"):
            tail = "由 %s 覆盖" % e["covered_by"]
        else:
            tail = "无进展"
        out_lines.append("### %s　%s｜%s（本场：%s，%s）"
                         % (nums[wi], wi, title_of(e), e.get("kind") or "—", tail))
        out_lines.append("")

        base = kw.get("base") or ""
        if _is_ph(base):
            base, gaps["base"] = PH_BASE, gaps["base"] + 1
        out_lines += [SEG_BASE, base, ""]

        out_lines += [SEG_NOW, ""]
        if not bs:
            kept_now = kw.get("now") or ""
            if not _is_ph(kept_now) and "本场无独立块" not in kept_now:
                out_lines += [kept_now, ""]          # 人写的「本场无进展 + 判据」要留住
            elif e.get("covered_by"):
                host = nums.get(e["covered_by"], "?")
                who = "、".join(wl.get(e["covered_by"]) or []) or "该条目的块"
                out_lines += ["**本场无独立块。** 由 §%s（%s）的 %s 覆盖——%s"
                              % (host, e["covered_by"], who,
                                 (e.get("note") or "按块数守恒，主挂一处，此处只留指针，不复制原文。")),
                              ""]
            else:
                out_lines += [PH_NOW_EMPTY, ""]
        for bid in bs:
            b = bmap[bid]
            kb = keep_blk.get(bid, {})
            bt = kb.get("title") or b.get("block_title") or ""
            # 只摘掉外层 **AgN｜ 与收尾的 **，块标题内部的粗体（如「**同时**支持」）要留住
            bt = re.sub(r"^\*\*(?:Ag|WA)\d+｜", "", bt).strip()
            bt = re.sub(r"\*\*$", "", bt).strip()
            head = "**%s%s**" % (bid, ("｜" + bt) if bt else "")
            sub = "FL#%s" % b.get("fl_round")
            if blk_issue.get(bid):
                sub += " · %s" % blk_issue[bid]
            kept_sub = (kb.get("sub") or "").strip()
            if kept_sub:
                # 正文里的 sub 带着 `· Issue#x-y`，那是 B2 判出来的归属，blocks.json 里没有。
                # 用算出来的 FL 去重建只会把它抹掉——和 `title_of` 一样，正文优先。
                if b.get("fl_round") and ("FL#%s" % b["fl_round"]) not in kept_sub:
                    print("  ! %s 轮次不一致：正文写 `%s`，切块算 FL#%s（按正文保留）"
                          % (bid, kept_sub, b["fl_round"]), file=sys.stderr)
                sub = kept_sub
            out_lines.append("%s　<sub>%s</sub>" % (head, sub))
            out_lines.append("")
            out_lines.append("**`【原文】%s`**" % bid)
            raw = (kb.get("raw") or "").strip()
            if raw:
                # 已有正文里的原文段逐字带走，**不加任何前缀**：段里可能夹着 `〔校〕` 这类
                # 非引用注记，强行加 `>` 会把注记变成"原文的一部分"，语义就反了。
                out_lines += [ln.rstrip() for ln in raw.split("\n")]
                reused += 1
            else:
                # 新块从 blocks.json 注入：原文是纯文本，才需要补 `>` 让它成为引用块
                for ln in (b.get("text") or "").strip("\n").split("\n"):
                    ln = ln.rstrip()
                    out_lines.append("> " + ln if ln and not ln.startswith(">") else (ln or ">"))
                injected += 1
            out_lines.append("")
            jie = kb.get("jie") or ""
            if _is_ph(jie):
                jie, gaps["jie"] = PH_JIE, gaps["jie"] + 1
            out_lines += [SEG_JIE, jie, ""]
            mp = kb.get("map") or ""
            if _is_ph(mp):
                mp, gaps["map"] = ("WI **%s**｜预估受影响：TS xxx（功能块）· TS yyy" % wi,
                                   gaps["map"] + 1)
            out_lines += [SEG_MAP + " " + mp, ""]

        evol = kw.get("evol") or ""
        if _is_ph(evol):
            evol, gaps["evol"] = PH_EVOL, gaps["evol"] + 1
        out_lines += [SEG_EVOL, evol, ""]

        left = kw.get("left") or ""
        if _is_ph(left):
            mine = [f for f in ffs if f["block"] in bs]
            if mine:
                lines = ["FFS 原样清单：", ""]
                for f in mine:
                    lines.append("- **%s**：`FFS: %s`" % (f["block"], f["text"]))
                lines.append("")
                lines.append("**阻塞判断**：（待填——是否阻塞 Core 封版，给一句判据）")
                left = "\n".join(lines)
            else:
                left = PH_LEFT
            gaps["left"] += 1
        out_lines += [SEG_LEFT, left, ""]

    out_lines += ["---", ""]
    new_sec = "\n".join(out_lines).rstrip("\n") + "\n\n"
    # 块数守恒自证：生成的正文里每块恰好一个标签
    labs = re.findall(r"【原文】((?:Ag|WA)\d+)", new_sec)
    if len(labs) != total or len(set(labs)) != len(labs) or set(labs) != set(bmap):
        print("✗ 组装的正文块数不自证：标签 %d 个 / 应 %d 个" % (len(labs), total), file=sys.stderr)
        return 1

    doc_new = doc[:i] + new_sec + doc[j:]
    dst = os.path.abspath(out) if out else target
    with io.open(dst, "w", encoding="utf-8", newline="") as f:
        f.write(doc_new)

    filled = len(ents)
    n_block_ents = sum(1 for e in ents if e.get("blocks"))
    n_ptr = sum(1 for e in ents if not e.get("blocks") and e.get("covered_by"))
    if as_json:
        print(json.dumps({"wi_entries": filled, "with_blocks": n_block_ents,
                          "pointers": n_ptr, "empty": filled - n_block_ents - n_ptr,
                          "blocks": total, "reused_raw": reused, "injected_raw": injected,
                          "gaps": gaps, "file": dst},
                         ensure_ascii=False, indent=2))
        return 0
    print("WI 条目 %d：有块 %d / 指针 %d / 无进展 %d"
          % (filled, n_block_ents, n_ptr, filled - n_block_ents - n_ptr))
    print("块：%d/%d 归位（每块一次）✓　原文：复用正文 %d 块 / 新注入 %d 块"
          % (total, len(bmap), reused, injected))
    print("待填：① 基线原状 %d 条 ｜ ② 【解读】%d 块 ｜ 【映射】%d 块 ｜ "
          "③ 演进分析 %d 条 ｜ ④ 遗留 %d 条"
          % (gaps["base"], gaps["jie"], gaps["map"], gaps["evol"], gaps["left"]))
    if sum(gaps.values()) == 0:
        print("结构已满，无待填项 —— 下一步 check")
    else:
        print("下一步：按上面的清单逐项填（一次只读该块切片），填完再跑一次 compose 不会覆盖你写的内容")
    print("→ %s" % dst)
    return 0



def build_parser():
    p = argparse.ArgumentParser(prog="skillctl", description="技能调度与流程编排")
    p.add_argument("--root", help="项目根（默认自动向上查找 .workbuddy 或 docs）")
    p.add_argument("--skills-root", default=DEFAULT_SKILLS_ROOT, help="技能库根目录")
    p.add_argument("--json", action="store_true", help="机器可读输出")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("list", help="列出已安装技能")
    sp = sub.add_parser("dispatch", help="任务 -> 技能路由")
    sp.add_argument("query")
    sp.add_argument("--top", type=int, default=3)

    sub.add_parser("plan", help="打印阶段计划")
    sp = sub.add_parser("run", help="进入阶段并打印工作单")
    sp.add_argument("stage")
    sp = sub.add_parser("gate", help="只看过闸清单")
    sp.add_argument("stage")
    sp = sub.add_parser("done", help="标记阶段完成")
    sp.add_argument("stage")
    sp.add_argument("--note", default="")
    sub.add_parser("status", help="查看进度")

    sp = sub.add_parser("sources", help="清点一场会议的素材夹（主席报告 / FL Summary / TDoc）")
    sp.add_argument("dir")
    sp.add_argument("--agenda", default="", help="议程项，如 9.4.1；用来定位 by_agenda 下的 TDoc")

    sp = sub.add_parser("extract", help="把 docx 抽成纯文本段落（S1 导出逐字摘录用）")
    sp.add_argument("file")
    sp.add_argument("--out", default="", help="落盘路径（如 _eom_941_verbatim.txt）")
    sp.add_argument("--head", type=int, default=0, help="只打印前 N 段")

    sp = sub.add_parser("blocks", help="A3 切块：Agreement/WA 切块 + 按内嵌 FL 分隔行定轮次")
    sp.add_argument("verbatim", help="主席报告目标议程项的逐字文本")
    sp.add_argument("--out-dir", default="", help="产物目录（默认 _work_<agenda>）")
    sp.add_argument("--agenda", default="", help="议程项，如 9.4.1（只用于默认目录名）")

    sp = sub.add_parser("issues", help="A4 抽议题骨架：Topic#/Issue# 树 + 立场段/Proposal")
    sp.add_argument("files", nargs="+", help="各轮 FL 的纯文本（顺序：早 → 晚）")
    sp.add_argument("--out-dir", default="")
    sp.add_argument("--agenda", default="")

    sp = sub.add_parser("flow", help="A6 串讨论链：块→Issue 候选 + 起点 TDoc + 收口状态")
    sp.add_argument("--blocks", required=True)
    sp.add_argument("--issues", required=True)
    sp.add_argument("--out-dir", default="")
    sp.add_argument("--agenda", default="")
    sp.add_argument("--min-score", type=float, default=0.06, help="n-gram 重叠阈值")

    sp = sub.add_parser("tdoc", help="按需抽取单篇 TDoc（须在 flow.json 记 tdoc_reason）")
    sp.add_argument("file")
    sp.add_argument("--out", default="", help="默认 _tdoc/<文件名>.txt")
    sp.add_argument("--head", type=int, default=0)

    sp = sub.add_parser("rel", help="B2 关系判定：把块按 Issue 挂到 WI 条目下（关系类型留给模型）")
    sp.add_argument("--flow", required=True)
    sp.add_argument("--wid", required=True)
    sp.add_argument("--out-dir", default="")
    sp.add_argument("--agenda", default="")
    sp.add_argument("--apply", default="",
                    help="把模型判定（kind/base_ref/blocks/新增条目）合并进 rel.json")

    sp = sub.add_parser("compose",
                        help="B3 组装正文：按 rel.json 的 WI 条目重排 §n.x，块原文从 blocks.json 注入")
    sp.add_argument("--rel", required=True)
    sp.add_argument("--blocks", required=True)
    sp.add_argument("--target", required=True, help="续篇文件（就地重排它里面的一节）")
    sp.add_argument("--section", required=True, help="要组装的节号，如 4.7")
    sp.add_argument("--out", default="", help="写到另处（默认就地覆盖 target）")

    sp = sub.add_parser("init", help="生成续篇骨架")
    sp.add_argument("--base", required=True, help="基准报告路径")
    sp.add_argument("--meeting", default="")
    sp.add_argument("--agenda", default="")
    sp.add_argument("--out", default="")
    sp.add_argument("--eom", default="",
                    help="主席报告目标议程项的逐字文本（_eom_*_verbatim.txt）；"
                         "登记后 check/seal 才做块数对账")
    sp.add_argument("--dry-run", action="store_true")

    sp = sub.add_parser("check", help="交付物校验")
    sp.add_argument("file")
    sp.add_argument("--eom", default="",
                    help="主席报告逐字文本；给了就做「块数对账 + 原文本溯源」。"
                         "不传则回落到 init --eom 登记的路径")
    sp.add_argument("--workdir", default="",
                    help="_work_<agenda> 目录；给了就核对 WI 分节结构（rel.json / 块数守恒 / 四段齐全）")

    sp = sub.add_parser("seal", help="校验并封存")
    sp.add_argument("file")
    sp.add_argument("--eom", default="")
    sp.add_argument("--workdir", default="")

    sp = sub.add_parser("calc", help="定量折算")
    sp.add_argument("what", nargs="?", default="all",
                    choices=["all", "tac", "wf1", "wf2", "opt3", "pos"])
    sp.add_argument("--neg", type=float, default=2903.6)
    sp.add_argument("--pos", type=float, default=2 * 2903.6)
    sp.add_argument("--mu", type=int, nargs="*", default=[0, 1, 2, 3])
    sp.add_argument("--range-khz", type=float, default=127.08)
    sp.add_argument("--fc", type=float, default=30.0)
    sp.add_argument("--fc-list", type=float, nargs="*", default=[30.0, 2.0])
    sp.add_argument("--k", type=int, default=8)
    sp.add_argument("--ppm", type=float, default=0.01)

    # 顶层那三个「通用参数」只有写在子命令**之前**才被解析：argparse 的子解析器
    # 会独占其后的全部参数，所以 `skillctl check f --json`、
    # `skillctl calc all --json` 一律报 unrecognized arguments 并 exit 2。
    # 文档把它们写成通用参数，就得让它们在任何位置都能用 —— 给每个子解析器补一份。
    # default=SUPPRESS 是关键：子命令没写时不覆盖顶层已解析到的值。
    for sub_parser in sub.choices.values():
        sub_parser.add_argument("--root", default=argparse.SUPPRESS,
                                help=argparse.SUPPRESS)
        sub_parser.add_argument("--skills-root", default=argparse.SUPPRESS,
                                help=argparse.SUPPRESS)
        sub_parser.add_argument("--json", action="store_true",
                                default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg = load_cfg()
    root = find_root(args.root)

    if args.cmd == "list":
        skills = scan_skills(args.skills_root)
        cur = [s for s in skills if s["dir"] == SKILL_DIR]
        if args.json:
            print(json.dumps(skills, ensure_ascii=False, indent=2))
            return 0
        print("技能库：%s（%d 个）" % (args.skills_root, len(skills)))
        for s in skills:
            tag = " [可编排]" if s["has_config"] else ""
            warn = " [模板未填]" if s["todo_template"] else ""
            print(("  %-34s%s%s" % (s["name"], tag, warn)).rstrip())
            if s["description"] and not s["todo_template"]:
                print("      %s" % s["description"][:110])
        print("\n当前技能：%s%s" % (cur[0]["name"] if cur else "-", "（已安装于 " + SKILL_DIR + "）"))
        return 0

    if args.cmd == "dispatch":
        skills = scan_skills(args.skills_root)
        top = dispatch(args.query, skills, args.top)
        if args.json:
            print(json.dumps(top, ensure_ascii=False, indent=2))
            return 0
        if not top:
            print("没有匹配到技能。可试： skillctl list")
            return 2
        print("任务：「%s」" % args.query)
        for i, r in enumerate(top, 1):
            print("\n%d. %s  (score %.3f)" % (i, r["name"], r["score"]))
            print("   %s" % r["description"])
            if r["hits"]:
                print("   命中：%s" % "、".join(r["hits"]))
        best = top[0]
        if best["name"] == cfg["skill"]:
            print("\n→ 建议：加载 %s 并执行 skillctl run S0" % cfg["skill"])
        else:
            print("\n→ 建议：加载 %s（本工具只编排 %s）" % (best["name"], cfg["skill"]))
        return 0

    if args.cmd == "plan":
        return cmd_plan(cfg, args.json)

    if args.cmd == "run":
        return cmd_run(cfg, root, args.stage, args.json)

    if args.cmd == "gate":
        return cmd_gate(cfg, args.stage)

    if args.cmd == "done":
        return cmd_done(cfg, root, args.stage, args.note)

    if args.cmd == "status":
        return cmd_status(cfg, root, args.json)

    if args.cmd == "sources":
        return cmd_sources(cfg, args.dir, getattr(args, "agenda", ""), args.json)

    if args.cmd == "extract":
        return cmd_extract(args.file, getattr(args, "out", "") or None,
                           getattr(args, "head", 0), args.json)

    if args.cmd == "blocks":
        return cmd_blocks(args.verbatim, getattr(args, "out_dir", ""),
                          getattr(args, "agenda", ""), args.json)

    if args.cmd == "issues":
        return cmd_issues(args.files, getattr(args, "out_dir", ""),
                          getattr(args, "agenda", ""), args.json)

    if args.cmd == "flow":
        return cmd_flow(args.blocks, args.issues, getattr(args, "out_dir", ""),
                        getattr(args, "agenda", ""), args.json,
                        getattr(args, "min_score", 0.06))

    if args.cmd == "tdoc":
        return cmd_tdoc(args.file, getattr(args, "out", ""),
                        getattr(args, "head", 0), args.json)

    if args.cmd == "rel":
        return cmd_rel(args.flow, args.wid, getattr(args, "out_dir", ""),
                       getattr(args, "agenda", ""), args.json,
                       getattr(args, "apply", ""))

    if args.cmd == "compose":
        return cmd_compose(args.rel, args.blocks, getattr(args, "target", ""),
                           getattr(args, "out", ""), getattr(args, "section", ""),
                           args.json)

    if args.cmd == "init":
        return cmd_init(cfg, root, args.base, args.meeting, args.agenda, args.out,
                        args.dry_run, getattr(args, "eom", None))

    if args.cmd == "check":
        st = load_state(root, cfg)
        # 逐字文本是 S1 的产物，而 init 在 S0 —— 所以 `init --eom` 这一步天然赶不上。
        # 让 check 顺手把它记进状态：第一次带 --eom，之后 seal 就不用再打一遍。
        explicit_eom = getattr(args, "eom", None)
        if explicit_eom and os.path.isfile(explicit_eom):
            p = os.path.abspath(explicit_eom)
            if st.get("eom") != p:
                st["eom"] = p
                st["log"].append({"ts": now(), "stage": "check", "action": "register_eom",
                                  "eom": p})
                save_state(root, cfg, st)
        wd = getattr(args, "workdir", "") or _find_workdir(args.file)
        res = doclint.check(args.file, cfg["required_sections"], cfg["forbidden_patterns"],
                            base_report=st.get("base_report"),
                            base_mtime=st.get("base_mtime"),
                            base_md5=st.get("base_md5"),
                            eom=explicit_eom or st.get("eom"),
                            workdir=wd)
        res["stats"]["workdir"] = wd or None
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print(doclint.render(res))
        return 0 if res["ok"] else 1

    if args.cmd == "seal":
        return cmd_seal(cfg, root, args.file, getattr(args, "eom", None),
                        getattr(args, "workdir", "") or _find_workdir(args.file))

    if args.cmd == "calc":
        return cmd_calc(args.what, args)

    build_parser().print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
