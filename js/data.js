// 載入 ticker / benchmark JSON。前端純讀取本地檔案 (相對路徑)。
// 加上 cache-buster (用 index.json 的 generated 欄)，避免後端重建後前端讀到舊資料。

const Data = (() => {
  const cache = new Map();
  let version = "0";

  function cb(path) {
    return `${path}?v=${encodeURIComponent(version)}`;
  }

  async function loadJSON(path, useVersion = true) {
    const key = useVersion ? cb(path) : path;
    if (cache.has(key)) return cache.get(key);
    const res = await fetch(key, { cache: "no-cache" });
    if (!res.ok) throw new Error(`載入失敗：${path} (${res.status})`);
    const obj = await res.json();
    cache.set(key, obj);
    return obj;
  }

  async function loadIndex() {
    // index.json 不能加版本 (沒有 version 之前)，用 timestamp 強制 fresh
    const res = await fetch(`data/index.json?t=${Date.now()}`, { cache: "no-cache" });
    if (!res.ok) throw new Error(`載入失敗：data/index.json (${res.status})`);
    const obj = await res.json();
    version = obj.generated || String(Date.now());
    return obj;
  }

  async function loadTicker(code) {
    return loadJSON(`data/tickers/${code}.json`);
  }

  async function loadBenchmark(code) {
    return loadJSON(`data/benchmarks/${code}.json`);
  }

  return { loadIndex, loadTicker, loadBenchmark };
})();
