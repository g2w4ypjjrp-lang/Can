// Rebuilds the test database from migrations before the integration suite.
import { migrate } from '../../infrastructure/scripts/migrate.mjs';
import { TEST_DATABASE_URL } from '../helpers/env.js';

export default async function setup() {
  if (!/test/i.test(TEST_DATABASE_URL)) {
    throw new Error('Refusing to reset a database whose URL does not contain "test"');
  }
  await migrate({
    connectionString: TEST_DATABASE_URL,
    reset: true,
    withShim: true,
    log: () => undefined,
  });
}
