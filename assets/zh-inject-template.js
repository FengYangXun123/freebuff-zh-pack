/*
 * Freebuff 汉化注入器（0.0.201+ 架构：主界面来自 https://freebuff.com 远端页面）
 *
 * 由 scripts/patch-inject.py 注入到远端页面的主世界执行。作用是把页面里可见的
 * 英文 UI 文案换成中文：词典由构建期内联进本文件的 __DICT__ 占位符。
 *
 * 设计约束（都是踩过的坑）：
 *  1. 只译 UI，不译内容。聊天记录、AI 回复、代码块、终端输出里的英文必须原样保留，
 *     所以文本节点按「祖先元素角色」白名单 + 容器黑名单双重过滤。
 *  2. React 会重绘并把英文写回去，所以要用 MutationObserver 持续重刷；
 *     但重刷本身会触发 observer，必须用标志位防止自激循环。
 *  3. 页面是 SPA，路由切换不重载文档，靠 observer 即可覆盖。
 *  4. 属性类文案（placeholder / title / aria-label）单独处理，DOM 文本替换覆盖不到。
 */
(() => {
  const DICT = /*__DICT__*/ {};
  if (!DICT || typeof DICT !== "object" || Object.keys(DICT).length === 0) return;
  // 把词典挂到全局：第二层注入（社区库）改用同一份词典，
  // 避免两层各用一套措辞、在 React 重绘时互相覆盖。
  globalThis.__FB_ZH_DICT__ = DICT;
  globalThis.__FB_ZH_COMMUNITY_DICT__ = globalThis.__FB_ZH_COMMUNITY_DICT__ || {};
  // 重复注入保护：hook 会在 did-finish-load / did-frame-finish-load / did-navigate-in-page
  // 多次触发，同一页面可能注入好几次。不加保护会叠加多个 MutationObserver，白白消耗 CPU。
  if (window.__fbZhInstalled) return;

  const ATTRS = [
    "placeholder",
    "title",
    "aria-label",
    "aria-description",
    "aria-valuetext",
    "alt",
    "data-placeholder",
  ];

  // 这些容器里的文字是用户/模型产出，不翻译。
  // class 名来自远端 chunk 实测（0.0.201 的 freebuff.com 前端），不是猜的：
  //   workspace-transcript*  = 会话正文区
  //   *-bubble / *-prose / *-transcript / msg = 消息气泡与富文本
  //   not-prose / md-*         = 代码块与 Markdown 原文
  //   user-message-*           = 用户自己发的消息
  //   cli-demo-transcript      = CLI 演示录屏文本
  //
  // 分两套：
  //   SKIP_SEL   —— 内容容器（含标签级规则），用于「文本节点」判定
  //   SKIP_CLASS —— 仅 class 级规则，用于「属性」判定
  // 原因：表单控件（input/textarea）自身的 placeholder / aria-label 是 UI，要译；
  // 但它们内部的文本（value 回显）不能动。标签级规则不适用于属性判定。
  const SKIP_CLASS = [
    "[class*='bubble']",
    "[class*='prose']",
    "[class*='transcript']",
    "[class*='message']",
    "[class*='Message']",
    "[class*='markdown']",
    "[class*='Markdown']",
    "[class*='not-prose']",
    "[class*='md-']",
    "[class*='code-block']",
    "[class*='CodeBlock']",
    "[class*='artifacts']",
    "[class*='user-message']",
    "[class*='file-markdown']",
    "[class*='cli-demo']",
    "[class*='workspace-response']",
  ].join(",");

  // md-* 里既有代码正文（该跳过），也有代码块工具条上的按钮文案（要译）。
  // 例：`md-code-head` 里的 "Copy" 按钮是 UI，`md-pre`/`md-code` 里的代码是内容。
  const SKIP_SEL = [
    "pre",
    "code",
    "kbd",
    "samp",
    "var",
    "textarea",
    "[contenteditable='true']",
    "[class*='bubble']",
    "[class*='prose']",
    "[class*='transcript']",
    "[class*='message']",
    "[class*='Message']",
    "[class*='markdown']",
    "[class*='Markdown']",
    "[class*='not-prose']",
    "[class*='code-block']",
    "[class*='CodeBlock']",
    "[class*='artifacts']",
    "[class*='user-message']",
    "[class*='file-markdown']",
    "[class*='cli-demo']",
    "[class*='workspace-response']",
  ].join(",");

  const UI_TAGS = new Set([
    "BUTTON",
    "A",
    "LABEL",
    "H1",
    "H2",
    "H3",
    "H4",
    "H5",
    "H6",
    "TITLE",
    "LEGEND",
    "OPTION",
    "SUMMARY",
    "CAPTION",
    "TH",
    "TD",
  ]);
  const UI_ROLES = new Set([
    "button",
    "link",
    "tab",
    "menuitem",
    "menuitemcheckbox",
    "menuitemradio",
    "option",
    "heading",
    "treeitem",
    "switch",
    "checkbox",
    "radio",
    "tooltip",
    "dialog",
    "alert",
    "status",
    "group",
  ]);

  const MAX_KEY = Object.keys(DICT).reduce((m, k) => Math.max(m, k.length), 0);

  // 词级替换候选：词典里「纯英文单词/词组、不含数字与标点、长度 ≥2」的键。
  // 这类键可以安全地在任意文本里按整词替换（数字、单位符号原样保留）。
  //
  // ⚠️ 风险控制：词典里有 Open / Post / Close 这类常用词，若放进通用词级替换表，
  // 会把用户消息里的英文单词也换掉（"I'll close it" → "我会关闭它"）。
  // 因此词级表**只收单位与统计类词**（day/days/hour/hours/used/tokens/messages…），
  // 这些词只在统计数字旁出现，替换安全。UI 完整短语仍走 exact 表。
  // ⚠️ 词级白名单刻意不含那些「社区正则要整体匹配」的词：
  //   streak / streaks / active —— 社区规则 "3-day streak!" 整体匹配
  //   left / used / hours / remaining —— 社区规则 "5:00 left of today's 5:00."、
  //     "0:00 of 5:00 hours used, 5:00 left" 整体匹配。
  // 若这里先做词级替换把这些词换掉，社区正则就再也匹配不上，
  // 会留下「5:00 剩余 of 5:00」这种半中半英的残句（2026-11-20 实测）。
  // 处置：这些词交给社区正则处理；正则没命中时，靠 exact 词典的整段条目兜底。
  const WORD_ALLOW = /^(?:day|days|minute|minutes|second|seconds|week|weeks|month|months|year|years|total|messages?|requests?|tokens?|credits?|balance|balances|sessions?)$/i;
  const WORD_KEYS = Object.keys(DICT).filter(
    (k) => /^[A-Za-z][A-Za-z\s'-]{1,30}$/.test(k) && WORD_ALLOW.test(k),
  );

  // 「数字 + 英文单位」形态：必须以数字开头，整串只由数字、英文单词、空格、
  // 百分号、小数点、斜杠构成。用于 "0 days" / "4% used" / "1.2k tokens" 这类统计值。
  const NUM_UNIT_RE = /^\d[\d.,\s]*%?\s*[A-Za-z][A-Za-z\s'-]{0,20}$/;

  const isUiElement = (el) => {
    if (!el || el.nodeType !== 1) return false;
    if (UI_TAGS.has(el.tagName)) return true;
    const role = el.getAttribute && el.getAttribute("role");
    if (role && UI_ROLES.has(role.toLowerCase())) return true;
    return false;
  };

  // 「短文本 + 数值/单位形态」的容器：像 "0 days"、"4% used" 这类统计数字。
  // 只认明显是统计展示的容器 class，避免把普通段落逐词替换。
  const STAT_CLASS = /(?:^|[\s_-])(?:stat|metric|counter|count|usage|streak|activity|summary|figure|number|amount|value|total)(?:[\s_-]|$)/i;
  const isStatElement = (el) => {
    let cur = el;
    while (cur && cur.nodeType === 1 && cur.tagName !== "BODY") {
      const cls = typeof cur.className === "string" ? cur.className : "";
      if (STAT_CLASS.test(cls)) return true;
      cur = cur.parentElement;
    }
    return false;
  };

  // 内容容器判定：聊天正文 / 代码块 / 用户输入一律不动。
  // 只作用于「文本节点」——属性类文案另走 attrSkipped。
  const inSkipped = (node) => {
    let el = node.nodeType === 1 ? node : node.parentElement;
    while (el) {
      if (el.nodeType === 1) {
        if (el.matches && el.matches(SKIP_SEL)) return true;
        // 表单控件回显的 value 是用户数据，不能动
        const tag = el.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA") return true;
      }
      el = el.parentElement;
    }
    return false;
  };

  // 属性判定：比内容判定宽松——表单控件自身的 placeholder / aria-label 是 UI，要译；
  // 只有当属性挂聊天正文/代码块容器里才跳过。
  const attrSkipped = (el) => {
    let cur = el;
    while (cur && cur.nodeType === 1) {
      if (cur.matches && cur.matches(SKIP_CLASS)) return true;
      cur = cur.parentElement;
    }
    return false;
  };

  // 整段精确匹配：任何未跳过容器里的文本节点都可以替换
  const translateExact = (text) => {
    const trimmed = text.trim();
    if (!trimmed) return null;
    if (Object.prototype.hasOwnProperty.call(DICT, trimmed)) return DICT[trimmed];
    return null;
  };

  // 本地补的动态文案正则（社区库覆盖的是另一个上游版本的形态）。
  // ⚠️ 这些规则必须**在词级替换之前**跑：词级替换会先改掉 used/left/hours，
  // 规则就再也匹配不上（2026-11-20 实测）。
  const LOCAL_PATTERNS = [
    // 用量页额度条："5:00 left of 5:00"（社区规则覆盖的是 "left of today's" 形态）
    [/^([\d,]+(?::[0-5]\d)?)\s+left of\s+([\d,]+(?::[0-5]\d)?)$/,
      (_m, left, limit) => `${left} / ${limit}`],
    // 进度栏 aria-valuetext："0:00 of 5:00 hours used, 5:00 left"
    [/^([\d,:]+)\s+of\s+([\d,:]+)\s+hours used,\s+([\d,:]+)\s+left$/,
      (_m, used, limit, left) => `已用 ${used} / ${limit} 小时，剩余 ${left}`],
    // 侧栏余额："5:00 left of today's 5:00."
    [/^([\d,]+(?::[0-5]\d)?)\s+left of today's\s+([\d,]+(?::[0-5]\d)?)\.$/,
      (_m, left, limit) => `今日额度剩余 ${left} / ${limit}（时:分）。`],
    // 「About X」前缀（信息图标的 aria-label）：上游渲染成模板串 `About ${i}`，
    // 运行时才拼出 "About Hours" → 词典整串匹配不到，只能前缀匹配。
    // 社区库也有同样盲区（它只有 "About Hours" 这类整串条目）。
    // 主体本身也可能是运行时下发的值（"Lifetime tokens"、"Saving"），
    // 整串查不到 → 退化为按已知词片段替换（token → Token、saved → 已保存…）。
    [/^About\s*(.+)$/,
      (_m, subject) => {
        const s = subject.trim();
        if (!s) return null;
        const direct = DICT[s];
        if (direct) return `关于${direct}`;
        const partial = translateAboutSubject(s);
        return partial ? `关于${partial}` : null;
      }],
  ];

  const translateLocalPattern = (text) => {
    const trimmed = text.trim();
    if (!trimmed) return null;
    for (const rule of LOCAL_PATTERNS) {
      let m;
      try {
        m = rule[0].exec(trimmed);
      } catch (e) {
        continue;
      }
      if (!m) continue;
      try {
        const out = rule[1].apply(null, [m[0]].concat(Array.prototype.slice.call(m, 1)));
        if (typeof out === "string" && out) return out;
      } catch (e) { /* 单条规则出错不影响其它 */ }
    }
    return null;
  };

  // 「About X」里 X 是运行时下发值时的兜底：按已知词片段替换。
  // 只收高置信度的术语（Token / 累计 / 已保存），避免把普通词误译。
  const ABOUT_SUBJECT_PARTS = [
    [/\blifetime\b/gi, "累计"],
    [/\btokens?\b/gi, "Token"],
    [/\bcached\b/gi, "缓存"],
    [/\bsaving\b/gi, "已保存"],
    [/\bsaved\b/gi, "已保存"],
    [/\bhours?\b/gi, "小时额度"],
    [/\bbalance\b/gi, "余额"],
    [/\busage\b/gi, "用量"],
    [/\bactivity\b/gi, "活动"],
  ];

  const translateAboutSubject = (subject) => {
    let out = subject;
    let hit = false;
    for (const [re, zh] of ABOUT_SUBJECT_PARTS) {
      if (re.test(out)) {
        out = out.replace(re, zh);
        hit = true;
      }
      re.lastIndex = 0;
    }
    return hit ? out : null;
  };

  // 局部替换（长句里嵌着已知短语）：只在确定的 UI 元素里做，
  // 否则可能把用户消息/模型回复里的英文片段改掉。
  const translatePartial = (text, parent) => {
    const trimmed = text.trim();
    if (trimmed.length < 12 || trimmed.length > 400) return null;
    if (!isUiElement(parent)) return null;
    for (const k of Object.keys(DICT)) {
      if (k.length < 12) continue;
      if (trimmed.includes(k)) return trimmed.split(k).join(DICT[k]);
    }
    return null;
  };

  // 词级替换：处理「数字 + 英文单位」这类运行时拼装的文案。
  // 例："0 days" → "0 天"、"4% used" → "4% 已用"。
  // 规则：表里的键必须是纯英文单词/词组（不含数字），只替换整词出现处，
  // 数字与标点原样保留。键必须来自词典且长度 ≥2，避免误伤。
  const translateWords = (text) => {
    let hit = false;
    let out = text;
    for (const k of WORD_KEYS) {
      if (!out.includes(k)) continue;
      // 整词边界：前后不是字母即算独立词
      const re = new RegExp("(?<![A-Za-z])" + k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "(?![A-Za-z])", "g");
      if (re.test(out)) {
        re.lastIndex = 0;
        out = out.replace(re, DICT[k]);
        hit = true;
      }
    }
    return hit ? out : null;
  };

  let applying = false;

  const applyAttrs = (root) => {
    // 遍历范围是整个子树：placeholder / aria-label 这类属性挂在任意节点上，
    // 只查 [attr] 选择器会在属性后设时漏掉（React 常常复用已有节点）。
    const scope = root.querySelectorAll ? root.querySelectorAll("*") : [];
    for (const el of scope) {
      if (el.nodeType !== 1) continue;
      // 快速筛：只有当元素身上挂着待译属性时才做容器判定
      let has = false;
      for (const attr of ATTRS) {
        if (el.hasAttribute && el.hasAttribute(attr)) {
          has = true;
          break;
        }
      }
      if (!has) continue;
      if (attrSkipped(el)) continue;
      for (const attr of ATTRS) {
        const v = el.getAttribute && el.getAttribute(attr);
        if (!v) continue;
        let t = translateExact(v);
        if (t === null) t = translateLocalPattern(v);
        if (t && t !== v) el.setAttribute(attr, t);
      }
    }
  };

  const applyText = (node) => {
    if (!node || node.nodeType !== 3) return;
    const raw = node.nodeValue;
    if (!raw || !raw.trim()) return;
    if (inSkipped(node)) return;
    const parent = node.parentElement;
    let t = translateExact(raw);
    if (t === null) t = translateLocalPattern(raw);
    if (t === null) t = translatePartial(raw, parent);
    // 词级替换只对「短文本 + 确定的 UI 元素」生效。
    // 短文本门槛保证不会把整段英文散文逐词替换；UI 元素门槛保证不碰聊天正文。
    if (t === null && raw.trim().length <= 40 && (isUiElement(parent) || isStatElement(parent))) {
      t = translateWords(raw.trim());
    }
    // 「数字 + 英文单位」形态（如 "0 days"、"4% used"）：这类元素既不是标准 UI 标签，
    // class 也未必带 stat，只能靠形态判定——必须以数字开头、且只含数字与少量英文词。
    if (t === null && raw.trim().length <= 24 && NUM_UNIT_RE.test(raw.trim())) {
      t = translateWords(raw.trim());
    }
    if (t === null) return;
    const lead = raw.slice(0, raw.length - raw.trimStart().length);
    const trail = raw.slice(raw.trimEnd().length);
    const next = lead + t + trail;
    if (next !== raw) node.nodeValue = next;
  };

  const walk = (root) => {
    applyAttrs(root);
    if (!root || !root.childNodes) return;
    const nodes = root.childNodes;
    for (let i = 0; i < nodes.length; i++) {
      const n = nodes[i];
      if (n.nodeType === 3) applyText(n);
      else if (n.nodeType === 1) {
        applyAttrs(n);
        walk(n);
      }
    }
  };

  const applyAll = () => {
    if (applying) return;
    applying = true;
    try {
      walk(document.body || document.documentElement);
    } finally {
      applying = false;
    }
  };

  let timer = null;
  const schedule = () => {
    if (timer) return;
    timer = setTimeout(() => {
      timer = null;
      applyAll();
    }, 120);
  };

  const obs = new MutationObserver((records) => {
    if (applying) return;
    for (const r of records) {
      // attributes 必须一起监听：React 把 placeholder / aria-label 挂到已有节点上时
      // 不产生 childList 事件，只监听子节点会漏掉整批表单控件文案。
      if (r.type === "characterData" || r.type === "childList" || r.type === "attributes") {
        schedule();
        break;
      }
    }
  });

  const start = () => {
    applyAll();
    const root = document.body || document.documentElement;
    if (root)
      obs.observe(root, {
        childList: true,
        subtree: true,
        characterData: true,
        attributes: true,
        attributeFilter: ATTRS,
      });
    window.__fbZhInstalled = true;
    window.__fbZhApply = applyAll;
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
