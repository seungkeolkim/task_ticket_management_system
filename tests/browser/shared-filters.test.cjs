const { test } = require("node:test");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

/** 독립 Browser session으로 지정한 프로젝트 역할의 사용자를 인증한다. */
async function authenticatedContext(browser, baseUrl, loginId) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  const csrf = await (await context.request.get(`${baseUrl}/api/auth/csrf`)).json();
  const response = await context.request.post(`${baseUrl}/api/auth/login`, {
    headers: { Origin: baseUrl, "X-CSRF-Token": csrf.csrf_token },
    data: { login_id: loginId, password: "Ticket-test-password-123!" },
  });
  assert.equal(response.status(), 200);
  return context;
}

/** 관리자 관리와 다른 구성원의 공유 조건 적용·권한 구분을 검증한다. */
test("shared filters are managed by administrators and applied by project members", async () => {
  const baseUrl = process.env.TTMS_BROWSER_BASE_URL;
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL });
  try {
    const managerContext = await authenticatedContext(browser, baseUrl, "manager");
    const managerPage = await managerContext.newPage();
    const errors = [];
    managerPage.on("pageerror", error => errors.push(error.message));
    await managerPage.goto(`${baseUrl}/projects/DEV/tickets?type=TASK&sort_by=number&page_size=10`);
    const sharedPanel = managerPage.locator("[data-filter-scope=shared]");
    const personalPanel = managerPage.locator("[data-filter-scope=personal]");
    const name = "팀 공용 <img src=x onerror=alert(1)>";
    await managerPage.getByLabel("공유 필터 이름", { exact: true }).fill(name);
    await Promise.all([
      managerPage.waitForNavigation(),
      sharedPanel.getByRole("button", { name: "공유 필터 저장", exact: true }).click(),
    ]);
    assert.equal(await sharedPanel.locator("[data-shared-filter-name]").innerText(), name);
    assert.equal(await sharedPanel.locator("img").count(), 0);
    assert.equal(await personalPanel.locator("[data-personal-filter-id]").count(), 0);
    assert.match(await sharedPanel.locator("[data-shared-filter-feedback]").innerText(), /구성원 모두/);
    assert.equal(await managerPage.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    if (process.env.TTMS_SHARED_FILTER_SCREENSHOT) {
      await managerPage.screenshot({ path: process.env.TTMS_SHARED_FILTER_SCREENSHOT, fullPage: true });
    }
    for (const loginId of ["member", "guest"]) {
      const memberContext = await authenticatedContext(browser, baseUrl, loginId);
      const memberPage = await memberContext.newPage();
      memberPage.on("pageerror", error => errors.push(error.message));
      await memberPage.goto(`${baseUrl}/projects/DEV/board`);
      const memberSharedPanel = memberPage.locator("[data-filter-scope=shared]");
      assert.equal(await memberSharedPanel.locator("[data-shared-filter-name]").innerText(), name);
      assert.equal(await memberSharedPanel.locator("button").count(), 0);
      await memberSharedPanel.getByRole("link", { name: "적용", exact: true }).click();
      assert.equal(new URL(memberPage.url()).searchParams.get("type"), "TASK");
      assert.equal(new URL(memberPage.url()).searchParams.get("page_size"), "10");
      assert.equal(await memberPage.locator(".kanban-card").count(), 1);
      await memberContext.close();
    }
    const stalePage = await managerContext.newPage();
    await stalePage.goto(`${baseUrl}/projects/DEV/tickets`);
    await Promise.all([
      managerPage.waitForNavigation(),
      managerPage.waitForEvent("dialog").then(dialog => dialog.accept("팀 확인 대상")),
      sharedPanel.getByRole("button", { name: "이름 변경", exact: true }).click(),
    ]);
    await Promise.all([
      stalePage.waitForEvent("dialog").then(dialog => dialog.accept("오래된 변경")),
      stalePage.locator("[data-filter-scope=shared]").getByRole("button", { name: "이름 변경", exact: true }).click(),
    ]);
    await stalePage.locator("[data-shared-filter-feedback]").waitFor({ state: "visible" });
    assert.match(await stalePage.locator("[data-shared-filter-feedback]").innerText(), /새로고침/);
    await managerPage.goto(`${baseUrl}/projects/DEV/board?type=SUBTASK`);
    await Promise.all([
      managerPage.waitForNavigation(),
      managerPage.waitForEvent("dialog").then(dialog => dialog.accept()),
      sharedPanel.getByRole("button", { name: "현재 조건으로 덮어쓰기", exact: true }).click(),
    ]);
    await managerPage.goto(`${baseUrl}/projects/DEV/tickets`);
    await sharedPanel.getByRole("link", { name: "적용", exact: true }).click();
    assert.equal(new URL(managerPage.url()).searchParams.get("type"), "SUBTASK");
    await Promise.all([
      managerPage.waitForNavigation(),
      managerPage.waitForEvent("dialog").then(dialog => dialog.accept()),
      sharedPanel.getByRole("button", { name: "삭제", exact: true }).click(),
    ]);
    assert.equal(await sharedPanel.locator("[data-shared-filter-id]").count(), 0);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
});
