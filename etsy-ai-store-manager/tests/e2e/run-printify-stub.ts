// Starts the Printify contract stub on a fixed port for Playwright (test-only).
import { startPrintifyStub } from '../helpers/printify-stub.ts';

const port = Number(process.env.PRINTIFY_STUB_PORT ?? 4700);
await startPrintifyStub({ port });
console.warn(`printify stub listening on ${port}`);
