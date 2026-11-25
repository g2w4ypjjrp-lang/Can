// Starts the Etsy contract stub on a fixed port for Playwright (test-only).
import { startEtsyStub } from '../helpers/etsy-stub.ts';

const port = Number(process.env.ETSY_STUB_PORT ?? 4600);
await startEtsyStub({ port, listingCount: 30 });
console.warn(`etsy stub listening on ${port}`);
