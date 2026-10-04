const { test } = require("node:test");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

/** 개인·공유 구분과 저장·적용·수정·삭제의 실제 Browser 흐름을 검증한다. */
test("personal filters remain private and support their full UI lifecycle", async () => {
  const baseUrl = process.env.TTMS_BROWSER_BASE_URL;
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
    const csrf = await (await context.request.get(`${baseUrl}/api/auth/csrf`)).json();
    assert.equal((await context.request.post(`${baseUrl}/api/auth/login`, {
      headers: { Origin: baseUrl, "X-CSRF-Token": csrf.csrf_token },
      data: { login_id: "member", password: "Ticket-test-password-123!" },
    })).status(), 200);
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(`${baseUrl}/projects/DEV/tickets?type=TASK&status=TODO&sort_by=number&page_size=10`);
    const panel = page.locator("[data-personal-filters]");
    assert.match(await panel.innerText(), /내 개인 필터/);
    assert.match(await panel.innerText(), /나만 보기/);
    assert.match(await panel.locator(".saved-filter-shared").innerText(), /프로젝트 공유 필터/);
    assert.match(await panel.locator(".saved-filter-shared").innerText(), /구성원 공용/);
    assert.match(await panel.locator(".saved-filter-shared").innerText(), /프로젝트 관리자가 관리/);
    assert.equal(await panel.locator(".saved-filter-shared button").count(), 0);
    const filterName = "개인 업무 <img src=x onerror=alert(1)>";
    await page.getByLabel("개인 필터 이름", { exact: true }).fill(filterName);
    await Promise.all([
      page.waitForNavigation(),
      page.getByRole("button", { name: "개인 필터 저장", exact: true }).click(),
    ]);
    assert.equal(await panel.locator("[data-personal-filter-name]").innerText(), filterName);
    assert.equal(await panel.locator("img").count(), 0);
    assert.match(await panel.locator("[data-personal-filter-feedback]").innerText(), /나에게만 표시/);
    await page.goto(`${baseUrl}/projects/DEV/board`);
    await panel.getByRole("link", { name: "적용", exact: true }).click();
    await page.waitForLoadState("load");
    assert.equal(new URL(page.url()).searchParams.get("type"), "TASK");
    assert.equal(new URL(page.url()).searchParams.get("page_size"), "10");
    assert.equal(await page.locator(".kanban-card").count(), 1);
    await Promise.all([
      page.waitForNavigation(),
      page.waitForEvent("dialog").then(dialog => dialog.accept("내 등록 업무")),
      panel.getByRole("button", { name: "이름 변경", exact: true }).click(),
    ]);
    assert.equal(await panel.locator("[data-personal-filter-name]").innerText(), "내 등록 업무");
    await page.goto(`${baseUrl}/projects/DEV/board?type=SUBTASK`);
    await Promise.all([
      page.waitForNavigation(),
      page.waitForEvent("dialog").then(dialog => dialog.accept()),
      panel.getByRole("button", { name: "현재 조건으로 덮어쓰기", exact: true }).click(),
    ]);
    await page.getByRole("link", { name: "초기화", exact: true }).click();
    await panel.getByRole("link", { name: "적용", exact: true }).click();
    assert.equal(new URL(page.url()).searchParams.get("type"), "SUBTASK");
    assert.equal(await page.locator(".kanban-card").count(), 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    if (process.env.TTMS_PERSONAL_FILTER_SCREENSHOT) {
      await page.screenshot({ path: process.env.TTMS_PERSONAL_FILTER_SCREENSHOT, fullPage: true });
    }
    await Promise.all([
      page.waitForNavigation(),
      page.waitForEvent("dialog").then(dialog => dialog.accept()),
      panel.getByRole("button", { name: "삭제", exact: true }).click(),
    ]);
    assert.equal(await panel.locator("[data-personal-filter-id]").count(), 0);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
});
