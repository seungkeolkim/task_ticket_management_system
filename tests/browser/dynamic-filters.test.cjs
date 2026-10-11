const { test } = require("node:test");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");
const { authenticatedContext, saveFilter } = require("./filter-helpers.cjs");

/** 필요한 필드에 동적 기준값을 선택하고 생성된 조건 행을 반환한다. */
async function addDynamicCondition(page, field, source) {
  const root = page.locator(".filter-group").first();
  await root.locator(":scope > .filter-group-actions [data-filter-add-field]").selectOption(field);
  const row = root.locator(":scope > .filter-condition").last();
  await row.locator("[data-filter-value-source]").selectOption(source);
  return row;
}

/** 숫자 입력·기간 미리보기·사용자별 공용 적용·목록/칸반 복원을 검증한다. */
test("dynamic criteria retain rules and resolve for each applying user", async () => {
  const baseUrl = process.env.TTMS_BROWSER_BASE_URL;
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL });
  let managerContext;
  let savedIdentifier;
  try {
    managerContext = await authenticatedContext(browser, baseUrl, "manager");
    const page = await managerContext.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(`${baseUrl}/projects/DEV/tickets`);
    await addDynamicCondition(page, "creator", "current_user");
    const period = await addDynamicCondition(page, "updated_date", "relative_period");
    await period.locator("[data-filter-rule-days]").fill("1");
    assert.match(await period.locator("[data-filter-rule-preview]").innerText(), /최근 1일 · 오늘 포함/);
    await period.locator("[data-filter-rule-days]").fill("0");
    assert.equal(await period.locator("[data-filter-rule-days]").evaluate(input => input.checkValidity()), false);
    await period.locator("[data-filter-rule-days]").fill("7");
    await addDynamicCondition(page, "created_date", "this_week");
    await Promise.all([page.waitForNavigation(), page.getByRole("button", { name: "적용", exact: true }).click()]);
    const definition = JSON.parse(new URL(page.url()).searchParams.get("filter"));
    assert.equal(definition.schema_version, 4);
    assert.deepEqual(definition.expression.children[0].rule, { kind: "current_user" });
    assert.deepEqual(definition.expression.children[1].rule, { kind: "relative_period", days: 7, direction: "past" });
    assert.match(await page.locator("[data-filter-applied-resolution]").innerText(), /manager/);
    await saveFilter(page, "동적 공용 초안", "shared");
    const selectedValue = await page.locator("[data-saved-filter-selection]").inputValue();
    savedIdentifier = selectedValue.split(":")[1];
    for (const loginId of ["member", "guest"]) {
      const context = await authenticatedContext(browser, baseUrl, loginId);
      const memberPage = await context.newPage();
      memberPage.on("pageerror", error => errors.push(error.message));
      await memberPage.goto(`${baseUrl}/projects/DEV/board`);
      await memberPage.locator("[data-saved-filter-selection]").selectOption(selectedValue);
      await Promise.all([memberPage.waitForNavigation(), memberPage.getByRole("button", { name: "불러오기", exact: true }).click()]);
      assert.match(await memberPage.locator("[data-filter-applied-resolution]").innerText(), new RegExp(loginId));
      assert.equal(await memberPage.locator(".kanban-card").count(), loginId === "member" ? 2 : 0);
      await memberPage.getByRole("link", { name: "☷ 목록 보기" }).click();
      assert.equal(await memberPage.locator(".ticket-table-row").count(), loginId === "member" ? 3 : 0);
      const restored = JSON.parse(new URL(memberPage.url()).searchParams.get("filter"));
      assert.deepEqual(restored.expression, definition.expression);
      assert.equal(await memberPage.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      if (loginId === "member" && process.env.TTMS_DYNAMIC_FILTER_SCREENSHOT) {
        await memberPage.screenshot({ path: process.env.TTMS_DYNAMIC_FILTER_SCREENSHOT, fullPage: true });
      }
      await memberPage.reload();
      assert.equal(await memberPage.locator('[data-filter-value-source]').first().inputValue(), "current_user");
      await context.close();
    }
    await page.goto(`${baseUrl}/projects/DEV/tickets`);
    const boundary = await addDynamicCondition(page, "due_date", "day_offset");
    await boundary.locator("[data-filter-rule-days]").fill("7");
    await boundary.locator("[data-condition-operator]").selectOption("before");
    assert.match(await boundary.locator("[data-filter-rule-preview]").innerText(), /7일 전/);
    await Promise.all([page.waitForNavigation(), page.getByRole("button", { name: "적용", exact: true }).click()]);
    assert.equal(JSON.parse(new URL(page.url()).searchParams.get("filter")).expression.children[0].operator, "before");
    assert.deepEqual(errors, []);
  } finally {
    try {
      if (managerContext && savedIdentifier) {
        const summary = await (await managerContext.request.get(`${baseUrl}/api/projects/DEV/shared-filters/${savedIdentifier}`)).json();
        const csrf = await (await managerContext.request.get(`${baseUrl}/api/auth/csrf`)).json();
        const response = await managerContext.request.delete(`${baseUrl}/api/projects/DEV/shared-filters/${savedIdentifier}`, {
          headers: { Origin: baseUrl, "X-CSRF-Token": csrf.csrf_token },
          data: { expected_updated_at: summary.updated_at },
        });
        assert.equal(response.status(), 204);
      }
    } finally {
      await browser.close();
    }
  }
});
