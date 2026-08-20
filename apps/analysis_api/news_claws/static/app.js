(() => {
  const tokenKey = "news-claws-admin-token";
  const toast = document.querySelector("[data-toast]");

  const showToast = (message, isError = false) => {
    if (!toast) return;
    toast.textContent = message;
    toast.dataset.error = isError ? "true" : "false";
    toast.hidden = false;
    window.setTimeout(() => { toast.hidden = true; }, 4500);
  };

  const adminToken = () => window.localStorage.getItem(tokenKey) || "";
  const protectedFetch = async (url, options = {}) => {
    const token = adminToken();
    if (!token) throw new Error("请先设置管理令牌");
    const headers = new Headers(options.headers || {});
    headers.set("Authorization", `Bearer ${token}`);
    if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    const response = await fetch(url, { ...options, headers });
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}));
      throw new Error(problem.message || `请求失败 (${response.status})`);
    }
    return response;
  };

  const panel = document.querySelector("[data-token-panel]");
  const tokenInput = document.querySelector("#admin-token");
  document.querySelector("[data-token-toggle]")?.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) {
      tokenInput.value = adminToken();
      tokenInput.focus();
    }
  });
  document.querySelector("[data-token-save]")?.addEventListener("click", () => {
    window.localStorage.setItem(tokenKey, tokenInput.value.trim());
    panel.hidden = true;
    showToast("管理令牌已保存在当前浏览器");
    loadSubscriptions();
  });

  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-tab]").forEach((candidate) => {
        candidate.setAttribute("aria-selected", candidate === button ? "true" : "false");
      });
      document.querySelectorAll("[data-panel]").forEach((candidate) => {
        candidate.hidden = candidate.dataset.panel !== button.dataset.tab;
      });
    });
  });

  document.querySelectorAll("[data-pull-news]").forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const response = await protectedFetch("/api/v1/ingestion/pull", {
          method: "POST",
          body: JSON.stringify({ source_ids: [], max_items_per_source: 20 }),
        });
        const result = await response.json();
        showToast(`已处理 ${result.source_count} 个来源`);
        window.setTimeout(() => window.location.reload(), 700);
      } catch (error) {
        showToast(error.message, true);
      } finally {
        button.disabled = false;
      }
    });
  });

  document.querySelectorAll("[data-source-test]").forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const response = await protectedFetch(`/api/v1/sources/${button.dataset.sourceTest}/test`, { method: "POST" });
        const result = await response.json();
        showToast(`来源正常，读取 ${result.items} 条样本`);
      } catch (error) {
        showToast(error.message, true);
      } finally {
        button.disabled = false;
      }
    });
  });

  document.querySelectorAll("[data-source-toggle]").forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      const enabled = button.dataset.enabled !== "true";
      try {
        await protectedFetch("/api/v1/sources/" + button.dataset.sourceToggle, {
          method: "PATCH",
          body: JSON.stringify({ enabled }),
        });
        showToast(enabled ? "来源已启用" : "来源已停用");
        window.setTimeout(() => window.location.reload(), 500);
      } catch (error) {
        showToast(error.message, true);
        button.disabled = false;
      }
    });
  });

  const subscriptionList = document.querySelector("[data-subscription-list]");
  const subscriptionCount = document.querySelector("[data-subscription-count]");
  const selectedCompanies = new Map();

  const renderSelectedCompanies = () => {
    const container = document.querySelector("[data-selected-companies]");
    if (!container) return;
    container.replaceChildren();
    selectedCompanies.forEach((name, id) => {
      const chip = document.createElement("span");
      chip.className = "target-chip";
      const label = document.createElement("span");
      label.textContent = name;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.title = "移除 " + name;
      remove.setAttribute("aria-label", "移除 " + name);
      remove.addEventListener("click", () => {
        selectedCompanies.delete(id);
        renderSelectedCompanies();
      });
      chip.append(label, remove);
      container.append(chip);
    });
  };

  const loadSubscriptions = async () => {
    if (!subscriptionList || !adminToken()) return;
    try {
      const response = await protectedFetch("/api/v1/subscriptions");
      const data = await response.json();
      subscriptionList.replaceChildren();
      subscriptionCount.textContent = data.items.length + " 条";
      if (!data.items.length) {
        const empty = document.createElement("p");
        empty.className = "empty-inline";
        empty.textContent = "暂无订阅。";
        subscriptionList.append(empty);
        return;
      }
      data.items.forEach((item) => {
        const row = document.createElement("article");
        const identity = document.createElement("div");
        const email = document.createElement("strong");
        email.textContent = item.email;
        const scope = document.createElement("small");
        const targetCount = item.company_ids.length + item.industry_ids.length;
        scope.textContent = targetCount ? targetCount + " 个指定目标" : "全部事件";
        identity.append(email, scope);

        const policy = document.createElement("div");
        const frequency = document.createElement("strong");
        frequency.textContent = item.frequency === "daily" ? "每日摘要" : "即时通知";
        const threshold = document.createElement("small");
        threshold.textContent = "关联度 ≥ " + item.min_relevance;
        policy.append(frequency, threshold);

        const state = document.createElement("span");
        state.className = item.enabled ? "health-ok" : "health-unknown";
        state.textContent = item.enabled ? "启用" : "停用";

        const disable = document.createElement("button");
        disable.type = "button";
        disable.className = "quiet-button";
        disable.textContent = "停用";
        disable.disabled = !item.enabled;
        disable.addEventListener("click", async () => {
          disable.disabled = true;
          try {
            await protectedFetch("/api/v1/subscriptions/" + item.id, { method: "DELETE" });
            showToast("订阅已停用");
            await loadSubscriptions();
          } catch (error) {
            showToast(error.message, true);
            disable.disabled = false;
          }
        });
        row.append(identity, policy, state, disable);
        subscriptionList.append(row);
      });
    } catch (error) {
      showToast(error.message, true);
    }
  };

  const companySearch = document.querySelector("[data-company-search]");
  const companyResults = document.querySelector("[data-company-results]");
  let companySearchTimer;
  companySearch?.addEventListener("input", () => {
    window.clearTimeout(companySearchTimer);
    const query = companySearch.value.trim();
    if (query.length < 2) {
      companyResults.hidden = true;
      companyResults.replaceChildren();
      return;
    }
    companySearchTimer = window.setTimeout(async () => {
      try {
        const response = await protectedFetch(
          "/api/v1/catalog/companies?q=" + encodeURIComponent(query) + "&limit=12",
        );
        const data = await response.json();
        companyResults.replaceChildren();
        data.items.forEach((item) => {
          const option = document.createElement("button");
          option.type = "button";
          option.textContent = item.name + (item.country ? " · " + item.country : "");
          option.addEventListener("click", () => {
            selectedCompanies.set(item.id, item.name);
            renderSelectedCompanies();
            companyResults.hidden = true;
            companySearch.value = "";
          });
          companyResults.append(option);
        });
        companyResults.hidden = false;
      } catch (error) {
        showToast(error.message, true);
      }
    }, 250);
  });

  document.querySelector("[data-subscription-form]")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const industrySelect = form.querySelector("[name='industry_ids']");
    const payload = {
      email: data.get("email"),
      company_ids: [...selectedCompanies.keys()],
      industry_ids: [...industrySelect.selectedOptions].map((option) => option.value),
      min_relevance: Number(data.get("min_relevance")),
      frequency: data.get("frequency"),
      digest_hour_utc: Number(data.get("digest_hour_utc")),
      enabled: true,
    };
    try {
      await protectedFetch("/api/v1/subscriptions", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      form.reset();
      selectedCompanies.clear();
      renderSelectedCompanies();
      showToast("订阅已创建");
      await loadSubscriptions();
    } catch (error) {
      showToast(error.message, true);
    }
  });

  document.querySelector("[data-dispatch-notifications]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const response = await protectedFetch("/api/v1/notifications/dispatch", { method: "POST" });
      const result = await response.json();
      showToast(
        result.status === "disabled"
          ? "通知发送尚未启用"
          : "已发送 " + result.sent + " 条，失败 " + result.failed + " 条",
      );
    } catch (error) {
      showToast(error.message, true);
    } finally {
      button.disabled = false;
    }
  });

  loadSubscriptions();

  document.querySelector("[data-reanalyze]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await protectedFetch(`/api/v1/events/${button.dataset.reanalyze}/reanalyze`, {
        method: "POST",
        body: JSON.stringify({ stages: ["verify", "impact", "report"], reason: "manual dashboard request" }),
      });
      showToast("分析已更新");
      window.setTimeout(() => window.location.reload(), 500);
    } catch (error) {
      showToast(error.message, true);
      button.disabled = false;
    }
  });

  document.querySelector("[data-event-lock]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const currentlyLocked = button.dataset.locked === "true";
    const reason = window.prompt(currentlyLocked ? "请输入解除锁定原因" : "请输入锁定原因");
    if (reason === null) return;
    if (reason.trim().length < 3) {
      showToast("原因至少需要 3 个字符", true);
      return;
    }
    button.disabled = true;
    try {
      await protectedFetch(`/api/v1/events/${button.dataset.eventLock}/lock`, {
        method: "PATCH",
        body: JSON.stringify({
          locked: !currentlyLocked,
          reason: reason.trim(),
          actor: "local-analyst",
        }),
      });
      showToast(currentlyLocked ? "事件已解除锁定" : "事件已锁定");
      window.setTimeout(() => window.location.reload(), 500);
    } catch (error) {
      showToast(error.message, true);
      button.disabled = false;
    }
  });

  document.querySelector("[data-feedback-form]")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = Object.fromEntries(new FormData(form).entries());
    try {
      await protectedFetch("/api/v1/feedback", { method: "POST", body: JSON.stringify(payload) });
      showToast("反馈已记录");
      form.querySelector("textarea").value = "";
    } catch (error) {
      showToast(error.message, true);
    }
  });

  document.querySelectorAll("[data-protected-link]").forEach((link) => {
    link.addEventListener("click", async (event) => {
      event.preventDefault();
      try {
        const response = await protectedFetch(link.href);
        const blob = await response.blob();
        const objectUrl = URL.createObjectURL(blob);
        const download = document.createElement("a");
        download.href = objectUrl;
        download.download = "news-claws-report.md";
        download.click();
        URL.revokeObjectURL(objectUrl);
      } catch (error) {
        showToast(error.message, true);
      }
    });
  });
})();
