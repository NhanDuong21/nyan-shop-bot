import { useRef, useState } from "react";

import {
  fetchMockCatalog,
  fetchMockOrders,
  placeMockOrder,
  reconcileMockOrder,
} from "../../mock-checkout-api";
import type {
  MockCatalog,
  MockEvidence,
  MockOrder,
  MockScenario,
  MockVariant,
} from "../../mock-checkout-api";

import "./mock-checkout.css";

function money(value: { amount_minor: number; currency: string }): string {
  return `${new Intl.NumberFormat("vi-VN").format(value.amount_minor)} ${value.currency} (minor)`;
}

function stateLabel(order: MockOrder): string {
  switch (order.purchase_state) {
    case "SUCCEEDED": return "Thành công mô phỏng";
    case "FAILED_SAFE": return `Thất bại an toàn: ${order.failure_code ?? "không rõ"}`;
    case "UNKNOWN": return "UNKNOWN — chưa có kết quả cuối";
    case "RECONCILING": return "Đang đối soát — chưa có kết quả cuối";
    default: return "Đang xử lý — kiểm tra lại lịch sử";
  }
}

export function MockCheckout() {
  const [token, setToken] = useState("");
  const [catalog, setCatalog] = useState<MockCatalog | null>(null);
  const [orders, setOrders] = useState<MockOrder[]>([]);
  const [selection, setSelection] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<MockOrder | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const pending = useRef<{ key: string; scenario: MockScenario } | null>(null);
  const locked = useRef(false);

  const choices = catalog?.items.flatMap((product) =>
    product.variants.map((variant) => ({ product, variant, key: `${product.id}/${variant.id}` })),
  ) ?? [];
  const selected = choices.find((choice) => choice.key === selection) ?? choices[0];

  async function refresh() {
    if (locked.current || token.length === 0) return;
    locked.current = true;
    setLoading(true);
    setError("");
    try {
      const [nextCatalog, nextOrders] = await Promise.all([
        fetchMockCatalog(token),
        fetchMockOrders(token),
      ]);
      setCatalog(nextCatalog);
      setOrders(nextOrders);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không tải được dữ liệu MOCK.");
    } finally {
      locked.current = false;
      setLoading(false);
    }
  }

  async function submit(scenario: MockScenario) {
    if (locked.current || !selected || (submitted && pending.current === null)) return;
    locked.current = true;
    setLoading(true);
    setError("");
    const active = pending.current ?? { key: crypto.randomUUID(), scenario };
    pending.current = active;
    try {
      const order = await placeMockOrder(token, {
        product_id: selected.product.id,
        variant_id: selected.variant.id,
        quantity,
        idempotency_key: active.key,
        max_unit_price: selected.variant.price,
        scenario: active.scenario,
      });
      setResult(order);
      setSubmitted(true);
      pending.current = null;
      setOrders(await fetchMockOrders(token));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không xác định được kết quả. Xem lịch sử.");
    } finally {
      locked.current = false;
      setLoading(false);
    }
  }

  async function reconcile(intentId: string, evidence: MockEvidence) {
    if (locked.current) return;
    locked.current = true;
    setLoading(true);
    setError("");
    try {
      const updated = await reconcileMockOrder(token, intentId, evidence);
      setResult(updated);
      setOrders(await fetchMockOrders(token));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không đối soát được đơn MOCK.");
    } finally {
      locked.current = false;
      setLoading(false);
    }
  }

  function newOrder() {
    pending.current = null;
    setResult(null);
    setSubmitted(false);
    setError("");
  }

  return (
    <main className="mock-checkout" id="catalog-content">
      <header>
        <h1>Checkout MOCK</h1>
        <p>Chỉ sản phẩm tổng hợp. Tiền và supplier đều giả; không thanh toán, giao hàng hoặc gọi nguồn thật.</p>
      </header>
      <section className="mock-panel" aria-labelledby="mock-access-title">
        <h2 id="mock-access-title">Truy cập demo local</h2>
        <label htmlFor="mock-token">Khóa demo từ terminal</label>
        <div className="mock-inline">
          <input id="mock-token" type="password" autoComplete="off" value={token}
            onChange={(event) => setToken(event.target.value)} />
          <button type="button" onClick={refresh} disabled={loading || !token}>Tải catalog và lịch sử</button>
        </div>
        <p>Khóa chỉ giữ trong bộ nhớ tab; đóng hoặc tải lại trang sẽ xóa.</p>
      </section>
      {loading && <p role="status">Đang đọc trạng thái đơn từ PostgreSQL…</p>}
      {error && <p role="alert" className="mock-error">{error}</p>}
      {catalog && (
        <section className="mock-panel" aria-labelledby="mock-create-title">
          <h2 id="mock-create-title">Tạo đơn thử</h2>
          {choices.length === 0 ? <p>Catalog MOCK trống.</p> : (
            <>
              <label htmlFor="mock-product">Sản phẩm / biến thể</label>
              <select id="mock-product" value={selected?.key} disabled={submitted || loading}
                onChange={(event) => { setSelection(event.target.value); pending.current = null; }}>
                {choices.map(({ product, variant, key }) => (
                  <option key={key} value={key}>{product.name} / {variant.name}</option>
                ))}
              </select>
              {selected && <p>Giá hiện tại: {money(selected.variant.price)} · Tồn kho mô phỏng: {selected.variant.available_quantity}</p>}
              <label htmlFor="mock-quantity">Số lượng</label>
              <input id="mock-quantity" type="number" min="1" max="100" value={quantity}
                disabled={submitted || loading} onChange={(event) => setQuantity(Number(event.target.value))} />
              <div className="mock-actions">
                <button type="button" disabled={loading || submitted || !selected || !available(selected.variant, quantity)} onClick={() => submit("success")}>Mô phỏng thành công</button>
                <button type="button" disabled={loading || submitted || !selected || !available(selected.variant, quantity)} onClick={() => submit("failed_safe")}>Mô phỏng thất bại an toàn</button>
                <button type="button" disabled={loading || submitted || !selected || !available(selected.variant, quantity)} onClick={() => submit("unknown")}>Mô phỏng UNKNOWN</button>
                {pending.current && <button type="button" disabled={loading} onClick={() => submit(pending.current!.scenario)}>Thử lại cùng mã đơn</button>}
              </div>
              {submitted && <button type="button" onClick={newOrder}>Tạo đơn thử mới</button>}
            </>
          )}
          {result && <p role="status">{stateLabel(result)} · {money(result.total_price)} · {result.intent_id}</p>}
        </section>
      )}
      {catalog && (
        <section className="mock-panel" aria-labelledby="mock-history-title">
          <div className="mock-inline mock-history-heading">
            <h2 id="mock-history-title">Lịch sử đơn từ PostgreSQL</h2>
            <button type="button" disabled={loading} onClick={refresh}>Làm mới</button>
          </div>
          {orders.length === 0 ? <p>Chưa có đơn MOCK.</p> : (
            <ol className="mock-history">
              {orders.map((order) => (
                <li key={order.intent_id}>
                  <strong>{stateLabel(order)}</strong>
                  <span>{order.product_id} / {order.variant_id} · SL {order.quantity} · {money(order.total_price)}</span>
                  <small>{order.intent_id}</small>
                  {(order.purchase_state === "UNKNOWN" || order.purchase_state === "RECONCILING") && (
                    <div className="mock-actions">
                      <button type="button" disabled={loading} onClick={() => reconcile(order.intent_id, "unresolved")}>Đối soát: chưa rõ</button>
                      <button type="button" disabled={loading} onClick={() => reconcile(order.intent_id, "confirmed_success")}>Giả lập xác nhận thành công</button>
                      <button type="button" disabled={loading} onClick={() => reconcile(order.intent_id, "confirmed_out_of_stock")}>Giả lập xác nhận hết hàng</button>
                    </div>
                  )}
                </li>
              ))}
            </ol>
          )}
        </section>
      )}
    </main>
  );
}

function available(variant: MockVariant, quantity: number): boolean {
  return Number.isInteger(quantity) && quantity > 0 && quantity <= variant.available_quantity;
}
