// 主程式：UI 互動、狀態管理。

(async function () {
  const COLORS = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0891b2"];
  const BENCH_COLORS = { "0050": "#64748b", "IR0001": "#94a3b8" };

  const state = {
    index: null,           // 全部可用 ticker 清單
    selected: [],          // 主標的代碼陣列 (≤6)
    benchmarks: { "0050": false, "IR0001": false },
    range: "1Y",
    customStart: null,
    customEnd: null,
    loadedRows: new Map(), // code -> ticker JSON
  };

  Chart.init();

  // 1. 載入 index
  try {
    state.index = await Data.loadIndex();
    document.getElementById("updated").textContent = state.index.generated || "—";
    // 預填自訂區間：當年 1/1 → 最新資料日
    const latest = state.index.generated || new Date().toISOString().slice(0, 10);
    const yearStart = latest.slice(0, 4) + "-01-01";
    document.getElementById("custom-start").value = yearStart;
    document.getElementById("custom-end").value = latest;
  } catch (e) {
    alert("無法載入 data/index.json，請先執行 python scripts/update_all.py。\n錯誤：" + e.message);
    return;
  }

  // 2. 搜尋輸入處理
  const input = document.getElementById("ticker-input");
  const sugg = document.getElementById("ticker-suggest");
  let suggestActive = -1;

  function renderSuggest(query) {
    const q = query.trim().toLowerCase();
    if (!q) { sugg.classList.add("hidden"); return; }
    const matches = state.index.tickers
      .filter(t => !state.selected.includes(t.code))
      .filter(t => t.code.toLowerCase().includes(q) || (t.name || "").toLowerCase().includes(q))
      .slice(0, 30);
    if (!matches.length) {
      sugg.innerHTML = `<div class="suggest-item" data-action="fetch"><span class="code">${escape(query)}</span><span class="name">— 從 universe 中找不到，是否要嘗試自動下載？</span></div>`;
      sugg.classList.remove("hidden");
      return;
    }
    sugg.innerHTML = matches.map((t, i) => `
      <div class="suggest-item" data-code="${t.code}">
        <span class="code">${t.code}</span>
        <span class="name">${escape(t.name)}</span>
        <span class="market">${t.market}</span>
      </div>`).join("");
    suggestActive = -1;
    sugg.classList.remove("hidden");
  }

  input.addEventListener("input", e => renderSuggest(e.target.value));
  input.addEventListener("focus", e => renderSuggest(e.target.value));
  input.addEventListener("blur", () => setTimeout(() => sugg.classList.add("hidden"), 200));
  input.addEventListener("keydown", e => {
    const items = sugg.querySelectorAll(".suggest-item");
    if (e.key === "ArrowDown") {
      suggestActive = Math.min(items.length - 1, suggestActive + 1);
      updateActive(items);
      e.preventDefault();
    } else if (e.key === "ArrowUp") {
      suggestActive = Math.max(0, suggestActive - 1);
      updateActive(items);
      e.preventDefault();
    } else if (e.key === "Enter") {
      if (suggestActive >= 0 && items[suggestActive]) items[suggestActive].click();
      e.preventDefault();
    } else if (e.key === "Escape") {
      sugg.classList.add("hidden");
    }
  });
  function updateActive(items) {
    items.forEach((el, i) => el.classList.toggle("active", i === suggestActive));
  }
  sugg.addEventListener("click", e => {
    const item = e.target.closest(".suggest-item");
    if (!item) return;
    if (item.dataset.action === "fetch") {
      alert("自動下載未在 universe 中的代碼，目前需要從後端執行：\n\npython scripts/update_all.py --only " + input.value.trim() + "\n\n之後重新整理本頁。");
      return;
    }
    addTicker(item.dataset.code);
    input.value = "";
    sugg.classList.add("hidden");
    input.focus();
  });

  function addTicker(code) {
    if (state.selected.length >= 6) {
      alert("最多選 6 檔");
      return;
    }
    if (state.selected.includes(code)) return;
    state.selected.push(code);
    renderChips();
    update();
  }

  function removeTicker(code) {
    state.selected = state.selected.filter(c => c !== code);
    renderChips();
    update();
  }

  function renderChips() {
    const chips = document.getElementById("selected-tickers");
    chips.innerHTML = state.selected.map(code => {
      const t = state.index.tickers.find(x => x.code === code);
      return `<span class="chip" data-code="${code}">${code} ${escape(t ? t.name : "")}<span class="close" data-code="${code}">×</span></span>`;
    }).join("");
    chips.querySelectorAll(".close").forEach(el => {
      el.addEventListener("click", () => removeTicker(el.dataset.code));
    });
  }

  // 3. Benchmark checkboxes
  document.getElementById("bench-0050").addEventListener("change", e => {
    state.benchmarks["0050"] = e.target.checked;
    update();
  });
  document.getElementById("bench-IR0001").addEventListener("change", e => {
    state.benchmarks["IR0001"] = e.target.checked;
    update();
  });

  // 4. Range buttons
  document.querySelectorAll(".range-buttons button").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".range-buttons button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.range = btn.dataset.range;
      state.customStart = state.customEnd = null;
      update();
    });
  });
  document.getElementById("custom-apply").addEventListener("click", () => {
    const s = document.getElementById("custom-start").value;
    const e = document.getElementById("custom-end").value;
    if (!s || !e) { alert("請選擇起始與結束日"); return; }
    if (s > e) { alert("起始日不可晚於結束日"); return; }
    state.customStart = s;
    state.customEnd = e;
    state.range = "CUSTOM";
    document.querySelectorAll(".range-buttons button").forEach(b => b.classList.remove("active"));
    update();
  });

  // 5. 主更新流程
  async function update() {
    const codes = [...state.selected];
    const benchCodes = [];
    for (const k of ["0050", "IR0001"]) {
      if (state.benchmarks[k] && !codes.includes(k)) benchCodes.push(k);
    }

    if (!codes.length) {
      Chart.clear();
      document.querySelector("#summary-table tbody").innerHTML = "";
      return;
    }

    // 載入所有需要的 ticker
    const datasets = [];
    for (const code of codes) {
      try {
        const t = state.loadedRows.get(code) || await Data.loadTicker(code);
        state.loadedRows.set(code, t);
        datasets.push({ ...t, isBench: false });
      } catch (e) {
        alert(`無法載入 ${code}：${e.message}\n\n請先執行 python scripts/update_all.py --only ${code}`);
        removeTicker(code);
        return;
      }
    }
    for (const code of benchCodes) {
      try {
        const t = state.loadedRows.get("BENCH:" + code) || await Data.loadBenchmark(code);
        state.loadedRows.set("BENCH:" + code, t);
        datasets.push({ ...t, isBench: true });
      } catch (e) {
        console.warn("benchmark load fail", code, e);
      }
    }

    // 決定全局區間（用於圖表軸）：不取交集，讓每檔股票獨立
    let globalStart, globalEnd;
    if (state.range === "CUSTOM") {
      globalStart = state.customStart;
      globalEnd = state.customEnd;
    } else {
      // 計算理想區間（不考慮資料集的交集）
      const endDate = new Date();
      globalEnd = endDate.toISOString().slice(0, 10);
      if (state.range === "MAX") {
        globalStart = "2020-01-01";
      } else if (state.range === "YTD") {
        globalStart = `${endDate.getFullYear()}-01-01`;
      } else {
        const map = { "1M": 1, "3M": 3, "6M": 6, "1Y": 12 };
        const months = map[state.range] || 12;
        const d = new Date(endDate);
        d.setMonth(d.getMonth() - months);
        globalStart = d.toISOString().slice(0, 10);
      }
    }

    if (!globalStart || !globalEnd) return;

    // 切片並產生 series：每檔股票獨立使用自己的數據範圍
    const seriesList = [];
    const summaryRows = [];
    let mainIdx = 0;
    for (const d of datasets) {
      // 決定該股票的實際數據範圍
      const stockStart = d.rows[0].d;
      const stockEnd = d.rows[d.rows.length - 1].d;

      // 用全局區間與該股票的數據範圍相交
      const effectiveStart = globalStart > stockStart ? globalStart : stockStart;
      const effectiveEnd = globalEnd < stockEnd ? globalEnd : stockEnd;

      const sliced = Calc.slice(d.rows, effectiveStart, effectiveEnd);
      if (sliced.length < 2) continue;
      const data = Calc.cumReturnSeries(sliced, true);
      const color = d.isBench ? (BENCH_COLORS[d.code] || "#94a3b8") : COLORS[mainIdx++ % COLORS.length];
      seriesList.push({
        name: `${d.code} ${d.name || ""}`.trim(),
        data, color, benchmark: d.isBench,
      });
      const summary = Calc.summarize(sliced);
      // 記錄該股票的實際起點、終點、以及全局邊界（用於標誌缺失日期）
      summaryRows.push({
        ...summary,
        code: d.code,
        name: d.name,
        market: d.market,
        isBench: d.isBench,
        actualStart: stockStart,
        actualEnd: stockEnd,
        globalStart: globalStart,
        globalEnd: globalEnd,
      });
    }

    Chart.render(seriesList);
    renderSummary(summaryRows);
  }

  function renderSummary(rows) {
    const tbody = document.querySelector("#summary-table tbody");
    tbody.innerHTML = rows.map(r => {
      const cls = v => v == null ? "" : (v >= 0 ? "pos" : "neg");
      const fmt = (v, p = 2) => v == null ? "—" : (v * 100).toFixed(p) + "%";
      const label = r.isBench ? `${r.code} (基準)` : r.code;

      // 檢查是否有缺失日期（起點或終點不符合全局區間）
      const isMissing = (r.start !== r.globalStart || r.end !== r.globalEnd);
      const rowClass = isMissing ? "missing-data" : "";

      return `<tr class="${rowClass}">
        <td>${label} ${escape(r.name || "")}</td>
        <td>${r.market || ""}</td>
        <td>${r.start}</td>
        <td>${r.end}</td>
        <td>${r.days}</td>
        <td class="${cls(r.totalReturn)}">${fmt(r.totalReturn)}</td>
        <td class="${cls(r.priceReturn)}">${fmt(r.priceReturn)}</td>
        <td class="${cls(r.cagr)}">${r.cagr == null ? "—" : fmt(r.cagr)}</td>
      </tr>`;
    }).join("");
  }

  function escape(s) {
    return String(s || "").replace(/[<>&"']/g, c => ({
      "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }

  // 預設展示一些範例 (若已 build)
  const defaults = ["2330", "0056", "00878"].filter(c =>
    state.index.tickers.some(t => t.code === c)
  );
  for (const c of defaults) addTicker(c);
})();
