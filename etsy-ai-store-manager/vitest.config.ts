import { defineConfig } from 'vitest/config';
import swc from 'unplugin-swc';
import path from 'node:path';

const r = (p: string) => path.resolve(import.meta.dirname, p);

// SWC keeps decorator metadata, which NestJS dependency injection needs.
const swcPlugin = swc.vite({
  jsc: {
    parser: { syntax: 'typescript', decorators: true },
    transform: { legacyDecorator: true, decoratorMetadata: true },
    target: 'es2023',
  },
  module: { type: 'es6' },
});

const alias = {
  '@esm/shared': r('packages/shared/src/index.ts'),
  '@esm/integrations': r('packages/integrations/src/index.ts'),
  '@esm/profit-engine': r('packages/profit-engine/src/index.ts'),
  '@esm/ai-engine': r('packages/ai-engine/src/index.ts'),
};

export default defineConfig({
  test: {
    projects: [
      {
        plugins: [swcPlugin],
        resolve: { alias },
        test: {
          name: 'unit',
          include: ['tests/unit/**/*.spec.ts'],
          environment: 'node',
        },
      },
      {
        plugins: [swcPlugin],
        resolve: { alias },
        test: {
          name: 'integration',
          include: ['tests/integration/**/*.spec.ts'],
          environment: 'node',
          globalSetup: ['tests/integration/global-setup.ts'],
          fileParallelism: false,
          testTimeout: 30_000,
          hookTimeout: 60_000,
        },
      },
    ],
  },
});
