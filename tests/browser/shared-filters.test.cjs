const { test } = require("node:test");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");
const { filterUrl, condition, authenticatedContext, saveFilter } = require("./filter-helpers.cjs");

/** 관리 권한·구성원 적용·stale 탭·공용 조건 덮어쓰기를 검증한다. */
test("shared compound filters retain permissions and stale protection", async () => {
  const baseUrl = process.env.TTMS_BROWSER_BASE_URL;
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL });
  try {
    const managerContext = await authenticatedContext(browser, baseUrl, "manager");
    const managerPage = await managerContext.newPage();
    const errors = [];
    managerPage.on("pageerror", error => errors.push(error.message));
    await managerPage.goto(filterUrl(baseUrl, "tickets", [condition("type", "in", ["TASK"])], { sort_by: "number", page_size: 10 }));
    const panel = managerPage.locator("[data-saved-filters]");
    const selection = panel.locator("[data-saved-filter-selection]");
    const name = "팀 공용 <img src=x onerror=alert(1)>";
    await saveFilter(managerPage, name, "shared");
    const selectedValue = await selection.inputValue();
    assert.match(selectedValue, /^shared:/);
    assert.equal(await selection.locator("option:checked").textContent(), name);
    assert.equal(await panel.locator("img").count(), 0);
    assert.match(await panel.locator("[data-saved-filter-feedback]").innerText(), /구성원 모두/);
    for (const loginId of ["member", "guest"]) {
      const memberContext = await authenticatedContext(browser, baseUrl, loginId);
      const memberPage = await memberContext.newPage();
      memberPage.on("pageerror", error => errors.push(error.message));
      await memberPage.goto(`${baseUrl}/projects/DEV/board`);
      await memberPage.locator("[data-saved-filter-selection]").selectOption(selectedValue);
      assert.equal(await memberPage.getByRole("button", { name: "이름 변경", exact: true }).isVisible(), false);
      await Promise.all([memberPage.waitForNavigation(), memberPage.getByRole("button", { name: "불러오기", exact: true }).click()]);
      assert.equal(JSON.parse(new URL(memberPage.url()).searchParams.get("filter")).expression.children[0].values[0], "TASK");
      assert.equal(await memberPage.locator(".kanban-card").count(), 1);
      await memberPage.getByRole("button", { name: "필터 저장", exact: true }).click();
      assert.equal(await memberPage.getByLabel("공개 범위", { exact: true }).locator('option[value="shared"]').count(), 0);
      await memberPage.getByRole("button", { name: "취소", exact: true }).click();
      await memberContext.close();
    }
    const stalePage = await managerContext.newPage();
    await stalePage.goto(`${baseUrl}/projects/DEV/tickets`);
    await stalePage.locator("[data-saved-filter-selection]").selectOption(selectedValue);
    await Promise.all([
      managerPage.waitForNavigation(), managerPage.waitForEvent("dialog").then(dialog => dialog.accept("팀 확인 대상")),
      managerPage.getByRole("button", { name: "이름 변경", exact: true }).click(),
    ]);
    await Promise.all([
      stalePage.waitForEvent("dialog").then(dialog => dialog.accept("오래된 변경")),
      stalePage.getByRole("button", { name: "이름 변경", exact: true }).click(),
    ]);
    await stalePage.locator("[data-saved-filter-feedback]").waitFor({ state: "visible" });
    assert.match(await stalePage.locator("[data-saved-filter-feedback]").innerText(), /새로고침/);
    await managerPage.goto(filterUrl(baseUrl, "board", [condition("type", "in", ["SUBTASK"])]));
    await selection.selectOption(selectedValue);
    await Promise.all([
      managerPage.waitForNavigation(), managerPage.waitForEvent("dialog").then(dialog => dialog.accept()),
      managerPage.getByRole("button", { name: "현재 조건으로 덮어쓰기", exact: true }).click(),
    ]);
    await managerPage.goto(`${baseUrl}/projects/DEV/tickets`);
    await selection.selectOption(selectedValue);
    await Promise.all([managerPage.waitForNavigation(), managerPage.getByRole("button", { name: "불러오기", exact: true }).click()]);
    assert.equal(JSON.parse(new URL(managerPage.url()).searchParams.get("filter")).expression.children[0].values[0], "SUBTASK");
    assert.equal(await managerPage.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await Promise.all([
      managerPage.waitForNavigation(), managerPage.waitForEvent("dialog").then(dialog => dialog.accept()),
      managerPage.getByRole("button", { name: "삭제", exact: true }).click(),
    ]);
    assert.equal(await selection.locator(`option[value="${selectedValue}"]`).count(), 0);
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});
