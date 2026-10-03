/** Run with node --test after making Playwright available through NODE_PATH or node_modules. */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { chromium } = require("playwright");

/** 실제 편집 script의 필드 추가·수정·삭제와 안전한 문자열 처리를 확인한다. */
test("ticket-local Text fields add, rename, escape, submit and remove", async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL });
  try {
    const page = await browser.newPage();
    const stableIdentifier = "00000000-0000-4000-8000-000000000001";
    const existingFields = [{
      field_id: stableIdentifier, name: "기존 필드", field_type: "TEXT", value: "최초 값",
    }];
    await page.setContent(`<form><div data-ticket-custom-fields>
      <textarea name="custom_fields" data-custom-fields-payload hidden></textarea>
      <div data-custom-field-rows></div><p data-custom-field-error hidden></p>
      <button type="button" data-add-custom-field>+ 필드 추가</button>
      </div><button type="submit">저장</button></form>`);
    await page.locator("[data-custom-fields-payload]").evaluate(
      (element, fields) => { element.value = JSON.stringify(fields); }, existingFields,
    );
    await page.addScriptTag({ path: path.join(__dirname, "../../app/web/static/ticket-properties.js") });
    await page.locator("[data-field-name]").fill("현장 위치");
    await page.locator("[data-add-custom-field]").click();
    assert.equal(await page.locator("[data-field-name]").count(), 2);
    await page.locator("[data-field-name]").nth(1).fill("<img src=x onerror=alert(1)>");
    await page.locator("[data-field-value]").nth(1).fill("첫째 줄\n둘째 줄");
    assert.equal(await page.locator("[data-field-type]").nth(1).inputValue(), "TEXT");
    assert.equal(await page.locator("img").count(), 0);
    await page.locator("form").evaluate((form) => {
      form.addEventListener("submit", (event) => event.preventDefault());
    });
    await page.getByRole("button", { name: "저장", exact: true }).click();
    const savedFields = JSON.parse(await page.locator("[data-custom-fields-payload]").inputValue());
    assert.equal(savedFields[0].field_id, stableIdentifier);
    assert.equal(savedFields[0].name, "현장 위치");
    assert.equal(savedFields[1].value, "첫째 줄\n둘째 줄");
    await page.getByRole("button", { name: "필드 제거" }).first().click();
    await page.getByRole("button", { name: "필드 제거" }).first().click();
    assert.deepEqual(JSON.parse(await page.locator("[data-custom-fields-payload]").inputValue()), []);
  } finally {
    await browser.close();
  }
});

/** 잘못된 원본 입력이 빈 목록으로 조용히 대체되지 않는지 확인한다. */
test("invalid stored input remains recoverable instead of being cleared", async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL });
  try {
    const page = await browser.newPage();
    await page.setContent(`<form><div data-ticket-custom-fields>
      <textarea data-custom-fields-payload hidden>not-json</textarea>
      <div data-custom-field-rows></div><p data-custom-field-error hidden></p>
      <button type="button" data-add-custom-field>추가</button></div></form>`);
    await page.addScriptTag({ path: path.join(__dirname, "../../app/web/static/ticket-properties.js") });
    assert.equal(await page.locator("[data-custom-fields-payload]").inputValue(), "not-json");
    assert.equal(await page.locator("[data-custom-fields-payload]").isVisible(), true);
    assert.equal(await page.locator("[data-add-custom-field]").isDisabled(), true);
  } finally {
    await browser.close();
  }
});
