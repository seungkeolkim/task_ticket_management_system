/** TTMS_RUN_BROWSER_TESTS=1인 pytest의 임시 서버에서 실행하는 Browser 회귀 테스트다. */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

/** 실제 form 제출·화면 전환·drag 재조회에서 필터와 권한 계약을 검증한다. */
test("kanban filters survive navigation and drag reload", async () => {
  const baseUrl = process.env.TTMS_BROWSER_BASE_URL;
  assert.ok(baseUrl, "pytest의 임시 Browser 서버 주소가 필요합니다.");
  const browser = await chromium.launch({
    headless: true, channel: process.env.PLAYWRIGHT_CHANNEL,
  });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
    const csrfResponse = await context.request.get(`${baseUrl}/api/auth/csrf`);
    const csrfPayload = await csrfResponse.json();
    const loginResponse = await context.request.post(`${baseUrl}/api/auth/login`, {
      headers: { Origin: baseUrl, "X-CSRF-Token": csrfPayload.csrf_token },
      data: { login_id: "member", password: "Ticket-test-password-123!" },
    });
    assert.equal(loginResponse.status(), 200);
    const page = await context.newPage();
    const browserErrors = [];
    page.on("pageerror", error => browserErrors.push(error.message));
    await page.goto(`${baseUrl}/projects/DEV/board`);
    await page.locator(".ticket-filter-details summary").click();
    await page.locator('[name="type"][value="SUBTASK"]').check();
    await page.locator('[name="status"][value="TODO"]').check();
    await page.locator('.ticket-filter-toolbar [name="q"]').fill("Browser 하위");
    await Promise.all([
      page.waitForURL(url => url.searchParams.get("type") === "SUBTASK"),
      page.locator('.ticket-filter-toolbar button[type="submit"]').click(),
    ]);
    assert.equal(await page.locator(".kanban-card").count(), 1);
    assert.match(await page.locator(".parent-reference").innerText(), /상위 Task/);
    assert.equal(await page.locator("[data-board-column]").count(), 5);
    const filteredUrl = page.url();
    await page.reload();
    assert.equal(await page.locator('[name="status"][value="TODO"]').isChecked(), true);
    await page.getByRole("link", { name: "☷ 목록 보기" }).click();
    assert.equal(new URL(page.url()).searchParams.get("type"), "SUBTASK");
    assert.equal(await page.locator(".ticket-table-row").count(), 1);
    await page.getByRole("link", { name: "칸반 보기", exact: true }).click();
    assert.equal(new URL(page.url()).searchParams.get("q"), "Browser 하위");

    await page.waitForLoadState("load");
    const card = page.locator(".kanban-card");
    const progressColumn = page.locator('[data-board-column][data-status="IN_PROGRESS"]');
    await Promise.all([
      page.waitForEvent("dialog").then(dialog => dialog.dismiss()),
      card.dragTo(progressColumn, { sourcePosition: { x: 5, y: 5 }, targetPosition: { x: 40, y: 100 } }),
    ]);
    assert.equal(await card.count(), 1);
    await Promise.all([
      page.waitForEvent("dialog").then(dialog => dialog.accept()),
      page.waitForNavigation(),
      card.dragTo(progressColumn, { sourcePosition: { x: 5, y: 5 }, targetPosition: { x: 40, y: 100 } }),
    ]);
    assert.equal(new URL(page.url()).searchParams.get("status"), "TODO");
    assert.equal(await page.locator(".kanban-card").count(), 0);
    assert.match(await page.locator(".empty-state").innerText(), /조건에 맞는 카드가 없습니다/);
    assert.match(await page.locator("#board-feedback").innerText(), /상태를 변경했습니다/);

    await page.goto(`${baseUrl}/projects/DEV/board?unassigned=true`);
    assert.equal(await page.locator('[name="assignee_id"]').isDisabled(), true);
    await page.locator('[name="unassigned"]').uncheck();
    assert.equal(await page.locator('[name="assignee_id"]').isEnabled(), true);
    await page.getByRole("link", { name: "초기화", exact: true }).click();
    assert.equal(new URL(page.url()).search, "");
    assert.equal(await page.locator(".kanban-card").count(), 2);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    if (process.env.TTMS_BROWSER_SCREENSHOT) {
      await page.goto(filteredUrl.replace("status=TODO", "status=IN_PROGRESS"));
      await page.screenshot({ path: process.env.TTMS_BROWSER_SCREENSHOT, fullPage: true });
    }
    assert.deepEqual(browserErrors, []);
  } finally {
    await browser.close();
  }
});
