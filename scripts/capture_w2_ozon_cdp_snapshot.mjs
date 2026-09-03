#!/usr/bin/env node
// Read-only Ozon seller snapshot over local Chrome DevTools Protocol.
// It only calls page-side GET/POST data reads; it does not submit tickets,
// change prices, archive products, reply, withdraw, or enable subscriptions.

const CDP_BASE = process.env.CDP_BASE || 'http://127.0.0.1:9224';
const OUT_PATH = process.env.W2_SNAPSHOT_OUT || null;

const companies = [
  { id: 2735620, name: 'BEIJIXINGYOUXUAN' },
  { id: 2706897, name: 'LINYAN888' },
  { id: 2315091, name: 'Treasures of the road' }
];

async function getSellerPageWebSocket() {
  const res = await fetch(`${CDP_BASE}/json/list`);
  if (!res.ok) throw new Error(`CDP list failed: HTTP ${res.status}`);
  const pages = await res.json();
  const page = pages.find((p) => p.type === 'page' && /seller\.ozon\.ru/i.test(p.url || ''));
  if (!page) throw new Error('No Ozon seller page found in CDP target list');
  return page.webSocketDebuggerUrl;
}

function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let seq = 0;
    const pending = new Map();

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && pending.has(msg.id)) {
        pending.get(msg.id)(msg);
        pending.delete(msg.id);
      }
    };

    ws.onerror = () => {
      reject(new Error(`WebSocket error: ${wsUrl}`));
    };

    ws.onopen = () => {
      resolve({
        ws,
        send(method, params = {}) {
          return new Promise((resolveCommand, rejectCommand) => {
            const id = ++seq;
            pending.set(id, resolveCommand);
            ws.send(JSON.stringify({ id, method, params }));
            setTimeout(() => {
              if (pending.has(id)) {
                pending.delete(id);
                rejectCommand(new Error(`CDP timeout: ${method}`));
              }
            }, 30000);
          });
        },
        close() {
          ws.close();
        }
      });
    };
  });
}

function buildSnapshotExpression() {
  return `(async () => {
    const companies = ${JSON.stringify(companies)};
    const since = '2025-01-01T00:00:00Z';
    const until = new Date().toISOString();
    const out = [];
    for (const company of companies) {
      const row = { id: company.id, name: company.name };
      try {
        const res = await fetch('/api/site/self-gateway/api/balances/current_month', {
          headers: { accept: 'application/json', 'x-o3-company-id': String(company.id) }
        });
        row.balance = await res.json();
      } catch (err) {
        row.balanceError = String(err);
      }
      try {
        const res = await fetch('/api/posting-service/v2/fbs/posting/count/by-status-alias', {
          method: 'POST',
          headers: {
            accept: 'application/json',
            'content-type': 'application/json',
            'x-o3-company-id': String(company.id)
          },
          body: JSON.stringify({
            company_id: company.id,
            processed_at_from: since,
            processed_at_to: until,
            status_alias: ['awaiting_packaging', 'awaiting_deliver', 'delivering', 'delivered', 'cancelled']
          })
        });
        row.orders = await res.json();
      } catch (err) {
        row.orderError = String(err);
      }
      try {
        const res = await fetch('/api/posting-service/posting/count-by-warehouses', {
          method: 'POST',
          headers: {
            accept: 'application/json',
            'content-type': 'application/json',
            'x-o3-company-id': String(company.id)
          },
          body: JSON.stringify({
            filter: {
              company_id: company.id,
              processed_at_from: since,
              processed_at_to: until,
              status_alias: ['awaiting_packaging', 'awaiting_deliver', 'delivering', 'delivered', 'cancelled']
            },
            limit: 1000,
            offset: 0
          })
        });
        const warehousePayload = await res.json();
        const warehouseList = warehousePayload?.result?.warehouses ?? [];
        const byStatus = {};
        for (const warehouse of warehouseList) {
          const status = warehouse.status || 'unknown';
          byStatus[status] = (byStatus[status] || 0) + 1;
        }
        row.warehouse_summary = {
          total: warehouseList.length,
          by_status: byStatus,
          blocked: byStatus.blocked || 0
        };
        row.warehouses = warehouseList.map((warehouse) => ({
          warehouse_id: warehouse.warehouse_id,
          warehouse_name: warehouse.warehouse_name,
          status: warehouse.status,
          posting_count: warehouse.posting_count
        }));
      } catch (err) {
        row.warehouseError = String(err);
      }
      try {
        const res = await fetch('/api/site/product/list/summary-count', {
          method: 'POST',
          headers: {
            accept: 'application/json',
            'content-type': 'application/json',
            'x-o3-company-id': String(company.id)
          },
          body: JSON.stringify({ company_id: company.id })
        });
        const productPayload = await res.json();
        row.product_summary = {
          in_sale: productPayload?.visibilities?.['15'] ?? null,
          to_supply: productPayload?.visibilities?.['14'] ?? null
        };
      } catch (err) {
        row.productError = String(err);
      }
      try {
        const res = await fetch('/api/premium/status', {
          method: 'POST',
          headers: {
            accept: 'application/json',
            'content-type': 'application/json',
            'x-o3-company-id': String(company.id)
          },
          body: JSON.stringify({ company_id: company.id })
        });
        const premium = await res.json();
        row.premium = {
          is_premium: premium?.result?.is_premium ?? null,
          grace_period_available: premium?.result?.grace_period_available ?? null,
          premium_available: premium?.result?.grace_periods?.find((item) => item.subscription === 'PREMIUM')?.available ?? null
        };
      } catch (err) {
        row.premiumError = String(err);
      }
      out.push(row);
    }
    return out;
  })()`;
}

async function main() {
  const wsUrl = await getSellerPageWebSocket();
  const client = await connect(wsUrl);
  try {
    await client.send('Runtime.enable');
    const result = await client.send('Runtime.evaluate', {
      expression: buildSnapshotExpression(),
      awaitPromise: true,
      returnByValue: true
    });
    const value = result?.result?.result?.value;
    if (!value) throw new Error(`CDP evaluation did not return a value: ${JSON.stringify(result)}`);
    const payload = {
      captured_at: new Date().toISOString(),
      source: 'w2-ozon-cdp-readonly',
      companies: value
    };
    const json = JSON.stringify(payload, null, 2);
    if (OUT_PATH) {
      const fs = await import('node:fs/promises');
      await fs.writeFile(OUT_PATH, `${json}\n`, 'utf8');
      console.log(`WROTE ${OUT_PATH}`);
    } else {
      console.log(json);
    }
  } finally {
    client.close();
  }
}

main().catch((err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exitCode = 1;
});
