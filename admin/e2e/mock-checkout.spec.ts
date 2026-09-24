import { expect, test } from "@playwright/test";

const price = { amount_minor: 49000, currency: "VND", unit: "minor" };
const product = {
  id: "learning-pass",
  name: "Synthetic learning pass",
  description: "Fixture-only access",
  variants: [{ id: "learning-pass-30d", name: "30 days", price, available_quantity: 12 }],
};

test("browser submits one mock intent and shows reconciliation history", async ({ page }) => {
  const orders: Array<Record<string, unknown>> = [];
  let posts = 0;
  await page.route("**/api/**", async (route) => {
    const { pathname } = new URL(route.request().url());
    const method = route.request().method();
    const reply = (body: unknown, status = 200) => route.fulfill({
      status, contentType: "application/json", body: JSON.stringify(body),
    });
    if (pathname.endsWith("/v1/catalog/sources")) {
      await reply({ sources: [{ supplier: "mock", mode: "mock", read_only: true }], selection_required: false, aggregate_available: false });
    } else if (pathname.endsWith("/v1/catalog")) {
      await reply({ supplier: "mock", mode: "mock", read_only: true, partial: false, omitted_count: 0,
        state: "empty", freshness: null, items: [], error: null });
    } else if (pathname.endsWith("/v1/capabilities")) {
      const disabled = { status: "disabled", reason: "Demo only" };
      await reply({ catalog_read: disabled, catalog_detail: disabled, purchase: disabled,
        payment: disabled, top_up: disabled, refund: disabled, delivery: disabled });
    } else if (pathname.endsWith("/v1/mock-checkout/catalog")) {
      await reply({ mode: "MOCK", payment_mode: "disabled", items: [product] });
    } else if (pathname.endsWith("/v1/mock-checkout/orders") && method === "GET") {
      await reply(orders);
    } else if (pathname.endsWith("/v1/mock-checkout/orders") && method === "POST") {
      posts += 1;
      const input = route.request().postDataJSON();
      expect(route.request().headers().authorization).toBe("Bearer synthetic-demo-key");
      const order = {
        intent_id: "00000000-0000-0000-0000-000000000001",
        product_id: input.product_id,
        variant_id: input.variant_id,
        quantity: input.quantity,
        unit_price: price,
        max_unit_price: input.max_unit_price,
        total_price: price,
        purchase_state: "UNKNOWN",
        failure_code: null,
      };
      orders.unshift(order);
      await reply(order);
    } else if (pathname.endsWith("/reconcile") && method === "POST") {
      const input = route.request().postDataJSON();
      orders[0].purchase_state = input.evidence === "confirmed_success" ? "SUCCEEDED" : "RECONCILING";
      await reply(orders[0]);
    } else {
      await reply({ detail: "not found" }, 404);
    }
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Checkout MOCK" }).click();
  await expect(page.getByText("Checkout MOCK", { exact: true }).last()).toBeVisible();
  await page.getByLabel("Khóa demo từ terminal").fill("synthetic-demo-key");
  await page.getByRole("button", { name: "Tải catalog và lịch sử" }).click();
  await expect(page.getByLabel("Sản phẩm / biến thể")).toHaveValue("learning-pass/learning-pass-30d");
  await page.getByRole("button", { name: "Mô phỏng UNKNOWN" }).dblclick();
  await expect(page.getByText(/UNKNOWN — chưa có kết quả cuối/).first()).toBeVisible();
  expect(posts).toBe(1);
  await page.getByRole("button", { name: "Giả lập xác nhận thành công" }).click();
  await expect(page.getByText(/Thành công mô phỏng/).first()).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Checkout MOCK" }).click();
  await expect(page.getByLabel("Khóa demo từ terminal")).toHaveValue("");
});
