// 用最小 DOM stub 跑一遍注入脚本，捕获运行时错误
const fs = require("fs");

const el = () => ({
  nodeType: 1, tagName: "DIV", className: "",
  attributes: {},
  childNodes: [],
  getAttribute() { return null; },
  hasAttribute() { return false; },
  setAttribute() {},
  matches() { return false; },
  parentElement: null,
  querySelectorAll() { return []; },
  closest() { return null; },
  get clientHeight() { return 0; },
});

const body = el();
body.parentElement = null;

global.window = {
  __fbZhInstalled: false,
  addEventListener() {},
  setTimeout: (fn) => fn(),
  clearTimeout() {},
};
global.document = {
  readyState: "complete",
  addEventListener() {},
  body,
  documentElement: body,
  querySelectorAll() { return []; },
};
global.MutationObserver = class { observe() {} disconnect() {} };
global.Node = { TEXT_NODE: 3 };

const path = process.argv[2];
const src = fs.readFileSync(path, "utf8");
try {
  eval(src);
  console.log("脚本执行成功；window.__fbZhInstalled =", global.window.__fbZhInstalled);
} catch (e) {
  console.log("脚本执行失败：", e && e.stack ? e.stack.split("\n").slice(0, 6).join("\n") : e);
}
