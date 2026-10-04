const { test } = require('node:test');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

/** 실제 사용자 session으로 로그인한 독립 Browser context를 만든다. */
async function authenticatedContext(browser, baseUrl, loginId) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  const csrf = await (await context.request.get(`${baseUrl}/api/auth/csrf`)).json();
  const response = await context.request.post(`${baseUrl}/api/auth/login`, {
    headers: { Origin: baseUrl, 'X-CSRF-Token': csrf.csrf_token },
    data: { login_id: loginId, password: 'Ticket-test-password-123!' },
  });
  assert.equal(response.status(), 200);
  return context;
}

/** 설명·댓글 멘션을 키보드와 마우스로 선택하고 수신자가 확인한다. */
test('mention editor, persistence and dashboard read flow', async () => {
  const baseUrl = process.env.TTMS_BROWSER_BASE_URL;
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL });
  try {
    const sender = await authenticatedContext(browser, baseUrl, 'member');
    const page = await sender.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('dialog', dialog => dialog.accept());
    await page.goto(`${baseUrl}/projects/DEV/tickets/new`);
    await page.locator('[name=title]').fill('Browser 멘션 확인');
    const description = page.getByLabel('티켓 설명 편집기', { exact: true });
    await description.click();
    await description.pressSequentially('@guest');
    await page.locator('.mention-suggestions button').first().waitFor();
    await description.press('Enter');
    assert.equal(await description.locator('[data-mention-user-id]').count(), 1);
    await Promise.all([page.waitForNavigation(), page.locator('button[type=submit]').filter({ hasText: '티켓 만들기' }).click()]);
    const ticketUrl = page.url();
    assert.match(new URL(ticketUrl).pathname, /\/tickets\/DEV-\d+$/);
    const commentEditor = page.getByLabel('댓글 작성 편집기', { exact: true });
    await commentEditor.click();
    await commentEditor.pressSequentially('@guest');
    await page.locator('.mention-suggestions button').first().click();
    await Promise.all([page.waitForNavigation(), page.getByRole('button', { name: '댓글 등록', exact: true }).click()]);
    assert.equal(await page.locator('.comment-card [data-mention-user-id]').count(), 1);
    const recipient = await authenticatedContext(browser, baseUrl, 'guest');
    const inbox = await recipient.newPage();
    await inbox.goto(baseUrl);
    assert.equal(await inbox.locator('.mention-item').count(), 2);
    await Promise.all([inbox.waitForNavigation(), inbox.getByRole('button', { name: '원본 보기 · 읽음', exact: true }).first().click()]);
    assert.match(inbox.url(), /#comment-\d+$/);
    await inbox.goto(baseUrl);
    assert.equal(await inbox.locator('.mention-item').count(), 1);
    await Promise.all([inbox.waitForNavigation(), inbox.getByRole('button', { name: '모두 읽음 처리', exact: true }).click()]);
    assert.equal(await inbox.locator('.mention-item').count(), 0);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
});
