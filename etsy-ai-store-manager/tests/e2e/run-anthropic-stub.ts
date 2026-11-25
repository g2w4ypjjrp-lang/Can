// Starts the Claude Messages API contract stub on a fixed port for Playwright (test-only).
import http from 'node:http';
import { startAnthropicStub } from '../helpers/anthropic-stub.ts';

const port = Number(process.env.ANTHROPIC_STUB_PORT ?? 4800);
const stub = await startAnthropicStub();
// proxy fixed port -> stub (the helper listens on a random port)
http
  .createServer((req, res) => {
    const target = new URL(req.url ?? '/', stub.url);
    const p = http.request(target, { method: req.method, headers: req.headers }, (r) => {
      res.writeHead(r.statusCode ?? 502, r.headers);
      r.pipe(res);
    });
    req.pipe(p);
  })
  .listen(port, '127.0.0.1');
console.warn(`anthropic stub on ${port}`);
