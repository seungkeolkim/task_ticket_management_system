const assert = require("node:assert/strict");

/** 직접 작성한 v3 조건으로 테스트 URL을 만든다. */
function filterUrl(baseUrl, view, conditions, settings = {}) {
  const definition = { schema_version: 3, expression: { kind: "group", operator: "AND", children: conditions, negated: false }, ...settings };
  return `${baseUrl}/projects/DEV/${view}?filter=${encodeURIComponent(JSON.stringify(definition))}`;
}

/** 조건 하나를 v3 고정값 계약으로 만든다. */
function condition(field, operator, values = []) {
  return { kind: "condition", field, operator, values, negated: false };
}

/** 독립 Browser session을 주어진 프로젝트 사용자로 인증한다. */
async function authenticatedContext(browser, baseUrl, loginId = "member") {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  const csrf = await (await context.request.get(`${baseUrl}/api/auth/csrf`)).json();
  const response = await context.request.post(`${baseUrl}/api/auth/login`, {
    headers: { Origin: baseUrl, "X-CSRF-Token": csrf.csrf_token },
    data: { login_id: loginId, password: "Ticket-test-password-123!" },
  });
  assert.equal(response.status(), 200);
  return context;
}

/** 필드를 추가하고 선택형·Text·Date 값 입력을 채운다. */
async function addCondition(group, field, operator, values = []) {
  await group.locator(":scope > .filter-group-actions [data-filter-add-field]").selectOption(field);
  const row = group.locator(":scope > .filter-condition").last();
  await row.locator("[data-condition-operator]").selectOption(operator);
  if (["is_empty", "is_not_empty"].includes(operator)) return row;
  if (["search", "created_date", "updated_date", "due_date"].includes(field)) {
    const inputs = row.locator('.filter-condition-values input');
    for (let index = 0; index < values.length; index++) await inputs.nth(index).fill(values[index]);
  } else {
    await row.locator(".filter-value-picker summary").click();
    for (const value of values) await row.locator(`.filter-value-options input[value="${value}"]`).check();
    await row.locator(".filter-value-picker summary").click();
  }
  return row;
}

/** 생성 dialog에서 개인 또는 공유 필터를 저장한다. */
async function saveFilter(page, name, scope) {
  await page.getByRole("button", { name: "필터 저장", exact: true }).click();
  await page.getByLabel("필터 이름", { exact: true }).fill(name);
  await page.getByLabel("공개 범위", { exact: true }).selectOption(scope);
  await Promise.all([
    page.waitForNavigation(),
    page.getByRole("button", { name: "저장", exact: true }).click(),
  ]);
}

module.exports = { filterUrl, condition, authenticatedContext, addCondition, saveFilter };
